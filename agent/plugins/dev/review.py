"""Plugin review packet generation, template diffing, and LLM critic execution."""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.plugins.cli import _find_template_dir
from agent.plugins.dev.environment import now_utc
from agent.prompts.critics import PLUGIN_CRITIC_PROMPT


def build_template_diff(draft_dir: Path) -> str:
    """Generate unified diff of draft directory against starter template."""
    tmpl = _find_template_dir()
    diff_lines: list[str] = []
    if tmpl and tmpl.exists():
        for p in sorted(draft_dir.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                rel = p.relative_to(draft_dir)
                tmpl_file = tmpl / rel
                cur_text = p.read_text(encoding="utf-8", errors="replace").splitlines()
                tmpl_text = tmpl_file.read_text(encoding="utf-8", errors="replace").splitlines() if tmpl_file.exists() else []
                file_diff = list(
                    difflib.unified_diff(
                        tmpl_text,
                        cur_text,
                        fromfile=f"template/{rel.as_posix()}",
                        tofile=f"draft/{rel.as_posix()}",
                        lineterm="",
                    )
                )
                if file_diff:
                    diff_lines.extend(file_diff)
    return "\n".join(diff_lines) if diff_lines else "No source differences from template."


def execute_plugin_review(
    dev_dir: Path,
    logger: EventLogger,
    validate_fn: Callable[[str], dict[str, Any]],
    test_fn: Callable[[str], dict[str, Any]],
    review_call: Callable[..., Any] | None,
    pending_reviews: list[int],
    name: str,
) -> dict[str, Any]:
    """Run validation, isolated tests, and strict plugin critic LLM review."""
    clean_name = str(name).strip()
    if pending_reviews:
        highest_pct = max(pending_reviews)
        return {
            "ok": False,
            "error": (
                f"Mandatory stop-loss review at {highest_pct}% of estimate is pending for plugin '{clean_name}'. "
                "You must record an explicit continue / reduce_scope / abandon decision in your plan update before proceeding."
            ),
        }

    draft_dir = dev_dir / clean_name
    if not draft_dir.exists():
        return {"ok": False, "error": f"Draft '{clean_name}' does not exist."}

    # 1. Run validator
    val_res = validate_fn(clean_name)
    if not val_res.get("valid"):
        return {
            "ok": False,
            "error": "Plugin validation failed:\n" + "\n".join(val_res.get("errors", [])),
            "validation": val_res,
        }

    # 2. Run tests
    test_res = test_fn(clean_name)
    if not test_res.get("passed"):
        return {
            "ok": False,
            "error": f"Plugin tests failed or timed out:\n{test_res.get('output', '')}",
            "tests": test_res,
        }

    # 3. Generate unified diff against starter template
    diff_text = build_template_diff(draft_dir)

    # 4. Strict critic review
    verdict = {"approved": True, "issues": [], "critique": "Static checks passed."}
    if review_call is not None:
        manifest_json = (draft_dir / "plugin.json").read_text(encoding="utf-8", errors="replace")
        plugin_py = (draft_dir / "plugin.py").read_text(encoding="utf-8", errors="replace") if (draft_dir / "plugin.py").exists() else ""
        test_py = ""
        tests_dir = draft_dir / "tests"
        if tests_dir.exists():
            for tf in tests_dir.glob("test_*.py"):
                test_py += f"\n--- {tf.name} ---\n" + tf.read_text(encoding="utf-8", errors="replace")

        prompt_content = json.dumps({
            "plugin_name": clean_name,
            "manifest": manifest_json,
            "code": plugin_py[:10000],
            "tests": test_py[:10000],
            "permission_summary": val_res.get("permission_summary"),
        }, ensure_ascii=False)

        try:
            resp = review_call(
                system=PLUGIN_CRITIC_PROMPT,
                messages=[{"role": "user", "content": prompt_content}],
                tools=[],
                max_tokens=4096,
            )
            text = "\n".join(str(b.get("text", "")) for b in resp.content if b.get("type") == "text").strip()
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "approved" in parsed:
                verdict = parsed
        except Exception as exc:
            logger.log("plugin_critic_failed", name=clean_name, error=str(exc))
            return {"ok": False, "error": f"Critic review call failed: {exc}"}

    approved = verdict.get("approved") is True and not verdict.get("issues")

    packet = {
        "name": clean_name,
        "timestamp": now_utc(),
        "approved": approved,
        "critic_verdict": verdict,
        "permission_summary": val_res.get("permission_summary"),
        "diff": diff_text[:15000],
    }
    packet_file = draft_dir / "review_packet.json"
    packet_file.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    logger.log(
        "plugin_review_completed",
        name=clean_name,
        approved=approved,
        issues=verdict.get("issues", []),
    )

    return {
        "ok": True,
        "approved": approved,
        "critic_verdict": verdict,
        "diff": diff_text,
        "permission_summary": val_res.get("permission_summary"),
        "review_packet_file": str(packet_file),
        "message": "Review completed. Ready for human promotion if approved.",
    }
