"""Inspect extraction output for private/local PDF samples.

Usage:
    python tests/manual/inspect_pdf.py tests/manual/files/sample.pdf
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pdf_mcp import extractor


def inspect(path: str) -> None:
    print(f"\n== {path} ==")
    print(f"pages: {extractor.page_count(path)}")
    result = extractor.extract_tables(path, merge_multipage=True)
    print(f"tables: {result['n_tables']}")
    for i, table in enumerate(result["tables"]):
        pages = table.get("merged_from_pages", [table["page"]])
        print(f"\nTable {i} pages={pages} rows={table['n_rows']} clean={table['looks_clean']}")
        if table.get("warnings"):
            for warning in table["warnings"]:
                print(f"warning: {warning}")
        preview = table["rows"][:5]
        print(json.dumps(preview, indent=2))


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python tests/manual/inspect_pdf.py PATH [PATH ...]", file=sys.stderr)
        return 2
    for path in argv:
        inspect(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
