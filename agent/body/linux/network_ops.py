"""Network access operations: HTTP GET and local Ollama endpoint probing."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.redirect_handler import _LoggingRedirectHandler


def log_network(logger: EventLogger, url: str, method: str = "GET", **extra: Any) -> None:
    """Log an outgoing network request event."""
    parsed = urllib.parse.urlsplit(url)
    logger.log(
        "network_request",
        method=method,
        host=parsed.hostname or "",
        path=parsed.path or "/",
        **extra,
    )


def http_get_request(
    url: str,
    timeout: float,
    max_chars: int,
    output_cap: int,
    logger: EventLogger,
) -> dict[str, Any]:
    """Fetch a URL and record observable network access."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("http_get requires an http:// or https:// URL with a host")
    limit = max(1, min(int(max_chars), output_cap))

    def on_redirect(redir_url: str, method: str = "GET", **extra: Any) -> None:
        log_network(logger, redir_url, method=method, **extra)

    log_network(logger, url)
    opener = urllib.request.build_opener(_LoggingRedirectHandler(on_redirect))
    request = urllib.request.Request(url, headers={"User-Agent": "SELF/0.2"}, method="GET")
    try:
        with opener.open(request, timeout=max(0.1, float(timeout))) as response:
            body = response.read(limit + 1)
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            status = response.status
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        body = exc.read(limit + 1)
        content_type = exc.headers.get_content_type() if exc.headers else "text/plain"
        charset = exc.headers.get_content_charset() if exc.headers else None
        charset = charset or "utf-8"
        status = exc.code
        final_url = exc.geturl()
    final = urllib.parse.urlsplit(final_url)
    return {
        "status": status,
        "host": final.hostname or "",
        "path": final.path or "/",
        "content_type": content_type,
        "body": body[:limit].decode(charset, errors="replace"),
        "truncated": len(body) > limit,
    }


def probe_local_ollama_endpoint(logger: EventLogger) -> dict[str, Any]:
    """Check local Ollama availability without starting or pulling a model."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    parsed = urllib.parse.urlsplit(base_url)
    logger.log(
        "network_request",
        method="GET",
        host=parsed.hostname or "",
        path=f"{parsed.path}/api/tags",
        purpose="local_ollama_probe",
    )
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [str(item.get("name", "")) for item in payload.get("models", []) if item.get("name")]
        available = bool(models)
        return {
            "ok": available,
            "reachable": True,
            "models": models,
            "message": (
                "Local Ollama reachable."
                if available
                else "Ollama is reachable but no model is installed; no download was attempted."
            ),
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "ok": False,
            "reachable": False,
            "models": [],
            "message": f"Local Ollama is not reachable on {base_url}: {type(exc).__name__}.",
        }
