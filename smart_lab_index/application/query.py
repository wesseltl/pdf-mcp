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
DISPLAY_LIMIT = 500
ASSERTION_DISPLAY_LIMIT = 1_500


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
        counts = self._store.projection_counts()
        sources = self._store.list_sources(
            include_deleted=False,
            limit=DISPLAY_LIMIT,
        )
        entities = self._store.list_entities(limit=DISPLAY_LIMIT)
        assertion_records = self._store.list_active_assertions(
            limit=ASSERTION_DISPLAY_LIMIT
        )
        document_records = self._store.list_documents(
            active_only=True,
            limit=DISPLAY_LIMIT,
        )
        issue_records = self._store.list_issues(limit=DISPLAY_LIMIT)
        entity_ids = {entity.entity_id for entity in entities}
        source_record_ids = {item["source_record_id"] for item in sources}
        for assertion in assertion_records:
            entity_ids.add(assertion.subject_entity_id)
            if assertion.object_entity_id is not None:
                entity_ids.add(assertion.object_entity_id)
            source_record_ids.add(assertion.source_record_id)
        for document in document_records:
            source_record_ids.add(document["source_record_id"])
        for issue in issue_records:
            if issue["entity_id"] is not None:
                entity_ids.add(issue["entity_id"])
            if issue["source_record_id"] is not None:
                source_record_ids.add(issue["source_record_id"])

        entity_values = [_entity_value(entity) for entity in entities]
        entity_names = self._store.entity_names(entity_ids)
        source_paths = self._store.source_paths(source_record_ids)
        assertions = [
            _assertion_value(assertion, entity_names, source_paths)
            for assertion in assertion_records
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
            for document in document_records
        ]
        issues = [
            {
                **issue,
                "entity_name": entity_names.get(issue["entity_id"]),
            }
            for issue in issue_records
        ]
        reviews_by_issue: dict[str, list[dict[str, Any]]] = {}
        for review in self._store.list_review_decisions(
            issue_ids=[issue["issue_id"] for issue in issues]
        ):
            reviews_by_issue.setdefault(review["target_id"], []).append(review)
        for issue in issues:
            issue["reviews"] = reviews_by_issue.get(issue["issue_id"], [])
        facts_by_entity: dict[str, list[dict[str, Any]]] = {}
        for assertion in assertions:
            facts_by_entity.setdefault(assertion["subject_entity_id"], []).append(
                assertion
            )
        for entity in entity_values:
            entity["facts"] = facts_by_entity.get(entity["entity_id"], [])
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
                counts,
            ),
            "entities": entity_values,
            "assertions": assertions,
            "responsibilities": responsibilities,
            "documents": documents,
            "issues": issues,
            "sources": sources,
            "modules": normalized_modules,
            "collections": {
                "entities": _collection(len(entity_values), counts["entities"]),
                "assertions": _collection(len(assertions), counts["active_assertions"]),
                "documents": _collection(len(documents), counts["documents"]),
                "issues": _collection(len(issues), counts["issues"]),
                "sources": _collection(len(sources), counts["sources"]),
            },
        }

    def search(self, query: str, *, limit: int = 50) -> dict[str, Any]:
        results = self._store.search(query, limit=limit)
        return {
            "query": " ".join(query.split()),
            "results": results,
            "count": len(results),
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
    counts: Mapping[str, Any],
) -> list[dict[str, Any]]:
    active_types = {
        str(module.get("module_type"))
        for module in modules
        if module.get("enabled")
        and module.get("health") not in {"ERROR", "UNAVAILABLE"}
    }
    entity_counts = {
        entity_type.value: counts["entities_by_type"].get(entity_type.value, 0)
        for entity_type in EntityType
    }
    values: list[dict[str, Any]] = [
        {
            "view_id": "overview",
            "label": "Home",
            "kind": "overview",
            "group": "Workspace",
        },
        {
            "view_id": "search",
            "label": "Search",
            "kind": "search",
            "group": "Workspace",
        },
    ]
    if "ENTITY_EXTRACTOR" in active_types or entities:
        values.extend(
            (
                {
                    "view_id": "equipment",
                    "label": "Equipment",
                    "kind": "entity_list",
                    "group": "Lab knowledge",
                    "entity_type": EntityType.ASSET.value,
                    "count": entity_counts[EntityType.ASSET.value],
                },
                {
                    "view_id": "locations",
                    "label": "Locations",
                    "kind": "entity_list",
                    "group": "Lab knowledge",
                    "entity_type": EntityType.LOCATION.value,
                    "count": entity_counts[EntityType.LOCATION.value],
                },
                {
                    "view_id": "people",
                    "label": "People",
                    "kind": "entity_list",
                    "group": "Lab knowledge",
                    "entity_type": EntityType.PERSON.value,
                    "count": entity_counts[EntityType.PERSON.value],
                },
                {
                    "view_id": "organizations",
                    "label": "Teams",
                    "kind": "entity_list",
                    "group": "Lab knowledge",
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
                "group": "Lab knowledge",
                "count": counts["responsibilities"],
            }
        )
    if "PARSER" in active_types or documents:
        values.append(
            {
                "view_id": "documents",
                "label": "Documents",
                "kind": "document_list",
                "group": "Lab knowledge",
                "count": counts["documents"],
            }
        )
    if "ISSUE_RULE" in active_types or issues:
        open_issues = counts["issues_by_status"].get("OPEN", 0)
        values.append(
            {
                "view_id": "review",
                "label": "Needs review",
                "kind": "issue_list",
                "group": "Review",
                "status": "OPEN",
                "count": open_issues,
            }
        )
        if counts["issues"] > open_issues:
            values.append(
                {
                    "view_id": "issues",
                    "label": "Review history",
                    "kind": "issue_list",
                    "group": "Review",
                    "count": counts["issues"],
                }
            )
    if "CONNECTOR" in active_types or sources:
        values.append(
            {
                "view_id": "sources",
                "label": "Files",
                "kind": "source_list",
                "group": "System",
                "count": counts["sources"],
            }
        )
    values.append(
        {
            "view_id": "modules",
            "label": "System status",
            "kind": "module_list",
            "group": "System",
            "count": len(modules),
        }
    )
    return values


def _collection(loaded: int, total: int) -> dict[str, Any]:
    return {"loaded": loaded, "total": total, "truncated": loaded < total}
