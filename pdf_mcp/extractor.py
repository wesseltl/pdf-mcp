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


def extract_tables(path: str, page: int | None = None) -> dict:
    """Tables from one page (1-based) or the whole document.

    Each table is a list of rows (each row a list of cell strings), exactly as laid out in the PDF.
    Empty cells come back as "".
    """
    out = []
    with pdfplumber.open(_check_path(path)) as pdf:
        pages = [pdf.pages[page - 1]] if page is not None else pdf.pages
        for p in pages:
            for tbl in p.extract_tables():
                clean = [[("" if c is None else str(c).strip()) for c in row] for row in tbl]
                out.append({"page": p.page_number, "rows": clean, "n_rows": len(clean)})
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
