"""Inspect extraction output for private/local document samples.

Usage:
    python tests/manual/inspect_document.py tests/manual/files/sample.pdf
    python tests/manual/inspect_document.py tests/manual/files/sample.docx
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pdf_mcp import docx_extractor, extractor


def inspect_pdf(path: str) -> None:
    print(f"\n== {path} ==")
    print(f"pages: {extractor.page_count(path)}")
    result = extractor.extract_tables(path, merge_multipage=True)
    print_tables(result["tables"])


def inspect_docx(path: str) -> None:
    print(f"\n== {path} ==")
    text = docx_extractor.extract_docx_text(path)
    print(f"paragraphs: {text['n_paragraphs']}")
    result = docx_extractor.extract_docx_tables(path)
    print_tables(result["tables"])


def print_tables(tables: list[dict]) -> None:
    print(f"tables: {len(tables)}")
    for i, table in enumerate(tables):
        location = table.get("merged_from_pages", [table.get("page", table.get("index"))])
        print(f"\nTable {i} location={location} rows={table['n_rows']} clean={table['looks_clean']}")
        if table.get("warnings"):
            for warning in table["warnings"]:
                print(f"warning: {warning}")
        preview = table["rows"][:5]
        print(json.dumps(preview, indent=2))


def inspect(path: str) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        inspect_pdf(path)
    elif ext == ".docx":
        inspect_docx(path)
    else:
        raise ValueError(f"unsupported file type: {ext}")


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python tests/manual/inspect_document.py PATH [PATH ...]", file=sys.stderr)
        return 2
    for path in argv:
        inspect(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
