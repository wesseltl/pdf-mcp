"""Runtime policy and environment configuration owned by Core."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when runtime configuration is ambiguous or invalid."""


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"", "0", "false", "no", "off"}

DEFAULT_PARSER_TIMEOUT_SECONDS = 60.0
DEFAULT_PARSER_CPU_SECONDS = 45
DEFAULT_PARSER_MEMORY_BYTES = 1024 * 1024 * 1024
DEFAULT_PARSER_OUTPUT_BYTES = 128 * 1024 * 1024


def _aliased_value(
    values: Mapping[str, str],
    name: str,
    legacy_name: str,
) -> tuple[str | None, str]:
    """Read a renamed setting without allowing contradictory policy values."""
    current_present = name in values
    legacy_present = legacy_name in values
    if current_present and legacy_present and values[name] != values[legacy_name]:
        raise ConfigurationError(f"{name} conflicts with legacy {legacy_name}")
    if current_present:
        return values[name], name
    if legacy_present:
        return values[legacy_name], legacy_name
    return None, name


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
    value, name = _aliased_value(
        values,
        "LABOVERLAY_NO_EGRESS",
        "SMART_LAB_INDEX_NO_EGRESS",
    )
    return parse_boolean(
        value,
        name=name,
        default=False,
    )


def _positive_float(
    value: str | None,
    *,
    name: str,
    default: float,
) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ConfigurationError(f"{name} must be a positive number")
    return parsed


def _positive_int(
    value: str | None,
    *,
    name: str,
    default: int,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True)
class RuntimePolicy:
    """Security policy applied consistently when modules are registered and enabled."""

    no_egress: bool = False
    parser_isolation: bool = True
    parser_timeout_seconds: float = DEFAULT_PARSER_TIMEOUT_SECONDS
    parser_cpu_seconds: int = DEFAULT_PARSER_CPU_SECONDS
    parser_memory_bytes: int = DEFAULT_PARSER_MEMORY_BYTES
    parser_output_bytes: int = DEFAULT_PARSER_OUTPUT_BYTES
    production_mode: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.parser_timeout_seconds, bool)
            or not isinstance(self.parser_timeout_seconds, (int, float))
            or not math.isfinite(self.parser_timeout_seconds)
            or self.parser_timeout_seconds <= 0
        ):
            raise ConfigurationError("parser timeout must be positive")
        for name, value in (
            ("parser CPU limit", self.parser_cpu_seconds),
            ("parser memory limit", self.parser_memory_bytes),
            ("parser output limit", self.parser_output_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer")
        if self.production_mode and not self.no_egress:
            raise ConfigurationError("production mode requires no-egress mode")
        if self.production_mode and not self.parser_isolation:
            raise ConfigurationError("production mode requires isolated parsers")

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> RuntimePolicy:
        values = os.environ if environment is None else environment
        production_value, production_name = _aliased_value(
            values,
            "LABOVERLAY_PRODUCTION",
            "SMART_LAB_INDEX_PRODUCTION",
        )
        production_mode = parse_boolean(
            production_value,
            name=production_name,
            default=False,
        )
        isolation_value, isolation_name = _aliased_value(
            values,
            "LABOVERLAY_PARSER_ISOLATION",
            "SMART_LAB_INDEX_PARSER_ISOLATION",
        )
        timeout_value, timeout_name = _aliased_value(
            values,
            "LABOVERLAY_PARSER_TIMEOUT_SECONDS",
            "SMART_LAB_INDEX_PARSER_TIMEOUT_SECONDS",
        )
        cpu_value, cpu_name = _aliased_value(
            values,
            "LABOVERLAY_PARSER_CPU_SECONDS",
            "SMART_LAB_INDEX_PARSER_CPU_SECONDS",
        )
        memory_value, memory_name = _aliased_value(
            values,
            "LABOVERLAY_PARSER_MEMORY_MB",
            "SMART_LAB_INDEX_PARSER_MEMORY_MB",
        )
        output_value, output_name = _aliased_value(
            values,
            "LABOVERLAY_PARSER_OUTPUT_MB",
            "SMART_LAB_INDEX_PARSER_OUTPUT_MB",
        )
        return cls(
            no_egress=no_egress_enabled(values) or production_mode,
            parser_isolation=parse_boolean(
                isolation_value,
                name=isolation_name,
                default=True,
            ),
            parser_timeout_seconds=_positive_float(
                timeout_value,
                name=timeout_name,
                default=DEFAULT_PARSER_TIMEOUT_SECONDS,
            ),
            parser_cpu_seconds=_positive_int(
                cpu_value,
                name=cpu_name,
                default=DEFAULT_PARSER_CPU_SECONDS,
            ),
            parser_memory_bytes=(
                _positive_int(
                    memory_value,
                    name=memory_name,
                    default=DEFAULT_PARSER_MEMORY_BYTES // (1024 * 1024),
                )
                * 1024
                * 1024
            ),
            parser_output_bytes=(
                _positive_int(
                    output_value,
                    name=output_name,
                    default=DEFAULT_PARSER_OUTPUT_BYTES // (1024 * 1024),
                )
                * 1024
                * 1024
            ),
            production_mode=production_mode,
        )

    def to_dict(self) -> dict[str, bool | float | int]:
        return {
            "no_egress": self.no_egress,
            "parser_isolation": self.parser_isolation,
            "parser_timeout_seconds": self.parser_timeout_seconds,
            "parser_cpu_seconds": self.parser_cpu_seconds,
            "parser_memory_bytes": self.parser_memory_bytes,
            "parser_output_bytes": self.parser_output_bytes,
            "production_mode": self.production_mode,
        }
