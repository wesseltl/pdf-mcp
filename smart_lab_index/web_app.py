"""Loopback-only browser interface for Smart Lab Index."""

from __future__ import annotations

import argparse
import copy
import hmac
import json
import logging
import secrets
import threading
import webbrowser
from collections.abc import Iterable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from smart_lab_index.application import KnowledgeQueryService, build_application
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.storage import KnowledgeStore

LOGGER = logging.getLogger(__name__)
DEFAULT_PORT = 8876
STATIC_ASSETS = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _asset_bytes(name: str) -> bytes:
    return resources.files("smart_lab_index.web_ui").joinpath(name).read_bytes()


class WebAppState:
    """Thread-safe runtime state; SQLite connections stay request/thread local."""

    def __init__(
        self,
        root: str | Path,
        *,
        database: str | Path,
        source_id: str | None,
        policy: RuntimePolicy,
        disabled_module_ids: Iterable[str] = (),
    ) -> None:
        if str(database) == ":memory:":
            raise ValueError("the graphical app requires a durable database path")
        self.session_token = secrets.token_urlsafe(32)
        self.root = str(Path(root).expanduser().resolve())
        self.database = str(database)
        self.source_id = source_id
        self.policy = policy
        self.disabled_module_ids = tuple(disabled_module_ids)
        self._lock = threading.Lock()
        self._index_thread: threading.Thread | None = None
        self._operation: dict[str, Any] = {
            "state": "IDLE",
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
        }
        with self._application() as application:
            self.source_id = application.source.source_id
            self._modules = application.registry.snapshot()

    def _application(self):
        return build_application(
            self.root,
            database=self.database,
            source_id=self.source_id,
            policy=self.policy,
            disabled_module_ids=self.disabled_module_ids,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            operation = copy.deepcopy(self._operation)
            modules = copy.deepcopy(self._modules)
        with KnowledgeStore(self.database) as store:
            return KnowledgeQueryService(store).snapshot(
                source={
                    "source_id": self.source_id,
                    "root": self.root,
                    "no_egress": self.policy.no_egress,
                },
                modules=modules,
                operation=operation,
            )

    def start_index(self) -> bool:
        with self._lock:
            if self._operation["state"] == "INDEXING":
                return False
            self._operation = {
                "state": "INDEXING",
                "started_at": _now(),
                "completed_at": None,
                "result": None,
                "error": None,
            }
            self._index_thread = threading.Thread(
                target=self._run_index,
                name="smart-lab-index-job",
                daemon=False,
            )
            self._index_thread.start()
        return True

    def _run_index(self) -> None:
        result: dict[str, Any] | None = None
        error: str | None = None
        modules: list[dict[str, Any]] | None = None
        try:
            with self._application() as application:
                connector_error = application.startup_errors.get(
                    application.connector_module_id
                )
                if connector_error:
                    raise RuntimeError("filesystem connector could not start")
                result = application.indexing.run(application.source).to_dict()
                if application.startup_errors:
                    result["startup_errors"] = dict(application.startup_errors)
                modules = application.registry.snapshot()
        except Exception as exc:  # noqa: BLE001 - background jobs need a bounded failure state
            LOGGER.error("Smart Lab indexing failed (%s)", type(exc).__name__)
            error = f"{type(exc).__name__}: indexing could not be completed"
        with self._lock:
            if modules is not None:
                self._modules = modules
            self._operation = {
                "state": "FAILED" if error else "IDLE",
                "started_at": self._operation["started_at"],
                "completed_at": _now(),
                "result": result,
                "error": error,
            }

    def is_indexing(self) -> bool:
        with self._lock:
            return self._operation["state"] == "INDEXING"

    def wait_for_index(self, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._index_thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()


class SmartLabHandler(BaseHTTPRequestHandler):
    app_state: WebAppState
    server_version = "SmartLabIndex"

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.debug(format, *args)

    def do_GET(self) -> None:
        if not self._request_host_is_local():
            self._send_json(403, {"error": "This app accepts local requests only."})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = _asset_bytes("index.html").replace(
                b"__SMART_LAB_SESSION__",
                self.app_state.session_token.encode("ascii"),
            )
            self._send_bytes(200, html, "text/html; charset=utf-8")
            return
        if parsed.path in STATIC_ASSETS:
            filename, content_type = STATIC_ASSETS[parsed.path]
            self._send_bytes(200, _asset_bytes(filename), content_type)
            return
        if parsed.path == "/api/state":
            if not self._valid_session():
                self._send_json(
                    403, {"error": "This browser session is not authorized."}
                )
                return
            try:
                self._send_json(200, self.app_state.snapshot())
            except Exception as exc:  # noqa: BLE001 - return a bounded local API error
                LOGGER.error("Smart Lab state read failed (%s)", type(exc).__name__)
                self._send_json(500, {"error": "The index state could not be read."})
            return
        self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self._request_host_is_local() or not self._origin_is_local():
            self._send_json(403, {"error": "This app accepts local requests only."})
            return
        if not self._valid_session():
            self._send_json(403, {"error": "This browser session is not authorized."})
            return
        if not self._valid_body_size():
            self._send_json(413, {"error": "The request body is too large."})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/index":
            if not self.app_state.start_index():
                self._send_json(409, {"error": "An index run is already active."})
                return
            self._send_json(202, {"started": True})
            return
        if parsed.path == "/api/shutdown":
            if self.app_state.is_indexing():
                self._send_json(
                    409, {"error": "Wait for the active index run to finish."}
                )
                return
            self._send_json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._send_json(404, {"error": "Not found."})

    def do_OPTIONS(self) -> None:
        self._send_json(405, {"error": "Cross-origin requests are not supported."})

    def _request_host_is_local(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        hostname = host.rsplit(":", 1)[0].strip("[]")
        return hostname in {"127.0.0.1", "localhost", "::1"}

    def _origin_is_local(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }

    def _valid_session(self) -> bool:
        supplied = self.headers.get("X-Smart-Lab-Session", "")
        return bool(supplied) and hmac.compare_digest(
            supplied,
            self.app_state.session_token,
        )

    def _valid_body_size(self) -> bool:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return False
        return 0 <= length <= 4096

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send_bytes(
            status,
            json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send_bytes(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers(content_type)
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


def create_server(
    root: str | Path,
    *,
    database: str | Path = "~/.smart-lab-index/index.db",
    source_id: str | None = None,
    policy: RuntimePolicy | None = None,
    disabled_module_ids: Iterable[str] = (),
    port: int = DEFAULT_PORT,
) -> tuple[ThreadingHTTPServer, WebAppState]:
    """Create a session-protected server bound only to loopback."""
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    state = WebAppState(
        root,
        database=database,
        source_id=source_id,
        policy=policy or RuntimePolicy.from_env(),
        disabled_module_ids=disabled_module_ids,
    )
    handler = type(
        "ConfiguredSmartLabHandler",
        (SmartLabHandler,),
        {"app_state": state},
    )
    candidates = [0] if port == 0 else range(port, min(port + 20, 65536))
    last_error: OSError | None = None
    for candidate in candidates:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            server.daemon_threads = True
            return server, state
        except OSError as exc:
            last_error = exc
    raise OSError(
        "No available local port was found for Smart Lab Index."
    ) from last_error


def _policy(force_no_egress: bool) -> RuntimePolicy:
    environment_policy = RuntimePolicy.from_env()
    return RuntimePolicy(no_egress=force_no_egress or environment_policy.no_egress)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="smart-lab-index-app",
        description="Open the local Smart Lab Index operator interface.",
    )
    parser.add_argument("root", help="read-only laboratory folder to index")
    parser.add_argument("--database", default="~/.smart-lab-index/index.db")
    parser.add_argument("--source-id")
    parser.add_argument("--disable", action="append", default=[], metavar="MODULE_ID")
    parser.add_argument("--no-egress", action="store_true")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--index-on-start", action="store_true")
    args = parser.parse_args()

    try:
        server, state = create_server(
            args.root,
            database=args.database,
            source_id=args.source_id,
            policy=_policy(args.no_egress),
            disabled_module_ids=args.disable,
            port=args.port,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"smart-lab-index-app: {exc}")
        return 2
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"Smart Lab Index is ready at {url}")
    print(f"Source: {state.root}")
    print(f"Database: {Path(state.database).expanduser()}")
    print(f"No-egress: {'on' if state.policy.no_egress else 'off'}")
    print("Press Ctrl+C to stop the app.")
    if args.index_on_start:
        state.start_index()
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping Smart Lab Index.")
    finally:
        server.server_close()
        state.wait_for_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
