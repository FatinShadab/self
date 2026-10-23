"""Narrowly validated execution of pure arithmetic function in an empty process."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from typing import Any, Callable

CODE_TIMEOUT_SECONDS = 2

_CODE_RUNNER = """import ast, sys
source = sys.stdin.read(1201)
tree = ast.parse(source)
allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
           ast.BinOp, ast.Name, ast.Load, ast.Constant, ast.Add, ast.Sub,
           ast.Mult, ast.FloorDiv, ast.Div, ast.Mod, ast.UnaryOp, ast.USub)
if len(source) > 1200 or len(tree.body) != 1 or len(list(ast.walk(tree))) > 50:
    raise ValueError('invalid source size or shape')
fn = tree.body[0]
if not isinstance(fn, ast.FunctionDef) or fn.name != 'triangular' or len(fn.args.args) != 1 or fn.args.args[0].arg != 'n' or len(fn.body) != 1 or not isinstance(fn.body[0], ast.Return) or fn.decorator_list or fn.args.defaults:
    raise ValueError('invalid function')
for node in ast.walk(tree):
    if not isinstance(node, allowed) or isinstance(node, ast.Name) and node.id not in ('n', 'int') or isinstance(node, ast.Constant) and (type(node.value) is not int or abs(node.value) > 1000000):
        raise ValueError('disallowed syntax')
scope = {'__builtins__': {}, 'int': int}
exec(compile(tree, '<probe>', 'exec'), scope)
fn = scope['triangular']
if not all(type(fn(n)) is int and fn(n) == expected for n, expected in ((0, 0), (1, 1), (4, 10), (7, 28))):
    raise ValueError('wrong answer')
print('PASS')
"""


def execute_code_check(
    source: str,
    *,
    timeout: float = CODE_TIMEOUT_SECONDS,
    subprocess_run: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Run a narrowly validated pure arithmetic function in an empty process."""
    if source.startswith("```"):
        source = re.sub(r"^```(?:python)?\s*|\s*```$", "", source.strip(), flags=re.I)
    if len(source) > 1_200:
        return {"passed": False, "reason": "source_too_long"}
    try:
        with tempfile.TemporaryDirectory() as empty_dir:
            completed = subprocess_run(
                [sys.executable, "-I", "-S", "-B", "-c", _CODE_RUNNER],
                input=source,
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=empty_dir,
                env={"PYTHONIOENCODING": "utf-8"},
                timeout=timeout,
                close_fds=True,
            )
    except subprocess.TimeoutExpired:
        return {"passed": False, "reason": "timeout"}
    except (OSError, ValueError):
        return {"passed": False, "reason": "sandbox_unavailable"}
    if completed.returncode == 0 and completed.stdout.strip() == "PASS":
        return {"passed": True, "reason": "passed"}
    return {"passed": False, "reason": "invalid_code_or_wrong_answer"}
