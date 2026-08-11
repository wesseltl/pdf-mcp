"""Versioned extraction profiles and their validation rules."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path

from pdf_mcp.extractor import _check_path


PROFILE_SCHEMA_VERSION = "1.0"
_ALLOWED_TYPES = {"string", "integer", "decimal", "boolean", "date"}
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_COLUMN_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ProfileError(ValueError):
    """Raised when an extraction profile is missing or unsafe to execute."""


def _reject_unknown(value: dict, allowed: set[str], field: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise ProfileError(f"{field} contains unsupported keys: {', '.join(sorted(unknown))}")


def normalize_header(value: object) -> str:
    """Normalize a table header for deterministic alias matching."""
    text = "" if value is None else str(value)
    return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())


def _json_object(text: str, source: str) -> dict:
    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProfileError(f"duplicate JSON key {key!r} in {source}")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"invalid JSON in {source}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProfileError(f"profile in {source} must be a JSON object")
    return value


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field} must be a non-empty string")
    return value.strip()


def validate_profile(profile: dict) -> dict:
    """Validate and return a defensive copy of a profile."""
    if not isinstance(profile, dict):
        raise ProfileError("profile must be an object")
    checked = copy.deepcopy(profile)
    _reject_unknown(
        checked,
        {"$schema", "profile_schema_version", "id", "version", "description", "table"},
        "profile",
    )
    if checked.get("profile_schema_version") != PROFILE_SCHEMA_VERSION:
        raise ProfileError(
            f"profile_schema_version must be {PROFILE_SCHEMA_VERSION!r}"
        )

    profile_id = _require_string(checked.get("id"), "id")
    if not _ID_PATTERN.fullmatch(profile_id):
        raise ProfileError("id must contain 2-64 lowercase letters, numbers, '.', '_' or '-'")
    _require_string(checked.get("version"), "version")
    _require_string(checked.get("description"), "description")

    table = checked.get("table")
    if not isinstance(table, dict):
        raise ProfileError("table must be an object")
    _reject_unknown(
        table,
        {
            "columns", "header_search_rows", "minimum_header_match", "allow_extra_columns",
            "min_records", "unique_by",
        },
        "table",
    )
    columns = table.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ProfileError("table.columns must be a non-empty array")

    names = set()
    aliases = {}
    for index, column in enumerate(columns):
        prefix = f"table.columns[{index}]"
        if not isinstance(column, dict):
            raise ProfileError(f"{prefix} must be an object")
        _reject_unknown(
            column,
            {
                "name", "aliases", "type", "required", "allow_blank", "pattern", "enum",
                "minimum", "maximum", "formats",
            },
            prefix,
        )
        name = _require_string(column.get("name"), f"{prefix}.name")
        if not _COLUMN_PATTERN.fullmatch(name):
            raise ProfileError(
                f"{prefix}.name must use lowercase letters, numbers, and underscores"
            )
        if name in names:
            raise ProfileError(f"duplicate column name {name!r}")
        names.add(name)
        data_type = column.get("type", "string")
        if data_type not in _ALLOWED_TYPES:
            raise ProfileError(
                f"{prefix}.type must be one of {sorted(_ALLOWED_TYPES)}"
            )
        column["type"] = data_type
        for flag in ("required", "allow_blank"):
            if flag in column and not isinstance(column[flag], bool):
                raise ProfileError(f"{prefix}.{flag} must be a boolean")
        raw_aliases = column.get("aliases", [])
        if not isinstance(raw_aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in raw_aliases
        ):
            raise ProfileError(f"{prefix}.aliases must contain non-empty strings")
        column["aliases"] = list(dict.fromkeys([name, *raw_aliases]))
        for alias in column["aliases"]:
            normalized = normalize_header(alias)
            if not normalized:
                raise ProfileError(f"{prefix}.aliases may not normalize to an empty header")
            owner = aliases.get(normalized)
            if owner is not None and owner != name:
                raise ProfileError(
                    f"header alias {alias!r} is shared by columns {owner!r} and {name!r}"
                )
            aliases[normalized] = name
        if "pattern" in column:
            pattern = _require_string(column["pattern"], f"{prefix}.pattern")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ProfileError(f"invalid regex in {prefix}.pattern: {exc}") from exc
        if "enum" in column and (
            not isinstance(column["enum"], list) or not column["enum"]
        ):
            raise ProfileError(f"{prefix}.enum must be a non-empty array")
        if data_type == "date" and "formats" in column and (
            not isinstance(column["formats"], list)
            or not column["formats"]
            or not all(isinstance(fmt, str) and fmt for fmt in column["formats"])
        ):
            raise ProfileError(f"{prefix}.formats must be a non-empty array of strings")
        for boundary in ("minimum", "maximum"):
            if boundary in column:
                if data_type not in {"integer", "decimal"}:
                    raise ProfileError(f"{prefix}.{boundary} requires a numeric column type")
                try:
                    numeric_boundary = Decimal(str(column[boundary]))
                except InvalidOperation as exc:
                    raise ProfileError(f"{prefix}.{boundary} must be numeric") from exc
                if not numeric_boundary.is_finite():
                    raise ProfileError(f"{prefix}.{boundary} must be finite")
        if "minimum" in column and "maximum" in column \
                and Decimal(str(column["minimum"])) > Decimal(str(column["maximum"])):
            raise ProfileError(f"{prefix}.minimum may not exceed maximum")

    header_search_rows = table.get("header_search_rows", 3)
    if isinstance(header_search_rows, bool) or not isinstance(header_search_rows, int) \
            or not 1 <= header_search_rows <= 20:
        raise ProfileError("table.header_search_rows must be an integer between 1 and 20")
    table["header_search_rows"] = header_search_rows

    minimum_header_match = table.get("minimum_header_match", 1.0)
    if isinstance(minimum_header_match, bool) or not isinstance(
        minimum_header_match, (int, float)
    ) or not 0 < minimum_header_match <= 1:
        raise ProfileError("table.minimum_header_match must be greater than 0 and at most 1")
    table["minimum_header_match"] = float(minimum_header_match)

    min_records = table.get("min_records", 1)
    if isinstance(min_records, bool) or not isinstance(min_records, int) or min_records < 1:
        raise ProfileError("table.min_records must be a positive integer")
    table["min_records"] = min_records

    if "allow_extra_columns" in table and not isinstance(table["allow_extra_columns"], bool):
        raise ProfileError("table.allow_extra_columns must be a boolean")
    table.setdefault("allow_extra_columns", True)
    unique_by = table.get("unique_by", [])
    if not isinstance(unique_by, list) or not all(name in names for name in unique_by):
        raise ProfileError("table.unique_by must contain declared column names")
    if len(unique_by) != len(set(unique_by)):
        raise ProfileError("table.unique_by may not contain duplicates")
    table["unique_by"] = unique_by
    return checked


def _builtin_resource(name: str):
    if not _ID_PATTERN.fullmatch(name):
        return None
    resource = resources.files("pdf_mcp.profile_templates").joinpath(f"{name}.json")
    return resource if resource.is_file() else None


def load_profile(reference: str | dict) -> dict:
    """Load a built-in profile ID, local JSON profile path, or profile object."""
    if isinstance(reference, dict):
        return validate_profile(reference)
    if not isinstance(reference, str) or not reference.strip():
        raise ProfileError("profile must be a built-in profile ID, JSON path, or object")
    reference = reference.strip()
    resource = _builtin_resource(reference)
    if resource is not None:
        return validate_profile(_json_object(resource.read_text(encoding="utf-8"), reference))

    resolved = _check_path(reference)
    path = Path(resolved)
    if path.suffix.lower() != ".json":
        raise ProfileError("custom profiles must be JSON files")
    if not path.is_file():
        raise ProfileError(f"profile file not found: {reference}")
    if path.stat().st_size > 1_000_000:
        raise ProfileError("profile file exceeds the 1 MB limit")
    return validate_profile(_json_object(path.read_text(encoding="utf-8"), reference))


def profile_sha256(profile: dict) -> str:
    canonical = json.dumps(
        validate_profile(profile), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def list_builtin_profiles() -> list[dict]:
    """Return stable metadata for profiles shipped with the package."""
    result = []
    root = resources.files("pdf_mcp.profile_templates")
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        if resource.name.endswith(".json"):
            profile = validate_profile(
                _json_object(resource.read_text(encoding="utf-8"), resource.name)
            )
            result.append({
                "id": profile["id"],
                "version": profile["version"],
                "description": profile["description"],
                "columns": [column["name"] for column in profile["table"]["columns"]],
                "sha256": profile_sha256(profile),
            })
    return result
