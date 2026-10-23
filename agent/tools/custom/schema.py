"""AST-based schema extraction and validation from Python source code."""
from __future__ import annotations

import ast
from typing import Any


def schema_from_code(code: str) -> dict[str, Any]:
    """Derive a tool argument schema from Python source."""
    tree = ast.parse(code)
    explicit = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "INPUT_SCHEMA" for t in node.targets
        ):
            explicit = ast.literal_eval(node.value)
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run"
    ]
    if len(functions) != 1:
        raise ValueError("tool.py must define exactly one synchronous run(...) function")
    function = functions[0]
    if function.args.vararg or function.args.kwarg or function.args.posonlyargs:
        raise ValueError("run must use named arguments without *args, **kwargs or positional-only args")
    args = function.args.args + function.args.kwonlyargs
    if explicit is not None:
        if not isinstance(explicit, dict) or explicit.get("type") != "object":
            raise ValueError("INPUT_SCHEMA must be a literal JSON object schema")
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(explicit)
        properties = explicit.get("properties", {})
        if set(properties) != {arg.arg for arg in args}:
            raise ValueError("INPUT_SCHEMA properties must match run's named arguments")
        return explicit
    types = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }
    properties = {}
    required = []
    defaults = (
        [None] * (len(function.args.args) - len(function.args.defaults))
        + function.args.defaults
        + function.args.kw_defaults
    )
    for arg, default in zip(args, defaults):
        annotation = arg.annotation
        type_name = annotation.id if isinstance(annotation, ast.Name) else None
        if isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Name):
            type_name = annotation.value.id
        if type_name not in types:
            raise ValueError(f"Add a supported annotation or INPUT_SCHEMA for argument {arg.arg}")
        field: dict[str, Any] = {"type": types[type_name]}
        if default is None:
            required.append(arg.arg)
        else:
            field["default"] = ast.literal_eval(default)
        properties[arg.arg] = field
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
