"""Runtime policy and environment configuration owned by Core."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when runtime configuration is ambiguous or invalid."""


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"", "0", "false", "no", "off"}


def parse_boolean(value: str | None, *, name: str, default: bool = False) -> bool:
    """Parse a boolean without silently accepting misspelled security settings."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ConfigurationError(
        f"{name} must be one of: 1, 0, true, false, yes, no, on, or off"
    )


def no_egress_enabled(environment: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environment is None else environment
    return parse_boolean(
        values.get("SMART_LAB_INDEX_NO_EGRESS"),
        name="SMART_LAB_INDEX_NO_EGRESS",
        default=False,
    )


@dataclass(frozen=True)
class RuntimePolicy:
    """Security policy applied consistently when modules are registered and enabled."""

    no_egress: bool = False

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> RuntimePolicy:
        return cls(no_egress=no_egress_enabled(environment))
