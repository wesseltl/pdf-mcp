"""Shared mechanics for parser modules; none of these belong to Core."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

from smart_lab_index.core.domain import DocumentSource, Provenance


class DocumentParseError(ValueError):
    pass


def source_extension(source: DocumentSource) -> str:
    return PurePosixPath(source.path).suffix.lower()


def provenance(
    source: DocumentSource,
    locator: dict[str, Any],
    excerpt: str | None = None,
) -> Provenance:
    return Provenance(
        source_external_id=source.external_id,
        locator=locator,
        excerpt=excerpt,
    )


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return str(value.isoformat())
        except (TypeError, ValueError):
            pass
    return str(value).strip()


def assess_table(rows: Iterable[Iterable[str]]) -> dict[str, Any]:
    materialized = [list(row) for row in rows]
    if not materialized:
        return {"looks_clean": False, "warnings": ["empty table"]}
    widths = {len(row) for row in materialized}
    total = sum(len(row) for row in materialized)
    empty = sum(1 for row in materialized for cell in row if cell == "")
    empty_ratio = round(empty / total, 3) if total else 1.0
    warnings = []
    ragged = len(widths) > 1
    if ragged:
        warnings.append(
            f"ragged: rows have {sorted(widths)} columns (grid may be misdetected)"
        )
    if empty_ratio > 0.4:
        warnings.append(f"{int(empty_ratio * 100)}% of cells are empty (extraction may be off)")
    return {
        "looks_clean": not warnings,
        "column_count": None if ragged else next(iter(widths)),
        "empty_ratio": empty_ratio,
        "warnings": warnings,
    }


def json_safe_metadata(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_metadata(item) for item in value]
    return str(value)


def bbox(value: Any) -> list[float] | None:
    if value is None:
        return None
    return [round(float(coordinate), 3) for coordinate in value]
