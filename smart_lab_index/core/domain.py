"""Universal, provenance-first domain contracts owned by Smart Lab Core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


class EntityType(str, Enum):
    ORGANIZATION = "ORGANIZATION"
    ORGANIZATIONAL_UNIT = "ORGANIZATIONAL_UNIT"
    LOCATION = "LOCATION"
    ASSET = "ASSET"
    PERSON = "PERSON"
    DOCUMENT = "DOCUMENT"
    PROCESS = "PROCESS"
    SOURCE_SYSTEM = "SOURCE_SYSTEM"


class AssertionStatus(str, Enum):
    DIRECT = "DIRECT"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CONFLICTED = "CONFLICTED"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


class IssueSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class IndexRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class DiscoveryChange(str, Enum):
    NEW = "NEW"
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True)
class Provenance:
    """A structural reference back to the source that supports a value."""

    source_external_id: str
    locator: Mapping[str, Any]
    excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "source_external_id": self.source_external_id,
            "locator": dict(self.locator),
        }
        if self.excerpt is not None:
            value["excerpt"] = self.excerpt
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Provenance:
        return cls(
            source_external_id=str(value["source_external_id"]),
            locator=dict(value.get("locator", {})),
            excerpt=(
                None if value.get("excerpt") is None else str(value["excerpt"])
            ),
        )


@dataclass(frozen=True)
class SourceRecord:
    """Vendor-neutral record returned by connector modules."""

    external_id: str
    source_id: str
    name: str
    path: str
    content_type: str
    modified_at: str
    size_bytes: int
    checksum: str
    change_token: str
    content_ref: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    permission_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "source_id": self.source_id,
            "name": self.name,
            "path": self.path,
            "content_type": self.content_type,
            "modified_at": self.modified_at,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "change_token": self.change_token,
            "content_ref": self.content_ref,
            "metadata": dict(self.metadata),
            "permission_metadata": dict(self.permission_metadata),
        }

    def document_source(self) -> DocumentSource:
        """Return the path-safe metadata view exposed to parser modules."""
        return DocumentSource(
            external_id=self.external_id,
            source_id=self.source_id,
            name=self.name,
            path=self.path,
            content_type=self.content_type,
            modified_at=self.modified_at,
            size_bytes=self.size_bytes,
            checksum=self.checksum,
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class DocumentSource:
    """Parser input metadata; intentionally excludes connector content references."""

    external_id: str
    source_id: str
    name: str
    path: str
    content_type: str
    modified_at: str
    size_bytes: int
    checksum: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceDefinition:
    """A configured source instance backed by one installed connector provider."""

    source_id: str
    connector_module_id: str
    configuration: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        object.__setattr__(
            self,
            "configuration",
            MappingProxyType(dict(self.configuration)),
        )


@dataclass(frozen=True)
class DiscoveredSource:
    change: DiscoveryChange
    record: SourceRecord


@dataclass(frozen=True)
class DiscoveryFailure:
    external_id: str
    path: str
    error: str


@dataclass(frozen=True)
class DiscoveryBatch:
    sources: tuple[DiscoveredSource, ...] = ()
    failures: tuple[DiscoveryFailure, ...] = ()
    complete: bool = True


@dataclass(frozen=True)
class TextBlock:
    index: int
    kind: str
    text: str
    provenance: Provenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "text": self.text,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TextBlock:
        return cls(
            index=int(value["index"]),
            kind=str(value["kind"]),
            text=str(value["text"]),
            provenance=Provenance.from_dict(value["provenance"]),
        )


@dataclass(frozen=True)
class TableContent:
    index: int
    name: str | None
    rows: tuple[tuple[str, ...], ...]
    cell_provenance: tuple[tuple[Provenance, ...], ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "rows": [list(row) for row in self.rows],
            "cell_provenance": [
                [provenance.to_dict() for provenance in row]
                for row in self.cell_provenance
            ],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TableContent:
        return cls(
            index=int(value["index"]),
            name=None if value.get("name") is None else str(value["name"]),
            rows=tuple(
                tuple(str(cell) for cell in row)
                for row in value.get("rows", ())
            ),
            cell_provenance=tuple(
                tuple(Provenance.from_dict(item) for item in row)
                for row in value.get("cell_provenance", ())
            ),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True)
class DocumentContent:
    source_external_id: str
    content_type: str
    parser_module_id: str
    parser_version: str
    text_blocks: tuple[TextBlock, ...] = ()
    tables: tuple[TableContent, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_external_id": self.source_external_id,
            "content_type": self.content_type,
            "parser_module_id": self.parser_module_id,
            "parser_version": self.parser_version,
            "text_blocks": [block.to_dict() for block in self.text_blocks],
            "tables": [table.to_dict() for table in self.tables],
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DocumentContent:
        return cls(
            source_external_id=str(value["source_external_id"]),
            content_type=str(value["content_type"]),
            parser_module_id=str(value["parser_module_id"]),
            parser_version=str(value["parser_version"]),
            text_blocks=tuple(
                TextBlock.from_dict(item) for item in value.get("text_blocks", ())
            ),
            tables=tuple(
                TableContent.from_dict(item) for item in value.get("tables", ())
            ),
            metadata=dict(value.get("metadata", {})),
            warnings=tuple(str(item) for item in value.get("warnings", ())),
        )


@dataclass(frozen=True)
class EntityReference:
    entity_type: EntityType
    name: str | None = None
    identifier: str | None = None

    def __post_init__(self) -> None:
        if not (self.name or self.identifier):
            raise ValueError("an entity reference needs a name or identifier")


@dataclass(frozen=True)
class EntityCandidate:
    reference: EntityReference
    subtype: str | None
    aliases: tuple[str, ...]
    provenance: Provenance
    confidence: float
    extraction_method: str
    module_id: str
    module_version: str

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("entity candidate confidence must be between 0 and 1")


@dataclass(frozen=True)
class AssertionCandidate:
    subject: EntityReference
    predicate: str
    provenance: Provenance
    confidence: float
    extraction_method: str
    module_id: str
    module_version: str
    object_ref: EntityReference | None = None
    literal: Any = None
    status: AssertionStatus = AssertionStatus.DIRECT

    def __post_init__(self) -> None:
        if (self.object_ref is None) == (self.literal is None):
            raise ValueError("an assertion candidate needs exactly one object reference or literal")
        if not self.predicate.strip():
            raise ValueError("an assertion candidate predicate must not be empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("assertion candidate confidence must be between 0 and 1")


@dataclass(frozen=True)
class ExtractionResult:
    entities: tuple[EntityCandidate, ...] = ()
    assertions: tuple[AssertionCandidate, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityRecord:
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    normalized_name: str
    subtype: str | None
    identifier: str | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class AssertionRecord:
    assertion_id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str | None
    literal: Any
    source_record_id: str
    provenance: Mapping[str, Any]
    confidence: float
    extraction_method: str
    status: AssertionStatus
    module_id: str
    module_version: str
    document_id: str | None
    source_generation: int
    source_checksum: str


@dataclass(frozen=True)
class IssueDraft:
    """Read-only output from an issue rule; Core owns persistence and deduplication."""

    code: str
    severity: IssueSeverity
    entity_id: str | None
    source_record_id: str | None
    assertion_ids: tuple[str, ...]
    evidence: Mapping[str, Any]
    fingerprint: str
