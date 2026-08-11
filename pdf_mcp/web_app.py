"""Local browser interface for no-code document table conversion."""
from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from pdf_mcp import exporter, extractor

LOGGER = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_OUTPUT_BYTES = 50 * 1024 * 1024
MAX_TOTAL_DOWNLOAD_BYTES = 100 * 1024 * 1024
DOWNLOAD_TTL_SECONDS = 30 * 60
MAX_DOWNLOADS = 5
SUPPORTED_INPUTS = {".pdf", ".docx"}
SUPPORTED_OUTPUTS = {"xlsx", "csv", "json"}
OUTPUT_CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json; charset=utf-8",
}
STATIC_ASSETS = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


@dataclass(frozen=True)
class Download:
    content: bytes
    filename: str
    content_type: str
    created_at: float


class AppState:
    def __init__(self) -> None:
        self.session_token = secrets.token_urlsafe(32)
        self._downloads: dict[str, Download] = {}
        self._lock = threading.Lock()

    def add_download(self, content: bytes, filename: str, content_type: str) -> str:
        with self._lock:
            self._remove_expired_locked()
            while self._downloads and (
                len(self._downloads) >= MAX_DOWNLOADS
                or sum(len(item.content) for item in self._downloads.values()) + len(content)
                > MAX_TOTAL_DOWNLOAD_BYTES
            ):
                oldest = min(self._downloads, key=lambda key: self._downloads[key].created_at)
                self._downloads.pop(oldest, None)
            download_id = secrets.token_urlsafe(18)
            self._downloads[download_id] = Download(
                content=content,
                filename=filename,
                content_type=content_type,
                created_at=time.monotonic(),
            )
            return download_id

    def get_download(self, download_id: str) -> Download | None:
        with self._lock:
            self._remove_expired_locked()
            return self._downloads.get(download_id)

    def clear(self) -> None:
        with self._lock:
            self._downloads.clear()

    def _remove_expired_locked(self) -> None:
        cutoff = time.monotonic() - DOWNLOAD_TTL_SECONDS
        expired = [
            download_id
            for download_id, download in self._downloads.items()
            if download.created_at < cutoff
        ]
        for download_id in expired:
            self._downloads.pop(download_id, None)


def _asset_bytes(name: str) -> bytes:
    return resources.files("pdf_mcp.web_ui").joinpath(name).read_bytes()


def _original_filename(value: str) -> str:
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        raise ValueError("Choose a PDF or Word document with a valid filename.")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_INPUTS:
        raise ValueError("This app accepts PDF and Word .docx files only.")
    if len(name) > 180:
        name = f"{Path(name).stem[:160]}{suffix}"
    return name


def _output_filename(input_name: str, output_type: str) -> str:
    stem = Path(input_name).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._") or "document"
    return f"{safe_stem[:100]}-tables.{output_type}"


def _validate_file_signature(filename: str, content: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and b"%PDF-" not in content[:1024]:
        raise ValueError("This file has a .pdf name but does not appear to be a PDF.")
    if suffix == ".docx" and not content.startswith(b"PK"):
        raise ValueError("This file has a .docx name but does not appear to be a Word document.")


def _table_location(table: dict) -> str:
    pages = table.get("merged_from_pages")
    if pages:
        return f"Pages {pages[0]}-{pages[-1]}" if len(pages) > 1 else f"Page {pages[0]}"
    if table.get("page") is not None:
        return f"Page {table['page']}"
    if table.get("index") is not None:
        return f"Table {table['index'] + 1}"
    return "Document table"


def _preview_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= 160 else f"{text[:157]}..."


def _preview_tables(tables: list[dict]) -> list[dict]:
    previews = []
    for index, table in enumerate(tables[:10]):
        rows = table.get("rows", [])
        preview_rows = [
            [_preview_cell(cell) for cell in row[:12]]
            for row in rows[:25]
        ]
        previews.append({
            "name": f"Table {index + 1}",
            "location": _table_location(table),
            "looks_clean": bool(table.get("looks_clean")),
            "warnings": list(table.get("warnings") or []),
            "rows": preview_rows,
            "n_rows": table.get("n_rows", len(rows)),
            "preview_truncated": len(rows) > 25 or any(len(row) > 12 for row in rows),
        })
    return previews


class LocalAppHandler(BaseHTTPRequestHandler):
    app_state: AppState
    server_version = "pdf-mcp-local"

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.debug(format, *args)

    def do_GET(self) -> None:
        if not self._request_host_is_local():
            self._send_json(403, {"error": "This app accepts local requests only."})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = _asset_bytes("index.html").replace(
                b"__PDF_MCP_SESSION__",
                self.app_state.session_token.encode("ascii"),
            )
            self._send_bytes(200, html, "text/html; charset=utf-8")
            return
        if parsed.path in STATIC_ASSETS:
            filename, content_type = STATIC_ASSETS[parsed.path]
            self._send_bytes(200, _asset_bytes(filename), content_type)
            return
        if parsed.path.startswith("/api/download/"):
            self._serve_download(parsed.path.rsplit("/", 1)[-1])
            return
        self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self._request_host_is_local() or not self._origin_is_local():
            self._send_json(403, {"error": "This app accepts local requests only."})
            return
        if not self._valid_session():
            self._send_json(403, {"error": "This browser session is not authorized."})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/shutdown":
            self._send_json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if parsed.path != "/api/convert":
            self._send_json(404, {"error": "Not found."})
            return
        try:
            self._convert(parse_qs(parsed.query))
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except PermissionError:
            self._send_json(403, {"error": "The selected file could not be accessed."})
        except Exception:
            LOGGER.exception("Local conversion failed")
            self._send_json(500, {
                "error": "The document could not be converted.",
                "detail": "It may be damaged, password-protected, or use a table layout this version cannot read.",
            })

    def do_OPTIONS(self) -> None:
        self._send_json(405, {"error": "Cross-origin requests are not supported."})

    def _convert(self, query: dict[str, list[str]]) -> None:
        filename = _original_filename((query.get("filename") or [""])[0])
        output_type = (query.get("format") or ["xlsx"])[0].lower()
        if output_type not in SUPPORTED_OUTPUTS:
            raise ValueError("Choose Excel, CSV, or JSON as the output format.")
        merge_multipage = (query.get("merge_multipage") or ["1"])[0] != "0"
        content = self._read_upload()
        _validate_file_signature(filename, content)

        suffix = Path(filename).suffix.lower()
        output_name = _output_filename(filename, output_type)
        allowed_dir = os.environ.get("PDF_MCP_ALLOWED_DIR")
        temp_parent = allowed_dir if allowed_dir and os.path.isdir(allowed_dir) else None
        with tempfile.TemporaryDirectory(prefix="pdf-mcp-", dir=temp_parent) as temp_dir:
            input_path = Path(temp_dir) / f"input{suffix}"
            output_path = Path(temp_dir) / f"output.{output_type}"
            input_path.write_bytes(content)
            if suffix == ".pdf" and extractor.page_count(str(input_path)) > MAX_PDF_PAGES:
                raise ValueError("The PDF has more than the 100-page local-app limit.")
            result = exporter.extract_document_tables(
                str(input_path),
                merge_multipage=merge_multipage,
                source_name=filename,
            )
            if not result.get("tables"):
                warning = (result.get("warnings") or ["No tables were found."])[0]
                self._send_json(422, {
                    "error": "No tables were found in this document.",
                    "detail": warning,
                    "hint": "Scanned and image-only PDFs need OCR, which this version does not include.",
                })
                return
            summary = exporter.write_document_tables(result, str(output_path))
            output_content = output_path.read_bytes()
            if len(output_content) > MAX_OUTPUT_BYTES:
                raise ValueError("The converted output is larger than the 50 MB local-app limit.")

        download_id = self.app_state.add_download(
            output_content,
            output_name,
            OUTPUT_CONTENT_TYPES[output_type],
        )
        self._send_json(200, {
            "ok": True,
            "input_name": filename,
            "output_name": output_name,
            "output_type": output_type,
            "n_tables": summary["n_tables"],
            "tables_needing_review": summary["tables_needing_review"],
            "warnings": summary["warnings"],
            "download_id": download_id,
            "tables": _preview_tables(result["tables"]),
            "preview_tables_omitted": max(0, len(result["tables"]) - 10),
        })

    def _read_upload(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("The browser sent an invalid file size.") from exc
        if length <= 0:
            raise ValueError("Choose a non-empty PDF or Word document.")
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("The file is larger than the 25 MB local-app limit.")
        content = self.rfile.read(length)
        if len(content) != length:
            raise ValueError("The file upload ended before it was complete.")
        return content

    def _serve_download(self, download_id: str) -> None:
        if not self._valid_session():
            self._send_json(403, {"error": "This browser session is not authorized."})
            return
        download = self.app_state.get_download(download_id)
        if download is None:
            self._send_json(404, {"error": "This download expired. Convert the document again."})
            return
        self.send_response(200)
        self._security_headers(download.content_type)
        encoded_name = quote(download.filename)
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
        self.send_header("Content-Length", str(len(download.content)))
        self.end_headers()
        self.wfile.write(download.content)

    def _request_host_is_local(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        hostname = host.rsplit(":", 1)[0].strip("[]")
        return hostname in {"127.0.0.1", "localhost", "::1"}

    def _origin_is_local(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def _valid_session(self) -> bool:
        supplied = self.headers.get("X-Pdf-Mcp-Session", "")
        return bool(supplied) and hmac.compare_digest(supplied, self.app_state.session_token)

    def _send_json(self, status: int, payload: dict) -> None:
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
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")


def create_server(port: int = 8765) -> tuple[ThreadingHTTPServer, AppState]:
    """Create a loopback-only app server, trying nearby ports if the preferred one is busy."""
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    state = AppState()
    handler = type("ConfiguredLocalAppHandler", (LocalAppHandler,), {"app_state": state})
    candidates = [0] if port == 0 else range(port, min(port + 20, 65536))
    last_error: OSError | None = None
    for candidate in candidates:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            server.daemon_threads = True
            return server, state
        except OSError as exc:
            last_error = exc
    raise OSError("No available local port was found for the pdf-mcp app.") from last_error


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pdf-mcp-app",
        description="Open the simple local browser app for PDF and Word table conversion.",
    )
    parser.add_argument("--port", type=int, default=8765, help="Preferred local port (default: 8765).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically.")
    args = parser.parse_args()

    server, state = create_server(args.port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"pdf-mcp is ready at {url}")
    print("Files are processed on this computer and deleted after each conversion.")
    print("Press Ctrl+C to stop the app.")
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping pdf-mcp.")
    finally:
        state.clear()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
