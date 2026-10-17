#!/usr/bin/env python3
"""Minimal forward HTTP/HTTPS egress filtering proxy with allowlist for SELF.

Designed for the hardened compose profile to filter all outbound container traffic.
Requires zero external dependencies (Python standard library only).
"""
from __future__ import annotations

import argparse
import fnmatch
import logging
import select
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [egress-proxy]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("egress_proxy")


class Allowlist:
    """Manages allowed hosts loaded from an allowlist file."""

    def __init__(self, path: Path | str | None) -> None:
        self.path = Path(path) if path else None
        self.patterns: set[str] = set()
        self.reload()

    def reload(self) -> None:
        if not self.path or not self.path.exists():
            logger.warning(f"Allowlist file {self.path} not found; blocking all outbound requests.")
            self.patterns = set()
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            patterns = set()
            for line in lines:
                clean = line.split("#", 1)[0].strip().lower()
                if clean:
                    patterns.add(clean)
            self.patterns = patterns
            logger.info(f"Loaded {len(self.patterns)} egress allowlist patterns from {self.path}")
        except Exception as exc:
            logger.error(f"Failed to load allowlist from {self.path}: {exc}")

    def is_allowed(self, host: str) -> bool:
        host = host.lower().strip()
        # Remove port if present
        if ":" in host:
            host = host.split(":", 1)[0]
        for pattern in self.patterns:
            if pattern == host:
                return True
            if pattern.startswith("*.") and (host.endswith(pattern[1:]) or host == pattern[2:]):
                return True
            if fnmatch.fnmatch(host, pattern):
                return True
        return False


class EgressProxyHandler(BaseHTTPRequestHandler):
    """HTTP/HTTPS proxy request handler with allowlist enforcement."""

    allowlist: Allowlist

    def do_CONNECT(self) -> None:
        """Handle HTTPS CONNECT tunnels."""
        # target address is host:port
        target = self.path
        if ":" in target:
            host, port_str = target.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 443
        else:
            host = target
            port = 443

        if not self.allowlist.is_allowed(host):
            logger.warning(f"BLOCKED HTTPS egress to {host}:{port}")
            self.send_error(403, f"Egress to host '{host}' is blocked by egress policy.")
            return

        logger.info(f"ALLOWED HTTPS egress to {host}:{port}")
        try:
            target_sock = socket.create_connection((host, port), timeout=10.0)
        except Exception as exc:
            logger.error(f"Failed to connect to {host}:{port}: {exc}")
            self.send_error(502, f"Gateway connection failed: {exc}")
            return

        # Tunnel established
        self.send_response(200, "Connection Established")
        self.end_headers()

        # Shuttle bytes bidirectionally
        client_sock = self.connection
        conns = [client_sock, target_sock]
        try:
            while True:
                r, _, _ = select.select(conns, [], [], 30.0)
                if not r:
                    break
                for s in r:
                    other = target_sock if s is client_sock else client_sock
                    data = s.recv(8192)
                    if not data:
                        return
                    other.sendall(data)
        except Exception:
            pass
        finally:
            try:
                target_sock.close()
            except Exception:
                pass

    def do_GET(self) -> None:
        self._handle_http_forward()

    def do_POST(self) -> None:
        self._handle_http_forward()

    def do_PUT(self) -> None:
        self._handle_http_forward()

    def do_DELETE(self) -> None:
        self._handle_http_forward()

    def do_HEAD(self) -> None:
        self._handle_http_forward()

    def _handle_http_forward(self) -> None:
        """Forward plain HTTP requests."""
        split_url = urlsplit(self.path)
        host = split_url.hostname or self.headers.get("Host", "")
        if ":" in host:
            host = host.split(":", 1)[0]

        if not self.allowlist.is_allowed(host):
            logger.warning(f"BLOCKED HTTP egress to {host} for {self.command} {self.path}")
            self.send_error(403, f"Egress to host '{host}' is blocked by egress policy.")
            return

        logger.info(f"ALLOWED HTTP egress to {host} for {self.command} {self.path}")
        # Forward request
        port = split_url.port or 80
        try:
            target_sock = socket.create_connection((host, port), timeout=10.0)
        except Exception as exc:
            self.send_error(502, f"Failed to connect to host '{host}': {exc}")
            return

        try:
            # Reconstruct HTTP request line and headers
            path = split_url.path or "/"
            if split_url.query:
                path = f"{path}?{split_url.query}"
            req_line = f"{self.command} {path} {self.request_version}\r\n"
            target_sock.sendall(req_line.encode("iso-8859-1"))

            # Headers
            for header, value in self.headers.items():
                if header.lower() != "proxy-connection":
                    target_sock.sendall(f"{header}: {value}\r\n".encode("iso-8859-1"))
            target_sock.sendall(b"\r\n")

            # Forward body if present
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
                target_sock.sendall(body)

            # Read back response and stream to client
            client_sock = self.connection
            conns = [target_sock]
            while True:
                r, _, _ = select.select(conns, [], [], 30.0)
                if not r:
                    break
                data = target_sock.recv(8192)
                if not data:
                    break
                client_sock.sendall(data)
        except Exception as exc:
            logger.error(f"Error forwarding HTTP request to {host}: {exc}")
        finally:
            try:
                target_sock.close()
            except Exception:
                pass

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default HTTP server stderr output in favor of logging."""
        pass


def run_proxy(port: int = 8080, allowlist_path: Path | str | None = None) -> None:
    allowlist = Allowlist(allowlist_path)
    handler_class = type("ConfiguredHandler", (EgressProxyHandler,), {"allowlist": allowlist})
    server = HTTPServer(("0.0.0.0", port), handler_class)
    logger.info(f"Starting egress filtering proxy on 0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Proxy server shutting down.")
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="SELF Egress Filtering Proxy Sidecar")
    parser.add_argument("--port", type=int, default=8080, help="Listen port (default: 8080)")
    parser.add_argument("--allowlist", default="/config/egress_allowlist.txt", help="Path to allowlist file")
    args = parser.parse_args()

    allowlist_path = Path(args.allowlist)
    if not allowlist_path.exists() and Path("config/egress_allowlist.txt").exists():
        allowlist_path = Path("config/egress_allowlist.txt")

    run_proxy(port=args.port, allowlist_path=allowlist_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
