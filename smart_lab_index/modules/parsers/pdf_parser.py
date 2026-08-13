"""Born-digital PDF parser module."""

from __future__ import annotations

from typing import BinaryIO

import pdfplumber

from smart_lab_index.core.domain import (
    DocumentContent,
    DocumentSource,
    TableContent,
    TextBlock,
)
from smart_lab_index.core.modules import (
    FileAccess,
    ModuleCapability,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
    ParserModule,
)
from smart_lab_index.modules.parsers.common import (
    MAX_PDF_PAGES,
    DocumentParseError,
    assess_table,
    bbox,
    clean_cell,
    json_safe_metadata,
    provenance,
    require_table_budget,
    require_text_budget,
    source_extension,
)


class PdfParser(ParserModule):
    manifest = ModuleManifest(
        module_id="parser.pdf",
        name="PDF Parser",
        version="0.2.0",
        module_type=ModuleType.PARSER,
        description="Extracts text and tables from born-digital PDF streams.",
        capabilities=(ModuleCapability("parser.document", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def supports(self, source: DocumentSource) -> bool:
        return source_extension(source) == ".pdf" or source.content_type == "application/pdf"

    def parse(self, source: DocumentSource, content: BinaryIO) -> DocumentContent:
        try:
            content.seek(0)
            with pdfplumber.open(content) as pdf:
                if len(pdf.pages) > MAX_PDF_PAGES:
                    raise DocumentParseError("PDF document exceeds the page limit")
                blocks = []
                tables = []
                text_characters = 0
                table_rows = 0
                table_cells = 0
                for page in pdf.pages:
                    text = (page.extract_text() or "").strip()
                    if text:
                        text_characters += len(text)
                        require_text_budget(text_characters, "PDF document")
                        blocks.append(TextBlock(
                            index=len(blocks),
                            kind="page_text",
                            text=text,
                            provenance=provenance(
                                source,
                                {"page": page.page_number},
                                excerpt=text[:240],
                            ),
                        ))
                    for page_table_index, table in enumerate(page.find_tables()):
                        rows = tuple(
                            tuple(clean_cell(cell) for cell in row)
                            for row in table.extract()
                        )
                        table_rows += len(rows)
                        table_cells += sum(len(row) for row in rows)
                        require_table_budget(table_rows, table_cells, "PDF document")
                        cell_provenance = []
                        for row_index, row in enumerate(rows):
                            source_cells = (
                                table.rows[row_index].cells
                                if row_index < len(table.rows)
                                else []
                            )
                            cell_provenance.append(tuple(
                                provenance(source, {
                                    "page": page.page_number,
                                    "table": page_table_index,
                                    "row": row_index + 1,
                                    "column": column_index + 1,
                                    "bbox": bbox(source_cells[column_index])
                                    if column_index < len(source_cells)
                                    else None,
                                })
                                for column_index in range(len(row))
                            ))
                        tables.append(TableContent(
                            index=len(tables),
                            name=f"Page {page.page_number} table {page_table_index + 1}",
                            rows=rows,
                            cell_provenance=tuple(cell_provenance),
                            metadata={
                                "page": page.page_number,
                                "page_table_index": page_table_index,
                                "bbox": bbox(table.bbox),
                                **assess_table(rows),
                            },
                        ))
                warnings = []
                if not blocks:
                    warnings.append("no machine-readable PDF text detected")
                metadata = {
                    "page_count": len(pdf.pages),
                    "document_metadata": json_safe_metadata(pdf.metadata or {}),
                }
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError(f"PDF parsing failed: {exc}") from exc
        return DocumentContent(
            source_external_id=source.external_id,
            content_type=source.content_type,
            parser_module_id=self.manifest.module_id,
            parser_version=self.manifest.version,
            text_blocks=tuple(blocks),
            tables=tuple(tables),
            metadata=metadata,
            warnings=tuple(warnings),
        )
