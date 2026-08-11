"""Small synchronous event dispatcher for in-process module hooks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any


class EventType(str, Enum):
    SOURCE_DISCOVERED = "SOURCE_DISCOVERED"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    SOURCE_DELETED = "SOURCE_DELETED"
    DOCUMENT_REGISTERED = "DOCUMENT_REGISTERED"
    DOCUMENT_PARSED = "DOCUMENT_PARSED"
    DOCUMENT_PARSE_FAILED = "DOCUMENT_PARSE_FAILED"
    ENTITY_CANDIDATE_FOUND = "ENTITY_CANDIDATE_FOUND"
    ENTITY_CREATED = "ENTITY_CREATED"
    ASSERTION_CREATED = "ASSERTION_CREATED"
    ENTITY_MERGED = "ENTITY_MERGED"
    INDEX_RUN_COMPLETED = "INDEX_RUN_COMPLETED"
    ISSUE_CREATED = "ISSUE_CREATED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"


@dataclass(frozen=True)
class Event:
    event_type: EventType
    payload: Mapping[str, Any]
    source_module_id: str | None = None
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class HandlerFailure:
    owner: str
    error: str


EventHandler = Callable[[Event], None]


class EventBus:
    """Dispatch events synchronously and isolate failures per subscriber."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[tuple[str, EventHandler]]] = {}
        self._lock = RLock()

    def subscribe(self, event_type: EventType, owner: str, handler: EventHandler) -> None:
        with self._lock:
            self._handlers.setdefault(event_type, []).append((owner, handler))

    def unsubscribe_owner(self, owner: str) -> None:
        with self._lock:
            for event_type in list(self._handlers):
                self._handlers[event_type] = [
                    item for item in self._handlers[event_type] if item[0] != owner
                ]

    def emit(self, event: Event) -> tuple[HandlerFailure, ...]:
        with self._lock:
            handlers = tuple(self._handlers.get(event.event_type, ()))
        failures = []
        for owner, handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - module hooks are isolation boundaries
                failures.append(HandlerFailure(
                    owner=owner,
                    error=f"{type(exc).__name__}: event handler failed",
                ))
        return tuple(failures)
