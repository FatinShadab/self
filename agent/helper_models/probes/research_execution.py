"""Execution of official documentation research and model knowledge extraction."""
from __future__ import annotations

import urllib.parse
from typing import Any

from agent.helper_models.probes.fact_extraction import extract_model_facts
from agent.helper_models.probes.official_docs import _Text, official_url


def execute_model_research(
    prober: Any,
    name: str,
    *,
    facts: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Research official model information and save verified findings."""
    if name not in prober.registry.names:
        valid, err = prober.registry.validate_model_name(name)
        raise ValueError(err)
    entry = prober.registry.get_model(name)
    if entry["status"] == "disabled":
        raise ValueError("Model is disabled")
    url = official_url(prober.provider, name)
    if url is None:
        stored = prober.registry.record_research(
            name,
            status="no_official_page",
            source_url=None,
            facts=[],
            urls_tried=[],
            status_message="No official documentation URL is configured for this provider.",
        )
        stored["status"] = "no_official_page"
        stored["status_message"] = "No official documentation URL is configured for this provider."
        stored["source_url"] = None
        stored["urls_tried"] = []
        stored["body_excerpt"] = ""
        return stored
    urls_tried = [url]
    fetched = prober.fetcher(url, prober.logger)
    source_url = str(fetched.get("source_url") or url)
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme != "https" or parsed.hostname != urllib.parse.urlsplit(url).hostname:
        raise ValueError("Documentation source is outside the official host")
    status = fetched.get("status")
    if status == 404:
        msg = f"Official documentation page returned HTTP {status} Not Found"
        stored = prober.registry.record_research(
            name,
            status="not_found",
            source_url=source_url,
            urls_tried=urls_tried,
            facts=[],
            status_message=msg,
        )
        stored["status"] = "not_found"
        stored["status_message"] = msg
        stored["source_url"] = source_url
        stored["urls_tried"] = urls_tried
        stored["body_excerpt"] = ""
        return stored
    if status != 200:
        msg = "Official documentation page unreachable from current network"
        stored = prober.registry.record_research(
            name,
            status="unreachable",
            source_url=source_url,
            urls_tried=urls_tried,
            facts=[],
            status_message=msg,
        )
        stored["status"] = "unreachable"
        stored["status_message"] = msg
        stored["source_url"] = source_url
        stored["urls_tried"] = urls_tried
        stored["body_excerpt"] = ""
        return stored

    # Parse main library page body
    body = str(fetched.get("body", ""))
    parser = _Text()
    parser.feed(body)
    main_visible = " ".join(" ".join(parser.parts).split())
    all_visible = [main_visible]

    # Try tags page if provider is ollama
    if prober.provider == "ollama":
        tags_url = f"{url}/tags"
        urls_tried.append(tags_url)
        fetched_tags = prober.fetcher(tags_url, prober.logger)
        if fetched_tags.get("status") == 200:
            tags_parser = _Text()
            tags_parser.feed(str(fetched_tags.get("body", "")))
            tags_visible = " ".join(" ".join(tags_parser.parts).split())
            all_visible.append(tags_visible)

    combined_text = "\n".join(all_visible)
    extracted_fields, extracted_facts = extract_model_facts(combined_text, name, source_url)

    # Include any caller-supplied model_knowledge facts
    model_knowledge_facts: list[dict[str, Any]] = []
    if facts:
        if isinstance(facts, dict):
            for k, v in facts.items():
                if v is not None:
                    model_knowledge_facts.append({
                        "field": str(k)[:80],
                        "value": str(v)[:500],
                        "excerpt": f"agent model knowledge: {k}={v}",
                        "source_url": None,
                        "origin": "model_knowledge",
                        "verified": False,
                    })
        elif isinstance(facts, list):
            for item in facts:
                if isinstance(item, dict) and item.get("field") and item.get("value") is not None:
                    model_knowledge_facts.append({
                        "field": str(item["field"])[:80],
                        "value": str(item["value"])[:500],
                        "excerpt": str(item.get("excerpt", f"agent model knowledge: {item['field']}={item['value']}"))[:500],
                        "source_url": None,
                        "origin": "model_knowledge",
                        "verified": False,
                    })

    all_facts = [*extracted_facts, *model_knowledge_facts]
    research_status = "facts_found" if extracted_facts else "fetched_no_model_fact"
    status_message = "" if extracted_facts else "No verified model facts found on official documentation page."

    # If a field was not found in web facts but present in model_knowledge, fill it
    for mk_fact in model_knowledge_facts:
        fld = mk_fact["field"]
        if fld in extracted_fields and extracted_fields[fld] is None:
            extracted_fields[fld] = mk_fact["value"]

    stored = prober.registry.record_research(
        name,
        status=research_status,
        source_url=source_url,
        urls_tried=urls_tried,
        facts=all_facts,
        status_message=status_message,
        total_params=extracted_fields["total_params"],
        active_params=extracted_fields["active_params"],
        context_window=extracted_fields["context_window"],
        pricing=extracted_fields["pricing"],
        speed=extracted_fields["speed"],
        strengths=extracted_fields["strengths"],
    )
    stored["status"] = research_status
    stored["status_message"] = status_message
    stored["source_url"] = source_url
    stored["urls_tried"] = urls_tried
    stored["body_excerpt"] = prober.logger.redactor.text(combined_text[:4_000])
    return stored
