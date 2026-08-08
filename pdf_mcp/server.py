"""server.py — let an AI agent extract text and tables from PDFs as an MCP tool.

Agents can't read a PDF: they get a flattened blob where columns collapse and tables turn to mush.
This gives an agent tools to pull the text and the actual table structure out, so it works with clean
rows instead of guessing. Deterministic extraction; the model never invents a cell.

Run:  python -m pdf_mcp.server        (needs:  pip install "pdf-agent-mcp[mcp]")
"""
from __future__ import annotations

from pdf_mcp import extractor

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "The MCP server needs the 'mcp' package. Install it with:\n"
        '    pip install "pdf-agent-mcp[mcp]"'
    ) from exc

mcp = FastMCP("pdf-extractor")


@mcp.tool()
def page_count(path: str) -> int:
    """How many pages a PDF has.

    Args:
        path: path to the .pdf file.
    """
    return extractor.page_count(path)


@mcp.tool()
def extract_text(path: str, page: int | None = None) -> dict:
    """Extract text from a PDF, per page.

    Args:
        path: path to the .pdf file.
        page: 1-based page number, or omit for the whole document.
    """
    return extractor.extract_text(path, page)


@mcp.tool()
def extract_tables(path: str, page: int | None = None) -> dict:
    """Extract tables from a PDF as rows of cells (invoices, reports, statements).

    Args:
        path: path to the .pdf file.
        page: 1-based page number, or omit for the whole document.
    """
    return extractor.extract_tables(path, page)


@mcp.tool()
def table_to_csv(path: str, page: int | None = None, index: int = 0) -> str:
    """Extract one table from a PDF and return it as clean CSV text.

    Args:
        path: path to the .pdf file.
        page: 1-based page number, or omit to search the whole document.
        index: which table to return if there are several (default the first).
    """
    return extractor.table_to_csv(path, page, index)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
