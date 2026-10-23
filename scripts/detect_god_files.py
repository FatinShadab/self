#!/usr/bin/env python3
"""detect_god_files.py - Host-side static analysis script to detect god files in the SELF harness.

Analyzes Python files in the agent/ package using AST to measure:
- LOC (total lines of code)
- Number of classes and top-level functions
- Methods per class (flagging classes with > 15 methods)
- Longest functions (flagging functions > 60 lines)
- Distinct imports from other agent.* packages (fan-out)
- Number of distinct responsibilities / reasons to change

Flags files meeting any god-file criteria:
- LOC > 400
- Class with > 15 methods
- Function > 60 lines
- > 3 unrelated responsibilities
- Constructor wiring > 6 collaborators
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FileAnalysis:
    """Analysis results for a single Python source file."""
    path: Path
    rel_path: str
    loc: int
    num_classes: int
    num_top_level_functions: int
    class_methods: dict[str, int]
    max_methods_in_class: int
    longest_functions: list[tuple[str, int]]  # (name, lines)
    agent_import_fanout: set[str]
    responsibilities: set[str]
    max_constructor_collaborators: int
    flags: list[str] = field(default_factory=list)

    @property
    def is_god_file(self) -> bool:
        """Return True if any god-file threshold is exceeded."""
        return len(self.flags) > 0

    @property
    def severity_score(self) -> int:
        """Compute ranking score based on LOC and flag severity."""
        score = self.loc
        score += len(self.flags) * 100
        score += max(0, self.max_methods_in_class - 15) * 10
        score += len(self.agent_import_fanout) * 15
        score += len(self.responsibilities) * 20
        for _, flen in self.longest_functions:
            if flen > 60:
                score += (flen - 60) * 2
        return score


def identify_responsibilities(tree: ast.AST, code_text: str) -> set[str]:
    """Identify architectural responsibilities present in the AST and token text."""
    responsibilities = set()

    # 1. Persistence & File I/O
    io_patterns = {
        "open(", "read_text", "write_text", "read_bytes", "write_bytes",
        "json.load", "json.dump", "os.replace", "sqlite3", "atomic_write",
        "Path(", ".unlink(", ".mkdir("
    }
    if any(pat in code_text for pat in io_patterns):
        responsibilities.add("I/O & Persistence")

    # 2. Formatting & Display / Rich Markup
    formatting_patterns = {
        "rich", "Rich", "escape_rich_markup", "Panel(", "Table(", "Text(",
        "Console(", "format_", "markup", "[bold", "[dim", "[cyan", "[green",
        "[red", "[yellow", "cardiac_monitor"
    }
    if any(pat in code_text for pat in formatting_patterns):
        responsibilities.add("Formatting & Display")

    # 3. Validation, Security & Schema Guards
    validation_patterns = {
        "validate", "is_protected_path", "redact", "permission", "broker",
        "schema", "audit", "hash", "sha256", "check_code", "allowlist"
    }
    if any(pat in code_text.lower() for pat in validation_patterns):
        responsibilities.add("Validation & Security")

    # 4. Orchestration & Lifecycle
    orchestration_patterns = {
        "run_session", "session_runner", "cycle", "iterations", "pause_until",
        "step", "standing_goal", "checkpoint", "loop", "handoff", "stop_file",
        "start_agent", "boot"
    }
    if any(pat in code_text.lower() for pat in orchestration_patterns):
        responsibilities.add("Lifecycle & Orchestration")

    # 5. UI Interaction & Event Handling
    ui_patterns = {
        "textual", "App", "Widget", "ComposeResult", "on_mount", "on_key",
        "on_input", "action_", "screen", "tui", "view", "full_screen"
    }
    if any(pat in code_text for pat in ui_patterns):
        responsibilities.add("UI & Interaction")

    # 6. External Communication & Subprocess / LLM
    external_patterns = {
        "subprocess", "run_process", "popen", "anthropic", "llmclient",
        "urllib", "http", "requests", "fetch_official_page", "ask_model"
    }
    if any(pat in code_text.lower() for pat in external_patterns):
        responsibilities.add("External / Subprocess / LLM")

    # 7. Command Handling & Dispatch
    command_patterns = {
        "handle_slash_command", "on_input_submitted", "execute_plugin_tool",
        "toolrunner.execute", "dispatch", "register_command", "build_parser",
        "/stop", "/goal", "/archive", "/models", "/plugins"
    }
    if any(pat in code_text.lower() for pat in command_patterns):
        responsibilities.add("Command Routing & Dispatch")

    # 8. Telemetry, Metrics & Decision Recording
    telemetry_patterns = {
        "eventlogger", "telemetry", "record_call", "record_execution",
        "record_build_route", "record_task_outcomes", "cost_ledger",
        "decision_summary", "metrics"
    }
    if any(pat in code_text.lower() for pat in telemetry_patterns):
        responsibilities.add("Telemetry & Decision Tracking")

    return responsibilities


def analyze_file(path: Path, current_package: str) -> FileAnalysis:
    """Analyze a single Python source file for god-file metrics."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    loc = len(lines)

    try:
        tree = ast.parse(text, filename=str(path))
    except Exception as exc:
        return FileAnalysis(
            path=path,
            rel_path=str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            loc=loc,
            num_classes=0,
            num_top_level_functions=0,
            class_methods={},
            max_methods_in_class=0,
            longest_functions=[],
            agent_import_fanout=set(),
            responsibilities=set(),
            max_constructor_collaborators=0,
            flags=[f"AST Parse Error: {exc}"],
        )

    num_classes = 0
    num_top_level_functions = 0
    class_methods: dict[str, int] = {}
    longest_functions: list[tuple[str, int]] = []
    agent_import_fanout: set[str] = set()
    max_constructor_collaborators = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            num_classes += 1
            methods = 0
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods += 1
                    flen = (item.end_lineno or item.lineno) - item.lineno + 1
                    longest_functions.append((f"{node.name}.{item.name}", flen))
                    if item.name == "__init__":
                        # Exclude 'self'
                        args = [a.arg for a in item.args.args if a.arg != "self"]
                        max_constructor_collaborators = max(max_constructor_collaborators, len(args))
            class_methods[node.name] = methods
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Check if this function is at top level
            if node in tree.body:
                num_top_level_functions += 1
            flen = (node.end_lineno or node.lineno) - node.lineno + 1
            longest_functions.append((node.name, flen))

    # Also walk nested functions/methods if any
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("agent."):
                    pkg = alias.name.split(".")[1]
                    if pkg != current_package:
                        agent_import_fanout.add(pkg)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("agent."):
                parts = node.module.split(".")
                if len(parts) > 1:
                    pkg = parts[1]
                    if pkg != current_package:
                        agent_import_fanout.add(pkg)

    responsibilities = identify_responsibilities(tree, text)
    max_methods = max(class_methods.values()) if class_methods else 0

    # Sort longest functions
    longest_functions.sort(key=lambda x: x[1], reverse=True)

    # Check God-file thresholds:
    # 1. LOC > 400
    # 2. Class with > 15 methods
    # 3. Function > 60 lines
    # 4. > 3 unrelated responsibilities
    # 5. Constructor wiring > 6 collaborators
    flags = []
    if loc > 400:
        flags.append(f"LOC > 400 ({loc})")
    if max_methods > 15:
        # Find classes
        large_classes = [f"{cls} ({cnt})" for cls, cnt in class_methods.items() if cnt > 15]
        flags.append(f"Class > 15 methods: {', '.join(large_classes)}")
    long_funcs = [f"{name} ({length} lines)" for name, length in longest_functions if length > 60]
    if long_funcs:
        flags.append(f"Functions > 60 lines: {len(long_funcs)} (longest: {long_funcs[0]})")
    if len(responsibilities) > 3:
        flags.append(f"Responsibilities > 3 ({len(responsibilities)}: {', '.join(sorted(responsibilities))})")
    if max_constructor_collaborators > 6:
        flags.append(f"Constructor wires > 6 collaborators ({max_constructor_collaborators})")

    rel_path = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    return FileAnalysis(
        path=path,
        rel_path=rel_path,
        loc=loc,
        num_classes=num_classes,
        num_top_level_functions=num_top_level_functions,
        class_methods=class_methods,
        max_methods_in_class=max_methods,
        longest_functions=longest_functions,
        agent_import_fanout=agent_import_fanout,
        responsibilities=responsibilities,
        max_constructor_collaborators=max_constructor_collaborators,
        flags=flags,
    )


def run_detection() -> list[FileAnalysis]:
    """Scan all Python modules in agent/ (excluding tests) and report findings."""
    agent_dir = REPO_ROOT / "agent"
    results: list[FileAnalysis] = []

    for path in sorted(agent_dir.rglob("*.py")):
        # Skip tests and __pycache__
        rel_parts = path.relative_to(REPO_ROOT).parts
        if "tests" in rel_parts or "__pycache__" in rel_parts:
            continue
        # current package is the folder directly inside agent/
        try:
            rel_to_agent = path.relative_to(agent_dir)
            current_pkg = rel_to_agent.parts[0] if len(rel_to_agent.parts) > 1 else ""
        except ValueError:
            current_pkg = ""

        analysis = analyze_file(path, current_pkg)
        results.append(analysis)

    # Sort by severity score descending
    results.sort(key=lambda x: x.severity_score, reverse=True)
    return results


def generate_markdown_report(results: list[FileAnalysis]) -> str:
    """Generate Markdown report for docs/god-file-refactor/00-detection-report.md."""
    god_files = [r for r in results if r.is_god_file]
    clean_files = [r for r in results if not r.is_god_file]

    lines = [
        "# God File Detection Report",
        "",
        "This report identifies candidate 'god files' in the SELF agent harness (`agent/`) "
        "according to static analysis criteria defined in the refactoring specification.",
        "",
        "## Detection Criteria",
        "- **LOC > 400**: Total line count exceeds 400.",
        "- **Class Methods > 15**: A single class defines more than 15 methods.",
        "- **Function Lines > 60**: A single function or method exceeds 60 lines.",
        "- **Responsibilities > 3**: Module exhibits more than 3 distinct architectural responsibilities.",
        "- **Constructor Wiring > 6**: A class constructor takes more than 6 dependency collaborators.",
        "",
        "## Summary of Findings",
        f"- **Total Files Analyzed**: {len(results)}",
        f"- **God Files Flagged**: {len(god_files)}",
        f"- **Compliant Files**: {len(clean_files)}",
        "",
        "## Ranked God Files Table",
        "",
        "| Rank | File | LOC | Classes | Max Methods | Long Funcs (>60L) | Fan-Out | Responsibilities | Flags |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for rank, r in enumerate(god_files, 1):
        num_long_funcs = sum(1 for _, l in r.longest_functions if l > 60)
        flag_summary = "<br>".join(r.flags)
        lines.append(
            f"| {rank} | `{r.rel_path}` | {r.loc} | {r.num_classes} | "
            f"{r.max_methods_in_class} | {num_long_funcs} | "
            f"{len(r.agent_import_fanout)} | {len(r.responsibilities)} | {flag_summary} |"
        )

    lines.extend([
        "",
        "## Detailed Analysis per Flagged God File",
        "",
    ])

    for rank, r in enumerate(god_files, 1):
        lines.extend([
            f"### {rank}. `{r.rel_path}` (LOC: {r.loc}, Severity Score: {r.severity_score})",
            "",
            f"- **Responsibilities ({len(r.responsibilities)})**: {', '.join(sorted(r.responsibilities))}",
            f"- **Agent Package Fan-Out ({len(r.agent_import_fanout)})**: `{', '.join(sorted(r.agent_import_fanout)) or 'None'}`",
            f"- **Max Methods in Single Class**: {r.max_methods_in_class}",
            f"- **Max Constructor Collaborators**: {r.max_constructor_collaborators}",
            "",
            "**Triggered Flags**:",
        ])
        for f in r.flags:
            lines.append(f"- {f}")

        long_funcs = [(name, l) for name, l in r.longest_functions if l > 60]
        if long_funcs:
            lines.extend([
                "",
                "**Functions / Methods > 60 lines**:",
            ])
            for name, l in long_funcs:
                lines.append(f"- `{name}`: {l} lines")

        lines.append("")

    lines.extend([
        "## Clean / Compliant Files",
        "",
        "| File | LOC | Classes | Functions | Responsibilities |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])
    for r in clean_files:
        lines.append(
            f"| `{r.rel_path}` | {r.loc} | {r.num_classes} | {r.num_top_level_functions} | "
            f"{len(r.responsibilities)} |"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Run detection, save markdown report, and print summary."""
    results = run_detection()
    god_files = [r for r in results if r.is_god_file]

    report_content = generate_markdown_report(results)
    output_dir = REPO_ROOT / "docs" / "god-file-refactor"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / "00-detection-report.md"
    report_file.write_text(report_content, encoding="utf-8")

    print("=" * 80)
    print(f"GOD FILE DETECTION COMPLETED: {len(god_files)} of {len(results)} files flagged.")
    print(f"Report saved to: {report_file.relative_to(REPO_ROOT)}")
    print("=" * 80)
    print(f"{'Rank':<5} {'File':<35} {'LOC':<6} {'Methods':<8} {'LongF':<6} {'FanOut':<7} {'Flags'}")
    print("-" * 80)
    for rank, r in enumerate(god_files, 1):
        num_long_funcs = sum(1 for _, l in r.longest_functions if l > 60)
        flags_brief = f"{len(r.flags)} flags: " + "; ".join(f.split(":")[0] for f in r.flags[:2])
        print(f"{rank:<5} {r.rel_path:<35} {r.loc:<6} {r.max_methods_in_class:<8} {num_long_funcs:<6} {len(r.agent_import_fanout):<7} {flags_brief}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
