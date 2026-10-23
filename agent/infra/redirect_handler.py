"""HTTP redirect handler with event callback for auditing outgoing requests."""
from __future__ import annotations

from typing import Any
import urllib.request


class _LoggingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Urllib redirect handler that reports redirect target URLs to an audit callback."""

    def __init__(self, callback: Any) -> None:
        super().__init__()
        self._callback = callback

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        """Record the redirect event and delegate to the standard redirect handler."""
        self._callback(newurl, "GET", redirect_status=code)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


LoggingRedirectHandler = _LoggingRedirectHandler
