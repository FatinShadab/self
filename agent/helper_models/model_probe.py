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
FETCH_CAP = 12_000
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
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
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
            result = {"ok": not failed, "name": name, "probe_id": probe_id,
                      "origin": "skipped_budget" if any(row.get("origin") == "skipped_budget"
                                                        for row in cases) else "model_probe",
                      "outcome": ("failed" if failed or objective_failed else
                                  "inconclusive" if inconclusive else "passed"),
                      "note": INCONCLUSIVE_NOTE, "cases": cases}
            self.logger.log("model_probe_completed", name=name, probe_id=probe_id,
                            completed_cases=len(cases), failed=failed,
                            inconclusive=inconclusive)
            return result
        finally:
            self.registry.finish_probe(name, probe_id, failed=failed or objective_failed,
                                       inconclusive=inconclusive)

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

    def research_model(self, name: str) -> dict[str, Any]:
        """Research official model information and save verified findings."""
        if name not in self.registry.names:
            valid, err = self.registry.validate_model_name(name)
            raise ValueError(err)
        entry = self.registry.get_model(name)
        if entry["status"] == "disabled":
            raise ValueError("Model is disabled")
        url = _official_url(self.provider, name)
        if url is None:
            return self.registry.record_research(name, status="no_official_page",
                                                 source_url=None, facts=[],
                                                 status_message="No official documentation URL is configured for this provider.")
        fetched = self.fetcher(url, self.logger)
        source_url = str(fetched.get("source_url") or url)
        parsed = urllib.parse.urlsplit(source_url)
        if parsed.scheme != "https" or parsed.hostname != urllib.parse.urlsplit(url).hostname:
            raise ValueError("Documentation source is outside the official host")
        body = str(fetched.get("body", ""))[:FETCH_CAP]
        status = fetched.get("status")
        facts = []
        total_params = None
        active_params = None
        context_window = None
        status_message = ""
        if status == 200 and fetched.get("content_type", "text/html") in {"text/html", "text/plain"}:
            parser = _Text()
            parser.feed(body)
            visible = " ".join(" ".join(parser.parts).split())[:FETCH_CAP]
            match = re.search(re.escape(name), visible, flags=re.I)
            if match:
                facts.append({"field": "model_name_mentioned", "value": name,
                              "excerpt": visible[max(0, match.start() - 100):match.end() + 100],
                              "origin": "web"})
            param_match = re.search(r"(\d+(?:\.\d+)?)\s*[Bb](?:illion)?\s*(?:total)?\s*(?:parameters|params)?", visible)
            if param_match:
                total_params = param_match.group(0).strip()
            ctx_match = re.search(r"(\d+[\d,]*)\s*(?:k|K)?\s*context", visible)
            if ctx_match:
                context_window = ctx_match.group(0).strip()
            research_status = "verified_mention" if facts else "fetched_no_model_fact"
        elif status == 404:
            visible = ""
            research_status = "no_official_page"
            status_message = "Official documentation page returned 404 Not Found"
        else:
            visible = ""
            research_status = "unreachable"
            status_message = "Official documentation page unreachable from container network"
        stored = self.registry.record_research(name, status=research_status,
                                               source_url=source_url,
                                               facts=facts,
                                               status_message=status_message,
                                               total_params=total_params,
                                               active_params=active_params,
                                               context_window=context_window)
        stored["status"] = research_status
        stored["status_message"] = status_message
        stored["source_url"] = source_url
        stored["body_excerpt"] = self.logger.redactor.text(visible[:4_000])
        return stored
