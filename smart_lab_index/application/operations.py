"""Operational health, backup verification, and offline restore services."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smart_lab_index import __version__
from smart_lab_index.core.locking import DatabaseLease
from smart_lab_index.core.storage import SCHEMA_VERSION, KnowledgeStore, StorageError


def default_backup_path(database: str | Path) -> Path:
    source = Path(database).expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return source.parent / "backups" / f"{source.stem}-{timestamp}.db"


def backup_database(database: str | Path, output: str | Path) -> dict[str, Any]:
    source = _existing_regular(database, "active database")
    destination = _destination(output)
    if source == destination:
        raise ValueError("backup output must differ from the active database")
    if destination.exists():
        raise FileExistsError(f"backup already exists: {destination}")
    if backup_manifest_path(destination).exists():
        raise FileExistsError(
            f"backup manifest already exists: {backup_manifest_path(destination)}"
        )
    with KnowledgeStore(source) as store:
        health = store.integrity_report()
        if not health["healthy"]:
            raise StorageError(
                "active database failed integrity checks; backup was refused"
            )
        _require_backup_outside_sources(store, destination)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        os.chmod(temporary, 0o600)
        try:
            target = sqlite3.connect(temporary)
            try:
                store.connection.backup(target)
                target.execute("PRAGMA journal_mode = DELETE")
                target.commit()
            finally:
                target.close()
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    try:
        _fsync_file(temporary)
        verification = verify_backup(temporary)
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        _fsync_directory(destination.parent)
        manifest = {
            "format": "smart-lab-index-sqlite-backup",
            "format_version": 1,
            "product_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "backup_file": destination.name,
            "sha256": verification["sha256"],
            "size_bytes": verification["size_bytes"],
            "schema_version": verification["schema_version"],
        }
        manifest_path = backup_manifest_path(destination)
        _write_json_atomic(manifest_path, manifest)
        return {
            **verification,
            "path": str(destination),
            "manifest": str(manifest_path),
        }
    finally:
        temporary.unlink(missing_ok=True)


def verify_backup(
    backup: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    path = _existing_regular(backup, "backup")
    value = path.stat()
    if not stat.S_ISREG(value.st_mode):
        raise StorageError("backup is not a regular file")
    if value.st_nlink != 1:
        raise StorageError("backup must not have hard links")
    checksum = _sha256(path)
    if expected_sha256 is not None and not hmac.compare_digest(
        checksum,
        expected_sha256.strip().casefold(),
    ):
        raise StorageError("backup checksum does not match the expected SHA-256")
    uri = f"{path.as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        foreign_rows = connection.execute("PRAGMA foreign_key_check").fetchmany(101)
        applied = [
            int(row["version"])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    except sqlite3.Error as exc:
        raise StorageError("backup is not a valid LabOverlay database") from exc
    finally:
        connection.close()
    schema_version = applied[-1] if applied else 0
    compatible = applied == list(range(1, schema_version + 1)) and (
        0 < schema_version <= SCHEMA_VERSION
    )
    healthy = (
        quick_check == ["ok"]
        and not foreign_rows
        and compatible
        and journal_mode.casefold() == "delete"
    )
    if not healthy:
        raise StorageError("backup failed database integrity or compatibility checks")
    return {
        "healthy": True,
        "sha256": checksum,
        "size_bytes": value.st_size,
        "schema_version": schema_version,
        "page_count": page_count,
        "journal_mode": journal_mode,
        "foreign_key_violations": 0,
    }


def verify_backup_manifest(backup: str | Path) -> dict[str, Any]:
    path = _existing_regular(backup, "backup")
    manifest_path = _existing_regular(
        backup_manifest_path(path),
        "backup manifest",
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StorageError(f"backup manifest cannot be read: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise StorageError("backup manifest must contain a JSON object")
    if manifest.get("format") != "smart-lab-index-sqlite-backup":
        raise StorageError("backup manifest has an unknown format")
    if manifest.get("format_version") != 1:
        raise StorageError("backup manifest has an unsupported format version")
    if manifest.get("backup_file") != path.name:
        raise StorageError("backup manifest names a different backup file")
    expected = manifest.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise StorageError("backup manifest has no valid SHA-256")
    verification = verify_backup(path, expected_sha256=expected)
    if manifest.get("size_bytes") != verification["size_bytes"]:
        raise StorageError("backup manifest size does not match the backup file")
    if manifest.get("schema_version") != verification["schema_version"]:
        raise StorageError("backup manifest schema does not match the backup file")
    return {**verification, "path": str(path), "manifest": str(manifest_path)}


def restore_database(
    backup: str | Path,
    database: str | Path,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    source = _existing_regular(backup, "backup")
    destination = _destination(database)
    verification = verify_backup_manifest(source)
    if source == destination:
        raise ValueError("backup and restore destination must differ")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    safety_backup: str | None = None
    with DatabaseLease(destination):
        if destination.exists():
            if not replace:
                raise FileExistsError(
                    "restore destination exists; pass --replace for an offline restore"
                )
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safety_path = (
                destination.parent
                / "backups"
                / f"{destination.stem}-pre-restore-{timestamp}.db"
            )
            safety_backup = backup_database(destination, safety_path)["path"]

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".restore",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with (
                source.open("rb") as input_stream,
                temporary.open("wb") as output_stream,
            ):
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            os.chmod(temporary, 0o600)
            verify_backup(temporary, expected_sha256=verification["sha256"])
            Path(f"{destination}-wal").unlink(missing_ok=True)
            Path(f"{destination}-shm").unlink(missing_ok=True)
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
            _fsync_directory(destination.parent)
        finally:
            temporary.unlink(missing_ok=True)

        with KnowledgeStore(destination) as restored:
            health = restored.integrity_report()
            if not health["healthy"]:
                raise StorageError(
                    "restored database failed post-restore integrity checks"
                )
    return {
        "restored": True,
        "database": str(destination),
        "source_backup": str(source),
        "source_sha256": verification["sha256"],
        "safety_backup": safety_backup,
        "schema_version": health["schema_version"],
    }


def backup_manifest_path(backup: str | Path) -> Path:
    path = Path(backup)
    return path.with_name(f"{path.name}.manifest.json")


def _require_backup_outside_sources(store: KnowledgeStore, output: Path) -> None:
    rows = store.connection.execute("SELECT identity_json FROM source_bindings")
    for row in rows:
        identity = json.loads(row["identity_json"])
        root_value = identity.get("root")
        if not isinstance(root_value, str):
            continue
        root = Path(root_value).expanduser().resolve()
        try:
            output.relative_to(root)
        except ValueError:
            continue
        raise ValueError("backup output must be outside every read-only source root")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        payload = (
            json.dumps(
                value,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            ).encode("ascii")
            + b"\n"
        )
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _existing_regular(path: str | Path, label: str) -> Path:
    raw = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    try:
        value = raw.lstat()
    except OSError as exc:
        raise FileNotFoundError(f"{label} does not exist: {raw}") from exc
    if stat.S_ISLNK(value.st_mode):
        raise StorageError(f"{label} path must not be a symbolic link")
    if not stat.S_ISREG(value.st_mode):
        raise StorageError(f"{label} is not a regular file")
    if value.st_nlink != 1:
        raise StorageError(f"{label} must not have hard links")
    return raw.resolve(strict=True)


def _destination(path: str | Path) -> Path:
    raw = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
    if os.path.lexists(raw) and raw.is_symlink():
        raise StorageError("destination path must not be a symbolic link")
    return raw.parent.resolve() / raw.name
