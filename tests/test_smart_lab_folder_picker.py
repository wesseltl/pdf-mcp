"""Tests for the local desktop folder-selection adapter."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from smart_lab_index.folder_picker import (
    FolderPickerUnavailable,
    choose_source_folder,
    folder_picker_available,
)


class FolderPickerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.selected = self.root / "Lab Alpha"
        self.selected.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_linux_dialog_passes_paths_as_arguments_and_environment(self) -> None:
        calls: list[tuple[list[str], dict[str, str]]] = []

        def runner(command, **kwargs):
            calls.append((list(command), kwargs["env"]))
            return subprocess.CompletedProcess(command, 0, f"{self.selected}\n", "")

        chosen = choose_source_folder(
            self.root,
            platform="linux",
            environment={"DISPLAY": ":1", "LAB_API_KEY": "do-not-forward"},
            which=lambda name: "/usr/bin/zenity" if name == "zenity" else None,
            runner=runner,
        )

        self.assertEqual(chosen, self.selected.resolve())
        command, environment = calls[0]
        self.assertEqual(command[0], "/usr/bin/zenity")
        self.assertIn(f"--filename={self.root.resolve()}/", command)
        self.assertEqual(
            environment["SMART_LAB_INDEX_INITIAL_FOLDER"],
            str(self.root.resolve()),
        )
        self.assertNotIn("LAB_API_KEY", environment)

    def test_cancel_returns_none_without_treating_it_as_failure(self) -> None:
        chosen = choose_source_folder(
            self.root,
            platform="linux",
            environment={"DISPLAY": ":1"},
            which=lambda name: "/usr/bin/kdialog" if name == "kdialog" else None,
            runner=lambda command, **kwargs: subprocess.CompletedProcess(
                command, 1, "", "cancelled"
            ),
        )
        self.assertIsNone(chosen)

    def test_windows_initial_path_is_not_embedded_in_command_text(self) -> None:
        commands: list[list[str]] = []

        def runner(command, **kwargs):
            commands.append(list(command))
            return subprocess.CompletedProcess(command, 0, str(self.selected), "")

        chosen = choose_source_folder(
            self.root,
            platform="win32",
            environment={},
            which=lambda name: "powershell.exe" if name == "powershell.exe" else None,
            runner=runner,
        )

        self.assertEqual(chosen, self.selected.resolve())
        self.assertNotIn(str(self.root), " ".join(commands[0]))

    def test_unavailable_or_invalid_selection_fails_with_bounded_error(self) -> None:
        self.assertFalse(
            folder_picker_available(
                platform="linux",
                environment={},
                which=lambda _name: "/usr/bin/zenity",
            )
        )
        with self.assertRaisesRegex(FolderPickerUnavailable, "zenity, kdialog, or yad"):
            choose_source_folder(
                self.root,
                platform="linux",
                environment={"DISPLAY": ":1"},
                which=lambda _name: None,
            )

        missing = self.root / "missing"
        with self.assertRaisesRegex(FolderPickerUnavailable, "unavailable"):
            choose_source_folder(
                self.root,
                platform="darwin",
                environment={},
                which=lambda name: (
                    "/usr/bin/osascript" if name == "osascript" else None
                ),
                runner=lambda command, **kwargs: subprocess.CompletedProcess(
                    command, 0, str(missing), ""
                ),
            )


if __name__ == "__main__":
    unittest.main()
