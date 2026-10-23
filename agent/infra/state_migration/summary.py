"""Deterministic bounded summarization for cycle reports and memories."""
from __future__ import annotations

import re


def deterministic_summary(text: str, max_chars: int = 280) -> str:
    """Produce a deterministic bounded summary of cycle-report text.

    Rules (applied in order):
    1. Empty input -> sentinel string.
    2. Already <= max_chars -> returned unchanged (no report file).
    3. Strip markdown noise and boilerplate header lines.
    4. Prefer a "findings" section if one is present.
    5. Otherwise: first sentence + (if room) last sentence.
    6. Cut at a sentence/clause boundary; append ellipsis only when truncated.
    """
    if not text:
        return "Cycle completed without a textual report."

    # 1. Collapse unicode non-breaking / thin spaces to regular space
    text = text.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2011", "-")

    # 2. Line cleaning & section parsing
    _md_inline = re.compile(r"\*{1,2}([^*]*?)\*{1,2}|`([^`]*)`")
    _md_header = re.compile(r"^#+\s*")
    _md_list = re.compile(r"^\s*(\d+\.|\d+\)|\*|-|\+|[>|])\s+")

    def clean_text(s: str) -> str:
        s = _md_header.sub("", s)
        s = _md_list.sub("", s)
        s = _md_inline.sub(lambda m: m.group(1) or m.group(2) or "", s)
        return s.strip()

    # Priority ranking for findings sections:
    _p1 = re.compile(
        r"^(?:what\s+i\s+discovered|discoveries|verified\s+discoveries|key\s+verified\s+findings|findings|what\s+i\s+learned|new\s+knowledge|new\s+verified\s+entries)",
        re.IGNORECASE,
    )
    _p2 = re.compile(
        r"^(?:recorded\s+observation|what\s+i\s+observed|what\s+i\s+explored|lesson|result)",
        re.IGNORECASE,
    )
    _p3 = re.compile(
        r"^(?:what\s+i\s+did|action\s+taken|narrative|narration)",
        re.IGNORECASE,
    )
    _p4 = re.compile(
        r"^(?:(?:best\s+)?next\s+(?:steps?|actions?|recommended)|what[’\']?s\s+next)",
        re.IGNORECASE,
    )

    _title = re.compile(
        r"^(?:cycle\s*[\u2011\-]?\s*\d+|exploration\s+cycle\s*\d+)",
        re.IGNORECASE,
    )

    sections: list[tuple[int, str, list[str]]] = []
    current_rank = 3
    current_header = "body"
    current_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cleaned = clean_text(line)
        if not cleaned:
            continue

        hdr_candidate = cleaned.strip(":*# -")

        if _title.match(hdr_candidate):
            continue

        is_header = False
        rank = 3
        if _p1.match(hdr_candidate):
            is_header = True
            rank = 1
        elif _p2.match(hdr_candidate):
            is_header = True
            rank = 2
        elif _p3.match(hdr_candidate):
            is_header = True
            rank = 3
        elif _p4.match(hdr_candidate):
            is_header = True
            rank = 4

        if is_header:
            if current_lines:
                sections.append((current_rank, current_header, current_lines))
            current_rank = rank
            current_header = hdr_candidate
            current_lines = []
            colon_idx = cleaned.find(":")
            if colon_idx != -1 and colon_idx < len(cleaned) - 1:
                after_col = cleaned[colon_idx + 1 :].strip()
                if after_col:
                    current_lines.append(after_col)
        else:
            current_lines.append(cleaned)

    if current_lines:
        sections.append((current_rank, current_header, current_lines))

    # Pick the best section by rank
    sections.sort(key=lambda s: s[0])

    chosen_rank = 3
    chosen_lines: list[str] = []
    if sections:
        chosen_rank = sections[0][0]
        chosen_lines = sections[0][2]

    body = " ".join(chosen_lines)
    body = re.sub(r"\s{2,}", " ", body).strip()

    if not body:
        body_lines = [
            clean_text(l)
            for l in text.splitlines()
            if clean_text(l) and not _title.match(clean_text(l))
        ]
        body = " ".join(body_lines)
        body = re.sub(r"\s{2,}", " ", body).strip()
        chosen_rank = 3

    if chosen_rank >= 3 and len(body) > max_chars:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Za-z0-9])", body) if s.strip()]
        if len(sentences) >= 3:
            combined = f"{sentences[0]} … {sentences[-1]}"
            if len(combined) <= max_chars:
                return combined
            body = combined
        elif len(sentences) == 2:
            combined = f"{sentences[0]} {sentences[1]}"
            if len(combined) <= max_chars:
                return combined
            body = combined

    if len(body) <= max_chars:
        return body

    # 5. Cut at a boundary
    budget = max_chars - 1  # leave room for ellipsis char
    window_start = budget - max(1, budget // 5)  # last 20% of budget

    # Prefer sentence-end boundary (. ! ?)
    for end_char in ".!?":
        idx = body.rfind(end_char, window_start, budget)
        if idx != -1:
            return body[: idx + 1] + "…"

    # Fall back to clause boundary (; ,)
    for end_char in ";,":
        idx = body.rfind(end_char, window_start, budget)
        if idx != -1:
            return body[: idx + 1] + "…"

    # Fall back to word boundary
    idx = body.rfind(" ", window_start, budget)
    if idx != -1:
        return body[:idx] + "…"

    # Hard cut
    return body[:budget] + "…"
