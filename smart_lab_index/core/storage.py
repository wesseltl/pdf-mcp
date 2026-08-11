"""Core-owned durable SQLite storage for the Smart Lab knowledge index."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smart_lab_index.core.domain import (
    AssertionRecord,
    AssertionStatus,
    DocumentContent,
    EntityRecord,
    EntityType,
    IndexRunStatus,
    SourceRecord,
)

SCHEMA_VERSION = 1


class StorageError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _load_json(value: str | None, default: Any) -> Any:
    return default if value is None else json.loads(value)


def _id() -> str:
    return str(uuid.uuid4())


class KnowledgeStore:
    """Single durable repository boundary owned by Core, not individual modules."""

    def __init__(self, database: str | Path = "smart-lab-index.db") -> None:
        self.database = (
            ":memory:"
            if str(database) == ":memory:"
            else str(Path(database).expanduser().resolve())
        )
        if self.database != ":memory:":
            state_path = Path(self.database)
            state_parent = state_path.parent
            parent_existed = state_parent.exists()
            state_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not parent_existed:
                os.chmod(state_parent, 0o700)
            _validate_private_state_path(state_path)
        self.connection = sqlite3.connect(self.database)
        self._restrict_state_permissions()
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        if self.database != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()
        self._restrict_state_permissions()

    def __enter__(self) -> KnowledgeStore:  # noqa: PYI034 - Python 3.10 has no typing.Self
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Make a group of Core writes atomic without exposing SQLite to modules."""
        if self.connection.in_transaction:
            savepoint = f"sli_{uuid.uuid4().hex}"
            self.connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except Exception:
                self.connection.execute(f"ROLLBACK TO {savepoint}")
                self.connection.execute(f"RELEASE {savepoint}")
                raise
            else:
                self.connection.execute(f"RELEASE {savepoint}")
            return
        self.connection.execute("BEGIN")
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    @contextmanager
    def _write(self) -> Iterator[None]:
        if self.connection.in_transaction:
            yield
        else:
            with self.connection:
                yield

    def _restrict_state_permissions(self) -> None:
        if self.database == ":memory:":
            return
        for path in (
            Path(self.database),
            Path(f"{self.database}-wal"),
            Path(f"{self.database}-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)

    def _migrate(self) -> None:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            row["version"]
            for row in self.connection.execute("SELECT version FROM schema_migrations")
        }
        if any(version > SCHEMA_VERSION for version in applied):
            raise StorageError("database schema is newer than this Smart Lab Core")
        if 1 not in applied:
            self._apply_v1()

    def _apply_v1(self) -> None:
        with self._write():
            self.connection.executescript(
                """
                CREATE TABLE module_state (
                    module_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    module_type TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    lifecycle TEXT NOT NULL,
                    health TEXT NOT NULL,
                    health_detail TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    configuration_json TEXT NOT NULL,
                    configuration_hash TEXT NOT NULL,
                    security_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE index_runs (
                    index_run_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_configuration_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    enabled_modules_json TEXT NOT NULL,
                    module_versions_json TEXT NOT NULL,
                    module_configurations_json TEXT NOT NULL,
                    inference_module_json TEXT,
                    runtime_policy_json TEXT NOT NULL,
                    stats_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT
                );

                CREATE TABLE source_bindings (
                    source_id TEXT PRIMARY KEY,
                    connector_module_id TEXT NOT NULL,
                    identity_json TEXT NOT NULL,
                    identity_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE source_records (
                    source_record_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    connector_module_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    modified_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    change_token TEXT NOT NULL,
                    content_ref TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    permission_metadata_json TEXT NOT NULL,
                    source_generation INTEGER NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    last_seen_run_id TEXT,
                    UNIQUE(source_id, external_id),
                    FOREIGN KEY(last_seen_run_id) REFERENCES index_runs(index_run_id)
                );

                CREATE INDEX source_records_source_idx
                    ON source_records(source_id, deleted_at);

                CREATE TABLE documents (
                    document_id TEXT PRIMARY KEY,
                    source_record_id TEXT NOT NULL,
                    source_checksum TEXT NOT NULL,
                    source_generation INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    parser_module_id TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    index_run_id TEXT NOT NULL,
                    UNIQUE(
                        source_record_id, source_generation,
                        parser_module_id, parser_version
                    ),
                    FOREIGN KEY(source_record_id) REFERENCES source_records(source_record_id),
                    FOREIGN KEY(index_run_id) REFERENCES index_runs(index_run_id)
                );

                CREATE TABLE entities (
                    entity_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    subtype TEXT,
                    identifier TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(entity_type, identifier)
                );

                CREATE INDEX entities_name_idx
                    ON entities(entity_type, normalized_name);

                CREATE TABLE entity_aliases (
                    alias_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    source_record_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(entity_id, normalized_alias),
                    FOREIGN KEY(entity_id) REFERENCES entities(entity_id),
                    FOREIGN KEY(source_record_id) REFERENCES source_records(source_record_id)
                );

                CREATE INDEX entity_alias_lookup_idx
                    ON entity_aliases(normalized_alias);

                CREATE TABLE assertions (
                    assertion_id TEXT PRIMARY KEY,
                    subject_entity_id TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_entity_id TEXT,
                    literal_json TEXT,
                    source_record_id TEXT NOT NULL,
                    document_id TEXT,
                    source_generation INTEGER NOT NULL,
                    provenance_json TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                    extraction_method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    extraction_module_id TEXT NOT NULL,
                    extraction_module_version TEXT NOT NULL,
                    source_checksum TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    index_run_id TEXT NOT NULL,
                    CHECK((object_entity_id IS NOT NULL) != (literal_json IS NOT NULL)),
                    FOREIGN KEY(subject_entity_id) REFERENCES entities(entity_id),
                    FOREIGN KEY(object_entity_id) REFERENCES entities(entity_id),
                    FOREIGN KEY(source_record_id) REFERENCES source_records(source_record_id),
                    FOREIGN KEY(document_id) REFERENCES documents(document_id),
                    FOREIGN KEY(index_run_id) REFERENCES index_runs(index_run_id)
                );

                CREATE INDEX assertions_active_idx
                    ON assertions(predicate, status, subject_entity_id);

                CREATE TABLE document_processing (
                    document_id TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    module_version TEXT NOT NULL,
                    configuration_hash TEXT NOT NULL,
                    processing_context_hash TEXT NOT NULL,
                    index_run_id TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY(
                        document_id, module_id, module_version,
                        configuration_hash, processing_context_hash
                    ),
                    FOREIGN KEY(document_id) REFERENCES documents(document_id),
                    FOREIGN KEY(index_run_id) REFERENCES index_runs(index_run_id)
                );

                CREATE TABLE issues (
                    issue_id TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    entity_id TEXT,
                    source_record_id TEXT,
                    assertion_ids_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    rule_module_id TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    first_seen_run_id TEXT NOT NULL,
                    last_seen_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY(entity_id) REFERENCES entities(entity_id),
                    FOREIGN KEY(source_record_id) REFERENCES source_records(source_record_id),
                    FOREIGN KEY(first_seen_run_id) REFERENCES index_runs(index_run_id),
                    FOREIGN KEY(last_seen_run_id) REFERENCES index_runs(index_run_id)
                );

                CREATE INDEX issues_status_idx ON issues(status, code);

                CREATE TABLE review_decisions (
                    review_decision_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE audit_events (
                    audit_event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    detail_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                """
            )
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, _now()),
            )

    def sync_modules(self, modules: Iterable[Mapping[str, Any]]) -> None:
        timestamp = _now()
        with self._write():
            for module in modules:
                self.connection.execute(
                    """
                    INSERT INTO module_state(
                        module_id, name, version, module_type, enabled, lifecycle, health,
                        health_detail, capabilities_json, dependencies_json, configuration_json,
                        configuration_hash, security_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(module_id) DO UPDATE SET
                        name=excluded.name, version=excluded.version,
                        module_type=excluded.module_type, enabled=excluded.enabled,
                        lifecycle=excluded.lifecycle, health=excluded.health,
                        health_detail=excluded.health_detail,
                        capabilities_json=excluded.capabilities_json,
                        dependencies_json=excluded.dependencies_json,
                        configuration_json=excluded.configuration_json,
                        configuration_hash=excluded.configuration_hash,
                        security_json=excluded.security_json, updated_at=excluded.updated_at
                    """,
                    (
                        module["module_id"], module["name"], module["version"],
                        module["module_type"], int(bool(module["enabled"])), module["lifecycle"],
                        module["health"], module.get("health_detail", ""),
                        _json(module.get("capabilities", [])),
                        _json(module.get("dependencies", [])),
                        _json(module.get("configuration", {})),
                        module["configuration_hash"], _json(module.get("security", {})), timestamp,
                    ),
                )

    def begin_index_run(
        self,
        *,
        source_id: str,
        module_snapshot: Sequence[Mapping[str, Any]],
        runtime_policy: Mapping[str, Any] | None = None,
        source_configuration_hash: str = "",
    ) -> str:
        run_id = _id()
        enabled = [module["module_id"] for module in module_snapshot if module["enabled"]]
        versions = {
            module["module_id"]: module["version"]
            for module in module_snapshot
            if module["enabled"]
        }
        configurations = {
            module["module_id"]: module["configuration_hash"]
            for module in module_snapshot
            if module["enabled"]
        }
        inference = [
            {"module_id": module["module_id"], "version": module["version"]}
            for module in module_snapshot
            if module["enabled"] and module["module_type"] == "INFERENCE"
        ]
        with self._write():
            self.connection.execute(
                """
                INSERT INTO index_runs(
                    index_run_id, source_id, source_configuration_hash,
                    status, enabled_modules_json,
                    module_versions_json, module_configurations_json,
                    inference_module_json, runtime_policy_json,
                    stats_json, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, source_id, source_configuration_hash,
                    IndexRunStatus.RUNNING.value, _json(enabled),
                    _json(versions), _json(configurations),
                    _json(inference) if inference else None,
                    _json(dict(runtime_policy or {})), _json({}), _now(),
                ),
            )
        return run_id

    def bind_source(
        self,
        *,
        source_id: str,
        connector_module_id: str,
        identity: Mapping[str, Any],
    ) -> None:
        serialized = _json(dict(identity))
        identity_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            "SELECT * FROM source_bindings WHERE source_id=?",
            (source_id,),
        ).fetchone()
        if existing is not None and (
            existing["connector_module_id"] != connector_module_id
            or existing["identity_hash"] != identity_hash
        ):
            raise StorageError(
                f"source_id {source_id!r} is already bound to a different source"
            )
        timestamp = _now()
        with self._write():
            self.connection.execute(
                """
                INSERT INTO source_bindings(
                    source_id, connector_module_id, identity_json,
                    identity_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (
                    source_id,
                    connector_module_id,
                    serialized,
                    identity_hash,
                    timestamp,
                    timestamp,
                ),
            )

    def finish_index_run(
        self,
        run_id: str,
        *,
        status: IndexRunStatus,
        stats: Mapping[str, Any],
        error: str | None = None,
    ) -> None:
        with self._write():
            cursor = self.connection.execute(
                """
                UPDATE index_runs
                SET status=?, stats_json=?, completed_at=?, error=?
                WHERE index_run_id=?
                """,
                (status.value, _json(dict(stats)), _now(), error, run_id),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"unknown index run: {run_id}")

    def source_records(self, source_id: str) -> dict[str, SourceRecord]:
        rows = self.connection.execute(
            "SELECT * FROM source_records WHERE source_id=? AND deleted_at IS NULL",
            (source_id,),
        )
        return {row["external_id"]: self._source_from_row(row) for row in rows}

    def list_sources(self, *, include_deleted: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM source_records"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY source_id, external_id"
        rows = self.connection.execute(sql).fetchall()
        return [
            {
                "source_record_id": row["source_record_id"],
                "source_id": row["source_id"],
                "external_id": row["external_id"],
                "connector_module_id": row["connector_module_id"],
                "name": row["name"],
                "path": row["path"],
                "content_type": row["content_type"],
                "modified_at": row["modified_at"],
                "size_bytes": row["size_bytes"],
                "checksum": row["checksum"],
                "source_generation": row["source_generation"],
                "metadata": _load_json(row["metadata_json"], {}),
                "permission_metadata": _load_json(
                    row["permission_metadata_json"],
                    {},
                ),
                "deleted_at": row["deleted_at"],
            }
            for row in rows
        ]

    def source_record_id(self, source_id: str, external_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT source_record_id FROM source_records WHERE source_id=? AND external_id=?",
            (source_id, external_id),
        ).fetchone()
        return None if row is None else row["source_record_id"]

    def source_generation(self, source_record_id: str) -> int:
        row = self.connection.execute(
            "SELECT source_generation FROM source_records WHERE source_record_id=?",
            (source_record_id,),
        ).fetchone()
        if row is None:
            raise StorageError(f"unknown source record: {source_record_id}")
        return int(row["source_generation"])

    def upsert_source(
        self,
        record: SourceRecord,
        *,
        connector_module_id: str,
        index_run_id: str,
    ) -> tuple[str, bool]:
        existing = self.connection.execute(
            """
            SELECT source_record_id, checksum, deleted_at, source_generation
            FROM source_records WHERE source_id=? AND external_id=?
            """,
            (record.source_id, record.external_id),
        ).fetchone()
        source_record_id = existing["source_record_id"] if existing else _id()
        source_generation = 1
        if existing is not None:
            source_generation = int(existing["source_generation"])
            if existing["checksum"] != record.checksum or existing["deleted_at"] is not None:
                source_generation += 1
        timestamp = _now()
        with self._write():
            self.connection.execute(
                """
                INSERT INTO source_records(
                    source_record_id, source_id, external_id, connector_module_id, name, path,
                    content_type, modified_at, size_bytes, checksum, change_token, content_ref,
                    metadata_json, permission_metadata_json, source_generation,
                    first_seen_at, updated_at,
                    deleted_at, last_seen_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(source_id, external_id) DO UPDATE SET
                    connector_module_id=excluded.connector_module_id, name=excluded.name,
                    path=excluded.path, content_type=excluded.content_type,
                    modified_at=excluded.modified_at, size_bytes=excluded.size_bytes,
                    checksum=excluded.checksum, change_token=excluded.change_token,
                    content_ref=excluded.content_ref, metadata_json=excluded.metadata_json,
                    permission_metadata_json=excluded.permission_metadata_json,
                    source_generation=excluded.source_generation,
                    updated_at=excluded.updated_at, deleted_at=NULL,
                    last_seen_run_id=excluded.last_seen_run_id
                """,
                (
                    source_record_id, record.source_id, record.external_id,
                    connector_module_id, record.name, record.path, record.content_type,
                    record.modified_at, record.size_bytes, record.checksum, record.change_token,
                    record.content_ref, _json(dict(record.metadata)),
                    _json(dict(record.permission_metadata)), source_generation,
                    timestamp, timestamp, index_run_id,
                ),
            )
        return source_record_id, existing is None

    def mark_source_deleted(
        self, source_id: str, external_id: str, index_run_id: str
    ) -> str | None:
        row = self.connection.execute(
            "SELECT source_record_id FROM source_records WHERE source_id=? AND external_id=?",
            (source_id, external_id),
        ).fetchone()
        if row is None:
            return None
        timestamp = _now()
        with self._write():
            self.connection.execute(
                """
                UPDATE source_records
                SET deleted_at=?, updated_at=?, last_seen_run_id=?
                WHERE source_record_id=?
                """,
                (timestamp, timestamp, index_run_id, row["source_record_id"]),
            )
            self.connection.execute(
                """
                UPDATE assertions SET status=?, updated_at=?
                WHERE source_record_id=? AND status NOT IN (?, ?)
                """,
                (
                    AssertionStatus.SUPERSEDED.value, timestamp, row["source_record_id"],
                    AssertionStatus.REJECTED.value, AssertionStatus.SUPERSEDED.value,
                ),
            )
        return row["source_record_id"]

    def supersede_source_assertions(self, source_record_id: str) -> int:
        with self._write():
            cursor = self.connection.execute(
                """
                UPDATE assertions SET status=?, updated_at=?
                WHERE source_record_id=? AND status NOT IN (?, ?)
                """,
                (
                    AssertionStatus.SUPERSEDED.value, _now(), source_record_id,
                    AssertionStatus.REJECTED.value, AssertionStatus.SUPERSEDED.value,
                ),
            )
        return cursor.rowcount

    def supersede_source_module_assertions(
        self,
        *,
        source_record_id: str,
        module_id: str,
        current_index_run_id: str,
    ) -> int:
        with self._write():
            cursor = self.connection.execute(
                """
                UPDATE assertions SET status=?, updated_at=?
                WHERE source_record_id=? AND extraction_module_id=?
                  AND index_run_id<>? AND status NOT IN (?, ?)
                """,
                (
                    AssertionStatus.SUPERSEDED.value,
                    _now(),
                    source_record_id,
                    module_id,
                    current_index_run_id,
                    AssertionStatus.REJECTED.value,
                    AssertionStatus.SUPERSEDED.value,
                ),
            )
        return cursor.rowcount

    def save_document(
        self,
        *,
        source_record_id: str,
        source_checksum: str,
        content: Mapping[str, Any],
        content_type: str,
        parser_module_id: str,
        parser_version: str,
        index_run_id: str,
        source_generation: int,
    ) -> tuple[str, bool]:
        existing = self.connection.execute(
            """
            SELECT document_id FROM documents
            WHERE source_record_id=? AND source_generation=? AND source_checksum=?
              AND parser_module_id=? AND parser_version=?
            """,
            (
                source_record_id,
                source_generation,
                source_checksum,
                parser_module_id,
                parser_version,
            ),
        ).fetchone()
        if existing:
            return existing["document_id"], False
        document_id = _id()
        with self._write():
            self.connection.execute(
                """
                INSERT INTO documents(
                    document_id, source_record_id, source_checksum, content_type,
                    source_generation, parser_module_id, parser_version,
                    content_json, created_at, index_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id, source_record_id, source_checksum, content_type,
                    source_generation, parser_module_id, parser_version,
                    _json(dict(content)), _now(), index_run_id,
                ),
            )
        return document_id, True

    def find_document(
        self,
        *,
        source_record_id: str,
        source_checksum: str,
        source_generation: int,
        parser_module_id: str,
        parser_version: str,
    ) -> tuple[str, DocumentContent] | None:
        row = self.connection.execute(
            """
            SELECT document_id, content_json FROM documents
            WHERE source_record_id=? AND source_generation=? AND source_checksum=?
              AND parser_module_id=? AND parser_version=?
            """,
            (
                source_record_id,
                source_generation,
                source_checksum,
                parser_module_id,
                parser_version,
            ),
        ).fetchone()
        if row is None:
            return None
        content = DocumentContent.from_dict(_load_json(row["content_json"], {}))
        return row["document_id"], content

    def list_documents(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT document_id, source_record_id, source_checksum, content_type,
                   source_generation, parser_module_id, parser_version,
                   created_at, index_run_id
            FROM documents ORDER BY created_at, document_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def processing_complete(
        self,
        *,
        document_id: str,
        module_id: str,
        module_version: str,
        configuration_hash: str,
        processing_context_hash: str,
    ) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM document_processing
            WHERE document_id=? AND module_id=? AND module_version=?
              AND configuration_hash=? AND processing_context_hash=?
            """,
            (
                document_id,
                module_id,
                module_version,
                configuration_hash,
                processing_context_hash,
            ),
        ).fetchone()
        return row is not None

    def mark_processing_complete(
        self,
        *,
        document_id: str,
        module_id: str,
        module_version: str,
        configuration_hash: str,
        processing_context_hash: str,
        index_run_id: str,
    ) -> None:
        with self._write():
            self.connection.execute(
                """
                INSERT OR REPLACE INTO document_processing(
                    document_id, module_id, module_version, configuration_hash,
                    processing_context_hash, index_run_id, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    module_id,
                    module_version,
                    configuration_hash,
                    processing_context_hash,
                    index_run_id,
                    _now(),
                ),
            )

    def create_entity(
        self,
        *,
        entity_type: EntityType,
        canonical_name: str,
        normalized_name: str,
        subtype: str | None,
        identifier: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EntityRecord:
        entity_id = _id()
        timestamp = _now()
        try:
            with self._write():
                self.connection.execute(
                    """
                    INSERT INTO entities(
                        entity_id, entity_type, canonical_name, normalized_name, subtype,
                        identifier, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id, entity_type.value, canonical_name, normalized_name, subtype,
                        identifier, _json(dict(metadata or {})), timestamp, timestamp,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageError(
                f"entity identifier already exists for {entity_type.value}: {identifier}"
            ) from exc
        return EntityRecord(
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            normalized_name=normalized_name,
            subtype=subtype,
            identifier=identifier,
            metadata=dict(metadata or {}),
        )

    def update_entity_identifier(self, entity_id: str, identifier: str) -> EntityRecord:
        with self._write():
            self.connection.execute(
                """
                UPDATE entities SET identifier=COALESCE(identifier, ?), updated_at=?
                WHERE entity_id=?
                """,
                (identifier, _now(), entity_id),
            )
        entity = self.get_entity(entity_id)
        if entity is None:
            raise StorageError(f"unknown entity: {entity_id}")
        return entity

    def enrich_entity(
        self,
        entity_id: str,
        *,
        identifier: str | None,
        subtype: str | None,
    ) -> EntityRecord:
        try:
            with self._write():
                self.connection.execute(
                    """
                    UPDATE entities
                    SET identifier=COALESCE(identifier, ?),
                        subtype=COALESCE(subtype, ?), updated_at=?
                    WHERE entity_id=?
                    """,
                    (identifier, subtype, _now(), entity_id),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageError(
                f"entity identifier already exists for another entity: {identifier}"
            ) from exc
        entity = self.get_entity(entity_id)
        if entity is None:
            raise StorageError(f"unknown entity: {entity_id}")
        return entity

    def add_alias(
        self,
        *,
        entity_id: str,
        alias: str,
        normalized_alias: str,
        source_record_id: str | None,
    ) -> None:
        with self._write():
            self.connection.execute(
                """
                INSERT OR IGNORE INTO entity_aliases(
                    alias_id, entity_id, alias, normalized_alias, source_record_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (_id(), entity_id, alias, normalized_alias, source_record_id, _now()),
            )

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        row = self.connection.execute(
            "SELECT * FROM entities WHERE entity_id=?", (entity_id,)
        ).fetchone()
        return None if row is None else self._entity_from_row(row)

    def find_entity_by_identifier(
        self, entity_type: str, identifier: str
    ) -> EntityRecord | None:
        row = self.connection.execute(
            "SELECT * FROM entities WHERE entity_type=? AND identifier=?",
            (entity_type, identifier),
        ).fetchone()
        return None if row is None else self._entity_from_row(row)

    def find_entity_by_alias(self, entity_type: str, alias: str) -> EntityRecord | None:
        rows = self.connection.execute(
            """
            SELECT entities.* FROM entity_aliases
            JOIN entities ON entities.entity_id=entity_aliases.entity_id
            WHERE entities.entity_type=? AND entity_aliases.normalized_alias=?
            ORDER BY entities.entity_id
            """,
            (entity_type, alias),
        ).fetchall()
        return self._entity_from_row(rows[0]) if len(rows) == 1 else None

    def find_entity_by_normalized_name(
        self, entity_type: str, normalized_name: str
    ) -> EntityRecord | None:
        rows = self.connection.execute(
            "SELECT * FROM entities WHERE entity_type=? AND normalized_name=? ORDER BY entity_id",
            (entity_type, normalized_name),
        ).fetchall()
        return self._entity_from_row(rows[0]) if len(rows) == 1 else None

    def list_entities(self, entity_type: EntityType | None = None) -> list[EntityRecord]:
        if entity_type is None:
            rows = self.connection.execute(
                "SELECT * FROM entities ORDER BY entity_type, canonical_name"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM entities WHERE entity_type=? ORDER BY canonical_name",
                (entity_type.value,),
            ).fetchall()
        return [self._entity_from_row(row) for row in rows]

    def create_assertion(
        self,
        *,
        subject_entity_id: str,
        predicate: str,
        object_entity_id: str | None,
        literal: Any,
        source_record_id: str,
        provenance: Mapping[str, Any],
        confidence: float,
        extraction_method: str,
        status: AssertionStatus,
        extraction_module_id: str,
        extraction_module_version: str,
        index_run_id: str,
        document_id: str | None = None,
    ) -> tuple[str, bool]:
        if (object_entity_id is None) == (literal is None):
            raise ValueError("an assertion needs exactly one object entity or literal")
        if not 0 <= confidence <= 1:
            raise ValueError("assertion confidence must be between 0 and 1")
        source = self.connection.execute(
            """
            SELECT checksum, source_generation FROM source_records
            WHERE source_record_id=?
            """,
            (source_record_id,),
        ).fetchone()
        if source is None:
            raise StorageError(f"unknown source record: {source_record_id}")
        identity = {
            "subject": subject_entity_id,
            "predicate": predicate,
            "object": object_entity_id,
            "literal": literal,
            "source": source_record_id,
            "document": document_id,
            "source_generation": source["source_generation"],
            "source_checksum": source["checksum"],
            "provenance": dict(provenance),
            "module": extraction_module_id,
            "module_version": extraction_module_version,
            "index_run_id": index_run_id,
        }
        fingerprint = hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            "SELECT assertion_id FROM assertions WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        if existing:
            return existing["assertion_id"], False
        assertion_id = _id()
        timestamp = _now()
        with self._write():
            self.connection.execute(
                """
                INSERT INTO assertions(
                    assertion_id, subject_entity_id, predicate, object_entity_id, literal_json,
                    source_record_id, document_id, source_generation,
                    provenance_json, confidence,
                    extraction_method, status,
                    extraction_module_id, extraction_module_version, source_checksum, fingerprint,
                    created_at, updated_at, index_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assertion_id, subject_entity_id, predicate, object_entity_id,
                    None if literal is None else _json(literal), source_record_id, document_id,
                    source["source_generation"],
                    _json(dict(provenance)), confidence, extraction_method, status.value,
                    extraction_module_id, extraction_module_version, source["checksum"],
                    fingerprint, timestamp, timestamp, index_run_id,
                ),
            )
        return assertion_id, True

    def list_active_assertions(self, predicate: str | None = None) -> list[AssertionRecord]:
        parameters: list[Any] = [
            AssertionStatus.REJECTED.value,
            AssertionStatus.SUPERSEDED.value,
        ]
        sql = "SELECT * FROM assertions WHERE status NOT IN (?, ?)"
        if predicate is not None:
            sql += " AND predicate=?"
            parameters.append(predicate)
        sql += " ORDER BY created_at, assertion_id"
        rows = self.connection.execute(sql, parameters).fetchall()
        return [self._assertion_from_row(row) for row in rows]

    def list_assertions(self, *, include_superseded: bool = True) -> list[AssertionRecord]:
        if include_superseded:
            rows = self.connection.execute(
                "SELECT * FROM assertions ORDER BY created_at, assertion_id"
            ).fetchall()
            return [self._assertion_from_row(row) for row in rows]
        return self.list_active_assertions()

    def create_issue(
        self,
        *,
        code: str,
        severity: str,
        entity_id: str | None,
        source_record_id: str | None,
        assertion_ids: Sequence[str],
        evidence: Mapping[str, Any],
        rule_module_id: str,
        rule_version: str,
        fingerprint: str,
        index_run_id: str,
    ) -> tuple[str, bool]:
        existing = self.connection.execute(
            "SELECT issue_id FROM issues WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        timestamp = _now()
        if existing:
            with self._write():
                self.connection.execute(
                    """
                    UPDATE issues SET status='OPEN', severity=?, entity_id=?, source_record_id=?,
                        assertion_ids_json=?, evidence_json=?, rule_version=?,
                        last_seen_run_id=?, updated_at=?, resolved_at=NULL
                    WHERE issue_id=?
                    """,
                    (
                        severity, entity_id, source_record_id, _json(list(assertion_ids)),
                        _json(dict(evidence)), rule_version, index_run_id, timestamp,
                        existing["issue_id"],
                    ),
                )
            return existing["issue_id"], False
        issue_id = _id()
        with self._write():
            self.connection.execute(
                """
                INSERT INTO issues(
                    issue_id, code, severity, status, entity_id, source_record_id,
                    assertion_ids_json, evidence_json, rule_module_id, rule_version, fingerprint,
                    first_seen_run_id, last_seen_run_id, created_at, updated_at
                ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_id, code, severity, entity_id, source_record_id,
                    _json(list(assertion_ids)), _json(dict(evidence)), rule_module_id,
                    rule_version, fingerprint, index_run_id, index_run_id, timestamp, timestamp,
                ),
            )
        return issue_id, True

    def resolve_issues_not_seen(
        self, rule_module_id: str, index_run_id: str, active_fingerprints: set[str]
    ) -> int:
        rows = self.connection.execute(
            "SELECT issue_id, fingerprint FROM issues WHERE rule_module_id=? AND status='OPEN'",
            (rule_module_id,),
        ).fetchall()
        stale = [row["issue_id"] for row in rows if row["fingerprint"] not in active_fingerprints]
        if not stale:
            return 0
        timestamp = _now()
        with self._write():
            self.connection.executemany(
                """
                UPDATE issues SET status='RESOLVED', resolved_at=?, updated_at=?,
                    last_seen_run_id=? WHERE issue_id=?
                """,
                [(timestamp, timestamp, index_run_id, issue_id) for issue_id in stale],
            )
        return len(stale)

    def resolve_issue_fingerprint(self, fingerprint: str, index_run_id: str) -> bool:
        timestamp = _now()
        with self._write():
            cursor = self.connection.execute(
                """
                UPDATE issues
                SET status='RESOLVED', resolved_at=?, updated_at=?, last_seen_run_id=?
                WHERE fingerprint=? AND status='OPEN'
                """,
                (timestamp, timestamp, index_run_id, fingerprint),
            )
        return cursor.rowcount == 1

    def list_issues(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is None:
            rows = self.connection.execute(
                "SELECT * FROM issues ORDER BY status, code, created_at"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM issues WHERE status=? ORDER BY code, created_at", (status,)
            ).fetchall()
        return [
            {
                "issue_id": row["issue_id"],
                "code": row["code"],
                "severity": row["severity"],
                "status": row["status"],
                "entity_id": row["entity_id"],
                "source_record_id": row["source_record_id"],
                "assertion_ids": _load_json(row["assertion_ids_json"], []),
                "evidence": _load_json(row["evidence_json"], {}),
                "rule_module_id": row["rule_module_id"],
                "rule_version": row["rule_version"],
            }
            for row in rows
        ]

    def record_audit_event(
        self,
        *,
        event_type: str,
        actor: str,
        target_type: str | None,
        target_id: str | None,
        detail: Mapping[str, Any],
    ) -> str:
        event_id = _id()
        with self._write():
            self.connection.execute(
                """
                INSERT INTO audit_events(
                    audit_event_id, event_type, actor, target_type, target_id,
                    detail_json, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, event_type, actor, target_type, target_id, _json(dict(detail)), _now()),
            )
        return event_id

    def summary(self) -> dict[str, Any]:
        def count(table: str, where: str = "") -> int:
            return self.connection.execute(
                f"SELECT COUNT(*) AS value FROM {table} {where}"
            ).fetchone()["value"]

        latest = self.connection.execute(
            "SELECT * FROM index_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return {
            "sources": count("source_records", "WHERE deleted_at IS NULL"),
            "documents": count("documents"),
            "entities": count("entities"),
            "active_assertions": count(
                "assertions", "WHERE status NOT IN ('REJECTED', 'SUPERSEDED')"
            ),
            "open_issues": count("issues", "WHERE status='OPEN'"),
            "latest_run": None if latest is None else {
                "index_run_id": latest["index_run_id"],
                "source_id": latest["source_id"],
                "source_configuration_hash": latest["source_configuration_hash"],
                "status": latest["status"],
                "stats": _load_json(latest["stats_json"], {}),
                "started_at": latest["started_at"],
                "completed_at": latest["completed_at"],
                "error": latest["error"],
                "runtime_policy": _load_json(latest["runtime_policy_json"], {}),
            },
        }

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            external_id=row["external_id"],
            source_id=row["source_id"],
            name=row["name"],
            path=row["path"],
            content_type=row["content_type"],
            modified_at=row["modified_at"],
            size_bytes=row["size_bytes"],
            checksum=row["checksum"],
            change_token=row["change_token"],
            content_ref=row["content_ref"],
            metadata=_load_json(row["metadata_json"], {}),
            permission_metadata=_load_json(row["permission_metadata_json"], {}),
        )

    @staticmethod
    def _entity_from_row(row: sqlite3.Row) -> EntityRecord:
        return EntityRecord(
            entity_id=row["entity_id"],
            entity_type=EntityType(row["entity_type"]),
            canonical_name=row["canonical_name"],
            normalized_name=row["normalized_name"],
            subtype=row["subtype"],
            identifier=row["identifier"],
            metadata=_load_json(row["metadata_json"], {}),
        )

    @staticmethod
    def _assertion_from_row(row: sqlite3.Row) -> AssertionRecord:
        return AssertionRecord(
            assertion_id=row["assertion_id"],
            subject_entity_id=row["subject_entity_id"],
            predicate=row["predicate"],
            object_entity_id=row["object_entity_id"],
            literal=_load_json(row["literal_json"], None),
            source_record_id=row["source_record_id"],
            provenance=_load_json(row["provenance_json"], {}),
            confidence=row["confidence"],
            extraction_method=row["extraction_method"],
            status=AssertionStatus(row["status"]),
            module_id=row["extraction_module_id"],
            module_version=row["extraction_module_version"],
            document_id=row["document_id"],
            source_generation=row["source_generation"],
            source_checksum=row["source_checksum"],
        )


def _validate_private_state_path(path: Path) -> None:
    if not path.exists():
        return
    value = path.stat()
    if not stat.S_ISREG(value.st_mode):
        raise StorageError(f"Core database is not a regular file: {path}")
    if value.st_nlink != 1:
        raise StorageError("Core database must not have hard links")
