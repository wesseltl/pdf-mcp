"""Cross-platform local folder selection for the desktop application."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

_INITIAL_FOLDER_ENV = "SMART_LAB_INDEX_INITIAL_FOLDER"
_TITLE = "Choose a laboratory folder"
_PASSTHROUGH_ENVIRONMENT = {
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "SystemRoot",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "WAYLAND_DISPLAY",
    "WINDIR",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
}


class FolderPickerUnavailable(RuntimeError):
    """Raised when the current desktop cannot provide a local folder dialog."""


def folder_picker_available(
    *,
    platform: str | None = None,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> bool:
    """Return whether a supported local dialog command is available."""
    target = platform or sys.platform
    current_environment = os.environ if environment is None else environment
    if target == "win32":
        return bool(which("powershell.exe") or which("pwsh.exe"))
    if target == "darwin":
        return bool(which("osascript"))
    if target.startswith("linux"):
        graphical = bool(
            current_environment.get("DISPLAY")
            or current_environment.get("WAYLAND_DISPLAY")
        )
        return graphical and any(
            which(command) for command in ("zenity", "kdialog", "yad")
        )
    return False


def choose_source_folder(
    initial_directory: str | Path | None = None,
    *,
    platform: str | None = None,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path | None:
    """Open a local folder dialog and return a validated path, or None on cancel."""
    target = platform or sys.platform
    initial = Path(initial_directory or Path.home()).expanduser().resolve()
    command, cancel_codes = _dialog_command(target, which, initial)
    current_environment = os.environ if environment is None else environment
    child_environment = {
        key: value
        for key, value in current_environment.items()
        if key in _PASSTHROUGH_ENVIRONMENT
    }
    child_environment[_INITIAL_FOLDER_ENV] = str(initial)
    try:
        completed = runner(
            command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            env=child_environment,
            errors="strict",
            text=True,
        )
    except OSError as exc:
        raise FolderPickerUnavailable(
            "the local folder dialog could not be opened"
        ) from exc

    if completed.returncode in cancel_codes:
        return None
    if completed.returncode != 0:
        raise FolderPickerUnavailable("the local folder dialog did not complete")

    selected = completed.stdout.strip()
    if not selected:
        return None
    try:
        resolved = Path(selected).expanduser().resolve(strict=True)
    except OSError as exc:
        raise FolderPickerUnavailable("the selected folder is unavailable") from exc
    if not resolved.is_dir():
        raise FolderPickerUnavailable("the selected path is not a folder")
    return resolved


def _dialog_command(
    target: str,
    which: Callable[[str], str | None],
    initial_directory: Path,
) -> tuple[Sequence[str], frozenset[int]]:
    if target == "win32":
        executable = which("powershell.exe") or which("pwsh.exe")
        if not executable:
            raise FolderPickerUnavailable("PowerShell is required for folder selection")
        script = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$dialog.Description = '{_TITLE}'; "
            "$initial = [Environment]::GetEnvironmentVariable("
            f"'{_INITIAL_FOLDER_ENV}'); "
            "if ($initial) { $dialog.SelectedPath = $initial }; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "[Console]::Out.Write($dialog.SelectedPath) }"
        )
        return (
            (executable, "-NoLogo", "-NoProfile", "-STA", "-Command", script),
            frozenset(),
        )

    if target == "darwin":
        executable = which("osascript")
        if not executable:
            raise FolderPickerUnavailable("the macOS folder dialog is unavailable")
        script = (
            "try\n"
            f'set startFolder to POSIX file (system attribute "{_INITIAL_FOLDER_ENV}")\n'
            f'return POSIX path of (choose folder with prompt "{_TITLE}" '
            "default location startFolder)\n"
            "on error number -128\n"
            'return ""\n'
            "end try"
        )
        return ((executable, "-e", script), frozenset())

    if target.startswith("linux"):
        zenity = which("zenity")
        if zenity:
            return (
                (
                    zenity,
                    "--file-selection",
                    "--directory",
                    f"--title={_TITLE}",
                    f"--filename={initial_directory}/",
                ),
                frozenset({1}),
            )
        kdialog = which("kdialog")
        if kdialog:
            return (
                (
                    kdialog,
                    "--getexistingdirectory",
                    str(initial_directory),
                    "--title",
                    _TITLE,
                ),
                frozenset({1}),
            )
        yad = which("yad")
        if yad:
            return (
                (
                    yad,
                    "--file-selection",
                    "--directory",
                    f"--title={_TITLE}",
                    f"--filename={initial_directory}/",
                ),
                frozenset({1}),
            )
        raise FolderPickerUnavailable(
            "install zenity, kdialog, or yad to enable Linux folder selection"
        )

    raise FolderPickerUnavailable("folder selection is not supported on this platform")
