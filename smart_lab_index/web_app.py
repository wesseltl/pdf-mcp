"""Loopback-only browser interface for Smart Lab Index."""

from __future__ import annotations

import argparse
import copy
import hashlib
import logging
import secrets
import threading
import webbrowser
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from smart_lab_index.application import KnowledgeQueryService, build_application
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.storage import KnowledgeStore
from smart_lab_index.folder_browser import choose_source_folder_in_browser
from smart_lab_index.folder_picker import (
    FolderPickerUnavailable,
    choose_source_folder,
    folder_picker_available,
)
from smart_lab_index.local_web import (
    LoopbackHandler,
    LoopbackHTTPServer,
    bind_loopback_server,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_PORT = 8876
DEFAULT_DATABASE = "~/.smart-lab-index/index.db"
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
        allow_source_change: bool = False,
    ) -> None:
        if str(database) == ":memory:":
            raise ValueError("the graphical app requires a durable database path")
        self.session_token = secrets.token_urlsafe(32)
        self.root = str(Path(root).expanduser().resolve())
        self.database = str(database)
        self.source_id = source_id
        self.policy = policy
        self.disabled_module_ids = tuple(disabled_module_ids)
        self.allow_source_change = allow_source_change
        self._lock = threading.Lock()
        self._index_thread: threading.Thread | None = None
        self._source_change_requested = False
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
                    "can_change_source": self.allow_source_change,
                },
                modules=modules,
                operation=operation,
            )

    def start_index(self) -> bool:
        with self._lock:
            if self._operation["state"] == "INDEXING" or self._source_change_requested:
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

    def request_source_change(self) -> bool:
        with self._lock:
            if (
                not self.allow_source_change
                or self._operation["state"] == "INDEXING"
                or self._source_change_requested
            ):
                return False
            self._source_change_requested = True
            self._operation["state"] = "CHANGING_SOURCE"
            return True

    @property
    def source_change_requested(self) -> bool:
        with self._lock:
            return self._source_change_requested

    def wait_for_index(self, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._index_thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()


class SmartLabHandler(LoopbackHandler):
    app_state: WebAppState
    server_version = "SmartLabIndex"

    @property
    def session_token(self) -> str:
        return self.app_state.session_token

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
        if not self._request_host_is_local() or not self._origin_is_same():
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
        if parsed.path == "/api/change-source":
            if not self.app_state.allow_source_change:
                self._send_json(409, {"error": "Folder selection is unavailable."})
                return
            if not self.app_state.request_source_change():
                self._send_json(
                    409, {"error": "Wait for the active operation to finish."}
                )
                return
            self._send_json(202, {"changing": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
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


def create_server(
    root: str | Path,
    *,
    database: str | Path = "~/.smart-lab-index/index.db",
    source_id: str | None = None,
    policy: RuntimePolicy | None = None,
    disabled_module_ids: Iterable[str] = (),
    allow_source_change: bool = False,
    port: int = DEFAULT_PORT,
) -> tuple[LoopbackHTTPServer, WebAppState]:
    """Create a session-protected server bound only to loopback."""
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    state = WebAppState(
        root,
        database=database,
        source_id=source_id,
        policy=policy or RuntimePolicy.from_env(),
        disabled_module_ids=disabled_module_ids,
        allow_source_change=allow_source_change,
    )
    handler = type(
        "ConfiguredSmartLabHandler",
        (SmartLabHandler,),
        {"app_state": state},
    )
    server = bind_loopback_server(
        handler,
        port,
        error_message="No available local port was found for Smart Lab Index.",
    )
    return server, state


def _policy(force_no_egress: bool) -> RuntimePolicy:
    environment_policy = RuntimePolicy.from_env()
    return RuntimePolicy(no_egress=force_no_egress or environment_policy.no_egress)


def _desktop_database(root: str | Path) -> Path:
    identity = hashlib.sha256(
        str(Path(root).expanduser().resolve()).encode("utf-8")
    ).hexdigest()[:20]
    return Path.home() / ".smart-lab-index" / "workspaces" / f"{identity}.db"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smart-lab-index-app",
        description="Open the local Smart Lab Index operator interface.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        help="read-only laboratory folder; omit to choose one graphically",
    )
    parser.add_argument("--database")
    parser.add_argument("--source-id")
    parser.add_argument("--disable", action="append", default=[], metavar="MODULE_ID")
    parser.add_argument("--no-egress", action="store_true")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--index-on-start", action="store_true")
    args = parser.parse_args(argv)

    picker_supported = folder_picker_available()
    selected_at_start = args.root is None
    requested_port = args.port
    browser_started = False
    root: str | Path | None = args.root
    if root is None and picker_supported:
        try:
            root = choose_source_folder()
        except FolderPickerUnavailable as exc:
            LOGGER.error("System folder selection failed (%s)", type(exc).__name__)
        else:
            if root is None:
                return 0
    if root is None:
        try:
            root, requested_port = choose_source_folder_in_browser(
                port=requested_port,
                open_browser=not args.no_browser,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"smart-lab-index-app: {exc}")
            return 2
        browser_started = not args.no_browser
        if root is None:
            return 0

    policy = _policy(args.no_egress or selected_at_start)
    source_id = args.source_id
    managed_database = selected_at_start and args.database is None
    database: str | Path = args.database or DEFAULT_DATABASE
    if managed_database:
        database = _desktop_database(root)
    index_on_start = args.index_on_start or selected_at_start
    recovery: tuple[str | Path, str | Path, str | None] | None = None

    while True:
        try:
            server, state = create_server(
                root,
                database=database,
                source_id=source_id,
                policy=policy,
                disabled_module_ids=args.disable,
                allow_source_change=True,
                port=requested_port,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            if recovery is not None:
                LOGGER.error(
                    "Selected source could not be opened (%s)", type(exc).__name__
                )
                root, database, source_id = recovery
                recovery = None
                index_on_start = False
                continue
            print(f"smart-lab-index-app: {exc}")
            return 2
        recovery = None
        actual_port = server.server_address[1]
        requested_port = actual_port
        url = f"http://127.0.0.1:{actual_port}/"
        print(f"Smart Lab Index is ready at {url}")
        print(f"Source: {state.root}")
        print(f"Database: {Path(state.database).expanduser()}")
        print(f"No-egress: {'on' if state.policy.no_egress else 'off'}")
        print("Press Ctrl+C to stop the app.")
        if index_on_start:
            state.start_index()
        if not args.no_browser and not browser_started:
            threading.Timer(
                0.35,
                lambda target=url: webbrowser.open(target),
            ).start()
            browser_started = True

        interrupted = False
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            interrupted = True
            print("\nStopping Smart Lab Index.")
        finally:
            server.server_close()
            state.wait_for_index()

        if interrupted or not state.source_change_requested:
            return 0

        selected: Path | None = None
        use_browser_picker = not picker_supported
        if picker_supported:
            try:
                selected = choose_source_folder(state.root)
            except FolderPickerUnavailable as exc:
                LOGGER.error("System folder selection failed (%s)", type(exc).__name__)
                use_browser_picker = True
        if use_browser_picker:
            try:
                selected, requested_port = choose_source_folder_in_browser(
                    state.root,
                    port=requested_port,
                    open_browser=False,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                LOGGER.error("Browser folder selection failed (%s)", type(exc).__name__)
        if selected is not None:
            changed = selected != Path(state.root)
            if changed:
                recovery = (root, database, source_id)
            root = selected
            if changed:
                source_id = None
                if managed_database:
                    database = _desktop_database(selected)
            index_on_start = True
        else:
            root = state.root
            index_on_start = False


if __name__ == "__main__":
    raise SystemExit(main())
