"""Plain UTF-8 text parser module."""

from __future__ import annotations

from typing import BinaryIO

from smart_lab_index.core.domain import DocumentContent, DocumentSource, TextBlock
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
    provenance,
    source_extension,
)


class TextParser(ParserModule):
    manifest = ModuleManifest(
        module_id="parser.txt",
        name="Text Parser",
        version="0.1.0",
        module_type=ModuleType.PARSER,
        description="Parses UTF-8 plain text streams into line-addressable blocks.",
        capabilities=(ModuleCapability("parser.document", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def supports(self, source: DocumentSource) -> bool:
        return source_extension(source) == ".txt" or source.content_type == "text/plain"

    def parse(self, source: DocumentSource, content: BinaryIO) -> DocumentContent:
        try:
            content.seek(0)
            text = content.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParseError(f"text parsing failed: {exc}") from exc
        blocks = tuple(
            TextBlock(
                index=index,
                kind="line",
                text=line.strip(),
                provenance=provenance(
                    source,
                    {"line": line_number},
                    excerpt=line.strip()[:240],
                ),
            )
            for index, (line_number, line) in enumerate(
                item for item in enumerate(text.splitlines(), start=1) if item[1].strip()
            )
        )
        return DocumentContent(
            source_external_id=source.external_id,
            content_type=source.content_type,
            parser_module_id=self.manifest.module_id,
            parser_version=self.manifest.version,
            text_blocks=blocks,
            metadata={"encoding": "utf-8", "line_count": len(text.splitlines())},
            warnings=() if blocks else ("text file contains no non-empty lines",),
        )
