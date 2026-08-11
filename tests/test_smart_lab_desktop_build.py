"""Tests for Smart Lab Index desktop release trust helpers."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from scripts import build_smart_lab_desktop_app as desktop_build


class SmartLabDesktopBuildTests(unittest.TestCase):
    def test_checksum_manifest_matches_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "smart-lab-index.zip"
            archive.write_bytes(b"tested desktop archive")

            checksum = desktop_build.write_checksum(archive)

            expected = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(
                checksum.read_text(encoding="ascii"),
                f"{expected}  {archive.name}\n",
            )

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
            executable = root / "smart-lab-index.exe"
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
