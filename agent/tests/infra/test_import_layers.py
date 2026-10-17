"""Keep the image-owned harness import graph acyclic and layered."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


# Dependencies point to an equal or lower rank. Identity precedes runtime
# because AgentLoop constructs IdentityStore in the existing behavior.
# Body is at Layer 1 alongside LLM; it depends only on infra (Layer 0) and
# exposes environmental capabilities and sensing to tools and runtime.
LAYER = {
    "infra": 0,
    "llm": 1,
    "body": 1,
    "tools": 2,
    "learning": 2,
    "helper_models": 2,
    "identity": 2,
    "runtime": 3,
    "session": 4,
    "reporting": 4,
    "ui": 5,
}



class ImportLayerTests(unittest.TestCase):
    def test_harness_imports_are_acyclic_and_downward(self) -> None:
        root = Path(__file__).resolve().parents[2]
        files = {
            ".".join(path.relative_to(root.parent).with_suffix("").parts): path
            for package in LAYER
            for path in (root / package).rglob("*.py")
        }
        graph: dict[str, set[str]] = {name: set() for name in files}
        for source, path in files.items():
            source_layer = source.split(".")[1]
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    targets = [node.module]
                for target in targets:
                    if not target.startswith("agent."):
                        continue
                    parts = target.split(".")
                    if len(parts) < 3 or parts[1] not in LAYER:
                        continue
                    self.assertLessEqual(LAYER[parts[1]], LAYER[source_layer],
                                         f"upward import: {source} -> {target}")
                    if target in graph:
                        graph[source].add(target)
                    elif target + ".__init__" in graph:
                        graph[source].add(target + ".__init__")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(module: str) -> None:
            self.assertNotIn(module, visiting, f"import cycle reaches {module}")
            if module in visited:
                return
            visiting.add(module)
            for child in graph[module]:
                visit(child)
            visiting.remove(module)
            visited.add(module)

        for module in graph:
            visit(module)
