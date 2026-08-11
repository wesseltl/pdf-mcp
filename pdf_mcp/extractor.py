"""Pull text, table rows, and source coordinates out of born-digital PDFs.

Agents can't read a PDF: they get a pasted blob where columns collapse and tables turn to mush. This
uses pdfplumber to extract parser-detected rows rather than asking a model to generate cell values.
Raw extraction is not an accuracy guarantee; profile checks provide the stricter workflow contract.
"""
from __future__ import annotations

import os

import pdfplumber

# Optional sandbox: if PDF_MCP_ALLOWED_DIR is set, only files inside it may be read. This lets you hand
# the server to an agent without it being able to read arbitrary files on the machine.
_ALLOWED_DIR = os.environ.get("PDF_MCP_ALLOWED_DIR")

_NO_TEXT_WARNING = (
    "no text detected; scanned or image-only PDFs require OCR, which is not supported"
)
_NO_TABLES_WARNING = (
    "no tables detected; scanned or image-only PDFs require OCR, which is not supported"
)


def _check_path(path: str) -> str:
    """Resolve `path` and, if a sandbox dir is configured, reject anything outside it.

    Uses realpath so symlinks and `..` traversal can't escape the allowed directory.
    """
    resolved = os.path.realpath(path)
    if _ALLOWED_DIR:
        base = os.path.realpath(_ALLOWED_DIR)
        if os.path.commonpath([resolved, base]) != base:
            raise PermissionError(
                f"access denied: {path!r} is outside the allowed directory ({_ALLOWED_DIR})")
    return resolved


def page_count(path: str) -> int:
    """How many pages the PDF has."""
    with pdfplumber.open(_check_path(path)) as pdf:
        return len(pdf.pages)


def _select_pages(pdf, page: int | None):
    """Return all pages or one validated 1-based page."""
    if page is None:
        return pdf.pages
    if isinstance(page, bool) or not isinstance(page, int):
        raise ValueError("page must be an integer using 1-based numbering")
    if page < 1 or page > len(pdf.pages):
        raise ValueError(f"page must be between 1 and {len(pdf.pages)} (received {page})")
    return [pdf.pages[page - 1]]


def extract_text(path: str, page: int | None = None) -> dict:
    """Text from one page (1-based) or the whole document if page is None."""
    with pdfplumber.open(_check_path(path)) as pdf:
        pages = _select_pages(pdf, page)
        parts = [{"page": p.page_number, "text": (p.extract_text() or "")} for p in pages]
    warnings = [] if any(part["text"].strip() for part in parts) else [_NO_TEXT_WARNING]
    return {"pages": parts, "n_pages": len(parts), "warnings": warnings}


def _assess(rows: list[list]) -> dict:
    """Judge how trustworthy an extracted table looks, so a clean parse is distinguishable from a
    confident guess.

    Two honest signals PDF table extraction gets wrong:
      - ragged: rows with differing column counts usually mean the grid was detected wrong.
      - empty_ratio: a table that's mostly blank cells is often a bad extraction.
    """
    if not rows:
        return {"looks_clean": False, "warnings": ["empty table"]}
    widths = {len(r) for r in rows}
    ragged = len(widths) > 1
    total = sum(len(r) for r in rows)
    empty = sum(1 for r in rows for c in r if c == "")
    empty_ratio = round(empty / total, 3) if total else 1.0
    warnings = []
    if ragged:
        warnings.append(f"ragged: rows have {sorted(widths)} columns (grid may be misdetected)")
    if empty_ratio > 0.4:
        warnings.append(f"{int(empty_ratio * 100)}% of cells are empty (extraction may be off)")
    return {"looks_clean": not warnings, "column_count": None if ragged else widths.pop(),
            "empty_ratio": empty_ratio, "warnings": warnings}


def _bbox(value) -> list[float] | None:
    """Return a stable, JSON-safe PDF bounding box."""
    if value is None:
        return None
    return [round(float(coordinate), 3) for coordinate in value]


def _table_result(table, page_number: int, table_index: int) -> dict:
    """Extract one table together with cell-level source coordinates."""
    rows = [
        [("" if cell is None else str(cell).strip()) for cell in row]
        for row in table.extract()
    ]
    cell_provenance = []
    for row_index, row in enumerate(rows):
        source_cells = table.rows[row_index].cells if row_index < len(table.rows) else []
        cell_provenance.append([
            {
                "page": page_number,
                "table_index": table_index,
                "row": row_index,
                "column": column_index,
                "bbox": _bbox(source_cells[column_index])
                if column_index < len(source_cells) else None,
            }
            for column_index in range(len(row))
        ])
    return {
        "page": page_number,
        "index": table_index,
        "bbox": _bbox(table.bbox),
        "rows": rows,
        "cell_provenance": cell_provenance,
        "n_rows": len(rows),
        **_assess(rows),
    }


def _stitch_multipage(tables: list[dict]) -> list[dict]:
    """Join tables that continue across page breaks.

    A table on the next page is treated as a continuation of the previous one when they have the same
    (non-ragged) column count. If the continuation repeats the header row, it's dropped. This is a
    heuristic, not a fact, so a merged table reports `merged_from_pages` and a warning, and the caller
    can turn merging off if it guesses wrong.
    """
    merged: list[dict] = []
    for t in tables:
        prev = merged[-1] if merged else None
        can_join = (
            prev is not None
            and prev.get("column_count") is not None
            and prev["column_count"] == t.get("column_count")
            and t["page"] == prev["merged_from_pages"][-1] + 1
        )
        if not can_join:
            merged.append({**t, "merged_from_pages": [t["page"]]})
            continue
        rows = t["rows"]
        cell_provenance = t.get("cell_provenance", [])
        # drop a repeated header on the continuation page
        if rows and rows[0] == prev["rows"][0]:
            rows = rows[1:]
            cell_provenance = cell_provenance[1:]
        new_rows = prev["rows"] + rows
        new_provenance = prev.get("cell_provenance", []) + cell_provenance
        bboxes_by_page = prev.get(
            "bboxes_by_page", [{"page": prev["page"], "bbox": prev.get("bbox")}]
        ) + [{"page": t["page"], "bbox": t.get("bbox")}]
        prev.update(rows=new_rows, n_rows=len(new_rows),
                    cell_provenance=new_provenance,
                    bbox=None, bboxes_by_page=bboxes_by_page,
                    merged_from_pages=prev["merged_from_pages"] + [t["page"]], **_assess(new_rows))
        prev["warnings"] = list(prev.get("warnings", [])) + [
            f"merged across pages {prev['merged_from_pages']} (continuation guessed from matching columns)"]
        prev["looks_clean"] = False   # a stitched table is a heuristic; flag it for review
    return merged


def extract_tables(path: str, page: int | None = None, merge_multipage: bool = False) -> dict:
    """Tables from one page (1-based) or the whole document.

    Each table is a list of rows (each row a list of cell strings), plus an honest assessment of how
    clean the extraction looks (ragged column counts and mostly-empty tables are flagged), so the
    caller can tell a reliable table from a shaky one instead of trusting tidy-looking output.

    Set `merge_multipage=True` to join tables that continue across page breaks (same column count).
    Merged tables are flagged with `merged_from_pages` and a warning, since continuation is a guess.
    """
    out = []
    with pdfplumber.open(_check_path(path)) as pdf:
        pages = _select_pages(pdf, page)
        for p in pages:
            for table_index, table in enumerate(p.find_tables()):
                out.append(_table_result(table, p.page_number, table_index))
    if merge_multipage:
        out = _stitch_multipage(out)
    warnings = [] if out else [_NO_TABLES_WARNING]
    return {"tables": out, "n_tables": len(out), "warnings": warnings}


def table_to_csv(path: str, page: int | None = None, index: int = 0) -> str:
    """Return one extracted table (default the first) as CSV text.

    First row is treated as the header.
    """
    import csv
    import io
    tables = extract_tables(path, page)["tables"]
    if not tables:
        return ""
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(tables):
        raise ValueError(f"table index must be between 0 and {len(tables) - 1} (received {index})")
    rows = tables[index]["rows"]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()
