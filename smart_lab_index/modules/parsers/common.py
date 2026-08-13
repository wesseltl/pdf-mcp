"""Shared mechanics for parser modules; none of these belong to Core."""

from __future__ import annotations

import zipfile
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from smart_lab_index.core.domain import DocumentSource, Provenance


class DocumentParseError(ValueError):
    pass


MAX_TEXT_CHARS = 10_000_000
MAX_TEXT_BLOCKS = 100_000
MAX_TABLE_ROWS = 100_000
MAX_TABLE_CELLS = 1_000_000
MAX_PDF_PAGES = 500
MAX_OFFICE_ENTRIES = 20_000
MAX_OFFICE_EXPANDED_BYTES = 512 * 1024 * 1024


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


def read_utf8_text(content: BinaryIO, label: str) -> str:
    content.seek(0)
    data = content.read(MAX_TEXT_CHARS * 4 + 1)
    if len(data) > MAX_TEXT_CHARS * 4:
        raise DocumentParseError(f"{label} exceeds the parser text limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentParseError(f"{label} is not valid UTF-8") from exc
    require_text_budget(len(text), label)
    return text


def require_text_budget(characters: int, label: str) -> None:
    if characters > MAX_TEXT_CHARS:
        raise DocumentParseError(f"{label} exceeds the parser text limit")


def require_table_budget(rows: int, cells: int, label: str) -> None:
    if rows > MAX_TABLE_ROWS:
        raise DocumentParseError(f"{label} exceeds the parser row limit")
    if cells > MAX_TABLE_CELLS:
        raise DocumentParseError(f"{label} exceeds the parser cell limit")


def preflight_office_archive(content: BinaryIO, label: str) -> None:
    """Reject encrypted or excessively expanded Office archives before parsing."""
    try:
        content.seek(0)
        with zipfile.ZipFile(content) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_OFFICE_ENTRIES:
                raise DocumentParseError(f"{label} exceeds the archive entry limit")
            expanded = 0
            for entry in entries:
                if entry.flag_bits & 0x1:
                    raise DocumentParseError(f"{label} contains encrypted archive entries")
                expanded += entry.file_size
                if expanded > MAX_OFFICE_EXPANDED_BYTES:
                    raise DocumentParseError(f"{label} exceeds the expanded archive limit")
    except zipfile.BadZipFile as exc:
        raise DocumentParseError(f"{label} is not a valid Office archive") from exc
    finally:
        content.seek(0)
