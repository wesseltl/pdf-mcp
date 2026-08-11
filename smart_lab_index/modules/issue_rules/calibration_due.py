"""Flag invalid or overdue calibration dates from deterministic assertions."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

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


class CalibrationDueRule(IssueRuleModule):
    manifest = ModuleManifest(
        module_id="issue.calibration_due",
        name="Calibration Due Rule",
        version="0.1.0",
        module_type=ModuleType.ISSUE_RULE,
        description="Flags overdue or invalid calibration due dates.",
        capabilities=(ModuleCapability("issue.rule", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def evaluate(self, repository: IssueRepository) -> tuple[IssueDraft, ...]:
        today = datetime.now(timezone.utc).date()
        drafts = []
        for assertion in repository.list_active_assertions("calibration_due"):
            raw = str(assertion.literal or "").strip()
            due = _parse_date(raw)
            if due is None:
                code = "INVALID_CALIBRATION_DATE"
                severity = IssueSeverity.WARNING
            elif due < today:
                code = "OVERDUE_CALIBRATION"
                severity = IssueSeverity.ERROR
            else:
                continue
            entity = repository.get_entity(assertion.subject_entity_id)
            identity = {
                "code": code,
                "asset": assertion.subject_entity_id,
                "value": raw,
            }
            drafts.append(IssueDraft(
                code=code,
                severity=severity,
                entity_id=assertion.subject_entity_id,
                source_record_id=assertion.source_record_id,
                assertion_ids=(assertion.assertion_id,),
                evidence={
                    "asset_name": None if entity is None else entity.canonical_name,
                    "calibration_due": raw,
                    "evaluated_on": today.isoformat(),
                    "provenance": dict(assertion.provenance),
                },
                fingerprint=hashlib.sha256(json.dumps(
                    identity,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")).hexdigest(),
            ))
        return tuple(drafts)


def _parse_date(value: str) -> date | None:
    if len(value) < 10 or (len(value) > 10 and value[10] not in {" ", "T"}):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
