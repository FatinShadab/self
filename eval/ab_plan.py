"""Host-only randomized helper-model campaign plan and seed builder."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import secrets
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
TASKS_PATH = HERE / "ab_tasks.json"
PLAN_PATH = HERE / "ab" / "plan.json"
SEED_ROOT = Path(os.getenv("AB_SEED_ROOT", "/opt/ab_seed"))


def load_tasks(path: Path = TASKS_PATH) -> list[dict]:
    """Load and validate the hidden A/B task definitions."""
    tasks = json.loads(path.read_text(encoding="utf-8"))["tasks"]
    if len({task["id"] for task in tasks}) != len(tasks):
        raise ValueError("A/B task IDs must be unique")
    return tasks


def content_hash(root: Path) -> str:
    """Hash the seed workspace contents in stable path order."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def container_facts() -> dict[str, object]:
    """Capture stable container facts for investigation tasks."""
    os_release = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            os_release[key] = value.strip('"')
    return {
        "python_major_minor": f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}",
        "implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "jq": shutil.which("jq") is not None,
        "git": shutil.which("git") is not None,
        "sqlite3": shutil.which("sqlite3") is not None,
        "os_id": os_release.get("ID"),
        "os_version_id": os_release.get("VERSION_ID"),
        "architecture": platform.machine(),
    }


def make_seed(source: Path, destination: Path = SEED_ROOT) -> dict:
    """Copy stable workspace state into a fresh experiment seed.

    Copy identity and environment state, reset model measurements, and omit
    run-specific logs, memories, and tools. Refuse to overwrite an existing
    seed so a saved plan keeps referring to the same source state.

    Returns:
        Seed content hash and captured container facts.
    """
    workspace = destination / "workspace"
    if workspace.exists():
        raise FileExistsError(f"Seed already exists: {workspace}; preserve it for reproducibility")
    state = workspace / "state"
    state.mkdir(parents=True)
    for filename in ("identity.json", "map.json", "models.json"):
        path = source / "state" / filename
        if path.is_file():
            shutil.copyfile(path, state / filename)
        elif filename == "map.json":
            (state / filename).write_text('{"schema_version":1,"entries":{}}\n', encoding="utf-8")
        else:
            raise FileNotFoundError(f"Seed requires {path}")
    models_path = state / "models.json"
    models = json.loads(models_path.read_text(encoding="utf-8"))
    for entry in models.get("models", []):
        entry["measured_stats"] = {
            "calls": 0, "failures": 0, "latency_ms_total": 0,
            "latency_ms_min": None, "latency_ms_max": None,
            "consecutive_failures": 0, "probe_passes": 0,
            "probe_failures": 0, "probe_inconclusive": 0,
        }
        entry["probe_history"] = []
        if entry.get("status") != "disabled":
            entry["status"] = "configured"
            entry["status_message"] = ""
            entry["last_failure_at"] = None
    models_path.write_text(json.dumps(models, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    metadata = {"seed_hash": content_hash(workspace), "facts": container_facts()}
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def make_plan(tasks: list[dict], arms: list[str], repetitions: int, seed: int,
              max_total_calls: int, seed_hash: str | None = None,
              campaign: str = "full") -> dict:
    """Randomize task, arm, and repetition combinations into a campaign.

    The returned plan records its random seed and the upper bound on
    provider attempts. Each repetition contains every selected task-arm
    pair once, shuffled without changing the task definitions.
    """
    if repetitions < 1 or max_total_calls < 1 or not arms:
        raise ValueError("repetitions, call cap, and arms must be positive")
    if len(set(arms)) != len(arms) or any(
        arm not in {"off", "on"} and not arm.startswith("forced_critic:") for arm in arms
    ):
        raise ValueError("Arms must be distinct and use off, on, or forced_critic:<model>")
    rng = random.Random(seed)
    runs = []
    for repetition in range(1, repetitions + 1):
        block = [(task, arm) for task in tasks for arm in arms]
        rng.shuffle(block)
        for task, arm in block:
            arm_slug = arm.replace(":", "-").replace("/", "-")
            runs.append({
                "run_id": f"{campaign}-{task['id']}-{arm_slug}-r{repetition}-{seed:08x}",
                "task_id": task["id"], "category": task["category"],
                "arm": arm, "repetition": repetition,
                "campaign": campaign,
                "limits": task["limits"], "provider_call_cap": task["limits"]["max_provider_calls"],
            })
    upper = min(max_total_calls, sum(run["provider_call_cap"] for run in runs))
    return {"schema_version": 1, "plan_seed": seed, "seed_hash": seed_hash,
            "campaign_id": f"{campaign}-{seed:08x}",
            "max_total_calls": max_total_calls, "planned_run_count": len(runs),
            "provider_call_upper_bound": upper, "runs": runs}


def main(argv: list[str] | None = None) -> int:
    """Parse command-line arguments and run this module's entry point."""
    parser = argparse.ArgumentParser(description="Plan a randomized helper-model A/B campaign.")
    parser.add_argument("--tasks", default="all", help="Comma-separated task IDs or all")
    parser.add_argument("--arms", default="off,on", help="Comma-separated arms")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--max-total-calls", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pilot", action="store_true", help="All tasks, off arm, three repetitions")
    parser.add_argument("--make-seed", action="store_true")
    args = parser.parse_args(argv)
    if args.make_seed:
        metadata = make_seed(Path("/home/entity"))
        print(f"seed_hash={metadata['seed_hash']} captured_facts={len(metadata['facts'])}")
        return 0
    all_tasks = load_tasks()
    ids = {part.strip() for part in args.tasks.split(",")} if args.tasks != "all" else None
    tasks = [task for task in all_tasks if ids is None or task["id"] in ids]
    if not tasks or (ids is not None and ids != {task["id"] for task in tasks}):
        parser.error("Unknown or empty task selection")
    arms = [part.strip() for part in ("off" if args.pilot else args.arms).split(",")]
    repetitions = 3 if args.pilot else args.runs
    seed = args.seed if args.seed is not None else secrets.randbits(32)
    metadata_path = SEED_ROOT / "metadata.json"
    seed_hash = json.loads(metadata_path.read_text(encoding="utf-8"))["seed_hash"] if metadata_path.exists() else None
    plan = make_plan(tasks, arms, repetitions, seed, args.max_total_calls, seed_hash,
                     campaign="pilot" if args.pilot else "full")
    print(f"planned_runs={plan['planned_run_count']} provider_call_upper_bound={plan['provider_call_upper_bound']} plan_seed={seed}")
    if not args.dry_run:
        PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLAN_PATH.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"plan={PLAN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
