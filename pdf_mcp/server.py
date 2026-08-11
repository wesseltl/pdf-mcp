"""Expose document extraction and profile validation as local MCP tools.

Agents often get a flattened blob where columns collapse and tables turn to mush. This gives an
agent deterministic parser output, source coordinates, versioned checks, and explicit review routing.
It does not treat tidy parser output as proof of accuracy.

Run:  python -m pdf_mcp.server        (needs:  pip install "pdf-agent-mcp[mcp]")
"""
from __future__ import annotations

from pdf_mcp import docx_extractor, exporter, extractor, profiles, verified

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


@mcp.tool()
def list_extraction_profiles() -> list[dict]:
    """List the built-in, versioned contracts available for profile-driven extraction."""
    return profiles.list_builtin_profiles()


@mcp.tool()
def extract_with_profile(path: str, profile: str = "lab-coa-v1") -> dict:
    """Extract document rows under a versioned contract with source evidence and review routing.

    An `accepted` decision means every deterministic profile check passed. `needs_review` and
    `rejected` results must not be used as trusted business data without human review.

    Args:
        path: path to a born-digital .pdf or .docx file.
        profile: built-in profile ID or path to a custom profile JSON file.
    """
    return verified.extract_with_profile(path, profile)


@mcp.tool()
def export_with_profile(input_path: str, profile: str, output_path: str) -> dict:
    """Export profile-checked rows and their evidence to .xlsx, .csv, or .json.

    XLSX output includes Review, Data, and cell-level Evidence worksheets. The returned decision must
    be `accepted` before an agent treats the rows as having passed the profile.

    Args:
        input_path: path to a born-digital .pdf or .docx file.
        profile: built-in profile ID or path to a custom profile JSON file.
        output_path: path to write. Supported extensions: .xlsx, .csv, .json.
    """
    return verified.export_with_profile(input_path, profile, output_path)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
