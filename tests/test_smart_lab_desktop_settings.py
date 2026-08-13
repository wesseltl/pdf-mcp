"""Tests for remembered self-service desktop workspaces."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from smart_lab_index.application.desktop_settings import (
    DesktopSettings,
    DesktopSettingsError,
    forget_desktop_settings,
    load_desktop_settings,
    save_desktop_settings,
)


class DesktopSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "Lab Alpha"
        self.root.mkdir()
        self.database = self.base / "state" / "index.db"
        self.settings_path = self.base / "preferences" / "desktop.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_private_settings_round_trip_without_credentials(self) -> None:
        settings = DesktopSettings(
            root=self.root.resolve(),
            database=self.database.resolve(),
            index_interval_minutes=30,
        )

        saved = save_desktop_settings(settings, self.settings_path)
        loaded = load_desktop_settings(self.settings_path)
        payload = json.loads(saved.read_text(encoding="ascii"))

        self.assertEqual(
            loaded,
            settings.__class__(
                root=settings.root,
                database=settings.database,
                index_interval_minutes=30,
                saved_at=payload["saved_at"],
            ),
        )
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn("token", saved.read_text(encoding="ascii").lower())
        self.assertFalse(any(saved.parent.glob("*.tmp")))

    def test_missing_settings_and_forget_are_idempotent(self) -> None:
        self.assertIsNone(load_desktop_settings(self.settings_path))
        self.assertFalse(forget_desktop_settings(self.settings_path))
        save_desktop_settings(
            DesktopSettings(self.root.resolve(), self.database.resolve()),
            self.settings_path,
        )
        self.assertTrue(forget_desktop_settings(self.settings_path))
        self.assertFalse(forget_desktop_settings(self.settings_path))

    def test_invalid_schema_unknown_fields_and_relative_paths_fail_closed(self) -> None:
        cases = (
            {"schema_version": 2, "workspace": {}},
            {
                "schema_version": 1,
                "workspace": {
                    "root": str(self.root.resolve()),
                    "database": str(self.database.resolve()),
                    "secret": "must-not-be-accepted",
                },
            },
            {
                "schema_version": 1,
                "workspace": {"root": "relative", "database": "relative.db"},
            },
        )
        self.settings_path.parent.mkdir()
        for payload in cases:
            self.settings_path.write_text(json.dumps(payload), encoding="utf-8")
            self.settings_path.chmod(0o600)
            with self.subTest(payload=payload), self.assertRaises(DesktopSettingsError):
                load_desktop_settings(self.settings_path)

    @unittest.skipUnless(os.name == "posix", "POSIX link and mode checks")
    def test_public_linked_or_oversized_settings_are_rejected(self) -> None:
        target = self.base / "target.json"
        target.write_text("{}", encoding="ascii")
        target.chmod(0o600)
        self.settings_path.parent.mkdir()

        self.settings_path.symlink_to(target)
        with self.assertRaisesRegex(DesktopSettingsError, "symbolic link"):
            load_desktop_settings(self.settings_path)
        self.settings_path.unlink()

        os.link(target, self.settings_path)
        with self.assertRaisesRegex(DesktopSettingsError, "hard links"):
            load_desktop_settings(self.settings_path)
        self.settings_path.unlink()
        target.unlink()

        self.settings_path.write_text("{}", encoding="ascii")
        self.settings_path.chmod(0o644)
        with self.assertRaisesRegex(DesktopSettingsError, "permissions"):
            load_desktop_settings(self.settings_path)


if __name__ == "__main__":
    unittest.main()
