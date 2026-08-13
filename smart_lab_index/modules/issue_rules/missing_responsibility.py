"""Flag assets that have no active responsibility assertion."""

from __future__ import annotations

import hashlib
import json

from smart_lab_index.core.domain import IssueDraft, IssueSeverity
from smart_lab_index.core.modules import (
    FileAccess,
    IssueRepository,
    IssueRuleModule,
    ModuleCapability,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
)

RESPONSIBILITY_PREDICATES = ("responsible_for", "owns", "maintained_by")


class MissingResponsibilityRule(IssueRuleModule):
    manifest = ModuleManifest(
        module_id="issue.missing_responsibility",
        name="Missing Responsibility Rule",
        version="0.1.0",
        module_type=ModuleType.ISSUE_RULE,
        description="Flags indexed assets without an active responsibility relationship.",
        capabilities=(ModuleCapability("issue.rule", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def evaluate(self, repository: IssueRepository) -> tuple[IssueDraft, ...]:
        assets = {entity.entity_id: entity for entity in repository.list_entities("ASSET")}
        covered: set[str] = set()
        for predicate in RESPONSIBILITY_PREDICATES:
            for assertion in repository.list_active_assertions(predicate):
                if assertion.subject_entity_id in assets:
                    covered.add(assertion.subject_entity_id)
                if assertion.object_entity_id in assets:
                    covered.add(assertion.object_entity_id)
        drafts = []
        for entity_id in sorted(set(assets) - covered):
            identity = {"code": "MISSING_RESPONSIBILITY", "asset": entity_id}
            drafts.append(IssueDraft(
                code="MISSING_RESPONSIBILITY",
                severity=IssueSeverity.WARNING,
                entity_id=entity_id,
                source_record_id=None,
                assertion_ids=(),
                evidence={
                    "asset_name": assets[entity_id].canonical_name,
                    "expected_relationships": list(RESPONSIBILITY_PREDICATES),
                },
                fingerprint=hashlib.sha256(json.dumps(
                    identity,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")).hexdigest(),
            ))
        return tuple(drafts)
