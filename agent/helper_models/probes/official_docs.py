"""HTML parsing and official documentation fetching for model research."""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from agent.infra.event_log import EventLogger

FETCH_CAP = 500_000


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


def official_url(provider: str, name: str) -> str | None:
    """Return the official documentation URL for a given provider and model name."""
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
        def redirect_request(
            self,
            req: Any,
            fp: Any,
            code: int,
            msg: str,
            headers: Any,
            newurl: str,
        ) -> Any:
            parsed = urllib.parse.urlsplit(newurl)
            if parsed.scheme != "https" or parsed.hostname != original_host:
                raise urllib.error.URLError("Documentation redirected outside the official host")
            logger.log(
                "network_request",
                method="GET",
                host=parsed.hostname,
                path=parsed.path or "/",
                purpose="model_research_redirect",
            )
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    parsed = urllib.parse.urlsplit(url)
    logger.log(
        "network_request",
        method="GET",
        host=parsed.hostname or "",
        path=parsed.path or "/",
        purpose="model_research",
    )
    opener = urllib.request.build_opener(OfficialRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "SELF-model-research/0.1"})
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(FETCH_CAP + 1)
            return {
                "status": response.status,
                "source_url": response.geturl(),
                "body": raw[:FETCH_CAP].decode("utf-8", errors="replace"),
                "content_type": response.headers.get_content_type(),
                "truncated": len(raw) > FETCH_CAP,
            }
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "source_url": url, "body": "", "truncated": False}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": None, "source_url": url, "body": "", "truncated": False}
