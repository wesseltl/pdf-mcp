"""Auditable operator review service over Core issues and assertions."""

from __future__ import annotations

from typing import Any

from smart_lab_index.core.storage import KnowledgeStore


class IssueReviewService:
    """Validate the small review contract before invoking atomic Core writes."""

    def __init__(self, store: KnowledgeStore, *, reviewer: str = "local-operator") -> None:
        self._store = store
        self._reviewer = reviewer

    def review(
        self,
        *,
        issue_id: str,
        decision: str,
        reason: str,
        assertion_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(issue_id, str) or not issue_id.strip():
            raise ValueError("issue_id is required")
        if not isinstance(decision, str):
            raise TypeError("decision is required")
        if not isinstance(reason, str):
            raise TypeError("reason is required")
        if assertion_id is not None and not isinstance(assertion_id, str):
            raise ValueError("assertion_id must be a string")
        return self._store.review_issue(
            issue_id=issue_id,
            decision=decision,
            reason=reason,
            reviewer=self._reviewer,
            assertion_id=assertion_id,
        )
