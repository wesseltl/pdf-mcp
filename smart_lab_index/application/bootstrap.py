"""Explicit built-in composition root for the modular monolith."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from smart_lab_index.application.indexing import IndexingService
from smart_lab_index.application.parsing import (
    InProcessParserExecutor,
    ProcessParserExecutor,
)
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.domain import SourceDefinition
from smart_lab_index.core.events import EventBus
from smart_lab_index.core.locking import DatabaseLease
from smart_lab_index.core.modules import ModuleRegistry
from smart_lab_index.core.paths import default_database_path
from smart_lab_index.core.storage import KnowledgeStore
from smart_lab_index.modules.connectors.filesystem import (
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_TOTAL_BYTES,
    FilesystemConnector,
)
from smart_lab_index.modules.domains import GeneralLabDomain
from smart_lab_index.modules.extractors import RuleBasedExtractor, StructuredExtractor
from smart_lab_index.modules.issue_rules import (
    CalibrationDueRule,
    ConflictingLocationRule,
    MissingResponsibilityRule,
)
from smart_lab_index.modules.parsers import (
    CsvParser,
    DocxParser,
    PdfParser,
    TextParser,
    XlsxParser,
)
from smart_lab_index.modules.resolvers import (
    AliasResolver,
    IdentifierResolver,
    NormalizedNameResolver,
)


@dataclass
class SmartLabApplication:
    registry: ModuleRegistry
    store: KnowledgeStore
    indexing: IndexingService
    source: SourceDefinition
    startup_errors: dict[str, str]
    parser_isolation: dict[str, bool]
    database_lease: DatabaseLease | None = None

    @property
    def connector_module_id(self) -> str:
        return self.source.connector_module_id

    def close(self) -> None:
        self.registry.stop_all()
        self.store.close()
        if self.database_lease is not None:
            self.database_lease.close()

    def __enter__(self) -> SmartLabApplication:  # noqa: PYI034
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def build_application(
    root: str | Path,
    *,
    database: str | Path | None = None,
    source_id: str | None = None,
    policy: RuntimePolicy | None = None,
    disabled_module_ids: Iterable[str] = (),
    enabled_module_ids: Iterable[str] = (),
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    exclude_patterns: Iterable[str] = (),
    verify_unchanged_content: bool = False,
    acquire_database_lease: bool = True,
) -> SmartLabApplication:
    """Register built-ins explicitly; no dynamic imports or hidden plugin loading."""
    database = database or default_database_path()
    _validate_state_path(root, database)
    database_lease: DatabaseLease | None = None
    events = EventBus()
    effective_policy = policy or RuntimePolicy.from_env()
    registry = ModuleRegistry(policy=effective_policy, events=events)
    domain = GeneralLabDomain()
    connector = FilesystemConnector()
    source = connector.source(
        root,
        source_id=source_id,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        exclude_patterns=tuple(exclude_patterns),
        verify_unchanged_content=verify_unchanged_content,
    )
    modules = (
        domain,
        connector,
        PdfParser(),
        DocxParser(),
        XlsxParser(),
        CsvParser(),
        TextParser(),
        StructuredExtractor(domain.structured_rules()),
        RuleBasedExtractor(domain.text_relationship_rules()),
        IdentifierResolver(),
        AliasResolver(),
        NormalizedNameResolver(),
        ConflictingLocationRule(),
        MissingResponsibilityRule(),
        CalibrationDueRule(),
    )
    disabled = set(disabled_module_ids)
    enabled_overrides = set(enabled_module_ids)
    default_disabled = {"issue.missing_responsibility"}
    for module in modules:
        module_id = module.manifest.module_id
        enabled = module_id not in disabled and (
            module_id not in default_disabled or module_id in enabled_overrides
        )
        registry.register(module, enabled=enabled)
    startup_errors = registry.start_all()
    store: KnowledgeStore | None = None
    try:
        database_lease = (
            DatabaseLease(database).acquire() if acquire_database_lease else None
        )
        store = KnowledgeStore(database)
        store.recover_interrupted_runs()
        store.sync_modules(registry.snapshot())
        if effective_policy.parser_isolation:
            parser_executor = ProcessParserExecutor(effective_policy)
            parser_isolation = parser_executor.status.to_dict()
        else:
            parser_executor = InProcessParserExecutor()
            parser_isolation = {
                "process_boundary": False,
                "wall_clock_timeout": False,
                "serialized_output_limit": False,
                "network_audit_guard": False,
                "cpu_limit": False,
                "memory_limit": False,
            }
        return SmartLabApplication(
            registry=registry,
            store=store,
            indexing=IndexingService(
                registry,
                store,
                events,
                parser_executor=parser_executor,
            ),
            source=source,
            startup_errors=startup_errors,
            parser_isolation=parser_isolation,
            database_lease=database_lease,
        )
    except Exception:
        registry.stop_all()
        if store is not None:
            store.close()
        if database_lease is not None:
            database_lease.close()
        raise


def _validate_state_path(root: str | Path, database: str | Path) -> None:
    if str(database) == ":memory:":
        return
    source_root = Path(root).expanduser().resolve()
    state_path = Path(database).expanduser().resolve()
    try:
        state_path.relative_to(source_root)
    except ValueError:
        return
    raise ValueError("the Core database must be outside the read-only source root")
