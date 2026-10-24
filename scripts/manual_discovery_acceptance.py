"""Manual acceptance script for SELF environment discovery.

Starts SELF with no body profile (body=None) or configured body profile,
executes 3 cycles using the real configured model (gpt-oss:120b via Ollama),
and dumps the verified environment map and unedited cycle transcripts to
docs/reports/discovery-acceptance-<env>.md.
"""
from __future__ import annotations

import argparse
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

from agent.body.container import ContainerBody
from agent.identity.identity import IdentityStore
from agent.infra.event_log import EventLogger
from agent.learning.learning import LearningStore
from agent.learning.plan import PlanStore
from agent.llm.client import LLMResult
from agent.llm.llm import LLMClient
from agent.runtime.config import AgentConfig
from agent.runtime.loop import AgentLoop
from agent.tools.base_tools import ToolRunner


def load_env_file(env_path: Path) -> None:
    """Load key-value pairs from .env into os.environ if present."""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'").strip('"')
            os.environ.setdefault(k, v)


class CapturingRealLLM(LLMClient):
    """Real LLM client that also captures calls and responses for transcript reporting."""

    def __init__(self, logger: EventLogger, **kwargs: Any) -> None:
        super().__init__(logger, **kwargs)
        self.captured_calls: list[dict[str, Any]] = []

    def call(self, **kwargs: Any) -> LLMResult:
        res = super().call(**kwargs)
        self.captured_calls.append({
            "system": kwargs.get("system", ""),
            "messages": kwargs.get("messages", []),
            "tools": kwargs.get("tools", []),
            "max_tokens": kwargs.get("max_tokens"),
            "response": {
                "content": res.content,
                "input_tokens": res.input_tokens,
                "output_tokens": res.output_tokens,
                "stop_reason": res.stop_reason,
                "model": res.model,
            },
        })
        return res


def run_acceptance(
    output_path: Path | None = None,
    body_type: str | None = None,
    cycles: int = 3,
) -> Path:
    """Execute cycles and dump results to markdown report."""
    load_env_file(REPO_ROOT / ".env")
    raw_env = platform.system().lower()
    env_name = "windows" if "win" in raw_env else ("linux" if "linux" in raw_env else raw_env)

    if output_path is None:
        suffix = f"-{body_type}" if body_type and body_type != "none" else ""
        output_path = REPO_ROOT / "docs" / "reports" / f"discovery-acceptance-{env_name}{suffix}.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="self-discovery-acceptance-"))

    try:
        log_path = temp_dir / "logs" / "actions.jsonl"
        logger = EventLogger(log_path)

        # Configure body if requested
        body = None
        if body_type == "container":
            body = ContainerBody(temp_dir, logger)

        # 1. First awakening
        identity = IdentityStore(temp_dir, logger, body=body)
        awakening_messages = identity.run_first_awakening("acceptance-session")

        # 2. Setup loop
        plan_store = PlanStore(temp_dir, logger)
        runner = ToolRunner(logger, temp_dir, body=body)
        runner.identity = identity
        runner.plan_store = plan_store

        llm = CapturingRealLLM(logger)
        config = AgentConfig(
            workspace=temp_dir,
            max_iterations=cycles,
            token_budget=200_000,
            retrieve_memories=False,
            body=body,
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
        c1_call = llm.captured_calls[0] if len(llm.captured_calls) > 0 else {}
        c1_user_msg = c1_call.get("messages", [{}])[0].get("content", "")
        c1_sys_prompt = c1_call.get("system", "")

        report_lines = [
            f"# SELF Environment Discovery Acceptance Report ({env_name}{' - ' + body_type if body_type and body_type != 'none' else ''})",
            "",
            f"- **Date / Time:** `{logger.redactor.text(str(platform.uname()))}`",
            f"- **Platform:** `{platform.platform()}`",
            f"- **Python Version:** `{platform.python_version()}`",
            f"- **Active Model / Provider:** `{llm.model}` via `{llm.provider}` (`{llm.base_url}`)",
            f"- **Body Profile Configured:** `{body.__class__.__name__ if body else 'None'}` ({'container expectations' if body else 'environment-agnostic core'})",
            f"- **Cycles Completed:** `{summary.iterations}`",
            f"- **Tokens Used:** `{summary.tokens_used}`",
            f"- **Stop Reason:** `{summary.reason}`",
            "",
            "## 1. First Awakening Output (Stages A to E)",
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
            "## 3. Verified Environment Map (State after cycles)",
            "```json",
            json.dumps(env_map_data, indent=2),
            "```",
            "",
            "## 4. Full Cycle LLM Transcripts (Unedited calls & model responses)",
            "",
        ])

        for call_idx, call_data in enumerate(llm.captured_calls, start=1):
            report_lines.extend([
                f"### Call {call_idx}",
                f"- **Model:** `{call_data['response'].get('model')}`",
                f"- **Input Tokens:** {call_data['response'].get('input_tokens')}, **Output Tokens:** {call_data['response'].get('output_tokens')}",
                f"- **Stop Reason:** `{call_data['response'].get('stop_reason')}`",
                "",
                "#### Model Output Content:",
                "```json",
                json.dumps(call_data["response"].get("content", []), indent=2),
                "```",
                "",
            ])

        report_lines.extend([
            "## 5. Event Log (actions.jsonl unedited events)",
            "",
            "| Event Index | Event Name | Details |",
            "| --- | --- | --- |",
        ])

        for idx, act in enumerate(actions_log, start=1):
            event_name = act.get("event", "unknown")
            details = {k: v for k, v in act.items() if k not in {"event", "timestamp"}}
            det_str = json.dumps(details, ensure_ascii=False)
            if len(det_str) > 160:
                det_str = det_str[:157] + "..."
            report_lines.append(f"| {idx} | `{event_name}` | `{det_str}` |")

        output_path.write_text("\n".join(report_lines), encoding="utf-8")
        print(f"Acceptance report generated successfully at: {output_path}")
        return output_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SELF acceptance discovery cycles.")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output markdown path")
    parser.add_argument("--body", "-b", choices=["none", "container"], default="none", help="Body profile")
    parser.add_argument("--cycles", "-c", type=int, default=3, help="Number of cycles")
    args = parser.parse_args()

    body_arg = args.body if args.body != "none" else None
    run_acceptance(output_path=args.output, body_type=body_arg, cycles=args.cycles)


if __name__ == "__main__":
    main()
