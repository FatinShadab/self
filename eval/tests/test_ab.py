"""Provider-free A/B planning, seed, verifier, and analysis tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.ab_analyze import render, summarize
from eval.ab_plan import load_tasks, make_plan, make_seed
from eval.ab_verify import collect_result, verify_task


class ABTests(unittest.TestCase):
    def test_plan_randomization_repetitions_and_dry_run_bound(self):
        tasks = load_tasks()
        self.assertEqual(len(tasks), 12)
        self.assertEqual({task["category"] for task in tasks}, {
            "create_tool", "data_and_code", "extraction_and_summary", "container_investigation"})
        first = make_plan(tasks, ["off", "on"], 3, 42, 1000)
        second = make_plan(tasks, ["off", "on"], 3, 42, 1000)
        other = make_plan(tasks, ["off", "on"], 3, 43, 1000)
        self.assertEqual(first["runs"], second["runs"])
        self.assertNotEqual(first["runs"], other["runs"])
        self.assertEqual(first["planned_run_count"], 72)
        self.assertEqual(first["provider_call_upper_bound"], 864)
        self.assertEqual(make_plan(tasks, ["off"], 3, 42, 1000)["planned_run_count"], 36)
        self.assertEqual(make_plan(tasks, ["off"], 3, 42, 1000)["provider_call_upper_bound"], 432)
        self.assertEqual(make_plan(tasks, ["off", "on"], 3, 42, 70)["provider_call_upper_bound"], 70)
        completed = {first["runs"][0]["run_id"], first["runs"][1]["run_id"]}
        pending = [run for run in first["runs"] if run["run_id"] not in completed]
        self.assertEqual(len(pending), 70)
        self.assertEqual(pending[0]["run_id"], first["runs"][2]["run_id"])

    def test_seed_keeps_only_identity_map_and_reset_models(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            state = source / "state"
            state.mkdir(parents=True)
            (state / "identity.json").write_text('{"name":"Atlas"}')
            (state / "map.json").write_text('{"schema_version":1,"entries":{}}')
            (state / "models.json").write_text(json.dumps({"base_model":"base", "models":[{
                "name":"base", "status":"reachable", "agent_assessment":"tested",
                "ratings":{"code":"high"}, "measured_stats":{"calls":9},
                "probe_history":[{"id":"old"}]}]}))
            for relative in ("logs/actions.jsonl", "memory/memory.jsonl", "tools/old/tool.py",
                             "state/model_decisions.jsonl", "state/model_outcomes.jsonl"):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("old")
            destination = Path(temp) / "seed"
            metadata = make_seed(source, destination)
            files = {p.relative_to(destination / "workspace").as_posix()
                     for p in (destination / "workspace").rglob("*") if p.is_file()}
            self.assertEqual(files, {"state/identity.json", "state/map.json", "state/models.json"})
            models = json.loads((destination / "workspace/state/models.json").read_text())
            self.assertEqual(models["models"][0]["agent_assessment"], "tested")
            self.assertEqual(models["models"][0]["ratings"], {"code":"high"})
            self.assertEqual(models["models"][0]["measured_stats"]["calls"], 0)
            self.assertEqual(models["models"][0]["probe_history"], [])
            self.assertEqual(len(metadata["seed_hash"]), 64)

    def test_verifiers_pass_and_fail_on_crafted_workspaces(self):
        tasks = load_tasks()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for task in tasks:
                spec = task["verifier"]
                self.assertFalse(verify_task(task, root, {key: "x" for key in spec.get("keys", [])})["passed"])
                if spec["kind"] == "create_tool":
                    folder = root / "tools" / spec["name"]
                    folder.mkdir(parents=True)
                    (folder / "meta.json").write_text('{"registered":true}')
                    # The hidden cases are exercised through a fresh child Python interpreter.
                    source = {
                        "slugify_text": "import re\ndef run(text): return re.sub(r'[^a-z0-9]+','-',text.strip().lower()).strip('-')\n",
                        "parse_duration": "import re\ndef run(text):\n t=text.split()\n if not t or any(not re.fullmatch(r'[0-9]+[hms]',x) for x in t): raise ValueError()\n return sum(int(x[:-1])*{'h':3600,'m':60,'s':1}[x[-1]] for x in t)\n",
                        "dedupe_records": "def run(records):\n seen=set(); out=[]\n for r in records:\n  if 'id' in r:\n   if r['id'] in seen: continue\n   seen.add(r['id'])\n  out.append(r)\n return out\n",
                    }[spec["name"]]
                    (folder / "tool.py").write_text(source)
                else:
                    path = root / spec["path"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if spec["kind"] == "container_facts":
                        data = {key: "x" for key in spec["keys"]}
                    else:
                        data = dict(spec["expected"])
                        if spec["kind"] == "facts":
                            data["summary"] = " ".join(spec["summary_facts"]) + "."
                    path.write_text(json.dumps(data))
                facts = {key: "x" for key in spec.get("keys", [])}
                self.assertTrue(verify_task(task, root, facts)["passed"], task["id"])

    def test_contamination_and_exclusion_math(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "state").mkdir()
            (root / "logs").mkdir()
            (root / "state/models.json").write_text('{"base_model":"base"}')
            (root / "logs/actions.jsonl").write_text(
                '{"event":"llm_call_attempt","model":"helper"}\n'
                '{"event":"run_completed","iterations":1}\n')
            task = {"id":"t", "category":"data_and_code",
                    "verifier":{"kind":"json_output","path":"ab_outputs/t.json","expected":{"v":1}}}
            (root / "ab_outputs").mkdir()
            (root / "ab_outputs/t.json").write_text('{"v":1}')
            run = {"run_id":"t-off-r1", "arm":"off", "repetition":1}
            result = collect_result(run, task, root, "hash", {}, plan_seed=3)
            self.assertTrue(result["contaminated"])
            self.assertEqual(result["provider_calls"], 1)
            (root / "state/ab_provider_calls.json").write_text('{"calls":2}')
            self.assertEqual(collect_result(run, task, root, "hash", {}, plan_seed=3)["provider_calls"], 2)
        rows = []
        for task_id, off, on in (("informative", [False, False], [True, True]),
                                 ("ceiling", [True, True], [True, True]),
                                 ("floor", [False, False], [False, False])):
            for arm, values in (("off", off), ("on", on)):
                rows += [{"run_id":f"{task_id}-{arm}-{i}","task_id":task_id,
                          "arm":arm,"category":"data_and_code","passed":value,
                          "score":float(value),"models_actually_called":["base"],
                          "base_model":"base","helper_calls":0,"decision_origins":{},
                          "contaminated":False,"infra_error":False}
                         for i,value in enumerate(values)]
        rows.append({**rows[0], "run_id":"excluded", "contaminated":True})
        result = summarize(rows, draws=100)
        self.assertEqual(set(result["uninformative"]), {"ceiling", "floor"})
        self.assertEqual(result["pooled_difference"], 1.0)
        self.assertEqual(result["bootstrap_interval"], (1.0, 1.0))
        self.assertEqual(len(result["excluded"]), 1)
        self.assertIn("OBSERVATIONAL", render(rows))
