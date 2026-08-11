"""Focused tests for Smart Lab Index Core infrastructure."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest import mock

from smart_lab_index.core.config import ConfigurationError, RuntimePolicy
from smart_lab_index.core.domain import (
    AssertionStatus,
    EntityType,
    IndexRunStatus,
    SourceRecord,
)
from smart_lab_index.core.events import Event, EventBus, EventType
from smart_lab_index.core.modules import (
    FileAccess,
    ModuleCapability,
    ModuleDependency,
    ModuleDependencyError,
    ModuleError,
    ModuleHealthState,
    ModuleLifecycleState,
    ModuleManifest,
    ModuleRegistry,
    ModuleType,
    NetworkAccess,
    NoEgressViolation,
    SmartLabModule,
)
from smart_lab_index.core.storage import KnowledgeStore, StorageError


class DummyModule(SmartLabModule):
    """Small observable module used to test Core lifecycle behavior."""

    def __init__(
        self,
        module_id: str,
        *,
        capabilities: tuple[ModuleCapability, ...] | None = None,
        dependencies: tuple[ModuleDependency, ...] = (),
        network_access: NetworkAccess = NetworkAccess.NONE,
        telemetry: bool = False,
        automatic_downloads: bool = False,
        configuration: Mapping[str, Any] | None = None,
        configuration_schema: Mapping[str, Any] | None = None,
        credentials_required: tuple[str, ...] = (),
        lifecycle_log: list[str] | None = None,
    ) -> None:
        self.manifest = ModuleManifest(
            module_id=module_id,
            name=module_id,
            version="1.0.0",
            module_type=ModuleType.SEARCH,
            description="Test-only module",
            dependencies=dependencies,
            capabilities=capabilities
            or (ModuleCapability(f"{module_id}.capability"),),
            configuration_schema=configuration_schema
            or {"type": "object", "additionalProperties": False},
            network_access=network_access,
            file_access=FileAccess.NONE,
            telemetry=telemetry,
            automatic_downloads=automatic_downloads,
            credentials_required=credentials_required,
        )
        self.lifecycle_log = lifecycle_log if lifecycle_log is not None else []
        super().__init__(configuration)

    def initialize(self, context):  # type: ignore[no-untyped-def]
        self.lifecycle_log.append(f"{self.manifest.module_id}:initialize")
        super().initialize(context)

    def start(self) -> None:
        self.lifecycle_log.append(f"{self.manifest.module_id}:start")
        super().start()

    def stop(self) -> None:
        self.lifecycle_log.append(f"{self.manifest.module_id}:stop")
        super().stop()


class ModuleRegistryTests(unittest.TestCase):
    def test_duplicate_module_ids_are_rejected(self):
        registry = ModuleRegistry()
        registry.register(DummyModule("test.duplicate"))

        with self.assertRaisesRegex(ModuleError, "already installed"):
            registry.register(DummyModule("test.duplicate"))

    def test_dependencies_control_start_order_and_disable_order(self):
        lifecycle_log: list[str] = []
        provider = DummyModule("test.provider", lifecycle_log=lifecycle_log)
        dependent = DummyModule(
            "test.dependent",
            dependencies=(ModuleDependency(module_id="test.provider"),),
            lifecycle_log=lifecycle_log,
        )
        registry = ModuleRegistry()
        registry.register(dependent)
        registry.register(provider)
        lifecycle_log.clear()

        self.assertEqual(registry.start_all(), {})
        self.assertEqual(
            lifecycle_log,
            ["test.provider:start", "test.dependent:start"],
        )
        states = {item["module_id"]: item for item in registry.snapshot()}
        self.assertEqual(
            states["test.provider"]["lifecycle"],
            ModuleLifecycleState.STARTED.value,
        )
        self.assertEqual(
            states["test.dependent"]["health"],
            ModuleHealthState.HEALTHY.value,
        )

        with self.assertRaisesRegex(ModuleDependencyError, "test.dependent"):
            registry.disable("test.provider")

        registry.disable("test.dependent")
        registry.disable("test.provider")
        self.assertEqual(
            lifecycle_log[-2:],
            ["test.dependent:stop", "test.provider:stop"],
        )
        self.assertEqual(registry.enabled_modules(), [])

    def test_missing_dependency_prevents_start(self):
        registry = ModuleRegistry()
        registry.register(
            DummyModule(
                "test.consumer",
                dependencies=(ModuleDependency(module_id="test.missing"),),
            )
        )

        errors = registry.start_all()

        self.assertEqual(errors, {"test.consumer": "test.missing"})
        self.assertEqual(registry.enabled_modules(), [])
        state = registry.snapshot()[0]
        self.assertEqual(state["health"], ModuleHealthState.ERROR.value)
        self.assertEqual(state["health_detail"], "test.missing")

    def test_capability_provider_cannot_be_disabled_without_an_alternative(self):
        capability = ModuleCapability("test.shared_capability", "1.0.0")
        provider = DummyModule("test.provider", capabilities=(capability,))
        dependent = DummyModule(
            "test.dependent",
            dependencies=(
                ModuleDependency(
                    capability="test.shared_capability",
                    minimum_version="1.0.0",
                ),
            ),
        )
        registry = ModuleRegistry()
        registry.register(provider)
        registry.register(dependent)
        registry.start_all()

        with self.assertRaisesRegex(ModuleDependencyError, "test.dependent"):
            registry.disable("test.provider")

        alternative = DummyModule("test.alternative", capabilities=(capability,))
        registry.register(alternative)
        registry.start_all()
        registry.disable("test.provider")
        self.assertEqual(
            {module.manifest.module_id for module in registry.enabled_modules()},
            {"test.alternative", "test.dependent"},
        )

    def test_no_egress_blocks_external_network_but_allows_loopback(self):
        registry = ModuleRegistry(policy=RuntimePolicy(no_egress=True))
        external = DummyModule(
            "test.external",
            network_access=NetworkAccess.INTERNET,
        )
        loopback = DummyModule(
            "test.loopback",
            network_access=NetworkAccess.LOOPBACK,
        )
        telemetry = DummyModule("test.telemetry", telemetry=True)
        downloads = DummyModule("test.downloads", automatic_downloads=True)

        registry.register(external)
        registry.register(loopback)
        registry.register(telemetry)
        registry.register(downloads)
        self.assertEqual(registry.start_all(), {})

        enabled_ids = {
            module.manifest.module_id for module in registry.enabled_modules()
        }
        self.assertEqual(enabled_ids, {"test.loopback"})
        states = {item["module_id"]: item for item in registry.snapshot()}
        self.assertFalse(states["test.external"]["enabled"])
        self.assertFalse(states["test.telemetry"]["enabled"])
        self.assertFalse(states["test.downloads"]["enabled"])
        self.assertEqual(
            states["test.external"]["lifecycle"],
            ModuleLifecycleState.BLOCKED.value,
        )
        self.assertIn("NO_EGRESS", states["test.external"]["health_detail"])
        self.assertEqual(
            states["test.loopback"]["health"],
            ModuleHealthState.HEALTHY.value,
        )
        self.assertNotIn("test.external:initialize", external.lifecycle_log)
        with self.assertRaises(NoEgressViolation):
            registry.enable("test.external")

    def test_invalid_no_egress_value_fails_closed(self):
        with self.assertRaises(ConfigurationError):
            RuntimePolicy.from_env({"SMART_LAB_INDEX_NO_EGRESS": "tru"})

    def test_non_finite_parser_timeout_fails_closed(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                RuntimePolicy.from_env({
                    "SMART_LAB_INDEX_PARSER_TIMEOUT_SECONDS": value,
                })
        with self.assertRaises(ConfigurationError):
            RuntimePolicy(parser_timeout_seconds=float("nan"))

    def test_snapshot_redacts_declared_and_conventionally_named_secrets(self):
        schema = {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string"},
                "client_id": {"type": "string"},
                "api_token": {"type": "string"},
                "nested": {
                    "type": "object",
                    "properties": {"password": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        }
        module = DummyModule(
            "test.configured",
            configuration={
                "endpoint": "http://127.0.0.1:11434",
                "client_id": "private-client",
                "api_token": "private-token",
                "nested": {"password": "private-password"},
            },
            configuration_schema=schema,
            credentials_required=("client_id",),
        )
        registry = ModuleRegistry()
        registry.register(module)
        registry.start_all()

        snapshot = registry.snapshot()[0]
        self.assertEqual(
            snapshot["configuration"],
            {
                "endpoint": "http://127.0.0.1:11434",
                "client_id": "[REDACTED]",
                "api_token": "[REDACTED]",
                "nested": {"password": "[REDACTED]"},
            },
        )
        serialized = json.dumps(snapshot)
        self.assertNotIn("private-client", serialized)
        self.assertNotIn("private-token", serialized)
        self.assertNotIn("private-password", serialized)
        self.assertEqual(len(snapshot["configuration_hash"]), 64)

        second_registry = ModuleRegistry()
        second_registry.register(DummyModule(
            "test.configured",
            configuration={
                "endpoint": "http://127.0.0.1:11434",
                "client_id": "different-client",
                "api_token": "different-token",
                "nested": {"password": "different-password"},
            },
            configuration_schema=schema,
            credentials_required=("client_id",),
        ))
        second_registry.start_all()
        self.assertEqual(
            second_registry.snapshot()[0]["configuration_hash"],
            snapshot["configuration_hash"],
        )

    def test_module_start_errors_do_not_persist_exception_secrets(self):
        secret = "canary-module-secret"
        module = DummyModule("test.failing_start")
        registry = ModuleRegistry()
        registry.register(module)
        with mock.patch.object(
            module,
            "start",
            side_effect=RuntimeError(f"failed with {secret}"),
        ):
            errors = registry.start_all()

        serialized = json.dumps({"errors": errors, "snapshot": registry.snapshot()})
        self.assertNotIn(secret, serialized)
        self.assertIn("RuntimeError: module start failed", serialized)


class EventBusTests(unittest.TestCase):
    def test_handler_failure_does_not_prevent_later_handlers(self):
        event_bus = EventBus()
        received: list[Event] = []

        def fail(_event: Event) -> None:
            raise RuntimeError("hook failed")

        event_bus.subscribe(EventType.ENTITY_CREATED, "test.failing", fail)
        event_bus.subscribe(EventType.ENTITY_CREATED, "test.observer", received.append)
        event = Event(
            event_type=EventType.ENTITY_CREATED,
            payload={"entity_id": "entity-1"},
            source_module_id="test.source",
        )

        failures = event_bus.emit(event)

        self.assertEqual(received, [event])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].owner, "test.failing")
        self.assertEqual(failures[0].error, "RuntimeError: event handler failed")


class KnowledgeStoreTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX mode checks are not portable to Windows")
    def test_state_directory_and_database_are_private_and_hard_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_directory = Path(temporary_directory, "private-state")
            database = state_directory / "index.db"
            with KnowledgeStore(database):
                self.assertEqual(stat.S_IMODE(state_directory.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)

            linked_database = Path(temporary_directory, "linked.db")
            os.link(database, linked_database)
            with self.assertRaisesRegex(StorageError, "must not have hard links"):
                KnowledgeStore(database)

            linked_database.unlink()
            symlinked_database = Path(temporary_directory, "symlinked.db")
            symlinked_database.symlink_to(database)
            with self.assertRaisesRegex(StorageError, "symbolic link"):
                KnowledgeStore(symlinked_database)

    def test_core_records_survive_reopening_and_keep_provenance(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "smart-lab-index.db"
            source = SourceRecord(
                external_id="equipment.xlsx",
                source_id="sample-lab",
                name="equipment.xlsx",
                path="equipment.xlsx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                modified_at="2026-08-11T12:00:00+00:00",
                size_bytes=128,
                checksum="sha256-equipment-v1",
                change_token="sha256-equipment-v1",
                content_ref="equipment.xlsx",
                metadata={"relative_path": "equipment.xlsx"},
                permission_metadata={"mode": "0444"},
            )
            provenance = {
                "source_external_id": source.external_id,
                "locator": {"sheet": "Assets", "row": 2},
            }

            with KnowledgeStore(database) as store:
                run_id = store.begin_index_run(
                    source_id=source.source_id,
                    module_snapshot=(),
                )
                source_record_id, source_created = store.upsert_source(
                    source,
                    connector_module_id="connector.filesystem",
                    index_run_id=run_id,
                )
                freezer = store.create_entity(
                    entity_type=EntityType.ASSET,
                    canonical_name="Freezer-001",
                    normalized_name="freezer-001",
                    subtype="FREEZER",
                    identifier="Freezer-001",
                    metadata={"site": "Site North"},
                )
                room = store.create_entity(
                    entity_type=EntityType.LOCATION,
                    canonical_name="Room A-101",
                    normalized_name="room a-101",
                    subtype="ROOM",
                    identifier="Room A-101",
                )
                store.add_alias(
                    entity_id=freezer.entity_id,
                    alias="Freezer One",
                    normalized_alias="freezer one",
                    source_record_id=source_record_id,
                )
                assertion_id, assertion_created = store.create_assertion(
                    subject_entity_id=freezer.entity_id,
                    predicate="located_in",
                    object_entity_id=room.entity_id,
                    literal=None,
                    source_record_id=source_record_id,
                    provenance=provenance,
                    confidence=0.99,
                    extraction_method="structured_columns",
                    status=AssertionStatus.DIRECT,
                    extraction_module_id="relationship.structured",
                    extraction_module_version="1.0.0",
                    index_run_id=run_id,
                )
                duplicate_id, duplicate_created = store.create_assertion(
                    subject_entity_id=freezer.entity_id,
                    predicate="located_in",
                    object_entity_id=room.entity_id,
                    literal=None,
                    source_record_id=source_record_id,
                    provenance=provenance,
                    confidence=0.99,
                    extraction_method="structured_columns",
                    status=AssertionStatus.DIRECT,
                    extraction_module_id="relationship.structured",
                    extraction_module_version="1.0.0",
                    index_run_id=run_id,
                )
                issue_id, issue_created = store.create_issue(
                    code="CONFLICTING_LOCATION",
                    severity="ERROR",
                    entity_id=freezer.entity_id,
                    source_record_id=source_record_id,
                    assertion_ids=[assertion_id],
                    evidence={"observed_locations": ["Room A-101", "Room A-102"]},
                    rule_module_id="issue.conflicting_location",
                    rule_version="1.0.0",
                    fingerprint="conflicting-location:freezer-001",
                    index_run_id=run_id,
                )
                duplicate_issue_id, duplicate_issue_created = store.create_issue(
                    code="CONFLICTING_LOCATION",
                    severity="ERROR",
                    entity_id=freezer.entity_id,
                    source_record_id=source_record_id,
                    assertion_ids=[assertion_id],
                    evidence={"observed_locations": ["Room A-101", "Room A-102"]},
                    rule_module_id="issue.conflicting_location",
                    rule_version="1.0.0",
                    fingerprint="conflicting-location:freezer-001",
                    index_run_id=run_id,
                )
                store.finish_index_run(
                    run_id,
                    status=IndexRunStatus.COMPLETED,
                    stats={"entities": 2, "assertions": 1, "issues": 1},
                )

                self.assertTrue(source_created)
                self.assertTrue(assertion_created)
                self.assertEqual(duplicate_id, assertion_id)
                self.assertFalse(duplicate_created)
                self.assertTrue(issue_created)
                self.assertEqual(duplicate_issue_id, issue_id)
                self.assertFalse(duplicate_issue_created)

            with KnowledgeStore(database) as reopened:
                self.assertEqual(
                    reopened.source_records(source.source_id),
                    {source.external_id: source},
                )
                self.assertEqual(reopened.get_entity(freezer.entity_id), freezer)
                self.assertEqual(
                    reopened.find_entity_by_identifier("ASSET", "Freezer-001"),
                    freezer,
                )
                self.assertEqual(
                    reopened.find_entity_by_alias("ASSET", "freezer one"),
                    freezer,
                )
                self.assertEqual(
                    reopened.find_entity_by_normalized_name("LOCATION", "room a-101"),
                    room,
                )

                assertions = reopened.list_active_assertions("located_in")
                self.assertEqual(len(assertions), 1)
                self.assertEqual(assertions[0].assertion_id, assertion_id)
                self.assertEqual(assertions[0].object_entity_id, room.entity_id)
                self.assertEqual(assertions[0].provenance, provenance)

                issues = reopened.list_issues(status="OPEN")
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]["issue_id"], issue_id)
                self.assertEqual(issues[0]["assertion_ids"], [assertion_id])
                self.assertEqual(
                    issues[0]["evidence"],
                    {"observed_locations": ["Room A-101", "Room A-102"]},
                )

                summary = reopened.summary()
                self.assertEqual(summary["sources"], 1)
                self.assertEqual(summary["entities"], 2)
                self.assertEqual(summary["active_assertions"], 1)
                self.assertEqual(summary["open_issues"], 1)
                self.assertEqual(
                    summary["latest_run"]["status"],
                    IndexRunStatus.COMPLETED.value,
                )
                self.assertEqual(
                    summary["latest_run"]["stats"],
                    {"entities": 2, "assertions": 1, "issues": 1},
                )


if __name__ == "__main__":
    unittest.main()
