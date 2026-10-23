"""Fact extraction from documentation text for configured models."""
from __future__ import annotations

import re
from typing import Any


def extract_model_facts(text: str, name: str, source_url: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extract model facts from text, ignoring navigation and header boilerplate.

    Returns (extracted_fields_dict, facts_list).
    Only returns a fact if its excerpt contains the extracted value.
    """
    fields: dict[str, Any] = {
        "total_params": None,
        "active_params": None,
        "context_window": None,
        "pricing": None,
        "speed": None,
        "strengths": None,
    }
    facts: list[dict[str, Any]] = []

    def _add_fact(field: str, value: str, match_span: tuple[int, int]) -> None:
        start = max(0, match_span[0] - 60)
        end = min(len(text), match_span[1] + 60)
        excerpt = text[start:end].strip()
        if value in excerpt:
            fields[field] = value
            facts.append({
                "field": field,
                "value": value,
                "excerpt": excerpt,
                "source_url": source_url,
                "origin": "web",
                "verified": True,
            })

    # 1. Total & Active params
    # Combined e.g. "550B total / 55B active" or "550B/55B active"
    combo = re.search(
        r"(?<![GgMmTtKk])\b(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*(?:total)?\s*[\/\\]\s*(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*active\b",
        text,
        re.I,
    )
    if combo:
        _add_fact("total_params", f"{combo.group(1)}B", combo.span(1))
        _add_fact("active_params", f"{combo.group(2)}B", combo.span(2))
    else:
        # Separate active params e.g. "55B active" or "active: 55B"
        act_match = re.search(
            r"(?<![GgMmTtKk])\b(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*active(?:\s*(?:parameters?|params?))?\b",
            text,
            re.I,
        )
        if not act_match:
            act_match = re.search(
                r"\bactive(?:\s*(?:parameters?|params?))?[:\s]+(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\b",
                text,
                re.I,
            )
        if act_match:
            _add_fact("active_params", f"{act_match.group(1)}B", act_match.span(1))

        # Separate total params e.g. "30B parameters", "4B parameter count", "550B total"
        tot_match = re.search(
            r"(?<![GgMmTtKk])\b(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*(?:total\s*)?(?:parameters?|params?)\b",
            text,
            re.I,
        )
        if not tot_match:
            tot_match = re.search(
                r"(?<![GgMmTtKk])\b(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*total\b",
                text,
                re.I,
            )
        if not tot_match:
            tot_match = re.search(
                r"\bparameter\s*count(?:\s*model)?[:\s]+(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\b",
                text,
                re.I,
            )
        if not tot_match and ":" in name:
            tag = name.split(":", 1)[1]
            tag_num = re.match(r"^(\d+(?:\.\d+)?)b$", tag, re.I)
            if tag_num:
                tag_re = re.search(
                    rf"\b{re.escape(name)}\b[^\n•]*?(?:•\s*)?(\d+(?:\.\d+)?)\s*[Bb]",
                    text,
                    re.I,
                )
                if tag_re:
                    tot_match = tag_re
        if tot_match:
            _add_fact("total_params", f"{tot_match.group(1)}B", tot_match.span(1))

    # 2. Context window e.g. "1M context window", "256K context window", "262k context"
    ctx_match = re.search(r"\b(\d+[\d,]*(?:\.\d+)?\s*[KkMm]?)\s*context(?:\s*window)?\b", text, re.I)
    if not ctx_match:
        ctx_match = re.search(r"\bcontext(?:\s*window)?[:\s]+(\d+[\d,]*(?:\.\d+)?\s*[KkMm]?)\b", text, re.I)
    if ctx_match:
        raw_val = ctx_match.group(1).strip()
        ctx_val = f"{raw_val} context window" if not raw_val.lower().endswith("context") else raw_val
        _add_fact("context_window", ctx_val, ctx_match.span(0))

    # 3. Pricing e.g. "free tier", "open source", "$0.15 / 1M tokens"
    price_match = re.search(
        r"\b(free\s*tier|open\s*source|free\s*to\s*use|\$\d+(?:\.\d+)?\s*\/\s*(?:1[Mm]|million)\s*tokens?)\b",
        text,
        re.I,
    )
    if not price_match:
        price_match = re.search(r"\bpricing[:\s]+([^.,\n]{3,40})", text, re.I)
    if price_match:
        val = price_match.group(1).strip()
        if not any(w in val.lower() for w in ("sign in", "download", "docs", "github")):
            _add_fact("pricing", val, price_match.span(1))

    # 4. Speed e.g. "120 tokens/sec", "speed: fast"
    speed_match = re.search(r"\b(\d+(?:\.\d+)?\s*(?:tokens?\/sec(?:ond)?|tps))\b", text, re.I)
    if not speed_match:
        speed_match = re.search(r"\b(?:speed|throughput|latency)[:\s]+([^.,\n]{3,40})", text, re.I)
    if speed_match:
        val = speed_match.group(1).strip()
        if not any(w in val.lower() for w in ("sign in", "download", "docs", "github")):
            _add_fact("speed", val, speed_match.span(1))

    # 5. Strengths e.g. "strengths: reasoning, coding"
    str_match = re.search(
        r"\b(?:strengths?|specialties|designed\s*for|suited\s*for)[:\s]+([^.,\n]{5,80})",
        text,
        re.I,
    )
    if str_match:
        val = str_match.group(1).strip()
        if not any(w in val.lower() for w in ("sign in", "download", "docs", "github")):
            _add_fact("strengths", val, str_match.span(1))

    return fields, facts
