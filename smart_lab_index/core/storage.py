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

SCHEMA_VERSION = 2


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
        if str(database) == ":memory:":
            self.database = ":memory:"
        else:
            requested = Path(
                os.path.abspath(os.fspath(Path(database).expanduser()))
            )
            _validate_private_state_path(requested)
            self.database = str(requested.parent.resolve() / requested.name)
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
        if 2 not in applied:
            self._apply_v2()

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

    def _apply_v2(self) -> None:
        with self._write():
            self.connection.execute(
                "ALTER TABLE document_processing ADD COLUMN entity_count INTEGER NOT NULL DEFAULT 0"
            )
            self.connection.execute(
                "ALTER TABLE document_processing ADD COLUMN assertion_count INTEGER NOT NULL DEFAULT 0"
            )
            self.connection.execute(
                "ALTER TABLE document_processing ADD COLUMN warnings_json TEXT NOT NULL DEFAULT '[]'"
            )
            self.connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (2, _now()),
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

    def recover_interrupted_runs(self) -> int:
        """Close runs left RUNNING after an exclusive-owner process stopped."""
        timestamp = _now()
        with self._write():
            cursor = self.connection.execute(
                """
                UPDATE index_runs
                SET status=?, completed_at=?, error=?
                WHERE status=?
                """,
                (
                    IndexRunStatus.FAILED.value,
                    timestamp,
                    "indexing process stopped before the run completed",
                    IndexRunStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount:
                self.connection.execute(
                    """
                    INSERT INTO audit_events(
                        audit_event_id, event_type, actor, target_type, target_id,
                        detail_json, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _id(),
                        "INTERRUPTED_RUNS_RECOVERED",
                        "system",
                        "INDEX_RUN",
                        None,
                        _json({"count": cursor.rowcount}),
                        timestamp,
                    ),
                )
        return cursor.rowcount

    def source_records(self, source_id: str) -> dict[str, SourceRecord]:
        rows = self.connection.execute(
            "SELECT * FROM source_records WHERE source_id=? AND deleted_at IS NULL",
            (source_id,),
        )
        return {row["external_id"]: self._source_from_row(row) for row in rows}

    def list_sources(
        self,
        *,
        include_deleted: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM source_records"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY source_id, external_id"
        parameters: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            parameters = (_positive_limit(limit),)
        rows = self.connection.execute(sql, parameters).fetchall()
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

    def list_documents(
        self,
        *,
        active_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if active_only:
            sql = """
                WITH ranked AS (
                    SELECT documents.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY source_record_id, source_generation
                               ORDER BY created_at DESC, document_id DESC
                           ) AS document_rank
                    FROM documents
                )
                SELECT ranked.document_id, ranked.source_record_id,
                       ranked.source_checksum, ranked.content_type,
                       ranked.source_generation, ranked.parser_module_id,
                       ranked.parser_version, ranked.content_json,
                       ranked.created_at, ranked.index_run_id
                FROM ranked
                JOIN source_records
                  ON source_records.source_record_id=ranked.source_record_id
                WHERE ranked.document_rank=1
                  AND source_records.deleted_at IS NULL
                  AND ranked.source_generation=source_records.source_generation
                  AND ranked.source_checksum=source_records.checksum
                ORDER BY source_records.path
            """
        else:
            sql = """
                SELECT document_id, source_record_id, source_checksum, content_type,
                       source_generation, parser_module_id, parser_version,
                       content_json, created_at, index_run_id
                FROM documents ORDER BY created_at, document_id
            """
        parameters: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            parameters = (_positive_limit(limit),)
        rows = self.connection.execute(sql, parameters).fetchall()
        documents = []
        for row in rows:
            value = dict(row)
            content = _load_json(value.pop("content_json"), {})
            value["parser_warnings"] = list(content.get("warnings", []))
            value["processing"] = []
            value["extracted_entity_count"] = 0
            value["extracted_assertion_count"] = 0
            documents.append(value)
        if not documents:
            return documents
        placeholders = ",".join("?" for _ in documents)
        processing_rows = self.connection.execute(
            f"""
            SELECT * FROM document_processing
            WHERE document_id IN ({placeholders})
            ORDER BY completed_at, module_id
            """,
            tuple(document["document_id"] for document in documents),
        ).fetchall()
        latest: dict[tuple[str, str], sqlite3.Row] = {}
        for row in processing_rows:
            latest[(row["document_id"], row["module_id"])] = row
        by_document = {document["document_id"]: document for document in documents}
        for row in latest.values():
            processing = {
                "module_id": row["module_id"],
                "module_version": row["module_version"],
                "entity_count": row["entity_count"],
                "assertion_count": row["assertion_count"],
                "warnings": _load_json(row["warnings_json"], []),
                "completed_at": row["completed_at"],
            }
            document = by_document[row["document_id"]]
            document["processing"].append(processing)
            document["extracted_entity_count"] += row["entity_count"]
            document["extracted_assertion_count"] += row["assertion_count"]
        return documents

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
        entity_count: int = 0,
        assertion_count: int = 0,
        warnings: Sequence[str] = (),
    ) -> None:
        with self._write():
            self.connection.execute(
                """
                INSERT OR REPLACE INTO document_processing(
                    document_id, module_id, module_version, configuration_hash,
                    processing_context_hash, index_run_id, completed_at,
                    entity_count, assertion_count, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    module_id,
                    module_version,
                    configuration_hash,
                    processing_context_hash,
                    index_run_id,
                    _now(),
                    entity_count,
                    assertion_count,
                    _json(list(warnings)),
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

    def list_entities(
        self,
        entity_type: EntityType | None = None,
        *,
        limit: int | None = None,
    ) -> list[EntityRecord]:
        if entity_type is None:
            sql = "SELECT * FROM entities ORDER BY entity_type, canonical_name"
            parameters: tuple[Any, ...] = ()
        else:
            sql = "SELECT * FROM entities WHERE entity_type=? ORDER BY canonical_name"
            parameters = (entity_type.value,)
        if limit is not None:
            sql += " LIMIT ?"
            parameters += (_positive_limit(limit),)
        rows = self.connection.execute(sql, parameters).fetchall()
        return [self._entity_from_row(row) for row in rows]

    def entity_names(self, entity_ids: Iterable[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        for identifiers in _identifier_batches(entity_ids):
            placeholders = ",".join("?" for _ in identifiers)
            rows = self.connection.execute(
                f"SELECT entity_id, canonical_name FROM entities "
                f"WHERE entity_id IN ({placeholders})",
                identifiers,
            )
            values.update({row["entity_id"]: row["canonical_name"] for row in rows})
        return values

    def source_paths(self, source_record_ids: Iterable[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        for identifiers in _identifier_batches(source_record_ids):
            placeholders = ",".join("?" for _ in identifiers)
            rows = self.connection.execute(
                f"SELECT source_record_id, path FROM source_records "
                f"WHERE source_record_id IN ({placeholders})",
                identifiers,
            )
            values.update({row["source_record_id"]: row["path"] for row in rows})
        return values

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

    def list_active_assertions(
        self,
        predicate: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[AssertionRecord]:
        parameters: list[Any] = [
            AssertionStatus.REJECTED.value,
            AssertionStatus.SUPERSEDED.value,
        ]
        sql = "SELECT * FROM assertions WHERE status NOT IN (?, ?)"
        if predicate is not None:
            sql += " AND predicate=?"
            parameters.append(predicate)
        sql += " ORDER BY created_at, assertion_id"
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(_positive_limit(limit))
        rows = self.connection.execute(sql, parameters).fetchall()
        return [self._assertion_from_row(row) for row in rows]

    def list_assertions(
        self,
        *,
        include_superseded: bool = True,
        limit: int | None = None,
    ) -> list[AssertionRecord]:
        if include_superseded:
            sql = "SELECT * FROM assertions ORDER BY created_at, assertion_id"
            parameters: tuple[int, ...] = ()
            if limit is not None:
                sql += " LIMIT ?"
                parameters = (_positive_limit(limit),)
            rows = self.connection.execute(sql, parameters).fetchall()
            return [self._assertion_from_row(row) for row in rows]
        return self.list_active_assertions(limit=limit)

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
            "SELECT issue_id, status, assertion_ids_json FROM issues WHERE fingerprint=?",
            (fingerprint,),
        ).fetchone()
        timestamp = _now()
        if existing:
            reviewed = self.connection.execute(
                """
                SELECT 1 FROM review_decisions
                WHERE target_type='ISSUE' AND target_id=? LIMIT 1
                """,
                (existing["issue_id"],),
            ).fetchone()
            same_evidence = set(_load_json(existing["assertion_ids_json"], [])) == set(
                assertion_ids
            )
            status = existing["status"] if reviewed and same_evidence else "OPEN"
            with self._write():
                self.connection.execute(
                    """
                    UPDATE issues SET status=?, severity=?, entity_id=?, source_record_id=?,
                        assertion_ids_json=?, evidence_json=?, rule_version=?,
                        last_seen_run_id=?, updated_at=?,
                        resolved_at=CASE WHEN ?='OPEN' THEN NULL ELSE resolved_at END
                    WHERE issue_id=?
                    """,
                    (
                        status, severity, entity_id, source_record_id, _json(list(assertion_ids)),
                        _json(dict(evidence)), rule_version, index_run_id, timestamp, status,
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

    def list_issues(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if status is None:
            sql = "SELECT * FROM issues ORDER BY status, code, created_at"
            parameters: tuple[Any, ...] = ()
        else:
            sql = "SELECT * FROM issues WHERE status=? ORDER BY code, created_at"
            parameters = (status,)
        if limit is not None:
            sql += " LIMIT ?"
            parameters += (_positive_limit(limit),)
        rows = self.connection.execute(sql, parameters).fetchall()
        return [self._issue_from_row(row) for row in rows]

    def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM issues WHERE issue_id=?",
            (issue_id,),
        ).fetchone()
        return None if row is None else self._issue_from_row(row)

    def review_issue(
        self,
        *,
        issue_id: str,
        decision: str,
        reason: str,
        reviewer: str,
        assertion_id: str | None = None,
    ) -> dict[str, Any]:
        reason = " ".join(reason.split())
        if not reason or len(reason) > 1000:
            raise ValueError("review reason must contain between 1 and 1000 characters")
        if not reviewer.strip() or len(reviewer) > 100:
            raise ValueError("reviewer must contain between 1 and 100 characters")
        if decision not in {"CONFIRM_ASSERTION", "DISMISS"}:
            raise ValueError("unsupported review decision")
        timestamp = _now()
        review_id = _id()
        with self.transaction():
            issue_row = self.connection.execute(
                "SELECT * FROM issues WHERE issue_id=?",
                (issue_id,),
            ).fetchone()
            if issue_row is None:
                raise StorageError(f"unknown issue: {issue_id}")
            if issue_row["status"] != "OPEN":
                raise StorageError("only open issues can be reviewed")
            assertion_ids = set(_load_json(issue_row["assertion_ids_json"], []))
            if decision == "CONFIRM_ASSERTION" and assertion_id not in assertion_ids:
                raise ValueError("selected assertion does not belong to this issue")
            if decision == "CONFIRM_ASSERTION":
                rows = self.connection.execute(
                    f"SELECT assertion_id, object_entity_id FROM assertions WHERE assertion_id IN ({','.join('?' for _ in assertion_ids)})",
                    tuple(sorted(assertion_ids)),
                ).fetchall()
                if {row["assertion_id"] for row in rows} != assertion_ids:
                    raise StorageError("issue references an unknown assertion")
                selected_object = next(
                    row["object_entity_id"]
                    for row in rows
                    if row["assertion_id"] == assertion_id
                )
                if selected_object is None:
                    raise ValueError(
                        "only entity-valued assertions can resolve this issue"
                    )
                for row in rows:
                    candidate_id = row["assertion_id"]
                    status = (
                        AssertionStatus.CONFIRMED.value
                        if row["object_entity_id"] == selected_object
                        else AssertionStatus.REJECTED.value
                    )
                    self.connection.execute(
                        "UPDATE assertions SET status=?, updated_at=? WHERE assertion_id=?",
                        (status, timestamp, candidate_id),
                    )
                issue_status = "RESOLVED"
            else:
                issue_status = "DISMISSED"
            updated = self.connection.execute(
                """
                UPDATE issues SET status=?, resolved_at=?, updated_at=?
                WHERE issue_id=? AND status='OPEN'
                """,
                (issue_status, timestamp, timestamp, issue_id),
            )
            if updated.rowcount != 1:
                raise StorageError("issue was reviewed by another operation")
            self.connection.execute(
                """
                INSERT INTO review_decisions(
                    review_decision_id, target_type, target_id, decision,
                    reason, reviewer, created_at
                ) VALUES (?, 'ISSUE', ?, ?, ?, ?, ?)
                """,
                (review_id, issue_id, decision, reason, reviewer, timestamp),
            )
            self.record_audit_event(
                event_type="ISSUE_REVIEWED",
                actor=reviewer,
                target_type="issue",
                target_id=issue_id,
                detail={
                    "decision": decision,
                    "reason": reason,
                    "assertion_id": assertion_id,
                    "review_decision_id": review_id,
                },
            )
        reviewed = self.get_issue(issue_id)
        if reviewed is None:  # pragma: no cover - protected by transaction
            raise StorageError(f"unknown issue after review: {issue_id}")
        return reviewed

    def list_review_decisions(
        self,
        *,
        issue_id: str | None = None,
        issue_ids: Sequence[str] | None = None,
        per_issue_limit: int = 20,
    ) -> list[dict[str, Any]]:
        if issue_id is not None and issue_ids is not None:
            raise ValueError("provide issue_id or issue_ids, not both")
        if issue_ids is not None:
            identifiers = tuple(dict.fromkeys(issue_ids))
            if not identifiers:
                return []
            if len(identifiers) > 500:
                raise ValueError("at most 500 issue IDs can be loaded at once")
            limit = _positive_limit(per_issue_limit)
            placeholders = ",".join("?" for _ in identifiers)
            rows = self.connection.execute(
                f"""
                WITH ranked AS (
                    SELECT review_decisions.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY target_id ORDER BY created_at DESC
                           ) AS review_rank
                    FROM review_decisions
                    WHERE target_type='ISSUE' AND target_id IN ({placeholders})
                )
                SELECT review_decision_id, target_type, target_id, decision,
                       reason, reviewer, created_at
                FROM ranked WHERE review_rank <= ?
                ORDER BY created_at DESC
                """,
                (*identifiers, limit),
            ).fetchall()
        elif issue_id is None:
            rows = self.connection.execute(
                "SELECT * FROM review_decisions ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM review_decisions
                WHERE target_type='ISSUE' AND target_id=?
                ORDER BY created_at DESC
                """,
                (issue_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def projection_counts(self) -> dict[str, Any]:
        entity_counts = {
            row["entity_type"]: row["value"]
            for row in self.connection.execute(
                "SELECT entity_type, COUNT(*) AS value FROM entities GROUP BY entity_type"
            )
        }
        issue_counts = {
            row["status"]: row["value"]
            for row in self.connection.execute(
                "SELECT status, COUNT(*) AS value FROM issues GROUP BY status"
            )
        }
        responsibilities = self.connection.execute(
            """
            SELECT COUNT(*) AS value FROM assertions
            WHERE status NOT IN ('REJECTED', 'SUPERSEDED')
              AND predicate IN ('backup_for', 'maintained_by', 'owns', 'responsible_for')
            """
        ).fetchone()["value"]
        documents = self.connection.execute(
            """
            SELECT COUNT(DISTINCT source_records.source_record_id) AS value
            FROM source_records
            JOIN documents
              ON documents.source_record_id=source_records.source_record_id
             AND documents.source_generation=source_records.source_generation
             AND documents.source_checksum=source_records.checksum
            WHERE source_records.deleted_at IS NULL
            """
        ).fetchone()["value"]
        sources = self.connection.execute(
            "SELECT COUNT(*) AS value FROM source_records WHERE deleted_at IS NULL"
        ).fetchone()["value"]
        assertions = self.connection.execute(
            """
            SELECT COUNT(*) AS value FROM assertions
            WHERE status NOT IN ('REJECTED', 'SUPERSEDED')
            """
        ).fetchone()["value"]
        return {
            "sources": sources,
            "documents": documents,
            "entities": sum(entity_counts.values()),
            "entities_by_type": entity_counts,
            "active_assertions": assertions,
            "responsibilities": responsibilities,
            "issues": sum(issue_counts.values()),
            "issues_by_status": issue_counts,
        }

    def search(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        query = " ".join(query.split())
        if len(query) < 2:
            raise ValueError("search query must contain at least two characters")
        if len(query) > 200:
            raise ValueError("search query must not exceed 200 characters")
        limit = min(_positive_limit(limit), 100)
        pattern = f"%{_escape_like(query)}%"
        results: list[dict[str, Any]] = []

        entity_rows = self.connection.execute(
            """
            SELECT * FROM entities
            WHERE canonical_name LIKE ? ESCAPE '\\' COLLATE NOCASE
               OR COALESCE(identifier, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
               OR COALESCE(subtype, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
               OR metadata_json LIKE ? ESCAPE '\\' COLLATE NOCASE
               OR EXISTS (
                   SELECT 1 FROM entity_aliases
                   WHERE entity_aliases.entity_id=entities.entity_id
                     AND alias LIKE ? ESCAPE '\\' COLLATE NOCASE
               )
            ORDER BY canonical_name LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, pattern, limit),
        ).fetchall()
        for row in entity_rows:
            details = [row["entity_type"]]
            if row["subtype"]:
                details.append(row["subtype"])
            if row["identifier"] and row["identifier"] != row["canonical_name"]:
                details.append(row["identifier"])
            results.append({
                "kind": "entity",
                "id": row["entity_id"],
                "title": row["canonical_name"],
                "subtitle": " | ".join(details),
                "snippet": "",
                "entity_type": row["entity_type"],
            })

        document_rows = self.connection.execute(
            """
            SELECT documents.document_id, source_records.path, source_records.name,
                   documents.parser_module_id,
                   CASE WHEN source_records.path LIKE ? ESCAPE '\\' COLLATE NOCASE
                        THEN 1 ELSE 0 END AS path_match
            FROM documents
            JOIN source_records
              ON source_records.source_record_id=documents.source_record_id
             AND source_records.source_generation=documents.source_generation
             AND source_records.checksum=documents.source_checksum
            WHERE source_records.deleted_at IS NULL
              AND (
                  source_records.path LIKE ? ESCAPE '\\' COLLATE NOCASE
                  OR documents.content_json LIKE ? ESCAPE '\\' COLLATE NOCASE
              )
              AND documents.created_at=(
                  SELECT MAX(current_document.created_at) FROM documents current_document
                  WHERE current_document.source_record_id=documents.source_record_id
                    AND current_document.source_generation=documents.source_generation
              )
            ORDER BY source_records.path LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()
        for row in document_rows:
            if row["path_match"]:
                snippet = row["path"]
            else:
                content_row = self.connection.execute(
                    "SELECT content_json FROM documents WHERE document_id=?",
                    (row["document_id"],),
                ).fetchone()
                content = _load_json(content_row["content_json"], {})
                snippet = _document_snippet(content, query)
            results.append({
                "kind": "document",
                "id": row["document_id"],
                "title": row["name"],
                "subtitle": row["path"],
                "snippet": snippet,
                "source_path": row["path"],
            })

        issue_rows = self.connection.execute(
            """
            SELECT issues.*, entities.canonical_name
            FROM issues LEFT JOIN entities ON entities.entity_id=issues.entity_id
            WHERE issues.code LIKE ? ESCAPE '\\' COLLATE NOCASE
               OR issues.evidence_json LIKE ? ESCAPE '\\' COLLATE NOCASE
               OR COALESCE(entities.canonical_name, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
            ORDER BY issues.status, issues.code LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()
        for row in issue_rows:
            issue = self._issue_from_row(row)
            issue["entity_name"] = row["canonical_name"]
            results.append({
                "kind": "issue",
                "id": row["issue_id"],
                "title": row["code"].replace("_", " ").title(),
                "subtitle": f"{row['status']} | {row['severity']}",
                "snippet": row["canonical_name"] or "",
                "issue_id": row["issue_id"],
                "record": issue,
            })

        source_rows = self.connection.execute(
            """
            SELECT source_record_id, name, path, content_type FROM source_records
            WHERE deleted_at IS NULL
              AND (name LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR path LIKE ? ESCAPE '\\' COLLATE NOCASE)
            ORDER BY path LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()
        for row in source_rows:
            results.append({
                "kind": "source",
                "id": row["source_record_id"],
                "title": row["name"],
                "subtitle": row["content_type"],
                "snippet": row["path"],
                "source_path": row["path"],
            })

        assertion_rows = self.connection.execute(
            """
            SELECT assertions.assertion_id, assertions.predicate,
                   assertions.literal_json, subjects.canonical_name AS subject_name,
                   objects.canonical_name AS object_name, source_records.path
            FROM assertions
            JOIN entities subjects ON subjects.entity_id=assertions.subject_entity_id
            LEFT JOIN entities objects ON objects.entity_id=assertions.object_entity_id
            JOIN source_records ON source_records.source_record_id=assertions.source_record_id
            WHERE assertions.status NOT IN ('REJECTED', 'SUPERSEDED')
              AND (
                  assertions.predicate LIKE ? ESCAPE '\\' COLLATE NOCASE
                  OR COALESCE(assertions.literal_json, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
                  OR subjects.canonical_name LIKE ? ESCAPE '\\' COLLATE NOCASE
                  OR COALESCE(objects.canonical_name, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
              )
            ORDER BY subjects.canonical_name, assertions.predicate LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, limit),
        ).fetchall()
        for row in assertion_rows:
            value = row["object_name"]
            if value is None:
                value = _load_json(row["literal_json"], None)
            results.append({
                "kind": "assertion",
                "id": row["assertion_id"],
                "title": row["subject_name"],
                "subtitle": row["predicate"].replace("_", " "),
                "snippet": "" if value is None else str(value),
                "source_path": row["path"],
            })

        kind_order = {"entity": 0, "document": 1, "assertion": 2, "issue": 3, "source": 4}
        folded = query.casefold()
        results.sort(key=lambda item: (
            not item["title"].casefold().startswith(folded),
            kind_order[item["kind"]],
            item["title"].casefold(),
        ))
        return results[:limit]

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
        projections = self.projection_counts()
        return {
            "sources": count("source_records", "WHERE deleted_at IS NULL"),
            "documents": projections["documents"],
            "historical_documents": count("documents"),
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

    def integrity_report(self) -> dict[str, Any]:
        """Run bounded SQLite consistency checks for startup and supervision."""
        quick_rows = self.connection.execute("PRAGMA quick_check(1)").fetchall()
        quick_check = [str(row[0]) for row in quick_rows]
        foreign_rows = self.connection.execute("PRAGMA foreign_key_check").fetchmany(100)
        applied = [
            int(row["version"])
            for row in self.connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        healthy = quick_check == ["ok"] and not foreign_rows and applied == list(
            range(1, SCHEMA_VERSION + 1)
        )
        return {
            "healthy": healthy,
            "quick_check": quick_check,
            "foreign_key_violations": len(foreign_rows),
            "schema_version": applied[-1] if applied else 0,
            "expected_schema_version": SCHEMA_VERSION,
            "journal_mode": self.connection.execute("PRAGMA journal_mode").fetchone()[0],
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

    @staticmethod
    def _issue_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
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
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
        }


def _validate_private_state_path(path: Path) -> None:
    try:
        value = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(value.st_mode):
        raise StorageError("Core database path must not be a symbolic link")
    if not stat.S_ISREG(value.st_mode):
        raise StorageError(f"Core database is not a regular file: {path}")
    if value.st_nlink != 1:
        raise StorageError("Core database must not have hard links")


def _positive_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    return limit


def _identifier_batches(values: Iterable[str]) -> Iterator[tuple[str, ...]]:
    identifiers = tuple(sorted(set(values)))
    for offset in range(0, len(identifiers), 400):
        yield identifiers[offset : offset + 400]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _document_snippet(content: Mapping[str, Any], query: str) -> str:
    folded = query.casefold()
    for block in content.get("text_blocks", []):
        text = str(block.get("text", ""))
        if folded in text.casefold():
            return _around_match(text, folded)
    for table in content.get("tables", []):
        for row in table.get("rows", []):
            text = " | ".join(str(cell) for cell in row)
            if folded in text.casefold():
                return _around_match(text, folded)
    return ""


def _around_match(text: str, folded_query: str, maximum: int = 240) -> str:
    compact = " ".join(text.split())
    position = compact.casefold().find(folded_query)
    if len(compact) <= maximum:
        return compact
    start = max(0, position - maximum // 3)
    end = min(len(compact), start + maximum)
    prefix = "..." if start else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"
