"""Private, non-secret preferences for the self-service desktop experience."""

from __future__ import annotations

import json
import math
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smart_lab_index.core.paths import default_desktop_settings_file

SETTINGS_SCHEMA_VERSION = 1
DEFAULT_DESKTOP_INDEX_INTERVAL_MINUTES = 15.0
MAX_SETTINGS_BYTES = 64 * 1024


class DesktopSettingsError(ValueError):
    """Raised when remembered desktop settings cannot be trusted or parsed."""


@dataclass(frozen=True)
class DesktopSettings:
    """The last approved desktop workspace; credentials never belong here."""

    root: Path
    database: Path
    index_interval_minutes: float = DEFAULT_DESKTOP_INDEX_INTERVAL_MINUTES
    saved_at: str = ""

    def __post_init__(self) -> None:
        if (
            isinstance(self.index_interval_minutes, bool)
            or not isinstance(self.index_interval_minutes, (int, float))
            or not math.isfinite(self.index_interval_minutes)
            or self.index_interval_minutes <= 0
        ):
            raise DesktopSettingsError("desktop scan interval must be positive")
        if not self.root.is_absolute() or not self.database.is_absolute():
            raise DesktopSettingsError("desktop workspace paths must be absolute")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "workspace": {
                "root": str(self.root),
                "database": str(self.database),
                "index_interval_minutes": self.index_interval_minutes,
            },
            "saved_at": self.saved_at or datetime.now(timezone.utc).isoformat(),
        }


def default_desktop_settings_path() -> Path:
    return default_desktop_settings_file()


def load_desktop_settings(path: str | Path | None = None) -> DesktopSettings | None:
    """Load a private regular settings file without following a final symlink."""
    target = _absolute(path or default_desktop_settings_path())
    if not os.path.lexists(target):
        return None
    metadata = target.lstat()
    _validate_existing_file(metadata)
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise DesktopSettingsError("desktop settings changed while being opened")
        content = os.read(descriptor, MAX_SETTINGS_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(content) > MAX_SETTINGS_BYTES:
        raise DesktopSettingsError("desktop settings file is too large")
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DesktopSettingsError("desktop settings contain invalid JSON") from exc
    return _settings_from_payload(payload)


def save_desktop_settings(
    settings: DesktopSettings,
    path: str | Path | None = None,
) -> Path:
    """Atomically persist owner-only preferences without storing credentials."""
    target = _absolute(path or default_desktop_settings_path())
    parent_existed = target.parent.exists()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix" and not parent_existed:
        os.chmod(target.parent, 0o700)
    if os.path.lexists(target):
        _validate_existing_file(target.lstat())

    content = (
        json.dumps(
            settings.to_dict(),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            else:
                os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def forget_desktop_settings(path: str | Path | None = None) -> bool:
    target = _absolute(path or default_desktop_settings_path())
    if not os.path.lexists(target):
        return False
    _validate_existing_file(target.lstat())
    target.unlink()
    _fsync_directory(target.parent)
    return True


def _settings_from_payload(payload: object) -> DesktopSettings:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise DesktopSettingsError("desktop settings use an unsupported schema")
    workspace = payload.get("workspace")
    if not isinstance(workspace, dict):
        raise DesktopSettingsError("desktop settings do not contain a workspace")
    allowed = {"root", "database", "index_interval_minutes"}
    if set(workspace) - allowed:
        raise DesktopSettingsError("desktop settings contain unknown workspace fields")
    root = workspace.get("root")
    database = workspace.get("database")
    interval = workspace.get(
        "index_interval_minutes",
        DEFAULT_DESKTOP_INDEX_INTERVAL_MINUTES,
    )
    if (
        not isinstance(root, str)
        or not root
        or not isinstance(database, str)
        or not database
    ):
        raise DesktopSettingsError("desktop settings contain invalid workspace paths")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)):
        raise DesktopSettingsError("desktop scan interval must be a number")
    return DesktopSettings(
        root=Path(root),
        database=Path(database),
        index_interval_minutes=float(interval),
        saved_at=str(payload.get("saved_at") or ""),
    )


def _validate_existing_file(metadata: os.stat_result) -> None:
    if stat.S_ISLNK(metadata.st_mode):
        raise DesktopSettingsError("desktop settings path must not be a symbolic link")
    if not stat.S_ISREG(metadata.st_mode):
        raise DesktopSettingsError("desktop settings must be a regular file")
    if metadata.st_nlink != 1:
        raise DesktopSettingsError("desktop settings must not have hard links")
    if os.name == "posix":
        if metadata.st_mode & 0o077:
            raise DesktopSettingsError(
                "desktop settings permissions must be 0600 or stricter"
            )
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise DesktopSettingsError(
                "desktop settings must be owned by the current account"
            )


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
