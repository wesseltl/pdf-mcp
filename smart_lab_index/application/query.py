"""Read-only GUI projection over the Core knowledge store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from smart_lab_index import __version__
from smart_lab_index.core.domain import AssertionRecord, EntityRecord, EntityType
from smart_lab_index.core.storage import KnowledgeStore

_RESPONSIBILITY_PREDICATES = {
    "backup_for",
    "maintained_by",
    "owns",
    "responsible_for",
}


class KnowledgeQueryService:
    """Build a user-facing projection without exposing Core write methods."""

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    def snapshot(
        self,
        *,
        source: Mapping[str, Any],
        modules: Sequence[Mapping[str, Any]],
        operation: Mapping[str, Any],
    ) -> dict[str, Any]:
        sources = self._store.list_sources()
        entities = self._store.list_entities()
        entity_values = [_entity_value(entity) for entity in entities]
        entity_names = {entity.entity_id: entity.canonical_name for entity in entities}
        source_paths = {item["source_record_id"]: item["path"] for item in sources}
        assertions = [
            _assertion_value(assertion, entity_names, source_paths)
            for assertion in self._store.list_active_assertions()
        ]
        responsibilities = [
            assertion
            for assertion in assertions
            if assertion["predicate"] in _RESPONSIBILITY_PREDICATES
        ]
        documents = [
            {
                **document,
                "source_path": source_paths.get(
                    document["source_record_id"],
                    document["source_record_id"],
                ),
            }
            for document in self._store.list_documents()
        ]
        issues = [
            {
                **issue,
                "entity_name": entity_names.get(issue["entity_id"]),
            }
            for issue in self._store.list_issues()
        ]
        summary = self._store.summary()
        normalized_modules = [dict(module) for module in modules]
        return {
            "product_version": __version__,
            "source": dict(source),
            "operation": dict(operation),
            "summary": summary,
            "views": _view_manifest(
                normalized_modules,
                entity_values,
                responsibilities,
                documents,
                issues,
                sources,
            ),
            "entities": entity_values,
            "assertions": assertions,
            "responsibilities": responsibilities,
            "documents": documents,
            "issues": issues,
            "sources": sources,
            "modules": normalized_modules,
        }


def _entity_value(entity: EntityRecord) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type.value,
        "canonical_name": entity.canonical_name,
        "subtype": entity.subtype,
        "identifier": entity.identifier,
        "metadata": dict(entity.metadata),
    }


def _assertion_value(
    assertion: AssertionRecord,
    entity_names: Mapping[str, str],
    source_paths: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "assertion_id": assertion.assertion_id,
        "subject_entity_id": assertion.subject_entity_id,
        "subject_name": entity_names.get(
            assertion.subject_entity_id,
            assertion.subject_entity_id,
        ),
        "predicate": assertion.predicate,
        "object_entity_id": assertion.object_entity_id,
        "object_name": entity_names.get(assertion.object_entity_id or ""),
        "literal": assertion.literal,
        "source_record_id": assertion.source_record_id,
        "source_path": source_paths.get(
            assertion.source_record_id,
            assertion.source_record_id,
        ),
        "document_id": assertion.document_id,
        "source_generation": assertion.source_generation,
        "source_checksum": assertion.source_checksum,
        "provenance": dict(assertion.provenance),
        "confidence": assertion.confidence,
        "status": assertion.status.value,
        "module_id": assertion.module_id,
        "module_version": assertion.module_version,
    }


def _view_manifest(
    modules: Sequence[Mapping[str, Any]],
    entities: Sequence[Mapping[str, Any]],
    responsibilities: Sequence[Mapping[str, Any]],
    documents: Sequence[Mapping[str, Any]],
    issues: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    active_types = {
        str(module.get("module_type"))
        for module in modules
        if module.get("enabled")
        and module.get("health") not in {"ERROR", "UNAVAILABLE"}
    }
    entity_counts = {
        entity_type.value: sum(
            1 for entity in entities if entity["entity_type"] == entity_type.value
        )
        for entity_type in EntityType
    }
    values: list[dict[str, Any]] = [
        {"view_id": "overview", "label": "Overview", "kind": "overview"},
    ]
    if "ENTITY_EXTRACTOR" in active_types or entities:
        values.extend(
            (
                {
                    "view_id": "equipment",
                    "label": "Equipment",
                    "kind": "entity_list",
                    "entity_type": EntityType.ASSET.value,
                    "count": entity_counts[EntityType.ASSET.value],
                },
                {
                    "view_id": "locations",
                    "label": "Locations",
                    "kind": "entity_list",
                    "entity_type": EntityType.LOCATION.value,
                    "count": entity_counts[EntityType.LOCATION.value],
                },
                {
                    "view_id": "people",
                    "label": "People",
                    "kind": "entity_list",
                    "entity_type": EntityType.PERSON.value,
                    "count": entity_counts[EntityType.PERSON.value],
                },
                {
                    "view_id": "organizations",
                    "label": "Organizations",
                    "kind": "entity_list",
                    "entity_types": [
                        EntityType.ORGANIZATION.value,
                        EntityType.ORGANIZATIONAL_UNIT.value,
                    ],
                    "count": (
                        entity_counts[EntityType.ORGANIZATION.value]
                        + entity_counts[EntityType.ORGANIZATIONAL_UNIT.value]
                    ),
                },
            )
        )
    if "RELATIONSHIP_EXTRACTOR" in active_types or responsibilities:
        values.append(
            {
                "view_id": "responsibilities",
                "label": "Responsibilities",
                "kind": "relationship_list",
                "count": len(responsibilities),
            }
        )
    if "PARSER" in active_types or documents:
        values.append(
            {
                "view_id": "documents",
                "label": "Documents",
                "kind": "document_list",
                "count": len(documents),
            }
        )
    if "ISSUE_RULE" in active_types or issues:
        open_issues = sum(1 for issue in issues if issue["status"] == "OPEN")
        values.extend(
            (
                {
                    "view_id": "review",
                    "label": "Review queue",
                    "kind": "issue_list",
                    "status": "OPEN",
                    "count": open_issues,
                },
                {
                    "view_id": "issues",
                    "label": "All issues",
                    "kind": "issue_list",
                    "count": len(issues),
                },
            )
        )
    if "CONNECTOR" in active_types or sources:
        values.append(
            {
                "view_id": "sources",
                "label": "Sources",
                "kind": "source_list",
                "count": len(sources),
            }
        )
    values.append(
        {
            "view_id": "modules",
            "label": "Modules",
            "kind": "module_list",
            "count": len(modules),
        }
    )
    return values
