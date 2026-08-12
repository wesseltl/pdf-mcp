"""Shared security primitives for loopback-only browser interfaces."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import logging
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LoopbackHTTPServer(ThreadingHTTPServer):
    """Reusable local HTTP server with prompt shutdown semantics."""

    allow_reuse_address = True
    daemon_threads = True
    close_callback: Callable[[], None] | None = None

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            callback = self.close_callback
            self.close_callback = None
            if callback is not None:
                callback()


class LoopbackHandler(BaseHTTPRequestHandler):
    """Hardened response and request helpers shared by local browser tools."""

    session_token = ""
    operator_token: str | None = None

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.debug("Loopback %s request completed", self.command)

    def _request_host_is_local(self) -> bool:
        hostname, port = self._request_host()
        return (
            hostname in LOCAL_HOSTS
            and port == self.server.server_address[1]
        )

    def _origin_is_same(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return False
        parsed = urlparse(origin)
        request_hostname, request_port = self._request_host()
        try:
            origin_port = parsed.port or 80
        except ValueError:
            return False
        return (
            parsed.scheme == "http"
            and parsed.hostname == request_hostname
            and parsed.hostname in LOCAL_HOSTS
            and origin_port == request_port
            and request_port == self.server.server_address[1]
        )

    def _request_host(self) -> tuple[str | None, int]:
        host = self.headers.get("Host") or ""
        try:
            parsed = urlparse(f"//{host}")
            port = parsed.port or self.server.server_address[1]
        except ValueError:
            return None, -1
        return parsed.hostname, port

    def _valid_session(self) -> bool:
        supplied = self.headers.get("X-Smart-Lab-Session", "")
        return bool(supplied) and hmac.compare_digest(
            supplied,
            self.session_token,
        )

    def _valid_operator(self) -> bool:
        expected = self.operator_token
        if expected is None:
            return True
        authorization = self.headers.get("Authorization", "")
        scheme, separator, encoded = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "basic" or not encoded:
            return False
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
        username, separator, supplied = decoded.partition(":")
        return (
            separator == ":"
            and hmac.compare_digest(username, "operator")
            and hmac.compare_digest(supplied, expected)
        )

    def _send_operator_challenge(self) -> None:
        self._send_json(
            401,
            {"error": "Operator authentication is required."},
            headers={
                "WWW-Authenticate": 'Basic realm="LabOverlay", charset="UTF-8"'
            },
        )

    def _valid_body_size(self, maximum: int = 4096) -> bool:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return False
        return 0 <= length <= maximum

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._send_bytes(
            status,
            json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            "application/json; charset=utf-8",
            headers=headers,
        )

    def _send_bytes(
        self,
        status: int,
        content: bytes,
        content_type: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self._security_headers(content_type)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _security_headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'; object-src 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )


def bind_loopback_server(
    handler: type[BaseHTTPRequestHandler],
    port: int,
    *,
    error_message: str,
) -> LoopbackHTTPServer:
    """Bind a handler to the requested loopback port or the next free port."""
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    candidates = [0] if port == 0 else range(port, min(port + 20, 65536))
    last_error: OSError | None = None
    for candidate in candidates:
        try:
            return LoopbackHTTPServer(("127.0.0.1", candidate), handler)
        except OSError as exc:
            last_error = exc
    code = None if last_error is None else getattr(last_error, "winerror", None)
    if code is None and last_error is not None:
        code = last_error.errno
    detail = type(last_error).__name__ if last_error is not None else "OSError"
    if code is not None:
        detail = f"{detail} {code}"
    raise OSError(f"{error_message.rstrip('.')} ({detail}).") from last_error
