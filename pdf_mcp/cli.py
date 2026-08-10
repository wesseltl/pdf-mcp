"""Command-line tools for pdf-agent-mcp."""
from __future__ import annotations

import argparse

from pdf_mcp import exporter


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="export-document-tables",
        description="Export tables from a PDF or Word document to .xlsx, .csv, or .json.",
    )
    parser.add_argument("input_path", help="Path to a .pdf or .docx file.")
    parser.add_argument("output_path", help="Path to write: .xlsx, .csv, or .json.")
    parser.add_argument(
        "--no-merge-multipage",
        action="store_true",
        help="Do not heuristically merge same-width PDF tables across adjacent pages.",
    )
    args = parser.parse_args()
    result = exporter.export_document_tables(
        args.input_path,
        args.output_path,
        merge_multipage=not args.no_merge_multipage,
    )
    print(
        f"Wrote {result['n_tables']} table(s) to {result['output']} "
        f"({result['tables_needing_review']} need review)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
