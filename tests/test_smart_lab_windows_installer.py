"""Tests for the Smart Lab Index Windows installer contract."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_smart_lab_windows_installer as installer_build


class SmartLabWindowsInstallerTests(unittest.TestCase):
    def test_installer_is_per_user_upgradeable_and_preserves_user_data(self) -> None:
        definition = installer_build.INNO_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            "AppId={{A3B6E3AE-82EA-4F6A-B941-7E3289C62B8F}", definition
        )
        self.assertIn("PrivilegesRequired=lowest", definition)
        self.assertIn(
            "DefaultDirName={localappdata}\\Programs\\Smart Lab Index", definition
        )
        self.assertIn("ArchitecturesAllowed=x64compatible", definition)
        self.assertIn("CloseApplications=yes", definition)
        self.assertIn("UninstallDisplayIcon={app}\\smart-lab-index.exe", definition)
        self.assertNotIn("[UninstallDelete]", definition)
        self.assertNotIn(".smart-lab-index", definition)

    def test_installer_provides_start_menu_optional_desktop_and_launch(self) -> None:
        definition = installer_build.INNO_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('Name: "{group}\\Smart Lab Index"', definition)
        self.assertIn('Name: "desktopicon"', definition)
        self.assertIn('Name: "{userdesktop}\\Smart Lab Index"', definition)
        self.assertIn("postinstall skipifsilent", definition)

    def test_installer_artifact_name_is_versioned_and_unambiguous(self) -> None:
        name = installer_build.installer_path().name

        self.assertTrue(name.startswith("smart-lab-index-setup-v"))
        self.assertTrue(name.endswith("-windows-x64.exe"))

    def test_configured_inno_compiler_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            compiler = Path(temporary) / "ISCC.exe"
            compiler.write_bytes(b"compiler fixture")
            with patch.dict(
                os.environ,
                {"SMART_LAB_INNO_SETUP_COMPILER": str(compiler)},
                clear=True,
            ):
                discovered = installer_build.find_inno_compiler()

        self.assertEqual(discovered, compiler.resolve())


if __name__ == "__main__":
    unittest.main()
