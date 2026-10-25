"""Extract and update the First 10 Cycle 1 Tool Actions section in acceptance reports."""
from __future__ import annotations

import json
from pathlib import Path

reports = [
    Path("docs/reports/discovery-acceptance-windows.md"),
    Path("docs/reports/discovery-acceptance-wsl.md"),
    Path("docs/reports/discovery-acceptance-docker.md"),
]

for rep_path in reports:
    if not rep_path.exists():
        continue
    with open(rep_path, "rb") as f:
        b = f.read()

    # Extract calls
    text = b.decode("utf-8")
    calls = text.split("### Call ")
    c1_actions = []
    for call_block in calls[1:]:
        if "```json" in call_block:
            json_str = call_block.split("```json", 1)[1].split("```", 1)[0].strip()
            try:
                data = json.loads(json_str)
                for item in data:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        c1_actions.append({
                            "tool": item.get("name"),
                            "arguments": item.get("input"),
                        })
                        if len(c1_actions) >= 10:
                            break
            except Exception:
                pass
        if len(c1_actions) >= 10:
            break

    idx1 = b.find(b"## 2. First 10 Cycle 1 Tool Actions")
    idx2 = b.find(b"## 3. Raw Environment Map", idx1)
    if idx1 != -1 and idx2 != -1:
        prefix = b[:idx1]
        suffix = b[idx2:]
        nl = b"\r\n" if b"\r\n" in b else b"\n"
        actions_json = json.dumps(c1_actions, indent=2).encode("utf-8")
        if nl == b"\r\n":
            actions_json = actions_json.replace(b"\n", b"\r\n")
        new_section = (
            b"## 2. First 10 Cycle 1 Tool Actions"
            + nl
            + b"```json"
            + nl
            + actions_json
            + nl
            + b"```"
            + nl
            + nl
        )
        with open(rep_path, "wb") as f:
            f.write(prefix + new_section + suffix)
        print(f"Updated {rep_path.name} with {len(c1_actions)} actions.")
    else:
        print(f"Indices not found for {rep_path.name}")
