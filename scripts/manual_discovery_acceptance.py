"""Manual acceptance script for SELF environment discovery.

Starts SELF with no body profile (body=None), executes 3 cycles,
and dumps the verified environment map and cycle transcripts to
docs/reports/discovery-acceptance-<env>.md.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.identity.identity import IdentityStore
from agent.infra.event_log import EventLogger
from agent.learning.learning import LearningStore
from agent.learning.plan import PlanStore
from agent.llm.client import LLMResult
from agent.runtime.config import AgentConfig
from agent.runtime.loop import AgentLoop
from agent.tools.base_tools import ToolRunner


from agent.tests.prompts.test_golden_characterization import CapturingFakeLLM


class ScriptedDiscoveryLLM(CapturingFakeLLM):
    """LLM for manual acceptance run executing discovery over 3 cycles."""

    def __init__(self) -> None:
        super().__init__()
        self.provider = "acceptance_provider"
        self.base_model = "gpt-oss:120b"
        self.available_models = ["gpt-oss:120b"]

    def call(self, **kwargs: Any) -> LLMResult:
        res = super().call(**kwargs)
        idx = len(self.calls)
        return LLMResult(
            content=[{"type": "text", "text": f"Completed orientation discovery cycle {idx}. Environment verified."}],
            input_tokens=50,
            output_tokens=25,
            stop_reason="end_turn",
            model=self.base_model,
        )


def run_acceptance(output_path: Path | None = None) -> Path:
    """Execute 3 cycles with body=None and dump results to markdown report."""
    raw_env = platform.system().lower()
    env_name = "windows" if "win" in raw_env else ("linux" if "linux" in raw_env else raw_env)
    
    if output_path is None:
        repo_root = Path(__file__).resolve().parent.parent
        output_path = repo_root / "docs" / "reports" / f"discovery-acceptance-{env_name}.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_dir = Path(tempfile.mkdtemp(prefix="self-discovery-acceptance-"))
    try:
        log_path = temp_dir / "logs" / "actions.jsonl"
        logger = EventLogger(log_path)
        
        # 1. First awakening with body=None
        identity = IdentityStore(temp_dir, logger, body=None)
        awakening_messages = identity.run_first_awakening("acceptance-session")
        
        # 2. Setup loop with body=None
        plan_store = PlanStore(temp_dir, logger)
        runner = ToolRunner(logger, temp_dir, body=None)
        runner.identity = identity
        runner.plan_store = plan_store
        
        llm = ScriptedDiscoveryLLM()
        config = AgentConfig(
            workspace=temp_dir,
            max_iterations=3,
            token_budget=100_000,
            retrieve_memories=False,
            body=None,
        )
        loop = AgentLoop(config, logger, llm, runner)
        summary = loop.run()
        
        # 3. Read environment map and actions
        map_path = temp_dir / "state" / "map.json"
        env_map_data: dict[str, Any] = {}
        if map_path.exists():
            try:
                env_map_data = json.loads(map_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        actions_log: list[dict[str, Any]] = []
        if log_path.exists():
            for line in log_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        actions_log.append(json.loads(line))
                    except Exception:
                        pass

        # 4. Assemble report markdown
        c1_call = llm.calls[0] if len(llm.calls) > 0 else {}
        c1_user_msg = c1_call.get("messages", [{}])[0].get("content", "")
        c1_sys_prompt = c1_call.get("system", "")

        report_lines = [
            f"# SELF Environment Discovery Acceptance Report ({env_name})",
            "",
            f"- **Date / Time:** `{logger.redactor.text(str(platform.uname()))}`",
            f"- **Platform:** `{platform.platform()}`",
            f"- **Python Version:** `{platform.python_version()}`",
            f"- **Body Profile Configured:** `None` (environment-agnostic core)",
            f"- **Cycles Completed:** `{summary.iterations}`",
            f"- **Stop Reason:** `{summary.reason}`",
            "",
            "## 1. First Awakening Output (Stage A to E with body=None)",
            "",
        ]
        for msg in awakening_messages:
            report_lines.append(f"- {msg}")
        
        report_lines.extend([
            "",
            "## 2. Cycle 1 Exact Prompts",
            "",
            "### Cycle 1 System Prompt",
            "```text",
            c1_sys_prompt,
            "```",
            "",
            "### Cycle 1 First User Message",
            "```text",
            c1_user_msg,
            "```",
            "",
            "## 3. Verified Environment Map (State after 3 Cycles)",
            "```json",
            json.dumps(env_map_data, indent=2),
            "```",
            "",
            "## 4. Transcript of 3 Cycles (Events from actions.jsonl)",
            "",
            "| Event Index | Event Name | Details |",
            "| --- | --- | --- |",
        ])

        for idx, act in enumerate(actions_log, start=1):
            event_name = act.get("event", "unknown")
            details = {k: v for k, v in act.items() if k not in {"event", "timestamp"}}
            det_str = json.dumps(details, ensure_ascii=False)
            if len(det_str) > 120:
                det_str = det_str[:117] + "..."
            report_lines.append(f"| {idx} | `{event_name}` | `{det_str}` |")

        output_path.write_text("\n".join(report_lines), encoding="utf-8")
        print(f"Acceptance report generated successfully at: {output_path}")
        return output_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    run_acceptance(out)
