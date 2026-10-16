"""Check production Python modules and public APIs for missing docstrings."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def missing_docstrings(path: Path) -> list[str]:
    """Return public symbols without PEP 257 style docstrings in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    missing: list[str] = []
    if not ast.get_docstring(tree):
        missing.append("module")

    def visit(node: ast.AST, parent: str = "") -> None:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        if node.name.startswith("_"):
            return
        name = f"{parent}.{node.name}" if parent else node.name
        if not ast.get_docstring(node):
            missing.append(name)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                visit(child, name)

    for item in tree.body:
        visit(item)
    return missing


def main() -> int:
    """Report undocumented production APIs and return a failing status if found."""
    problems: list[str] = []
    checked = 0
    for package in ("agent", "eval"):
        for path in sorted((ROOT / package).rglob("*.py")):
            if "tests" in path.relative_to(ROOT).parts:
                continue
            checked += 1
            for name in missing_docstrings(path):
                problems.append(f"{path.relative_to(ROOT)}: {name}")
    if problems:
        print("\n".join(problems))
        return 1
    print(f"Docstrings present in {checked} production modules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
