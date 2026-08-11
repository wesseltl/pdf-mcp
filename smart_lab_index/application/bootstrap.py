"""Explicit built-in composition root for the modular monolith."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from smart_lab_index.application.indexing import IndexingService
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.domain import SourceDefinition
from smart_lab_index.core.events import EventBus
from smart_lab_index.core.modules import ModuleRegistry
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

    @property
    def connector_module_id(self) -> str:
        return self.source.connector_module_id

    def close(self) -> None:
        self.registry.stop_all()
        self.store.close()

    def __enter__(self) -> SmartLabApplication:  # noqa: PYI034
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def build_application(
    root: str | Path,
    *,
    database: str | Path = "~/.smart-lab-index/index.db",
    source_id: str | None = None,
    policy: RuntimePolicy | None = None,
    disabled_module_ids: Iterable[str] = (),
    enabled_module_ids: Iterable[str] = (),
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    exclude_patterns: Iterable[str] = (),
) -> SmartLabApplication:
    """Register built-ins explicitly; no dynamic imports or hidden plugin loading."""
    _validate_state_path(root, database)
    events = EventBus()
    registry = ModuleRegistry(policy=policy or RuntimePolicy.from_env(), events=events)
    domain = GeneralLabDomain()
    connector = FilesystemConnector()
    source = connector.source(
        root,
        source_id=source_id,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        exclude_patterns=tuple(exclude_patterns),
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
    store = KnowledgeStore(database)
    store.sync_modules(registry.snapshot())
    return SmartLabApplication(
        registry=registry,
        store=store,
        indexing=IndexingService(registry, store, events),
        source=source,
        startup_errors=startup_errors,
    )


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
