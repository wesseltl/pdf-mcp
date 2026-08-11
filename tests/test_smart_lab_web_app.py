"""End-to-end tests for the local Smart Lab Index browser interface."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from scripts.generate_smart_lab_example import generate
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.web_app import create_server


class SmartLabWebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name) / "sample-lab"
        generate(root)
        self.database = Path(self.temporary.name) / "state" / "index.db"
        self.server, self.state = create_server(
            root,
            database=self.database,
            source_id="lab-alpha-web",
            policy=RuntimePolicy(no_egress=True),
            port=0,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.state.wait_for_index(timeout=10)
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
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        content = response.read()
        result = response.status, dict(response.getheaders()), content
        connection.close()
        return result

    def api_headers(self) -> dict[str, str]:
        return {"X-Smart-Lab-Session": self.state.session_token}

    def state_payload(self) -> dict:
        status, _headers, content = self.request(
            "GET",
            "/api/state",
            headers=self.api_headers(),
        )
        self.assertEqual(status, 200)
        return json.loads(content)

    def test_home_and_assets_are_local_and_hardened(self) -> None:
        status, headers, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.state.session_token.encode(), html)
        self.assertNotIn(b"__SMART_LAB_SESSION__", html)
        self.assertNotIn(b"style=", html)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

        assets = [html]
        for path in ("/styles.css", "/app.js"):
            asset_status, asset_headers, content = self.request("GET", path)
            self.assertEqual(asset_status, 200)
            self.assertEqual(asset_headers["Cache-Control"], "no-store")
            assets.append(content)
        combined = b"\n".join(assets).lower()
        self.assertNotIn(b"https://", combined)
        self.assertNotIn(b"http://", combined)

    def test_state_requires_session_and_is_capability_driven(self) -> None:
        status, _headers, content = self.request("GET", "/api/state")
        self.assertEqual(status, 403)
        self.assertIn("not authorized", json.loads(content)["error"])

        payload = self.state_payload()
        self.assertEqual(payload["source"]["source_id"], "lab-alpha-web")
        self.assertTrue(payload["source"]["no_egress"])
        self.assertEqual(payload["summary"]["entities"], 0)
        view_ids = [view["view_id"] for view in payload["views"]]
        self.assertEqual(view_ids[0], "overview")
        self.assertIn("equipment", view_ids)
        self.assertIn("review", view_ids)
        self.assertIn("modules", view_ids)
        organizations = next(
            view for view in payload["views"] if view["view_id"] == "organizations"
        )
        self.assertEqual(
            organizations["entity_types"],
            ["ORGANIZATION", "ORGANIZATIONAL_UNIT"],
        )
        self.assertEqual(len(payload["modules"]), 13)
        self.assertTrue(
            all(module["health"] == "HEALTHY" for module in payload["modules"])
        )
        self.assertTrue(
            all(
                module["security"]["network_access"] == "NONE"
                for module in payload["modules"]
            )
        )

    def test_index_action_requires_session_and_same_origin(self) -> None:
        status, _headers, content = self.request("POST", "/api/index", body=b"")
        self.assertEqual(status, 403)
        self.assertIn("not authorized", json.loads(content)["error"])

        headers = self.api_headers()
        headers["Origin"] = "https://malicious.example"
        status, _headers, content = self.request(
            "POST",
            "/api/index",
            body=b"",
            headers=headers,
        )
        self.assertEqual(status, 403)
        self.assertIn("local requests", json.loads(content)["error"])

    def test_gui_rejects_in_memory_storage(self) -> None:
        with self.assertRaisesRegex(ValueError, "durable database"):
            create_server(
                self.state.root,
                database=":memory:",
                policy=RuntimePolicy(no_egress=True),
                port=0,
            )

    def test_gui_index_flow_preserves_evidence_and_is_incremental(self) -> None:
        status, _headers, content = self.request(
            "POST",
            "/api/index",
            body=b"",
            headers=self.api_headers(),
        )
        self.assertEqual(status, 202)
        self.assertTrue(json.loads(content)["started"])
        self.assertTrue(self.state.wait_for_index(timeout=10))

        payload = self.state_payload()
        self.assertEqual(payload["operation"]["state"], "IDLE")
        self.assertEqual(payload["operation"]["result"]["status"], "COMPLETED")
        self.assertEqual(payload["summary"]["sources"], 4)
        self.assertEqual(payload["summary"]["documents"], 4)
        self.assertEqual(payload["summary"]["entities"], 4)
        self.assertEqual(payload["summary"]["active_assertions"], 3)
        self.assertEqual(payload["summary"]["open_issues"], 1)
        self.assertEqual(
            {entity["canonical_name"] for entity in payload["entities"]},
            {"Alex Example", "Freezer-001", "Room A-101", "Room A-102"},
        )
        self.assertEqual(len(payload["responsibilities"]), 1)
        responsibility = payload["responsibilities"][0]
        self.assertEqual(responsibility["subject_name"], "Alex Example")
        self.assertEqual(responsibility["object_name"], "Freezer-001")

        issue = payload["issues"][0]
        self.assertEqual(issue["code"], "CONFLICTING_LOCATION")
        locations = issue["evidence"]["observed_locations"]
        evidence = {item["location_name"]: item["provenance"] for item in locations}
        self.assertEqual(evidence["Room A-101"]["locator"]["cell"], "D2")
        self.assertEqual(evidence["Room A-102"]["locator"]["paragraph"], 2)
        self.assertEqual(
            {assertion["source_path"] for assertion in payload["assertions"]},
            {
                "SOPs/SOP_freezers.docx",
                "equipment.xlsx",
                "responsibilities.xlsx",
            },
        )

        status, _headers, _content = self.request(
            "POST",
            "/api/index",
            body=b"",
            headers=self.api_headers(),
        )
        self.assertEqual(status, 202)
        self.assertTrue(self.state.wait_for_index(timeout=10))
        rerun = self.state_payload()["operation"]["result"]["stats"]
        self.assertEqual(rerun["unchanged"], 4)
        self.assertEqual(rerun["parsed"], 0)
        self.assertEqual(rerun["assertions"], 0)


if __name__ == "__main__":
    unittest.main()
