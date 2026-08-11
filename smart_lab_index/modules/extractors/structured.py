"""Configuration-driven entity and relationship extraction from normalized tables."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from smart_lab_index.core.domain import (
    AssertionCandidate,
    DocumentContent,
    EntityCandidate,
    EntityReference,
    EntityType,
    ExtractionResult,
    Provenance,
)
from smart_lab_index.core.modules import (
    ExtractorModule,
    FileAccess,
    ModuleCapability,
    ModuleDependency,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
)


class StructuredExtractor(ExtractorModule):
    manifest = ModuleManifest(
        module_id="extractor.structured",
        name="Structured Table Extractor",
        version="0.2.0",
        module_type=ModuleType.ENTITY_EXTRACTOR,
        description="Applies configured semantic column rules to normalized tables.",
        dependencies=(
            ModuleDependency(capability="domain.extraction_rules", minimum_version="1.0.0"),
        ),
        capabilities=(
            ModuleCapability("extractor.entities", "1.0.0"),
            ModuleCapability("extractor.relationships", "1.0.0"),
        ),
        configuration_schema={
            "type": "object",
            "required": ["rule_ids"],
            "additionalProperties": False,
            "properties": {
                "rule_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def __init__(self, rules: Sequence[Mapping[str, Any]]) -> None:
        self.rules = tuple(dict(rule) for rule in rules)
        super().__init__({"rule_ids": [str(rule["rule_id"]) for rule in self.rules]})

    def extract(self, document: DocumentContent) -> ExtractionResult:
        entities: list[EntityCandidate] = []
        assertions: list[AssertionCandidate] = []
        warnings = []
        for table in document.tables:
            if len(table.rows) < 2:
                continue
            matched_table = False
            for rule in self.rules:
                match = _find_header(table.rows, rule)
                if match is None:
                    continue
                matched_table = True
                header_index, field_indexes = match
                for row_index, row in enumerate(
                    table.rows[header_index + 1 :],
                    start=header_index + 1,
                ):
                    references: dict[str, EntityReference] = {}
                    for specification in rule.get("entities", []):
                        reference = _entity_reference(row, field_indexes, specification)
                        if reference is None:
                            continue
                        references[specification["ref"]] = reference
                        source = _row_provenance(
                            document.source_external_id,
                            table.index,
                            table.name,
                            row_index + 1,
                            field_indexes.get(
                                specification.get("name_field")
                                or specification.get("identifier_field")
                            ),
                            table.cell_provenance,
                            row_index,
                        )
                        subtype = _field_value(
                            row,
                            field_indexes.get(specification.get("subtype_field")),
                        )
                        entities.append(EntityCandidate(
                            reference=reference,
                            subtype=subtype.upper().replace(" ", "_") if subtype else None,
                            aliases=_aliases(row, field_indexes, specification),
                            provenance=source,
                            confidence=1.0,
                            extraction_method="structured_columns",
                            module_id=self.manifest.module_id,
                            module_version=self.manifest.version,
                        ))
                    for relationship in rule.get("relationships", []):
                        subject = references.get(relationship["subject_ref"])
                        object_ref = references.get(relationship["object_ref"])
                        if subject is None or object_ref is None:
                            if not relationship.get("optional", False):
                                warnings.append(
                                    f"{rule['rule_id']} skipped a relationship with missing values"
                                )
                            continue
                        predicate = relationship["predicate"]
                        predicate_field = relationship.get("predicate_field")
                        if predicate_field:
                            raw = _field_value(row, field_indexes.get(predicate_field))
                            if raw:
                                mapped = relationship.get("predicate_map", {}).get(
                                    _normalize_header(raw)
                                )
                                if mapped is None:
                                    warnings.append(
                                        f"{rule['rule_id']} ignored unknown predicate {raw!r}"
                                    )
                                    continue
                                predicate = mapped
                        assertions.append(AssertionCandidate(
                            subject=subject,
                            predicate=predicate,
                            object_ref=object_ref,
                            provenance=_row_provenance(
                                document.source_external_id,
                                table.index,
                                table.name,
                                row_index + 1,
                                field_indexes.get(
                                    relationship.get(
                                        "evidence_field",
                                        relationship["object_ref"],
                                    )
                                ),
                                table.cell_provenance,
                                row_index,
                            ),
                            confidence=1.0,
                            extraction_method="structured_columns",
                            module_id=self.manifest.module_id,
                            module_version=self.manifest.version,
                        ))
                    for literal in rule.get("literals", []):
                        subject = references.get(literal["subject_ref"])
                        value = _field_value(row, field_indexes.get(literal["field"]))
                        if subject is None or value is None:
                            if not literal.get("optional", True):
                                warnings.append(
                                    f"{rule['rule_id']} skipped a literal with missing values"
                                )
                            continue
                        assertions.append(AssertionCandidate(
                            subject=subject,
                            predicate=literal["predicate"],
                            literal=value,
                            provenance=_row_provenance(
                                document.source_external_id,
                                table.index,
                                table.name,
                                row_index + 1,
                                field_indexes.get(literal["field"]),
                                table.cell_provenance,
                                row_index,
                            ),
                            confidence=1.0,
                            extraction_method="structured_columns",
                            module_id=self.manifest.module_id,
                            module_version=self.manifest.version,
                        ))
            if not matched_table:
                warnings.append(
                    f"{table.name or f'Table {table.index + 1}'} did not match a configured table rule"
                )
        return ExtractionResult(
            entities=tuple(entities),
            assertions=tuple(assertions),
            warnings=tuple(warnings),
        )


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def _field_indexes(
    headers: Sequence[str], fields: Mapping[str, Sequence[str]]
) -> dict[str, int | None]:
    return {
        field: next(
            (
                headers.index(_normalize_header(alias))
                for alias in aliases
                if _normalize_header(alias) in headers
            ),
            None,
        )
        for field, aliases in fields.items()
    }


def _find_header(
    rows: Sequence[Sequence[str]],
    rule: Mapping[str, Any],
) -> tuple[int, dict[str, int | None]] | None:
    required_any = {
        _normalize_header(value) for value in rule.get("match_headers_any", ())
    }
    required_all = {
        _normalize_header(value) for value in rule.get("match_headers_all", ())
    }
    matches: list[tuple[int, int, dict[str, int | None]]] = []
    for row_index, row in enumerate(rows[:10]):
        headers = [_normalize_header(value) for value in row]
        if required_any and required_any.isdisjoint(headers):
            continue
        if not required_all.issubset(headers):
            continue
        indexes = _field_indexes(headers, rule.get("fields", {}))
        if not all(indexes.get(field) is not None for field in rule["match_all"]):
            continue
        score = sum(index is not None for index in indexes.values())
        matches.append((score, -row_index, indexes))
    if not matches:
        return None
    _score, negative_index, indexes = max(matches, key=lambda item: (item[0], item[1]))
    return -negative_index, indexes


def _aliases(
    row: Sequence[str],
    fields: Mapping[str, int | None],
    specification: Mapping[str, Any],
) -> tuple[str, ...]:
    values = {
        value
        for field in specification.get("alias_fields", ())
        if (value := _field_value(row, fields.get(field))) is not None
    }
    return tuple(sorted(values))


def _field_value(row: Sequence[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    value = row[index].strip()
    return value or None


def _entity_reference(
    row: Sequence[str],
    fields: Mapping[str, int | None],
    specification: Mapping[str, Any],
) -> EntityReference | None:
    identifier = _field_value(row, fields.get(specification.get("identifier_field")))
    name = _field_value(row, fields.get(specification.get("name_field")))
    if name is None:
        name = _field_value(row, fields.get(specification.get("fallback_name_field")))
    if not (identifier or name):
        return None
    return EntityReference(
        entity_type=EntityType(specification["type"]),
        name=name or identifier,
        identifier=identifier,
    )


def _row_provenance(
    external_id: str,
    table_index: int,
    table_name: str | None,
    row_number: int,
    column_index: int | None,
    cell_provenance: Sequence[Sequence[Provenance]],
    provenance_row_index: int,
) -> Provenance:
    locator: dict[str, Any] = {
        "table": table_index,
        "table_name": table_name,
        "row": row_number,
    }
    if column_index is not None:
        locator["column"] = column_index + 1
    if (
        column_index is not None
        and
        provenance_row_index < len(cell_provenance)
        and cell_provenance[provenance_row_index]
    ):
        source_column = column_index
        source_column = min(source_column, len(cell_provenance[provenance_row_index]) - 1)
        locator.update(cell_provenance[provenance_row_index][source_column].locator)
    return Provenance(source_external_id=external_id, locator=locator)
