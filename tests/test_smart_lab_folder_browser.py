"""Tests for the zero-dependency local folder navigator."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from smart_lab_index.folder_browser import (
    FolderBrowserState,
    create_folder_browser_server,
)


class FolderBrowserStateTests(unittest.TestCase):
    def test_snapshot_is_directory_only_sorted_and_bounded_to_requested_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Zulu").mkdir()
            (root / "Alpha").mkdir()
            (root / ".private").mkdir()
            (root / "notes.txt").write_text("not a folder", encoding="utf-8")
            state = FolderBrowserState(root)

            snapshot = state.directory_snapshot(None)
            hidden_snapshot = state.directory_snapshot(str(root), show_hidden=True)

        self.assertEqual(
            [folder["name"] for folder in snapshot["folders"]],
            ["Alpha", "Zulu"],
        )
        self.assertEqual(
            [folder["name"] for folder in hidden_snapshot["folders"]],
            [".private", "Alpha", "Zulu"],
        )
        self.assertEqual(snapshot["path"], str(root.resolve()))
        self.assertTrue(snapshot["ancestors"])
        self.assertFalse(snapshot["truncated"])

    def test_selection_requires_an_existing_readable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file_path = root / "record.txt"
            file_path.write_text("record", encoding="utf-8")
            state = FolderBrowserState(root)

            self.assertEqual(state.select(str(root)), root.resolve())
            self.assertEqual(state.selected, root.resolve())
            with self.assertRaisesRegex(ValueError, "not a folder"):
                state.select(str(file_path))
            with self.assertRaises(FileNotFoundError):
                state.select(str(root / "missing"))

    def test_large_directory_listing_is_memory_bounded_and_marked_truncated(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(503):
                (root / f"Folder {index:03d}").mkdir()
            state = FolderBrowserState(root)

            snapshot = state.directory_snapshot(None)

        self.assertEqual(len(snapshot["folders"]), 500)
        self.assertTrue(snapshot["truncated"])
        self.assertEqual(snapshot["folders"][0]["name"], "Folder 000")
        self.assertEqual(snapshot["folders"][-1]["name"], "Folder 499")


class FolderBrowserHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "Lab Alpha").mkdir()
        self.server, self.state = create_folder_browser_server(self.root, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        content = response.read()
        result = response.status, dict(response.getheaders()), content
        connection.close()
        return result

    def api_headers(self) -> dict[str, str]:
        return {
            "Origin": f"http://127.0.0.1:{self.port}",
            "X-Smart-Lab-Session": self.state.session_token,
        }

    def test_assets_are_local_and_folder_listing_requires_session(self) -> None:
        status, headers, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.state.session_token.encode(), html)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

        assets = [html]
        for path in ("/folder-browser.css", "/folder-browser.js"):
            asset_status, _asset_headers, content = self.request("GET", path)
            self.assertEqual(asset_status, 200)
            assets.append(content)
        combined = b"\n".join(assets).lower()
        self.assertNotIn(b"https://", combined)
        self.assertNotIn(b"http://", combined)

        status, _headers, content = self.request("GET", "/api/folders")
        self.assertEqual(status, 403)
        self.assertIn("not authorized", json.loads(content)["error"])

        status, _headers, content = self.request(
            "GET",
            "/api/folders",
            headers=self.api_headers(),
        )
        self.assertEqual(status, 200)
        payload = json.loads(content)
        self.assertEqual(payload["path"], str(self.root.resolve()))
        self.assertEqual(payload["folders"][0]["name"], "Lab Alpha")

    def test_selection_requires_exact_origin_and_stops_server(self) -> None:
        body = json.dumps({"path": str(self.root / "Lab Alpha")}).encode()
        status, _headers, content = self.request(
            "POST",
            "/api/select-folder",
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Smart-Lab-Session": self.state.session_token,
            },
        )
        self.assertEqual(status, 403)
        self.assertIn("same-origin", json.loads(content)["error"])

        headers = self.api_headers()
        headers["Content-Type"] = "application/json"
        headers["Origin"] = f"http://127.0.0.1:{self.port + 1}"
        status, _headers, content = self.request(
            "POST",
            "/api/select-folder",
            body=body,
            headers=headers,
        )
        self.assertEqual(status, 403)
        self.assertIn("same-origin", json.loads(content)["error"])

        forged_port = self.port + 1
        headers["Host"] = f"127.0.0.1:{forged_port}"
        headers["Origin"] = f"http://127.0.0.1:{forged_port}"
        status, _headers, content = self.request(
            "POST",
            "/api/select-folder",
            body=body,
            headers=headers,
        )
        self.assertEqual(status, 403)
        self.assertIn("same-origin", json.loads(content)["error"])

        headers.pop("Host")
        headers["Origin"] = f"http://127.0.0.1:{self.port}"
        status, _headers, content = self.request(
            "POST",
            "/api/select-folder",
            body=body,
            headers=headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(content)["selected"],
            str((self.root / "Lab Alpha").resolve()),
        )
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.state.selected, (self.root / "Lab Alpha").resolve())


if __name__ == "__main__":
    unittest.main()
