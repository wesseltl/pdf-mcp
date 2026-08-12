"""Default LabOverlay state paths with transparent legacy compatibility."""

from __future__ import annotations

from pathlib import Path

STATE_DIRECTORY_NAME = ".laboverlay"
LEGACY_STATE_DIRECTORY_NAME = ".smart-lab-index"


def default_state_directory(home: str | Path | None = None) -> Path:
    """Prefer LabOverlay state, but continue an existing legacy installation."""
    root = Path.home() if home is None else Path(home).expanduser()
    current = root / STATE_DIRECTORY_NAME
    legacy = root / LEGACY_STATE_DIRECTORY_NAME
    if not current.exists() and legacy.exists():
        return legacy
    return current


def default_database_path(home: str | Path | None = None) -> Path:
    return default_state_directory(home) / "index.db"


def default_operator_token_path(home: str | Path | None = None) -> Path:
    return default_state_directory(home) / "operator.token"


def default_desktop_settings_file(home: str | Path | None = None) -> Path:
    return default_state_directory(home) / "desktop-settings.json"


def default_workspace_directory(home: str | Path | None = None) -> Path:
    return default_state_directory(home) / "workspaces"
