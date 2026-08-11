"""Zero-dependency browser folder navigator for desktop fallback use."""

from __future__ import annotations

import heapq
import logging
import os
import secrets
import string
import threading
import webbrowser
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from smart_lab_index.local_web import (
    LoopbackHandler,
    LoopbackHTTPServer,
    bind_loopback_server,
)

LOGGER = logging.getLogger(__name__)
MAX_DIRECTORY_ENTRIES = 500
FOLDER_ASSETS = {
    "/folder-browser.js": ("folder-browser.js", "text/javascript; charset=utf-8"),
    "/folder-browser.css": ("folder-browser.css", "text/css; charset=utf-8"),
}


def _asset_bytes(name: str) -> bytes:
    return resources.files("smart_lab_index.web_ui").joinpath(name).read_bytes()


class FolderBrowserState:
    """Thread-safe selection state and bounded read-only directory listing."""

    def __init__(self, initial_directory: str | Path | None = None) -> None:
        self.session_token = secrets.token_urlsafe(32)
        self.initial_directory = self._initial_directory(initial_directory)
        self._lock = threading.Lock()
        self._selected: Path | None = None
        self._cancelled = False

    @staticmethod
    def _initial_directory(initial_directory: str | Path | None) -> Path:
        candidates = [initial_directory, Path.home(), Path.cwd(), Path.home().anchor]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return _validated_directory(candidate)
            except (OSError, ValueError):
                continue
        raise OSError("No readable starting folder is available.")

    @property
    def selected(self) -> Path | None:
        with self._lock:
            return self._selected

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def select(self, path: str) -> Path:
        selected = _validated_directory(path)
        with self._lock:
            self._selected = selected
        return selected

    def directory_snapshot(
        self,
        path: str | None,
        *,
        show_hidden: bool = False,
    ) -> dict[str, Any]:
        current = _validated_directory(path or self.initial_directory)
        folders: list[dict[str, str]] = []
        truncated = False
        with os.scandir(current) as entries:
            ordered = heapq.nsmallest(
                MAX_DIRECTORY_ENTRIES + 1,
                _directory_entries(entries, show_hidden=show_hidden),
                key=lambda entry: entry.name.casefold(),
            )
        if len(ordered) > MAX_DIRECTORY_ENTRIES:
            truncated = True
            ordered.pop()
        for entry in ordered:
            folders.append({"name": entry.name, "path": str(Path(entry.path))})

        parent = current.parent
        return {
            "path": str(current),
            "name": _path_name(current),
            "parent": None if parent == current else str(parent),
            "ancestors": _ancestors(current),
            "folders": folders,
            "truncated": truncated,
            "home": {"name": "Home", "path": str(Path.home().resolve())},
            "roots": _filesystem_roots(),
            "show_hidden": show_hidden,
        }


def _directory_entries(
    entries: os.ScandirIterator[str],
    *,
    show_hidden: bool,
):
    for entry in entries:
        if not show_hidden and entry.name.startswith("."):
            continue
        try:
            if entry.is_dir(follow_symlinks=True):
                yield entry
        except OSError:
            continue


def _validated_directory(path: str | Path) -> Path:
    if len(str(path)) > 4096:
        raise ValueError("Folder path is too long.")
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("The selected path is not a folder.")
    with os.scandir(resolved):
        pass
    return resolved


def _path_name(path: Path) -> str:
    return path.name or path.anchor or str(path)


def _ancestors(path: Path) -> list[dict[str, str]]:
    ordered = [*reversed(path.parents), path]
    return [{"name": _path_name(item), "path": str(item)} for item in ordered]


def _filesystem_roots() -> list[dict[str, str]]:
    if os.name == "nt":
        return [
            {"name": f"{letter}:", "path": f"{letter}:\\"}
            for letter in string.ascii_uppercase
            if Path(f"{letter}:\\").exists()
        ]
    return [{"name": "Computer", "path": "/"}]


class FolderBrowserHandler(LoopbackHandler):
    """Serve the local folder navigator and its authenticated API."""

    picker_state: FolderBrowserState
    server_version = "SmartLabFolderBrowser"

    @property
    def session_token(self) -> str:
        return self.picker_state.session_token

    def do_GET(self) -> None:
        if not self._request_host_is_local():
            self._send_json(403, {"error": "This app accepts local requests only."})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = _asset_bytes("folder-browser.html").replace(
                b"__SMART_LAB_SESSION__",
                self.session_token.encode("ascii"),
            )
            self._send_bytes(200, html, "text/html; charset=utf-8")
            return
        if parsed.path in FOLDER_ASSETS:
            filename, content_type = FOLDER_ASSETS[parsed.path]
            self._send_bytes(200, _asset_bytes(filename), content_type)
            return
        if parsed.path == "/api/folders":
            if not self._valid_session():
                self._send_json(
                    403, {"error": "This browser session is not authorized."}
                )
                return
            query = parse_qs(parsed.query, keep_blank_values=True)
            path = query.get("path", [None])[0]
            show_hidden = query.get("hidden", ["0"])[0] == "1"
            try:
                snapshot = self.picker_state.directory_snapshot(
                    path,
                    show_hidden=show_hidden,
                )
            except (OSError, ValueError):
                self._send_json(400, {"error": "That folder cannot be opened."})
                return
            self._send_json(200, snapshot)
            return
        self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self._request_host_is_local() or not self._origin_is_same():
            self._send_json(
                403, {"error": "This app accepts same-origin requests only."}
            )
            return
        if not self._valid_session():
            self._send_json(403, {"error": "This browser session is not authorized."})
            return
        if not self._valid_body_size():
            self._send_json(413, {"error": "The request body is too large."})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/select-folder":
            payload = self._read_json_body()
            path = payload.get("path") if payload else None
            if not isinstance(path, str):
                self._send_json(400, {"error": "Choose a valid folder."})
                return
            try:
                selected = self.picker_state.select(path)
            except (OSError, ValueError):
                self._send_json(400, {"error": "That folder cannot be opened."})
                return
            self._send_json(200, {"selected": str(selected)})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if parsed.path == "/api/cancel":
            self.picker_state.cancel()
            self._send_json(200, {"cancelled": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._send_json(404, {"error": "Not found."})

    def do_OPTIONS(self) -> None:
        self._send_json(405, {"error": "Cross-origin requests are not supported."})


def create_folder_browser_server(
    initial_directory: str | Path | None = None,
    *,
    port: int = 8876,
) -> tuple[LoopbackHTTPServer, FolderBrowserState]:
    """Create a session-protected local folder browser."""
    state = FolderBrowserState(initial_directory)
    handler = type(
        "ConfiguredFolderBrowserHandler",
        (FolderBrowserHandler,),
        {"picker_state": state},
    )
    server = bind_loopback_server(
        handler,
        port,
        error_message="No available local port was found for folder selection.",
    )
    return server, state


def choose_source_folder_in_browser(
    initial_directory: str | Path | None = None,
    *,
    port: int = 8876,
    open_browser: bool = True,
) -> tuple[Path | None, int]:
    """Wait for a folder selection in a secured loopback browser workspace."""
    server, state = create_folder_browser_server(initial_directory, port=port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"Choose a Smart Lab Index source folder at {url}")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        state.cancel()
    finally:
        server.server_close()
    return state.selected, actual_port
