"""Tests for LabOverlay desktop release trust helpers."""

from __future__ import annotations

import hashlib
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from scripts import build_smart_lab_desktop_app as desktop_build


class SmartLabDesktopBuildTests(unittest.TestCase):
    def test_smoke_waits_for_a_deferred_initial_index(self) -> None:
        self.assertTrue(
            desktop_build._index_pending({"state": "IDLE", "completed_at": None})
        )
        self.assertTrue(
            desktop_build._index_pending(
                {"state": "INDEXING", "completed_at": None}
            )
        )
        self.assertFalse(
            desktop_build._index_pending(
                {"state": "IDLE", "completed_at": "2026-08-12T00:00:00Z"}
            )
        )

    def test_index_failure_detail_is_bounded_and_actionable(self) -> None:
        state = {
            "operation": {"error": None},
            "issues": [
                {
                    "code": "PARSING_FAILURE",
                    "status": "OPEN",
                    "evidence": {"error": "parser worker exited with code 1"},
                }
            ],
        }

        self.assertEqual(
            desktop_build._index_failure_detail(state),
            "PARSING_FAILURE=parser worker exited with code 1",
        )

    def test_smoke_environment_preserves_case_insensitive_windows_runtime(self) -> None:
        values = {
            "Path": "C:\\Windows\\System32",
            "SystemRoot": "C:\\Windows",
            "APPDATA": "C:\\Users\\Example\\AppData\\Roaming",
            "GITHUB_TOKEN": "must-not-reach-the-app",
            "SMART_LAB_WINDOWS_CERTIFICATE_PASSWORD": "also-secret",
        }
        with patch.dict(os.environ, values, clear=True):
            environment = desktop_build._smoke_environment()

        self.assertEqual(
            environment,
            {
                "Path": values["Path"],
                "SystemRoot": values["SystemRoot"],
                "APPDATA": values["APPDATA"],
            },
        )

    def test_checksum_manifest_matches_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "laboverlay.zip"
            archive.write_bytes(b"tested desktop archive")

            checksum = desktop_build.write_checksum(archive)

            expected = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(
                checksum.read_text(encoding="ascii"),
                f"{expected}  {archive.name}\n",
            )

    def test_windows_version_quad_is_numeric_and_padded(self) -> None:
        self.assertEqual(
            desktop_build.windows_version_quad("0.7.0-beta.3"),
            (0, 7, 0, 3),
        )
        self.assertEqual(desktop_build.windows_version_quad("2.1"), (2, 1, 0, 0))

    def test_windows_assets_include_product_metadata_and_icon_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            icon = desktop_build.write_windows_icon(root / "laboverlay.ico")
            version_info = desktop_build.write_windows_version_info(
                root / "version.txt", "1.2.3"
            )

            reserved, image_type, image_count = struct.unpack(
                "<HHH", icon.read_bytes()[:6]
            )
            metadata = version_info.read_text(encoding="utf-8")

        self.assertEqual((reserved, image_type), (0, 1))
        self.assertGreaterEqual(image_count, 6)
        self.assertIn("ProductName', u'LabOverlay", metadata)
        self.assertIn("filevers=(1, 2, 3, 0)", metadata)

    def test_unsigned_is_explicit_without_platform_credentials(self) -> None:
        with (
            patch.object(desktop_build.sys, "platform", "win32"),
            patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(desktop_build.sign_desktop_app(), "unsigned")

        with (
            patch.object(desktop_build.sys, "platform", "darwin"),
            patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(desktop_build.sign_desktop_app(), "unsigned")

    def test_windows_signing_uses_sha256_timestamp_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            certificate = root / "publisher.pfx"
            executable = root / "laboverlay.exe"
            certificate.write_bytes(b"certificate fixture")
            executable.write_bytes(b"executable fixture")
            environment = {
                "SMART_LAB_WINDOWS_CERTIFICATE_PATH": str(certificate),
                "SMART_LAB_WINDOWS_CERTIFICATE_PASSWORD": "test-password",
                "SMART_LAB_WINDOWS_TIMESTAMP_URL": "https://timestamp.example",
            }
            with (
                patch.object(desktop_build.sys, "platform", "win32"),
                patch.dict(os.environ, environment, clear=True),
                patch.object(desktop_build, "signing_target", return_value=executable),
                patch.object(
                    desktop_build,
                    "_windows_signtool",
                    return_value=Path("signtool.exe"),
                ),
                patch.object(desktop_build.subprocess, "run") as run,
            ):
                status = desktop_build.sign_desktop_app()

        self.assertEqual(status, "signed")
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    [
                        "signtool.exe",
                        "sign",
                        "/fd",
                        "SHA256",
                        "/tr",
                        "https://timestamp.example",
                        "/td",
                        "SHA256",
                        "/f",
                        str(certificate.resolve()),
                        "/p",
                        "test-password",
                        str(executable),
                    ],
                    check=True,
                ),
                call(
                    [
                        "signtool.exe",
                        "verify",
                        "/pa",
                        "/v",
                        str(executable),
                    ],
                    check=True,
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
