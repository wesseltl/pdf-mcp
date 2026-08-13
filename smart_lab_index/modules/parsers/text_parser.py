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
    MAX_TEXT_BLOCKS,
    DocumentParseError,
    provenance,
    read_utf8_text,
    source_extension,
)


class TextParser(ParserModule):
    manifest = ModuleManifest(
        module_id="parser.txt",
        name="Text Parser",
        version="0.2.0",
        module_type=ModuleType.PARSER,
        description="Parses UTF-8 plain text streams into line-addressable blocks.",
        capabilities=(ModuleCapability("parser.document", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def supports(self, source: DocumentSource) -> bool:
        return source_extension(source) == ".txt" or source.content_type == "text/plain"

    def parse(self, source: DocumentSource, content: BinaryIO) -> DocumentContent:
        text = read_utf8_text(content, "text document")
        lines = text.splitlines()
        blocks = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            if len(blocks) >= MAX_TEXT_BLOCKS:
                raise DocumentParseError("text document exceeds the block limit")
            blocks.append(TextBlock(
                index=len(blocks),
                kind="line",
                text=line.strip(),
                provenance=provenance(
                    source,
                    {"line": line_number},
                    excerpt=line.strip()[:240],
                ),
            ))
        return DocumentContent(
            source_external_id=source.external_id,
            content_type=source.content_type,
            parser_module_id=self.manifest.module_id,
            parser_version=self.manifest.version,
            text_blocks=tuple(blocks),
            metadata={"encoding": "utf-8", "line_count": len(lines)},
            warnings=() if blocks else ("text file contains no non-empty lines",),
        )
