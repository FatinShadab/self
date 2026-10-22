"""SELF probe prompts."""
from __future__ import annotations

PROBE_SYSTEM_PROMPT = "You are taking a small public-data capability probe. Follow the user instruction exactly."

PROBE_CASES = (
    ("reasoning", "A shelf has four boxes with three pencils in each. Five pencils are taken away, then two are added. Reply with only the final integer."),
    ("summarization", "Summarize this passage in at most 20 words. Mention the new Saturday opening time and unchanged weekday hours: The town library moved its Saturday opening from 9 a.m. to 10 a.m. during repairs. Weekday hours did not change."),
    ("json", 'Return only a JSON object with exactly these fields and values: "status" is "ready" and "count" is 3.'),
    ("code", "Write only Python source for def triangular(n: int) -> int, returning 1+2+...+n for nonnegative n. Use one return expression with only n, integer constants, +, -, *, and //; no calls, imports, comments, or markdown."),
)
