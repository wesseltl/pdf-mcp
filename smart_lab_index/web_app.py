"""Loopback-only browser interface for Smart Lab Index."""

from __future__ import annotations

import argparse
import copy
import hashlib
import logging
import math
import multiprocessing
import os
import secrets
import sqlite3
import threading
import time
import webbrowser
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from smart_lab_index.application import (
    DEFAULT_DESKTOP_INDEX_INTERVAL_MINUTES,
    DesktopSettings,
    DesktopSettingsError,
    IssueReviewService,
    KnowledgeQueryService,
    build_application,
    default_desktop_settings_path,
    forget_desktop_settings,
    load_desktop_settings,
    save_desktop_settings,
)
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.locking import DatabaseLease
from smart_lab_index.core.security import load_operator_token, validate_operator_token
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
from smart_lab_index.modules.connectors.filesystem import (
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_TOTAL_BYTES,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_PORT = 8876
DEFAULT_DATABASE = "~/.smart-lab-index/index.db"
STATIC_ASSETS = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/icons.svg": ("icons.svg", "image/svg+xml"),
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
        enabled_module_ids: Iterable[str] = (),
        allow_source_change: bool = False,
        max_files: int = DEFAULT_MAX_FILES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        exclude_patterns: Iterable[str] = (),
        operator_token: str | None = None,
        index_interval_seconds: float | None = None,
        managed_desktop: bool = False,
    ) -> None:
        if str(database) == ":memory:":
            raise ValueError("the graphical app requires a durable database path")
        self.session_token = secrets.token_urlsafe(32)
        self.root = str(Path(root).expanduser().resolve())
        self.database = str(database)
        self.source_id = source_id
        self.policy = policy
        self.disabled_module_ids = tuple(disabled_module_ids)
        self.enabled_module_ids = tuple(enabled_module_ids)
        self.allow_source_change = allow_source_change
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes
        self.exclude_patterns = tuple(exclude_patterns)
        if operator_token is not None:
            validate_operator_token(operator_token)
        if policy.production_mode and operator_token is None:
            raise ValueError("production mode requires an operator token")
        self.operator_token = operator_token
        if index_interval_seconds is not None and (
            not math.isfinite(index_interval_seconds) or index_interval_seconds <= 0
        ):
            raise ValueError("index interval must be positive when enabled")
        self.index_interval_seconds = index_interval_seconds
        self.managed_desktop = managed_desktop
        self._database_lease = DatabaseLease(self.database).acquire()
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._readiness_cache: tuple[float, bool] | None = None
        self._index_thread: threading.Thread | None = None
        self._source_change_requested = False
        self._operation: dict[str, Any] = {
            "state": "IDLE",
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
            "cancel_requested": False,
            "progress": None,
        }
        try:
            with self._application() as application:
                self.source_id = application.source.source_id
                self._modules = application.registry.snapshot()
                self._parser_isolation = dict(application.parser_isolation)
        except Exception:
            self._database_lease.close()
            raise
        if self.index_interval_seconds is not None:
            self._scheduler_thread = threading.Thread(
                target=self._schedule_indexes,
                name="smart-lab-index-scheduler",
                daemon=True,
            )
            self._scheduler_thread.start()

    def _application(self):
        return build_application(
            self.root,
            database=self.database,
            source_id=self.source_id,
            policy=self.policy,
            disabled_module_ids=self.disabled_module_ids,
            enabled_module_ids=self.enabled_module_ids,
            max_files=self.max_files,
            max_total_bytes=self.max_total_bytes,
            exclude_patterns=self.exclude_patterns,
            acquire_database_lease=False,
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
                    "display_name": Path(self.root).name or self.root,
                    "no_egress": self.policy.no_egress,
                    "production_mode": self.policy.production_mode,
                    "managed_desktop": self.managed_desktop,
                    "parser_isolation": dict(self._parser_isolation),
                    "index_interval_seconds": self.index_interval_seconds,
                    "automation": {
                        "enabled": self.index_interval_seconds is not None,
                        "interval_minutes": (
                            None
                            if self.index_interval_seconds is None
                            else self.index_interval_seconds / 60
                        ),
                    },
                    "can_change_source": self.allow_source_change,
                    "limits": {
                        "max_files": self.max_files,
                        "max_total_bytes": self.max_total_bytes,
                        "exclude_patterns": list(self.exclude_patterns),
                    },
                },
                modules=modules,
                operation=operation,
            )

    def search(self, query: str, *, limit: int = 50) -> dict[str, Any]:
        with KnowledgeStore(self.database) as store:
            return KnowledgeQueryService(store).search(query, limit=limit)

    def operational_health(self) -> dict[str, Any]:
        with KnowledgeStore(self.database) as store:
            database = store.integrity_report()
        with self._lock:
            operation = self._operation["state"]
            modules = copy.deepcopy(self._modules)
        required_failures = [
            module["module_id"]
            for module in modules
            if module["enabled"] and module["health"] in {"ERROR", "MISCONFIGURED"}
        ]
        ready = database["healthy"] and not required_failures
        return {
            "status": "READY" if ready else "DEGRADED",
            "ready": ready,
            "database": database,
            "operation": operation,
            "required_module_failures": required_failures,
            "parser_isolation": dict(self._parser_isolation),
            "production_mode": self.policy.production_mode,
            "no_egress": self.policy.no_egress,
        }

    def is_ready(self) -> bool:
        now = time.monotonic()
        with self._lock:
            cached = self._readiness_cache
            if cached is not None and now - cached[0] < 5:
                return cached[1]
        try:
            ready = bool(self.operational_health()["ready"])
        except Exception:  # noqa: BLE001 - readiness must fail closed
            ready = False
        with self._lock:
            self._readiness_cache = (now, ready)
        return ready

    def review_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._operation["state"] == "INDEXING":
                raise RuntimeError("wait for the active index run to finish")
            with KnowledgeStore(self.database) as store:
                return IssueReviewService(store).review(
                    issue_id=payload.get("issue_id"),
                    decision=payload.get("decision"),
                    reason=payload.get("reason"),
                    assertion_id=payload.get("assertion_id"),
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
                "cancel_requested": False,
                "progress": {
                    "phase": "STARTING",
                    "current": 0,
                    "total": None,
                },
            }
            self._cancel_event.clear()
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
                result = application.indexing.run(
                    application.source,
                    progress=self._update_progress,
                    should_cancel=self._cancel_event.is_set,
                ).to_dict()
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
                "cancel_requested": self._cancel_event.is_set(),
                "progress": self._operation.get("progress"),
            }

    def _update_progress(self, value: Mapping[str, Any]) -> None:
        with self._lock:
            self._operation["progress"] = dict(value)

    def request_cancel(self) -> bool:
        with self._lock:
            if self._operation["state"] != "INDEXING":
                return False
            self._operation["cancel_requested"] = True
            self._cancel_event.set()
            return True

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

    def close(self) -> None:
        self._scheduler_stop.set()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=2)
        self.request_cancel()
        self.wait_for_index()
        self._database_lease.close()

    def _schedule_indexes(self) -> None:
        interval = self.index_interval_seconds
        if interval is None:
            return
        while not self._scheduler_stop.wait(interval):
            self.start_index()


class SmartLabHandler(LoopbackHandler):
    app_state: WebAppState
    server_version = "SmartLabIndex"

    @property
    def session_token(self) -> str:
        return self.app_state.session_token

    @property
    def operator_token(self) -> str | None:
        return self.app_state.operator_token

    def do_GET(self) -> None:
        if not self._request_host_is_local():
            self._send_json(403, {"error": "This app accepts local requests only."})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path == "/readyz":
            ready = self.app_state.is_ready()
            self._send_json(
                200 if ready else 503, {"status": "ready" if ready else "unavailable"}
            )
            return
        if not self._valid_operator():
            self._send_operator_challenge()
            return
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
        if parsed.path == "/api/search":
            if not self._valid_session():
                self._send_json(
                    403, {"error": "This browser session is not authorized."}
                )
                return
            parameters = parse_qs(parsed.query, keep_blank_values=True)
            query = parameters.get("q", [""])[0]
            try:
                limit = int(parameters.get("limit", ["50"])[0])
                self._send_json(200, self.app_state.search(query, limit=limit))
            except (TypeError, ValueError):
                self._send_json(400, {"error": "Enter at least two search characters."})
            except Exception as exc:  # noqa: BLE001 - bounded local API error
                LOGGER.error("Smart Lab search failed (%s)", type(exc).__name__)
                self._send_json(500, {"error": "Search could not be completed."})
            return
        if parsed.path == "/api/health":
            if not self._valid_session():
                self._send_json(
                    403, {"error": "This browser session is not authorized."}
                )
                return
            try:
                self._send_json(200, self.app_state.operational_health())
            except Exception as exc:  # noqa: BLE001 - bounded local API error
                LOGGER.error("Smart Lab health check failed (%s)", type(exc).__name__)
                self._send_json(503, {"error": "Health checks could not be completed."})
            return
        self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self._request_host_is_local() or not self._origin_is_same():
            self._send_json(403, {"error": "This app accepts local requests only."})
            return
        if not self._valid_operator():
            self._send_operator_challenge()
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
        if parsed.path == "/api/cancel-index":
            if not self.app_state.request_cancel():
                self._send_json(409, {"error": "No index run is active."})
                return
            self._send_json(202, {"cancel_requested": True})
            return
        if parsed.path == "/api/review-issue":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(400, {"error": "A JSON review request is required."})
                return
            try:
                issue = self.app_state.review_issue(payload)
            except (TypeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except RuntimeError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            self._send_json(200, {"issue": issue})
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
    enabled_module_ids: Iterable[str] = (),
    allow_source_change: bool = False,
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    exclude_patterns: Iterable[str] = (),
    operator_token: str | None = None,
    index_interval_seconds: float | None = None,
    managed_desktop: bool = False,
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
        enabled_module_ids=enabled_module_ids,
        allow_source_change=allow_source_change,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        exclude_patterns=exclude_patterns,
        operator_token=operator_token,
        index_interval_seconds=index_interval_seconds,
        managed_desktop=managed_desktop,
    )
    handler = type(
        "ConfiguredSmartLabHandler",
        (SmartLabHandler,),
        {"app_state": state},
    )
    try:
        server = bind_loopback_server(
            handler,
            port,
            error_message="No available local port was found for Smart Lab Index.",
        )
    except Exception:
        state.close()
        raise
    server.close_callback = state.close
    return server, state


def _policy(force_no_egress: bool, *, production_mode: bool = False) -> RuntimePolicy:
    environment_policy = RuntimePolicy.from_env()
    effective_production = production_mode or environment_policy.production_mode
    return replace(
        environment_policy,
        no_egress=(
            force_no_egress or effective_production or environment_policy.no_egress
        ),
        production_mode=effective_production,
    )


def _desktop_database(root: str | Path) -> Path:
    identity = hashlib.sha256(
        str(Path(root).expanduser().resolve()).encode("utf-8")
    ).hexdigest()[:20]
    return Path.home() / ".smart-lab-index" / "workspaces" / f"{identity}.db"


def _schedule_initial_index(state: WebAppState) -> threading.Timer:
    """Let the loopback workspace accept requests before discovery starts."""
    timer = threading.Timer(0.15, state.start_index)
    timer.daemon = True
    timer.start()
    return timer


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
    parser.add_argument("--enable", action="append", default=[], metavar="MODULE_ID")
    parser.add_argument("--no-egress", action="store_true")
    parser.add_argument(
        "--production",
        action="store_true",
        help="enforce the controlled-production startup policy",
    )
    parser.add_argument(
        "--operator-token-file",
        help="owner-only access-key file required by production mode",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--index-on-start", action="store_true")
    parser.add_argument(
        "--settings-file",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--forget-setup",
        action="store_true",
        help="forget the remembered desktop folder before opening",
    )
    parser.add_argument(
        "--index-interval-minutes",
        type=float,
        help="repeat incremental indexing at this interval; production default: 15",
    )
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument(
        "--max-total-gb",
        type=float,
        default=DEFAULT_MAX_TOTAL_BYTES / (1024**3),
    )
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    args = parser.parse_args(argv)

    environment_policy = RuntimePolicy.from_env()
    production_mode = args.production or environment_policy.production_mode
    if production_mode and args.root is None:
        print("smart-lab-index-app: production mode requires an explicit source root")
        return 2
    try:
        operator_token = (
            None
            if args.operator_token_file is None
            else load_operator_token(args.operator_token_file)
        )
    except ValueError as exc:
        print(f"smart-lab-index-app: {exc}")
        return 2
    if production_mode and operator_token is None:
        print("smart-lab-index-app: production mode requires --operator-token-file")
        return 2
    desktop_mode = args.root is None and not production_mode
    settings_path = (
        Path(args.settings_file)
        if args.settings_file
        else default_desktop_settings_path()
    )
    if args.forget_setup:
        try:
            forget_desktop_settings(settings_path)
        except DesktopSettingsError as exc:
            print(f"smart-lab-index-app: {exc}")
            return 2

    remembered: DesktopSettings | None = None
    if desktop_mode:
        try:
            remembered = load_desktop_settings(settings_path)
        except DesktopSettingsError as exc:
            print(f"smart-lab-index-app: {exc}")
            return 2

    index_interval_minutes = args.index_interval_minutes
    if index_interval_minutes is None and remembered is not None:
        index_interval_minutes = remembered.index_interval_minutes
    if index_interval_minutes is None and production_mode:
        index_interval_minutes = 15.0
    if index_interval_minutes is None and desktop_mode:
        index_interval_minutes = DEFAULT_DESKTOP_INDEX_INTERVAL_MINUTES
    if index_interval_minutes is not None and (
        not math.isfinite(index_interval_minutes) or index_interval_minutes <= 0
    ):
        print("smart-lab-index-app: --index-interval-minutes must be positive")
        return 2

    picker_supported = folder_picker_available()
    requested_port = args.port
    browser_started = False
    root: str | Path | None = args.root
    remembered_database: Path | None = None
    if root is None and remembered is not None:
        if remembered.root.is_dir() and os.access(remembered.root, os.R_OK):
            root = remembered.root
            remembered_database = remembered.database
        else:
            LOGGER.warning("Remembered source folder is unavailable; opening setup")
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
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            print(f"smart-lab-index-app: {exc}")
            return 2
        browser_started = not args.no_browser
        if root is None:
            return 0

    policy = _policy(
        args.no_egress or desktop_mode,
        production_mode=production_mode,
    )
    source_id = args.source_id
    managed_database = desktop_mode and args.database is None
    database: str | Path = args.database or remembered_database or DEFAULT_DATABASE
    if managed_database:
        database = remembered_database or _desktop_database(root)
    if not math.isfinite(args.max_total_gb) or args.max_total_gb <= 0:
        print("smart-lab-index-app: --max-total-gb must be positive")
        return 2
    index_on_start = args.index_on_start or production_mode or desktop_mode
    recovery: tuple[str | Path, str | Path, str | None] | None = None

    while True:
        try:
            server, state = create_server(
                root,
                database=database,
                source_id=source_id,
                policy=policy,
                disabled_module_ids=args.disable,
                enabled_module_ids=args.enable,
                allow_source_change=not production_mode,
                max_files=args.max_files,
                max_total_bytes=int(args.max_total_gb * 1024**3),
                exclude_patterns=args.exclude,
                operator_token=operator_token,
                index_interval_seconds=(
                    None
                    if index_interval_minutes is None
                    else index_interval_minutes * 60
                ),
                managed_desktop=desktop_mode,
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
        if desktop_mode:
            try:
                save_desktop_settings(
                    DesktopSettings(
                        root=Path(state.root),
                        database=Path(state.database).expanduser().resolve(),
                        index_interval_minutes=(
                            index_interval_minutes
                            or DEFAULT_DESKTOP_INDEX_INTERVAL_MINUTES
                        ),
                    ),
                    settings_path,
                )
            except (DesktopSettingsError, OSError) as exc:
                server.server_close()
                print(f"smart-lab-index-app: desktop setup could not be saved: {exc}")
                return 2
        recovery = None
        actual_port = server.server_address[1]
        requested_port = actual_port
        url = f"http://127.0.0.1:{actual_port}/"
        print(f"Smart Lab Index is ready at {url}")
        print(f"Source: {state.root}")
        print(f"Database: {Path(state.database).expanduser()}")
        print(f"No-egress: {'on' if state.policy.no_egress else 'off'}")
        print(f"Production mode: {'on' if state.policy.production_mode else 'off'}")
        print(f"Operator authentication: {'on' if operator_token else 'off'}")
        if index_interval_minutes is not None:
            print(f"Index interval: {index_interval_minutes:g} minutes")
        print("Press Ctrl+C to stop the app.")
        initial_index_timer = (
            _schedule_initial_index(state) if index_on_start else None
        )
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
            if initial_index_timer is not None:
                initial_index_timer.cancel()
            server.server_close()
            if interrupted:
                state.request_cancel()
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
            index_on_start = desktop_mode and changed
        else:
            root = state.root
            index_on_start = False


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
