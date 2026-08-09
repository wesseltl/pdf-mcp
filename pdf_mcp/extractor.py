"""extractor.py — pull text and tables out of PDFs reliably.

Agents can't read a PDF: they get a pasted blob where columns collapse and tables turn to mush. This
uses pdfplumber to extract the text and the actual table structure, so an agent gets clean rows
instead of guessing. Deterministic extraction; the model never invents a cell.
"""
from __future__ import annotations

import os

import pdfplumber

# Optional sandbox: if PDF_MCP_ALLOWED_DIR is set, only files inside it may be read. This lets you hand
# the server to an agent without it being able to read arbitrary files on the machine.
_ALLOWED_DIR = os.environ.get("PDF_MCP_ALLOWED_DIR")


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


def extract_text(path: str, page: int | None = None) -> dict:
    """Text from one page (1-based) or the whole document if page is None."""
    with pdfplumber.open(_check_path(path)) as pdf:
        if page is not None:
            pages = [pdf.pages[page - 1]]
        else:
            pages = pdf.pages
        parts = [{"page": p.page_number, "text": (p.extract_text() or "")} for p in pages]
    return {"pages": parts, "n_pages": len(parts)}


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


def extract_tables(path: str, page: int | None = None) -> dict:
    """Tables from one page (1-based) or the whole document.

    Each table is a list of rows (each row a list of cell strings), plus an honest assessment of how
    clean the extraction looks (ragged column counts and mostly-empty tables are flagged), so the
    caller can tell a reliable table from a shaky one instead of trusting tidy-looking output.
    """
    out = []
    with pdfplumber.open(_check_path(path)) as pdf:
        pages = [pdf.pages[page - 1]] if page is not None else pdf.pages
        for p in pages:
            for tbl in p.extract_tables():
                clean = [[("" if c is None else str(c).strip()) for c in row] for row in tbl]
                out.append({"page": p.page_number, "rows": clean, "n_rows": len(clean), **_assess(clean)})
    return {"tables": out, "n_tables": len(out)}


def table_to_csv(path: str, page: int | None = None, index: int = 0) -> str:
    """Return one extracted table (default the first) as CSV text.

    First row is treated as the header.
    """
    import csv
    import io
    tables = extract_tables(path, page)["tables"]
    if not tables:
        return ""
    rows = tables[index]["rows"]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()
