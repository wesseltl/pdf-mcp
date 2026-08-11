"""Focused tests for the read-only filesystem connector."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from smart_lab_index.core.domain import DiscoveryChange, OperationCancelled
from smart_lab_index.modules.connectors.filesystem import FilesystemConnector


class FilesystemConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @staticmethod
    def _sources_by_id(batch):
        return {source.record.external_id: source for source in batch.sources}

    def test_recursive_discovery_is_read_only_and_filters_files(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        note = self.root / "note.txt"
        assets = nested / "assets.csv"
        note.write_bytes(b"local notes\n")
        assets.write_bytes(b"asset_id,location\nFreezer-001,Room A-101\n")
        (self.root / "ignored.json").write_bytes(b"{}")
        (self.root / ".hidden.txt").write_bytes(b"hidden")
        original_contents = {note: note.read_bytes(), assets: assets.read_bytes()}
        opened_modes: list[str] = []

        def tracking_open(path, mode="r", *args, **kwargs):
            opened_modes.append(mode)
            return open(path, mode, *args, **kwargs)

        connector = FilesystemConnector(open_file=tracking_open)
        definition = connector.source(self.root, source_id="lab-alpha")
        batch = connector.discover(definition, {})

        sources = self._sources_by_id(batch)
        self.assertTrue(batch.complete)
        self.assertFalse(batch.failures)
        self.assertEqual(set(sources), {"note.txt", "nested/assets.csv"})
        self.assertTrue(all(item.change is DiscoveryChange.NEW for item in sources.values()))
        self.assertEqual(opened_modes, ["rb", "rb"])
        self.assertEqual(note.read_bytes(), original_contents[note])
        self.assertEqual(assets.read_bytes(), original_contents[assets])
        self.assertEqual(sources["nested/assets.csv"].record.path, "nested/assets.csv")
        self.assertEqual(sources["nested/assets.csv"].record.source_id, "lab-alpha")

    def test_checksum_drives_unchanged_and_changed_with_restored_mtime(self) -> None:
        path = self.root / "sample.txt"
        path.write_bytes(b"alpha")
        connector = FilesystemConnector()
        definition = connector.source(self.root)

        initial = connector.discover(definition, {})
        initial_source = initial.sources[0]
        prior = {initial_source.record.external_id: initial_source.record}
        unchanged = connector.discover(definition, prior)

        self.assertIs(initial_source.change, DiscoveryChange.NEW)
        self.assertIs(unchanged.sources[0].change, DiscoveryChange.UNCHANGED)

        original_stat = path.stat()
        path.write_bytes(b"bravo")
        os.utime(
            path,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        changed = connector.discover(definition, prior)
        changed_record = changed.sources[0].record

        self.assertIs(changed.sources[0].change, DiscoveryChange.CHANGED)
        self.assertEqual(changed_record.size_bytes, initial_source.record.size_bytes)
        self.assertEqual(changed_record.modified_at, initial_source.record.modified_at)
        self.assertNotEqual(changed_record.checksum, initial_source.record.checksum)
        self.assertNotEqual(changed_record.change_token, initial_source.record.change_token)

    def test_inaccessible_file_failure_is_isolated(self) -> None:
        (self.root / "blocked.txt").write_bytes(b"not readable through boundary")
        (self.root / "readable.txt").write_bytes(b"available")

        def selective_open(path, mode="r", *args, **kwargs):
            if Path(path).name == "blocked.txt":
                raise PermissionError("denied by injected file boundary")
            return open(path, mode, *args, **kwargs)

        connector = FilesystemConnector(open_file=selective_open)
        definition = connector.source(self.root)
        batch = connector.discover(definition, {})

        self.assertTrue(batch.complete)
        self.assertEqual(
            [source.record.external_id for source in batch.sources],
            ["readable.txt"],
        )
        self.assertEqual(len(batch.failures), 1)
        self.assertEqual(batch.failures[0].external_id, "blocked.txt")
        self.assertIn("PermissionError", batch.failures[0].error)
        self.assertIn("injected file boundary", batch.failures[0].error)

    def test_open_content_enforces_ownership_containment_and_symlink_rules(self) -> None:
        path = self.root / "document.txt"
        path.write_bytes(b"source bytes")
        connector = FilesystemConnector()
        definition = connector.source(self.root, source_id="source-a")
        record = connector.discover(definition, {}).sources[0].record

        with connector.open_content(definition, record) as stream:
            self.assertEqual(stream.read(), b"source bytes")
        self.assertTrue(stream.closed)

        with (
            self.assertRaisesRegex(PermissionError, "different connector"),
            connector.open_content(definition, replace(record, source_id="source-b")),
        ):
            pass

        with tempfile.TemporaryDirectory() as outside_temp:
            outside = Path(outside_temp) / "outside.txt"
            outside.write_bytes(b"outside")
            with (
                self.assertRaisesRegex(PermissionError, "escapes configured root"),
                connector.open_content(
                    definition,
                    replace(record, content_ref=str(outside)),
                ),
            ):
                pass

        link = self.root / "document-link.txt"
        link.symlink_to(path)
        with (
            self.assertRaisesRegex(PermissionError, "symbolic-link"),
            connector.open_content(definition, replace(record, content_ref=str(link))),
        ):
            pass

        path.write_bytes(b"changed after discovery")
        with (
            self.assertRaisesRegex(OSError, "changed after discovery"),
            connector.open_content(definition, record),
        ):
            pass

    def test_root_stat_failure_marks_scan_incomplete(self) -> None:
        def inaccessible_stat(_path):
            raise PermissionError("root cannot be inspected")

        connector = FilesystemConnector(stat_file=inaccessible_stat)
        definition = connector.source(self.root)
        batch = connector.discover(definition, {})

        self.assertFalse(batch.complete)
        self.assertFalse(batch.sources)
        self.assertEqual(len(batch.failures), 1)
        self.assertEqual(batch.failures[0].external_id, ".")
        self.assertIn("root cannot be inspected", batch.failures[0].error)

    def test_walk_error_marks_scan_incomplete_and_preserves_partial_results(self) -> None:
        visible = self.root / "visible.txt"
        visible.write_bytes(b"visible")
        restricted = self.root / "restricted"

        def incomplete_walk(root, *, topdown, onerror, followlinks):
            self.assertTrue(topdown)
            self.assertFalse(followlinks)
            onerror(PermissionError(13, "permission denied", str(restricted)))
            yield str(root), [], [visible.name]

        connector = FilesystemConnector()
        definition = connector.source(self.root)
        with mock.patch(
            "smart_lab_index.modules.connectors.filesystem.os.walk",
            new=incomplete_walk,
        ):
            batch = connector.discover(definition, {})

        self.assertFalse(batch.complete)
        self.assertEqual(
            [source.record.external_id for source in batch.sources],
            ["visible.txt"],
        )
        self.assertEqual(len(batch.failures), 1)
        self.assertEqual(batch.failures[0].external_id, "restricted")
        self.assertIn("PermissionError", batch.failures[0].error)

    def test_escaping_symlink_keeps_lexical_failure_id_for_deletion_safety(self) -> None:
        path = self.root / "document.txt"
        path.write_bytes(b"original")
        connector = FilesystemConnector()
        definition = connector.source(self.root)
        initial = connector.discover(definition, {})
        previous = {initial.sources[0].record.external_id: initial.sources[0].record}

        with tempfile.TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory, "outside.txt")
            outside.write_bytes(b"outside")
            path.unlink()
            path.symlink_to(outside)
            batch = connector.discover(definition, previous)

        self.assertTrue(batch.complete)
        self.assertEqual(batch.sources, ())
        self.assertEqual(batch.failures[0].external_id, "document.txt")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO test requires POSIX mkfifo")
    def test_special_files_fail_without_blocking(self) -> None:
        fifo = self.root / "stream.txt"
        os.mkfifo(fifo)
        connector = FilesystemConnector()
        definition = connector.source(self.root)

        batch = connector.discover(definition, {})

        self.assertTrue(batch.complete)
        self.assertEqual(batch.sources, ())
        self.assertEqual(batch.failures[0].external_id, "stream.txt")
        self.assertIn("not a regular file", batch.failures[0].error)

    def test_scope_limit_fails_closed_before_file_content_is_read(self) -> None:
        for index in range(3):
            (self.root / f"document-{index}.txt").write_bytes(b"content")
        opened = mock.Mock(wraps=open)
        connector = FilesystemConnector(open_file=opened)
        definition = connector.source(self.root, max_files=2)

        batch = connector.discover(definition, {})

        self.assertFalse(batch.complete)
        self.assertFalse(batch.sources)
        self.assertTrue(batch.metadata["blocked"])
        self.assertEqual(batch.metadata["planned_files"], 3)
        self.assertIn("file count", batch.failures[0].error)
        opened.assert_not_called()

    def test_file_changed_after_preflight_is_isolated_before_hashing(self) -> None:
        source = self.root / "document.txt"
        source.write_bytes(b"first")
        changed = False

        def mutate_then_open(path, mode):
            nonlocal changed
            if not changed:
                changed = True
                source.write_bytes(b"replacement content")
            return open(path, mode)

        connector = FilesystemConnector(open_file=mutate_then_open)
        definition = connector.source(self.root)

        batch = connector.discover(definition, {})

        self.assertTrue(batch.complete)
        self.assertEqual(batch.sources, ())
        self.assertEqual(batch.failures[0].external_id, "document.txt")
        self.assertIn("changed after preflight", batch.failures[0].error)

    def test_exclusions_progress_and_cooperative_cancellation(self) -> None:
        (self.root / "keep.txt").write_bytes(b"keep")
        (self.root / "ignore.txt").write_bytes(b"ignore")
        connector = FilesystemConnector()
        definition = connector.source(
            self.root,
            exclude_patterns=("ignore.*",),
        )
        progress = []

        batch = connector.discover(definition, {}, progress=progress.append)

        self.assertEqual([item.record.external_id for item in batch.sources], ["keep.txt"])
        self.assertEqual({item["phase"] for item in progress}, {"PREFLIGHT", "DISCOVERY"})
        with self.assertRaises(OperationCancelled):
            connector.discover(definition, {}, should_cancel=lambda: True)

    @unittest.skipUnless(os.name == "posix", "POSIX ownership test")
    def test_permission_metadata_identifies_owner_group_and_access_model(self) -> None:
        (self.root / "document.txt").write_bytes(b"content")
        connector = FilesystemConnector()
        definition = connector.source(self.root)

        permissions = connector.discover(definition, {}).sources[0].record.permission_metadata

        self.assertEqual(permissions["permission_model"], "POSIX_MODE")
        self.assertIn("name", permissions["owner"])
        self.assertIn("name", permissions["group"])
        self.assertFalse(permissions["acl_captured"])


if __name__ == "__main__":
    unittest.main()
