"""Detect assets with multiple active observed locations."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

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


class ConflictingLocationRule(IssueRuleModule):
    manifest = ModuleManifest(
        module_id="issue.conflicting_location",
        name="Conflicting Location Rule",
        version="0.1.0",
        module_type=ModuleType.ISSUE_RULE,
        description="Flags subjects with multiple active located_in assertions.",
        capabilities=(ModuleCapability("issue.rule", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def evaluate(self, repository: IssueRepository) -> tuple[IssueDraft, ...]:
        grouped = defaultdict(list)
        for assertion in repository.list_active_assertions("located_in"):
            if assertion.object_entity_id is not None:
                grouped[assertion.subject_entity_id].append(assertion)
        drafts = []
        for subject_id, assertions in grouped.items():
            object_ids = sorted({
                assertion.object_entity_id
                for assertion in assertions
                if assertion.object_entity_id is not None
            })
            if len(object_ids) < 2:
                continue
            subject = repository.get_entity(subject_id)
            values = []
            for assertion in assertions:
                location = (
                    repository.get_entity(assertion.object_entity_id)
                    if assertion.object_entity_id
                    else None
                )
                values.append({
                    "assertion_id": assertion.assertion_id,
                    "location_entity_id": assertion.object_entity_id,
                    "location_name": None if location is None else location.canonical_name,
                    "source_record_id": assertion.source_record_id,
                    "provenance": dict(assertion.provenance),
                })
            identity = {
                "code": "CONFLICTING_LOCATION",
                "subject": subject_id,
                "objects": object_ids,
            }
            fingerprint = hashlib.sha256(json.dumps(
                identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            drafts.append(IssueDraft(
                code="CONFLICTING_LOCATION",
                severity=IssueSeverity.ERROR,
                entity_id=subject_id,
                source_record_id=None,
                assertion_ids=tuple(sorted(
                    assertion.assertion_id for assertion in assertions
                )),
                evidence={
                    "subject_name": None if subject is None else subject.canonical_name,
                    "observed_locations": values,
                },
                fingerprint=fingerprint,
            ))
        return tuple(drafts)
