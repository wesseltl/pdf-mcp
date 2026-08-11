"""End-to-end tests for the local Smart Lab Index browser interface."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from scripts.generate_smart_lab_example import generate
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.web_app import create_server, main


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
            allow_source_change=True,
            port=0,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        if self.thread.is_alive():
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
        return {
            "Origin": f"http://127.0.0.1:{self.port}",
            "X-Smart-Lab-Session": self.state.session_token,
        }

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
        self.assertTrue(payload["source"]["can_change_source"])
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
        status, _headers, content = self.request(
            "POST",
            "/api/index",
            body=b"",
            headers={"Origin": f"http://127.0.0.1:{self.port}"},
        )
        self.assertEqual(status, 403)
        self.assertIn("not authorized", json.loads(content)["error"])

        status, _headers, content = self.request(
            "POST",
            "/api/index",
            body=b"",
            headers={"X-Smart-Lab-Session": self.state.session_token},
        )
        self.assertEqual(status, 403)
        self.assertIn("local requests", json.loads(content)["error"])

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

        forged_port = self.port + 1
        headers = self.api_headers()
        headers["Host"] = f"127.0.0.1:{forged_port}"
        headers["Origin"] = f"http://127.0.0.1:{forged_port}"
        status, _headers, content = self.request(
            "POST",
            "/api/index",
            body=b"",
            headers=headers,
        )
        self.assertEqual(status, 403)
        self.assertIn("local requests", json.loads(content)["error"])

        headers["Origin"] = f"http://127.0.0.1:{self.port + 1}"
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

    def test_change_source_action_is_authenticated_and_stops_for_picker(self) -> None:
        status, _headers, _content = self.request(
            "POST",
            "/api/change-source",
            body=b"",
        )
        self.assertEqual(status, 403)

        status, _headers, content = self.request(
            "POST",
            "/api/change-source",
            body=b"",
            headers=self.api_headers(),
        )
        self.assertEqual(status, 202)
        self.assertTrue(json.loads(content)["changing"])
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.assertTrue(self.state.source_change_requested)

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


class SmartLabWebAppMainTests(unittest.TestCase):
    def test_no_root_uses_picker_enables_no_egress_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "lab"
            root.mkdir()
            server = Mock()
            server.server_address = ("127.0.0.1", 9020)
            state = Mock()
            state.root = str(root)
            state.database = str(Path(temporary) / "index.db")
            state.policy = RuntimePolicy(no_egress=True)
            state.source_change_requested = False
            with (
                patch(
                    "smart_lab_index.web_app.folder_picker_available",
                    return_value=True,
                ),
                patch(
                    "smart_lab_index.web_app.choose_source_folder",
                    return_value=root,
                ),
                patch(
                    "smart_lab_index.web_app.create_server",
                    return_value=(server, state),
                ) as create,
            ):
                result = main(["--no-browser", "--port", "0"])

        self.assertEqual(result, 0)
        self.assertTrue(create.call_args.kwargs["policy"].no_egress)
        self.assertTrue(create.call_args.kwargs["allow_source_change"])
        managed_database = Path(create.call_args.kwargs["database"])
        self.assertEqual(managed_database.parent.name, "workspaces")
        self.assertNotIn(root.name, managed_database.name)
        state.start_index.assert_called_once_with()
        server.serve_forever.assert_called_once_with(poll_interval=0.25)

    def test_no_root_falls_back_to_local_browser_folder_navigator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "lab"
            root.mkdir()
            server = Mock()
            server.server_address = ("127.0.0.1", 9025)
            state = Mock()
            state.root = str(root)
            state.database = str(Path(temporary) / "index.db")
            state.policy = RuntimePolicy(no_egress=True)
            state.source_change_requested = False
            with (
                patch(
                    "smart_lab_index.web_app.folder_picker_available",
                    return_value=False,
                ),
                patch(
                    "smart_lab_index.web_app.choose_source_folder_in_browser",
                    return_value=(root, 9025),
                ) as browser_picker,
                patch(
                    "smart_lab_index.web_app.create_server",
                    return_value=(server, state),
                ) as create,
            ):
                result = main(["--no-browser", "--port", "9025"])

        self.assertEqual(result, 0)
        browser_picker.assert_called_once_with(port=9025, open_browser=False)
        self.assertTrue(create.call_args.kwargs["allow_source_change"])
        self.assertTrue(create.call_args.kwargs["policy"].no_egress)
        state.start_index.assert_called_once_with()

    def test_source_change_restarts_same_port_and_clears_explicit_source_id(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_root = Path(temporary) / "first"
            second_root = Path(temporary) / "second"
            first_root.mkdir()
            second_root.mkdir()
            servers = [Mock(), Mock()]
            states = [Mock(), Mock()]
            for server in servers:
                server.server_address = ("127.0.0.1", 9030)
            for state, root, changing in zip(
                states,
                (first_root, second_root),
                (True, False),
                strict=True,
            ):
                state.root = str(root)
                state.database = str(Path(temporary) / "index.db")
                state.policy = RuntimePolicy(no_egress=True)
                state.source_change_requested = changing
            with (
                patch(
                    "smart_lab_index.web_app.folder_picker_available",
                    return_value=True,
                ),
                patch(
                    "smart_lab_index.web_app.choose_source_folder",
                    return_value=second_root,
                ),
                patch(
                    "smart_lab_index.web_app.create_server",
                    side_effect=list(zip(servers, states, strict=True)),
                ) as create,
            ):
                result = main(
                    [
                        str(first_root),
                        "--source-id",
                        "explicit-source",
                        "--no-browser",
                        "--port",
                        "9030",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(
            create.call_args_list,
            [
                call(
                    str(first_root),
                    database="~/.smart-lab-index/index.db",
                    source_id="explicit-source",
                    policy=RuntimePolicy(no_egress=False),
                    disabled_module_ids=[],
                    allow_source_change=True,
                    port=9030,
                ),
                call(
                    second_root,
                    database="~/.smart-lab-index/index.db",
                    source_id=None,
                    policy=RuntimePolicy(no_egress=False),
                    disabled_module_ids=[],
                    allow_source_change=True,
                    port=9030,
                ),
            ],
        )
        states[0].start_index.assert_not_called()
        states[1].start_index.assert_called_once_with()

    def test_source_change_uses_browser_navigator_when_system_dialog_is_absent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_root = Path(temporary) / "first"
            second_root = Path(temporary) / "second"
            first_root.mkdir()
            second_root.mkdir()
            servers = [Mock(), Mock()]
            states = [Mock(), Mock()]
            for server in servers:
                server.server_address = ("127.0.0.1", 9050)
            for state, root, changing in zip(
                states,
                (first_root, second_root),
                (True, False),
                strict=True,
            ):
                state.root = str(root)
                state.database = str(Path(temporary) / "index.db")
                state.policy = RuntimePolicy(no_egress=True)
                state.source_change_requested = changing
            with (
                patch(
                    "smart_lab_index.web_app.folder_picker_available",
                    return_value=False,
                ),
                patch(
                    "smart_lab_index.web_app.choose_source_folder_in_browser",
                    return_value=(second_root, 9050),
                ) as browser_picker,
                patch(
                    "smart_lab_index.web_app.create_server",
                    side_effect=list(zip(servers, states, strict=True)),
                ) as create,
            ):
                result = main(
                    [
                        str(first_root),
                        "--database",
                        states[0].database,
                        "--no-browser",
                        "--port",
                        "9050",
                    ]
                )

        self.assertEqual(result, 0)
        browser_picker.assert_called_once_with(
            str(first_root),
            port=9050,
            open_browser=False,
        )
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[1].args[0], second_root)
        self.assertTrue(create.call_args_list[1].kwargs["allow_source_change"])
        states[1].start_index.assert_called_once_with()

    def test_failed_source_change_restores_previous_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_root = Path(temporary) / "first"
            rejected_root = Path(temporary) / "rejected"
            first_root.mkdir()
            rejected_root.mkdir()
            first_server = Mock()
            restored_server = Mock()
            first_server.server_address = ("127.0.0.1", 9040)
            restored_server.server_address = ("127.0.0.1", 9040)
            first_state = Mock()
            first_state.root = str(first_root)
            first_state.database = str(Path(temporary) / "index.db")
            first_state.policy = RuntimePolicy(no_egress=True)
            first_state.source_change_requested = True
            restored_state = Mock()
            restored_state.root = str(first_root)
            restored_state.database = first_state.database
            restored_state.policy = RuntimePolicy(no_egress=True)
            restored_state.source_change_requested = False
            with (
                patch(
                    "smart_lab_index.web_app.folder_picker_available",
                    return_value=True,
                ),
                patch(
                    "smart_lab_index.web_app.choose_source_folder",
                    return_value=rejected_root,
                ),
                patch(
                    "smart_lab_index.web_app.create_server",
                    side_effect=[
                        (first_server, first_state),
                        ValueError("invalid selected source"),
                        (restored_server, restored_state),
                    ],
                ) as create,
            ):
                result = main(
                    [
                        str(first_root),
                        "--database",
                        first_state.database,
                        "--no-browser",
                        "--port",
                        "9040",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual(create.call_count, 3)
        self.assertEqual(create.call_args_list[-1].args[0], str(first_root))
        restored_state.start_index.assert_not_called()


if __name__ == "__main__":
    unittest.main()
