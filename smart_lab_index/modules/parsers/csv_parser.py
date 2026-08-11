"""Delimited-text CSV parser module."""

from __future__ import annotations

import csv
import io
from typing import BinaryIO

from smart_lab_index.core.domain import DocumentContent, DocumentSource, TableContent
from smart_lab_index.core.modules import (
    FileAccess,
    ModuleCapability,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
    ParserModule,
)
from smart_lab_index.modules.parsers.common import (
    DocumentParseError,
    assess_table,
    provenance,
    source_extension,
)


class CsvParser(ParserModule):
    manifest = ModuleManifest(
        module_id="parser.csv",
        name="CSV Parser",
        version="0.1.0",
        module_type=ModuleType.PARSER,
        description="Parses UTF-8 delimited streams into normalized table rows.",
        capabilities=(ModuleCapability("parser.document", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def supports(self, source: DocumentSource) -> bool:
        return source_extension(source) == ".csv" or source.content_type == "text/csv"

    def parse(self, source: DocumentSource, content: BinaryIO) -> DocumentContent:
        try:
            content.seek(0)
            text = content.read().decode("utf-8-sig")
            try:
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            rows = tuple(tuple(cell.strip() for cell in row) for row in csv.reader(
                io.StringIO(text, newline=""), dialect
            ))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise DocumentParseError(f"CSV parsing failed: {exc}") from exc
        references = tuple(
            tuple(
                provenance(source, {"row": row_index, "column": column_index})
                for column_index in range(1, len(row) + 1)
            )
            for row_index, row in enumerate(rows, start=1)
        )
        tables = () if not rows else (TableContent(
            index=0,
            name=source.name,
            rows=rows,
            cell_provenance=references,
            metadata={"dialect_delimiter": dialect.delimiter, **assess_table(rows)},
        ),)
        return DocumentContent(
            source_external_id=source.external_id,
            content_type=source.content_type,
            parser_module_id=self.manifest.module_id,
            parser_version=self.manifest.version,
            tables=tables,
            metadata={"encoding": "utf-8"},
            warnings=() if rows else ("CSV contains no rows",),
        )
