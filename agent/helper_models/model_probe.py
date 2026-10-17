"""Fixed, bounded model probes and conservative official-document research."""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.llm.llm import BudgetExceeded, call_with_minimum, response_truncated
from agent.llm.model_registry import ModelRegistry

OUTPUT_CAP = 1_200
FETCH_CAP = 500_000
CODE_TIMEOUT_SECONDS = 2

PROBE_CASES = (
    ("reasoning", "A shelf has four boxes with three pencils in each. Five pencils are taken away, then two are added. Reply with only the final integer."),
    ("summarization", "Summarize this passage in at most 20 words. Mention the new Saturday opening time and unchanged weekday hours: The town library moved its Saturday opening from 9 a.m. to 10 a.m. during repairs. Weekday hours did not change."),
    ("json", 'Return only a JSON object with exactly these fields and values: "status" is "ready" and "count" is 3.'),
    ("code", "Write only Python source for def triangular(n: int) -> int, returning 1+2+...+n for nonnegative n. Use one return expression with only n, integer constants, +, -, *, and //; no calls, imports, comments, or markdown."),
)

INCONCLUSIVE_NOTE = "Treat inconclusive output as unknown, not as a model failure."


def _not_found(error: Exception) -> bool:
    return (getattr(error, "status_code", None) in {404, "404"}
            or type(error).__name__ == "NotFoundError")

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


def check_code_output(source: str, *, timeout: float = CODE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run a narrowly validated pure arithmetic function in an empty process."""
    if source.startswith("```"):
        source = re.sub(r"^```(?:python)?\s*|\s*```$", "", source.strip(), flags=re.I)
    if len(source) > 1_200:
        return {"passed": False, "reason": "source_too_long"}
    try:
        with tempfile.TemporaryDirectory() as empty_dir:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", _CODE_RUNNER],
                input=source, text=True, encoding="utf-8", capture_output=True,
                cwd=empty_dir, env={"PYTHONIOENCODING": "utf-8"},
                timeout=timeout, close_fds=True,
            )
    except subprocess.TimeoutExpired:
        return {"passed": False, "reason": "timeout"}
    except (OSError, ValueError):
        return {"passed": False, "reason": "sandbox_unavailable"}
    if completed.returncode == 0 and completed.stdout.strip() == "PASS":
        return {"passed": True, "reason": "passed"}
    return {"passed": False, "reason": "invalid_code_or_wrong_answer"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "header", "footer"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _official_url(provider: str, name: str) -> str | None:
    if provider == "ollama":
        slug = name.split(":", 1)[0]
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", slug):
            return "https://ollama.com/library/" + urllib.parse.quote(slug)
    if provider == "anthropic":
        return "https://docs.anthropic.com/en/docs/about-claude/models/overview"
    return None


def fetch_official_page(url: str, logger: EventLogger) -> dict[str, Any]:
    """Fetch and extract text from an official model page."""
    original_host = urllib.parse.urlsplit(url).hostname

    class OfficialRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                             headers: Any, newurl: str) -> Any:
            parsed = urllib.parse.urlsplit(newurl)
            if parsed.scheme != "https" or parsed.hostname != original_host:
                raise urllib.error.URLError("Documentation redirected outside the official host")
            logger.log("network_request", method="GET", host=parsed.hostname,
                       path=parsed.path or "/", purpose="model_research_redirect")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    parsed = urllib.parse.urlsplit(url)
    logger.log("network_request", method="GET", host=parsed.hostname or "",
               path=parsed.path or "/", purpose="model_research")
    opener = urllib.request.build_opener(OfficialRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "SELF-model-research/0.1"})
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(FETCH_CAP + 1)
            return {"status": response.status, "source_url": response.geturl(),
                    "body": raw[:FETCH_CAP].decode("utf-8", errors="replace"),
                    "content_type": response.headers.get_content_type(),
                    "truncated": len(raw) > FETCH_CAP}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "source_url": url, "body": "", "truncated": False}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": None, "source_url": url, "body": "", "truncated": False}


class ModelProber:
    """Probe configured helper models and research their capabilities."""

    def __init__(self, registry: ModelRegistry, llm: Any, logger: EventLogger,
                 session_id: str, provider: str, *, clock: Callable[[], float] = time.time,
                 code_checker: Callable[[str], dict[str, Any]] = check_code_output,
                 fetcher: Callable[[str, EventLogger], dict[str, Any]] = fetch_official_page) -> None:
        self.registry = registry
        self.llm = llm
        self.logger = logger
        self.session_id = session_id
        self.provider = provider
        self.clock = clock
        self.code_checker = code_checker
        self.fetcher = fetcher
        self.client_records_stats = getattr(getattr(llm, "client", None), "model_registry", None) is registry

    def probe_model(self, name: str) -> dict[str, Any]:
        """Probe a configured model and store observed capability results."""
        if name not in self.registry.names:
            valid, err = self.registry.validate_model_name(name)
            raise ValueError(err)
        probe_id = self.registry.begin_probe(name, self.session_id, now=self.clock())
        cases: list[dict[str, Any]] = []
        failed = True
        objective_failed = False
        inconclusive = False
        try:
            cap = self.registry.get_output_cap(name)
            for case_item in PROBE_CASES:
                kind, prompt = case_item[0], case_item[1]
                attempts: list[dict[str, Any]] = []
                for attempt in (1, 2):
                    started = time.monotonic()
                    try:
                        response = call_with_minimum(self.llm, cap,
                            system="You are taking a small public-data capability probe. Follow the user instruction exactly.",
                            messages=[{"role": "user", "content": prompt}], tools=[],
                            max_tokens=cap, model=name)
                    except BudgetExceeded:
                        row = {"case": kind, "attempt": attempt,
                               "outcome": "inconclusive", "origin": "skipped_budget",
                               "passed": None, "check": "budget_unavailable",
                               "latency_ms": round((time.monotonic() - started) * 1000),
                               "input_tokens": None, "output_tokens": None,
                               "max_output_tokens": cap, "effective_cap": None,
                               "stop_reason": None, "raw_output": "", "truncated": False}
                        attempts.append(row)
                        self.logger.log("model_probe_case", name=name, probe_id=probe_id, **row)
                        break
                    except Exception as exc:
                        elapsed = round((time.monotonic() - started) * 1000)
                        not_found = _not_found(exc)
                        if not self.client_records_stats:
                            self.registry.record_call(name, failed=True, latency_ms=elapsed,
                                                      not_found=not_found)
                        elif not_found:
                            self.registry.mark_not_found(name)
                        row = {"case": kind, "attempt": attempt, "outcome": "failed",
                               "passed": False, "error_type": type(exc).__name__,
                               "error_kind": "not_found" if not_found else "call_error",
                               "message": ("The endpoint did not recognize this configured model name."
                                           if not_found else "Model call failed."),
                               "latency_ms": elapsed, "input_tokens": None,
                               "output_tokens": None, "max_output_tokens": cap,
                               "effective_cap": None,
                               "stop_reason": None, "raw_output": "", "truncated": False}
                        attempts.append(row)
                        self.logger.log("model_probe_case", name=name, probe_id=probe_id, **row)
                        break
                    elapsed = round((time.monotonic() - started) * 1000)
                    if not self.client_records_stats:
                        self.registry.record_call(name, failed=False, latency_ms=elapsed)
                    raw = "\n".join(str(block.get("text", "")) for block in response.content
                                    if block.get("type") == "text").strip()
                    text = self.logger.redactor.text(raw)
                    cap_used = response.max_output_tokens or cap
                    truncated = response_truncated(response, cap) or len(text) > OUTPUT_CAP
                    check = self._check(kind, raw) if raw and not truncated else {"passed": None, "reason": "no_complete_output"}
                    outcome = ("inconclusive" if not raw or truncated else
                               "passed" if check["passed"] else "failed")
                    self.registry.record_probe_outcome(name, outcome)
                    row = {"case": kind, "attempt": attempt, "outcome": outcome,
                           "passed": check["passed"], "check": check["reason"],
                           "fenced_json": bool(check.get("fenced_json", False)),
                           "latency_ms": elapsed, "input_tokens": response.input_tokens,
                           "output_tokens": response.output_tokens,
                           "max_output_tokens": cap_used,
                           "effective_cap": cap_used,
                           "stop_reason": response.stop_reason,
                           "raw_output": text[:OUTPUT_CAP], "truncated": truncated}
                    attempts.append(row)
                    self.logger.log("model_probe_case", name=name, probe_id=probe_id, **row)
                    if raw or attempt == 2:
                        break
                final = {**attempts[-1], "attempts": attempts}
                cases.append(final)
                if "error_type" in final or final.get("origin") == "skipped_budget":
                    break
            failed = any("error_type" in row for row in cases)
            objective_failed = any(row["outcome"] == "failed" for row in cases)
            inconclusive = (not failed and not objective_failed and
                            (len(cases) < len(PROBE_CASES) or
                             any(row["outcome"] == "inconclusive" for row in cases)))
            probe_latencies = [row.get("latency_ms") for row in cases if row.get("latency_ms") is not None]
            probe_avg_latency = round(sum(probe_latencies) / len(probe_latencies)) if probe_latencies else None
            result = {"ok": not failed, "name": name, "probe_id": probe_id,
                      "origin": "skipped_budget" if any(row.get("origin") == "skipped_budget"
                                                        for row in cases) else "model_probe",
                      "outcome": ("failed" if failed or objective_failed else
                                  "inconclusive" if inconclusive else "passed"),
                      "probe_latency_ms": probe_avg_latency,
                      "note": INCONCLUSIVE_NOTE, "cases": cases}
            self.logger.log("model_probe_completed", name=name, probe_id=probe_id,
                            completed_cases=len(cases), failed=failed,
                            inconclusive=inconclusive)
            return result
        finally:
            probe_latencies = [row.get("latency_ms") for row in cases if row.get("latency_ms") is not None]
            probe_avg_latency = round(sum(probe_latencies) / len(probe_latencies)) if probe_latencies else None
            self.registry.finish_probe(name, probe_id, failed=failed or objective_failed,
                                       inconclusive=inconclusive, latency_ms=probe_avg_latency)

    def _check(self, kind: str, text: str) -> dict[str, Any]:
        if kind == "reasoning":
            passed = text.strip() == "9"
            return {"passed": passed, "reason": "exact_answer" if passed else "wrong_answer"}
        if kind == "summarization":
            passed = len(text.split()) <= 20 and "10" in text and "weekday" in text.casefold()
            return {"passed": passed, "reason": "format_and_anchors" if passed else "format_or_anchor_failed"}
        if kind == "json":
            try:
                passed = json.loads(text) == {"status": "ready", "count": 3}
            except (ValueError, TypeError):
                passed = False
            fenced_json = False
            if not passed:
                fenced = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", text, re.I | re.S)
                if fenced:
                    try:
                        json.loads(fenced.group(1))
                        fenced_json = True
                    except (ValueError, TypeError):
                        pass
            return {"passed": passed, "reason": "valid_json" if passed else "invalid_json_or_values",
                    "fenced_json": fenced_json}
        return self.code_checker(text)

    def research_model(self, name: str, *, facts: list[dict[str, Any]] | dict[str, Any] | None = None) -> dict[str, Any]:
        """Research official model information and save verified findings."""
        if name not in self.registry.names:
            valid, err = self.registry.validate_model_name(name)
            raise ValueError(err)
        entry = self.registry.get_model(name)
        if entry["status"] == "disabled":
            raise ValueError("Model is disabled")
        url = _official_url(self.provider, name)
        if url is None:
            stored = self.registry.record_research(name, status="no_official_page",
                                                   source_url=None, facts=[], urls_tried=[],
                                                   status_message="No official documentation URL is configured for this provider.")
            stored["status"] = "no_official_page"
            stored["status_message"] = "No official documentation URL is configured for this provider."
            stored["source_url"] = None
            stored["urls_tried"] = []
            stored["body_excerpt"] = ""
            return stored
        urls_tried = [url]
        fetched = self.fetcher(url, self.logger)
        source_url = str(fetched.get("source_url") or url)
        parsed = urllib.parse.urlsplit(source_url)
        if parsed.scheme != "https" or parsed.hostname != urllib.parse.urlsplit(url).hostname:
            raise ValueError("Documentation source is outside the official host")
        status = fetched.get("status")
        if status == 404:
            msg = f"Official documentation page returned HTTP {status} Not Found"
            stored = self.registry.record_research(name, status="not_found",
                                                   source_url=source_url,
                                                   urls_tried=urls_tried,
                                                   facts=[],
                                                   status_message=msg)
            stored["status"] = "not_found"
            stored["status_message"] = msg
            stored["source_url"] = source_url
            stored["urls_tried"] = urls_tried
            stored["body_excerpt"] = ""
            return stored
        if status != 200:
            msg = "Official documentation page unreachable from container network"
            stored = self.registry.record_research(name, status="unreachable",
                                                   source_url=source_url,
                                                   urls_tried=urls_tried,
                                                   facts=[],
                                                   status_message=msg)
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
        if self.provider == "ollama":
            tags_url = f"{url}/tags"
            urls_tried.append(tags_url)
            fetched_tags = self.fetcher(tags_url, self.logger)
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

        stored = self.registry.record_research(name, status=research_status,
                                               source_url=source_url,
                                               urls_tried=urls_tried,
                                               facts=all_facts,
                                               status_message=status_message,
                                               total_params=extracted_fields["total_params"],
                                               active_params=extracted_fields["active_params"],
                                               context_window=extracted_fields["context_window"],
                                               pricing=extracted_fields["pricing"],
                                               speed=extracted_fields["speed"],
                                               strengths=extracted_fields["strengths"])
        stored["status"] = research_status
        stored["status_message"] = status_message
        stored["source_url"] = source_url
        stored["urls_tried"] = urls_tried
        stored["body_excerpt"] = self.logger.redactor.text(combined_text[:4_000])
        return stored


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
    combo = re.search(r"(?<![GgMmTtKk])\b(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*(?:total)?\s*[\/\\]\s*(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*active\b", text, re.I)
    if combo:
        _add_fact("total_params", f"{combo.group(1)}B", combo.span(1))
        _add_fact("active_params", f"{combo.group(2)}B", combo.span(2))
    else:
        # Separate active params e.g. "55B active" or "active: 55B"
        act_match = re.search(r"(?<![GgMmTtKk])\b(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*active(?:\s*(?:parameters?|params?))?\b", text, re.I)
        if not act_match:
            act_match = re.search(r"\bactive(?:\s*(?:parameters?|params?))?[:\s]+(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\b", text, re.I)
        if act_match:
            _add_fact("active_params", f"{act_match.group(1)}B", act_match.span(1))

        # Separate total params e.g. "30B parameters", "4B parameter count", "550B total"
        tot_match = re.search(r"(?<![GgMmTtKk])\b(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*(?:total\s*)?(?:parameters?|params?)\b", text, re.I)
        if not tot_match:
            tot_match = re.search(r"(?<![GgMmTtKk])\b(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\s*total\b", text, re.I)
        if not tot_match:
            tot_match = re.search(r"\bparameter\s*count(?:\s*model)?[:\s]+(\d+(?:\.\d+)?)\s*(?:[Bb]|billion)\b", text, re.I)
        if not tot_match and ":" in name:
            tag = name.split(":", 1)[1]
            tag_num = re.match(r"^(\d+(?:\.\d+)?)b$", tag, re.I)
            if tag_num:
                tag_re = re.search(rf"\b{re.escape(name)}\b[^\n•]*?(?:•\s*)?(\d+(?:\.\d+)?)\s*[Bb]", text, re.I)
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
    price_match = re.search(r"\b(free\s*tier|open\s*source|free\s*to\s*use|\$\d+(?:\.\d+)?\s*\/\s*(?:1[Mm]|million)\s*tokens?)\b", text, re.I)
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
    str_match = re.search(r"\b(?:strengths?|specialties|designed\s*for|suited\s*for)[:\s]+([^.,\n]{5,80})", text, re.I)
    if str_match:
        val = str_match.group(1).strip()
        if not any(w in val.lower() for w in ("sign in", "download", "docs", "github")):
            _add_fact("strengths", val, str_match.span(1))

    return fields, facts
