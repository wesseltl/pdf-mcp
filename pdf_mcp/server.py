"""server.py — let an AI agent extract text and tables from documents as an MCP tool.

Agents often get a flattened blob where columns collapse and tables turn to mush. This gives an
agent tools to pull the text and the actual table structure out of PDFs and Word documents, so it
works with clean rows instead of guessing. Deterministic extraction; the model never invents a cell.

Run:  python -m pdf_mcp.server        (needs:  pip install "pdf-agent-mcp[mcp]")
"""
from __future__ import annotations

from pdf_mcp import docx_extractor, exporter, extractor

try:
    from fastmcp import FastMCP            # standalone FastMCP (mcp SDK 2.x+)
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP   # bundled in mcp SDK 1.x
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The MCP server needs FastMCP. Install it with:\n"
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
def extract_tables(path: str, page: int | None = None, merge_multipage: bool = False) -> dict:
    """Extract tables from a PDF as rows of cells (invoices, reports, statements).

    Args:
        path: path to the .pdf file.
        page: 1-based page number, or omit for the whole document.
        merge_multipage: join tables that continue across page breaks (same column count). Merged
            tables are flagged with merged_from_pages and a warning, since continuation is a guess.
    """
    return extractor.extract_tables(path, page, merge_multipage)


@mcp.tool()
def table_to_csv(path: str, page: int | None = None, index: int = 0) -> str:
    """Extract one table from a PDF and return it as clean CSV text.

    Args:
        path: path to the .pdf file.
        page: 1-based page number, or omit to search the whole document.
        index: which table to return if there are several (default the first).
    """
    return extractor.table_to_csv(path, page, index)


@mcp.tool()
def extract_docx_text(path: str) -> dict:
    """Extract text from a Word .docx file.

    Args:
        path: path to the .docx file.
    """
    return docx_extractor.extract_docx_text(path)


@mcp.tool()
def extract_docx_tables(path: str) -> dict:
    """Extract tables from a Word .docx file as rows of cells.

    Args:
        path: path to the .docx file.
    """
    return docx_extractor.extract_docx_tables(path)


@mcp.tool()
def docx_table_to_csv(path: str, index: int = 0) -> str:
    """Extract one Word table and return it as clean CSV text.

    Args:
        path: path to the .docx file.
        index: which table to return if there are several (default the first).
    """
    return docx_extractor.docx_table_to_csv(path, index)


@mcp.tool()
def export_document_tables(input_path: str, output_path: str, merge_multipage: bool = True) -> dict:
    """Export tables from a PDF or Word document to .xlsx, .csv, or .json.

    Args:
        input_path: path to the .pdf or .docx file.
        output_path: path to write. Supported extensions: .xlsx, .csv, .json.
        merge_multipage: join PDF tables that continue across page breaks. Merged tables are flagged
            with warnings because continuation is a guess.
    """
    return exporter.export_document_tables(input_path, output_path, merge_multipage)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
