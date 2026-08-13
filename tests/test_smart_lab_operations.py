"""Production operation tests for leases, recovery, backup, and restore."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from smart_lab_index.application import (
    backup_database,
    build_application,
    restore_database,
    verify_backup,
    verify_backup_manifest,
)
from smart_lab_index.cli import main as cli_main
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.domain import IndexRunStatus
from smart_lab_index.core.locking import DatabaseBusyError, DatabaseLease
from smart_lab_index.core.storage import KnowledgeStore, StorageError


class SmartLabOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        (self.root / "note.txt").write_text(
            "Freezer-001 located in Room A-101.",
            encoding="utf-8",
        )
        self.database = Path(self.temporary.name) / "state" / "index.db"
        with build_application(
            self.root,
            database=self.database,
            policy=RuntimePolicy(no_egress=True, parser_isolation=False),
        ) as application:
            result = application.indexing.run(application.source)
        self.assertEqual(result.status, IndexRunStatus.COMPLETED)

    def test_database_lease_rejects_a_second_writer_and_releases_cleanly(self) -> None:
        first = DatabaseLease(self.database).acquire()
        try:
            with self.assertRaises(DatabaseBusyError):
                DatabaseLease(self.database).acquire()
        finally:
            first.close()
        with DatabaseLease(self.database):
            pass

    def test_backup_manifest_verification_and_restore_preserve_knowledge(self) -> None:
        backup = Path(self.temporary.name) / "backups" / "index.db"
        result = backup_database(self.database, backup)
        self.assertTrue(result["healthy"])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        verified = verify_backup_manifest(backup)
        self.assertEqual(verified["sha256"], result["sha256"])
        self.assertEqual(verified["journal_mode"], "delete")

        restored = Path(self.temporary.name) / "restored" / "index.db"
        restore_database(backup, restored)
        with KnowledgeStore(restored) as store:
            self.assertEqual(store.summary()["active_assertions"], 1)
            self.assertTrue(store.integrity_report()["healthy"])

    def test_checksum_tampering_and_source_root_backup_are_rejected(self) -> None:
        backup = Path(self.temporary.name) / "backup.db"
        result = backup_database(self.database, backup)
        corrupt = Path(self.temporary.name) / "corrupt.db"
        corrupt.write_bytes(backup.read_bytes() + b"tampered")
        with self.assertRaisesRegex(StorageError, "checksum"):
            verify_backup(corrupt, expected_sha256=result["sha256"])

        with self.assertRaisesRegex(ValueError, "outside every read-only source"):
            backup_database(self.database, self.root / "forbidden-backup.db")
        self.assertFalse((self.root / "forbidden-backup.db").exists())

    def test_replace_restore_creates_a_verified_safety_backup(self) -> None:
        backup = Path(self.temporary.name) / "backup.db"
        backup_database(self.database, backup)
        result = restore_database(backup, self.database, replace=True)
        self.assertIsNotNone(result["safety_backup"])
        self.assertTrue(Path(result["safety_backup"]).is_file())
        self.assertTrue(verify_backup_manifest(result["safety_backup"])["healthy"])

    def test_restore_requires_the_original_manifest(self) -> None:
        backup = Path(self.temporary.name) / "backup.db"
        result = backup_database(self.database, backup)
        Path(result["manifest"]).unlink()

        restored = Path(self.temporary.name) / "restored" / "index.db"
        with self.assertRaisesRegex(
            FileNotFoundError, "backup manifest does not exist"
        ):
            restore_database(backup, restored)
        self.assertFalse(restored.exists())

    def test_health_command_bounds_a_corrupt_database_failure(self) -> None:
        corrupt = Path(self.temporary.name) / "corrupt-index.db"
        corrupt.write_bytes(b"not a sqlite database")
        errors = StringIO()

        with redirect_stderr(errors):
            result = cli_main(["health", "--database", str(corrupt)])

        self.assertEqual(result, 2)
        self.assertIn("laboverlay:", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

    def test_exclusive_startup_recovers_interrupted_runs(self) -> None:
        with KnowledgeStore(self.database) as store:
            run_id = store.begin_index_run(
                source_id="interrupted-source",
                module_snapshot=(),
                runtime_policy={"no_egress": True},
                source_configuration_hash="interrupted",
            )
            self.assertEqual(store.summary()["latest_run"]["status"], "RUNNING")

        with build_application(
            self.root,
            database=self.database,
            policy=RuntimePolicy(no_egress=True, parser_isolation=False),
        ) as application:
            latest = application.store.summary()["latest_run"]
            audit = application.store.connection.execute(
                "SELECT detail_json FROM audit_events "
                "WHERE event_type='INTERRUPTED_RUNS_RECOVERED'"
            ).fetchone()

        self.assertEqual(latest["index_run_id"], run_id)
        self.assertEqual(latest["status"], "FAILED")
        self.assertEqual(json.loads(audit["detail_json"]), {"count": 1})


if __name__ == "__main__":
    unittest.main()
