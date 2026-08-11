"""Deterministic, generation-aware, failure-isolated indexing orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from smart_lab_index import CORE_API_VERSION
from smart_lab_index.core.domain import (
    AssertionRecord,
    DiscoveryBatch,
    DiscoveryFailure,
    DocumentContent,
    EntityCandidate,
    EntityRecord,
    EntityReference,
    ExtractionResult,
    IndexRunStatus,
    OperationCancelled,
    Provenance,
    SourceDefinition,
    SourceRecord,
)
from smart_lab_index.core.events import Event, EventBus, EventType
from smart_lab_index.core.modules import (
    ConnectorModule,
    EntityRepository,
    ExtractorModule,
    IssueRepository,
    IssueRuleModule,
    ModuleRegistry,
    ModuleType,
    ParserModule,
    ResolverModule,
)
from smart_lab_index.core.normalization import normalize_name
from smart_lab_index.core.storage import KnowledgeStore


@dataclass(frozen=True)
class IndexRunResult:
    index_run_id: str
    status: IndexRunStatus
    stats: dict[str, int]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_run_id": self.index_run_id,
            "status": self.status.value,
            "stats": dict(self.stats),
            "errors": list(self.errors),
        }


class ModuleExecutionError(RuntimeError):
    def __init__(self, module_id: str, operation: str, cause: BaseException) -> None:
        self.module_id = module_id
        self.operation = operation
        self.cause_type = type(cause).__name__
        super().__init__(f"{module_id} {operation} failed ({self.cause_type})")


class _EntityReadRepository(EntityRepository):
    """Narrow facade: modules cannot reach Core write methods or the SQLite connection."""

    __slots__ = ("__store",)

    def __init__(self, store: KnowledgeStore) -> None:
        self.__store = store

    def find_entity_by_identifier(
        self,
        entity_type: str,
        identifier: str,
    ) -> EntityRecord | None:
        return self.__store.find_entity_by_identifier(entity_type, identifier)

    def find_entity_by_alias(self, entity_type: str, alias: str) -> EntityRecord | None:
        return self.__store.find_entity_by_alias(entity_type, alias)

    def find_entity_by_normalized_name(
        self,
        entity_type: str,
        normalized_name: str,
    ) -> EntityRecord | None:
        return self.__store.find_entity_by_normalized_name(
            entity_type,
            normalized_name,
        )


class _IssueReadRepository(IssueRepository):
    __slots__ = ("__store",)

    def __init__(self, store: KnowledgeStore) -> None:
        self.__store = store

    def find_entity_by_identifier(
        self,
        entity_type: str,
        identifier: str,
    ) -> EntityRecord | None:
        return self.__store.find_entity_by_identifier(entity_type, identifier)

    def find_entity_by_alias(self, entity_type: str, alias: str) -> EntityRecord | None:
        return self.__store.find_entity_by_alias(entity_type, alias)

    def find_entity_by_normalized_name(
        self,
        entity_type: str,
        normalized_name: str,
    ) -> EntityRecord | None:
        return self.__store.find_entity_by_normalized_name(
            entity_type,
            normalized_name,
        )

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return self.__store.get_entity(entity_id)

    def list_entities(self, entity_type: str | None = None) -> list[EntityRecord]:
        from smart_lab_index.core.domain import EntityType

        return self.__store.list_entities(
            None if entity_type is None else EntityType(entity_type)
        )

    def list_active_assertions(
        self,
        predicate: str | None = None,
    ) -> list[AssertionRecord]:
        return self.__store.list_active_assertions(predicate)


class IndexingService:
    """Core-owned pipeline; modules return values and never receive write repositories."""

    def __init__(
        self,
        registry: ModuleRegistry,
        store: KnowledgeStore,
        events: EventBus | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.events = events or registry.events
        self._entity_reader = _EntityReadRepository(store)
        self._issue_reader = _IssueReadRepository(store)

    def run(
        self,
        source: SourceDefinition,
        *,
        progress: Callable[[Mapping[str, Any]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> IndexRunResult:
        connector = self.registry.get(source.connector_module_id)
        if not isinstance(connector, ConnectorModule):
            raise TypeError(f"{source.connector_module_id} is not a connector module")
        if connector not in self.registry.enabled_modules(ModuleType.CONNECTOR):
            raise RuntimeError(
                f"connector is not started and healthy: {source.connector_module_id}"
            )
        connector.validate_source(source)
        self.store.bind_source(
            source_id=source.source_id,
            connector_module_id=source.connector_module_id,
            identity=connector.source_identity(source),
        )
        snapshot = self.registry.snapshot()
        self.store.sync_modules(snapshot)
        run_id = self.store.begin_index_run(
            source_id=source.source_id,
            module_snapshot=snapshot,
            runtime_policy={"no_egress": self.registry.policy.no_egress},
            source_configuration_hash=_source_configuration_hash(source),
        )
        stats = _empty_stats()
        errors: list[str] = []
        for module in snapshot:
            if module["enabled"] and module["health"] == "ERROR":
                stats["module_failures"] += 1
                errors.append(
                    f"{module['module_id']} failed to start: {module['health_detail']}"
                )
        configuration_hashes = {
            item["module_id"]: item["configuration_hash"] for item in snapshot
        }
        processing_context_hash = _processing_context_hash(snapshot)
        try:
            _check_cancelled(should_cancel)
            previous = self.store.source_records(source.source_id)
            batch = self._discover(
                connector,
                source,
                previous,
                stats,
                errors,
                progress,
                should_cancel,
            )
            stats["planned_files"] = int(batch.metadata.get("planned_files", 0))
            stats["planned_bytes"] = int(batch.metadata.get("planned_bytes", 0))
            seen_ids = {item.record.external_id for item in batch.sources}
            failed_ids = {failure.external_id for failure in batch.failures}

            if batch.complete:
                self._resolve_operational_issue(
                    run_id=run_id,
                    code="SOURCE_DISCOVERY_FAILURE",
                    source_id=source.source_id,
                    external_id=".",
                    module_id=connector.manifest.module_id,
                )
            for failure in batch.failures:
                stats["failed"] += 1
                detail = f"discovery failed for {failure.path}: {failure.error}"
                errors.append(detail)
                self._operational_issue(
                    run_id=run_id,
                    code="SOURCE_DISCOVERY_FAILURE",
                    source_id=source.source_id,
                    external_id=failure.external_id,
                    module_id=connector.manifest.module_id,
                    error=failure.error,
                    stats=stats,
                )

            _report(
                progress,
                phase="PROCESSING",
                current=0,
                total=len(batch.sources),
            )
            for position, discovered in enumerate(batch.sources, start=1):
                _check_cancelled(should_cancel)
                stats["discovered"] += 1
                stats[discovered.change.value.casefold()] += 1
                source_record_id, _ = self.store.upsert_source(
                    discovered.record,
                    connector_module_id=connector.manifest.module_id,
                    index_run_id=run_id,
                )
                self._resolve_operational_issue(
                    run_id=run_id,
                    code="SOURCE_DISCOVERY_FAILURE",
                    source_id=source.source_id,
                    external_id=discovered.record.external_id,
                    module_id=connector.manifest.module_id,
                )
                self._emit(
                    Event(
                        EventType.SOURCE_DISCOVERED,
                        {
                            "index_run_id": run_id,
                            "external_id": discovered.record.external_id,
                            "change": discovered.change.value,
                        },
                        connector.manifest.module_id,
                    ),
                    stats,
                )
                if discovered.change.value == "CHANGED":
                    self._emit(
                        Event(
                            EventType.SOURCE_CHANGED,
                            {
                                "index_run_id": run_id,
                                "external_id": discovered.record.external_id,
                            },
                            connector.manifest.module_id,
                        ),
                        stats,
                    )
                self._process_source(
                    connector=connector,
                    definition=source,
                    source=discovered.record,
                    source_record_id=source_record_id,
                    run_id=run_id,
                    stats=stats,
                    errors=errors,
                    configuration_hashes=configuration_hashes,
                    processing_context_hash=processing_context_hash,
                )
                stats["processed_files"] += 1
                _report(
                    progress,
                    phase="PROCESSING",
                    current=position,
                    total=len(batch.sources),
                    path=discovered.record.external_id,
                )

            _check_cancelled(should_cancel)
            if batch.complete:
                deleted_ids = sorted(set(previous) - seen_ids - failed_ids)
                for external_id in deleted_ids:
                    source_record_id = self.store.mark_source_deleted(
                        source.source_id,
                        external_id,
                        run_id,
                    )
                    if source_record_id is None:
                        continue
                    stats["deleted"] += 1
                    self._emit(
                        Event(
                            EventType.SOURCE_DELETED,
                            {"index_run_id": run_id, "external_id": external_id},
                            connector.manifest.module_id,
                        ),
                        stats,
                    )

            _report(progress, phase="FINALIZING", current=0, total=1)
            self._evaluate_issues(run_id, stats, errors)
            status = (
                IndexRunStatus.COMPLETED_WITH_ERRORS
                if errors
                else IndexRunStatus.COMPLETED
            )
            self.store.finish_index_run(
                run_id,
                status=status,
                stats=stats,
                error=_error_summary(errors),
            )
            self._emit(
                Event(
                    EventType.INDEX_RUN_COMPLETED,
                    {"index_run_id": run_id, "status": status.value, "stats": stats},
                ),
                stats,
            )
            return IndexRunResult(run_id, status, stats, tuple(errors))
        except OperationCancelled:
            status = IndexRunStatus.CANCELLED
            self.store.finish_index_run(
                run_id,
                status=status,
                stats=stats,
                error="cancelled by operator",
            )
            self._emit(
                Event(
                    EventType.INDEX_RUN_COMPLETED,
                    {"index_run_id": run_id, "status": status.value, "stats": stats},
                ),
                stats,
            )
            _report(progress, phase="CANCELLED", current=0, total=0)
            return IndexRunResult(run_id, status, stats, tuple(errors))
        except Exception as exc:
            errors.append(f"index run failed: {type(exc).__name__}")
            self.store.finish_index_run(
                run_id,
                status=IndexRunStatus.FAILED,
                stats=stats,
                error=_error_summary(errors),
            )
            raise

    def _discover(
        self,
        connector: ConnectorModule,
        source: SourceDefinition,
        previous: dict[str, SourceRecord],
        stats: dict[str, int],
        errors: list[str],
        progress: Callable[[Mapping[str, Any]], None] | None,
        should_cancel: Callable[[], bool] | None,
    ) -> DiscoveryBatch:
        try:
            batch = connector.discover(
                source,
                previous,
                progress=progress,
                should_cancel=should_cancel,
            )
            _validate_discovery_batch(batch, source)
            return batch
        except OperationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - connector boundary
            stats["module_failures"] += 1
            detail = f"{connector.manifest.module_id}: {type(exc).__name__}: discovery failed"
            errors.append(detail)
            return DiscoveryBatch(
                failures=(DiscoveryFailure(".", source.source_id, detail),),
                complete=False,
            )

    def _process_source(
        self,
        *,
        connector: ConnectorModule,
        definition: SourceDefinition,
        source: SourceRecord,
        source_record_id: str,
        run_id: str,
        stats: dict[str, int],
        errors: list[str],
        configuration_hashes: dict[str, str],
        processing_context_hash: str,
    ) -> None:
        parser, selection_error = self._select_parser(
            source,
            run_id,
            stats,
            errors,
            source_record_id,
        )
        if parser is None:
            stats["failed"] += 1
            detail = selection_error or f"no enabled parser supports {source.external_id}"
            errors.append(detail)
            self._operational_issue(
                run_id=run_id,
                code="PARSING_FAILURE",
                source_id=source.source_id,
                external_id=source.external_id,
                module_id="core.indexing",
                error=detail,
                stats=stats,
                source_record_id=source_record_id,
            )
            return

        source_generation = self.store.source_generation(source_record_id)
        found = self.store.find_document(
            source_record_id=source_record_id,
            source_checksum=source.checksum,
            source_generation=source_generation,
            parser_module_id=parser.manifest.module_id,
            parser_version=parser.manifest.version,
        )
        if found is None:
            try:
                with connector.open_content(definition, source) as content:
                    document = parser.parse(source.document_source(), content)
                document_id, _ = self.store.save_document(
                    source_record_id=source_record_id,
                    source_checksum=source.checksum,
                    source_generation=source_generation,
                    content=document.to_dict(),
                    content_type=document.content_type,
                    parser_module_id=parser.manifest.module_id,
                    parser_version=parser.manifest.version,
                    index_run_id=run_id,
                )
                stats["parsed"] += 1
                self._resolve_operational_issue(
                    run_id=run_id,
                    code="PARSING_FAILURE",
                    source_id=source.source_id,
                    external_id=source.external_id,
                    module_id=parser.manifest.module_id,
                )
                self._emit(
                    Event(
                        EventType.DOCUMENT_REGISTERED,
                        {
                            "index_run_id": run_id,
                            "document_id": document_id,
                            "external_id": source.external_id,
                        },
                        parser.manifest.module_id,
                    ),
                    stats,
                )
                self._emit(
                    Event(
                        EventType.DOCUMENT_PARSED,
                        {
                            "index_run_id": run_id,
                            "document_id": document_id,
                            "external_id": source.external_id,
                        },
                        parser.manifest.module_id,
                    ),
                    stats,
                )
            except Exception as exc:  # noqa: BLE001 - per-document parser isolation
                stats["failed"] += 1
                detail = (
                    f"{parser.manifest.module_id} failed for {source.external_id}: "
                    f"{type(exc).__name__}"
                )
                errors.append(detail)
                self._operational_issue(
                    run_id=run_id,
                    code="PARSING_FAILURE",
                    source_id=source.source_id,
                    external_id=source.external_id,
                    module_id=parser.manifest.module_id,
                    error=detail,
                    stats=stats,
                    source_record_id=source_record_id,
                )
                self._emit(
                    Event(
                        EventType.DOCUMENT_PARSE_FAILED,
                        {"index_run_id": run_id, "external_id": source.external_id},
                        parser.manifest.module_id,
                    ),
                    stats,
                )
                return
        else:
            document_id, document = found
            self._resolve_operational_issue(
                run_id=run_id,
                code="PARSING_FAILURE",
                source_id=source.source_id,
                external_id=source.external_id,
                module_id=parser.manifest.module_id,
            )

        for extractor in self._extractors():
            configuration_hash = configuration_hashes[extractor.manifest.module_id]
            if self.store.processing_complete(
                document_id=document_id,
                module_id=extractor.manifest.module_id,
                module_version=extractor.manifest.version,
                configuration_hash=configuration_hash,
                processing_context_hash=processing_context_hash,
            ):
                continue
            self._run_extractor(
                extractor=extractor,
                document=document,
                document_id=document_id,
                source=source,
                source_record_id=source_record_id,
                run_id=run_id,
                configuration_hash=configuration_hash,
                processing_context_hash=processing_context_hash,
                stats=stats,
                errors=errors,
            )

    def _run_extractor(
        self,
        *,
        extractor: ExtractorModule,
        document: DocumentContent,
        document_id: str,
        source: SourceRecord,
        source_record_id: str,
        run_id: str,
        configuration_hash: str,
        processing_context_hash: str,
        stats: dict[str, int],
        errors: list[str],
    ) -> None:
        try:
            result = extractor.extract(document)
            _validate_extraction_result(extractor, result)
            events: list[Event] = []
            created_entities = 0
            created_assertions = 0
            with self.store.transaction():
                resolved: dict[tuple[Any, ...], EntityRecord] = {}
                for candidate in result.entities:
                    entity, created = self._resolve_candidate(candidate, source_record_id)
                    resolved[_reference_key(candidate.reference)] = entity
                    created_entities += int(created)
                    events.extend(_entity_events(
                        run_id,
                        source.external_id,
                        extractor.manifest.module_id,
                        entity,
                        created,
                    ))
                for assertion in result.assertions:
                    subject, created = self._resolve_reference(
                        assertion.subject,
                        assertion.provenance,
                        assertion.confidence,
                        assertion.extraction_method,
                        assertion.module_id,
                        assertion.module_version,
                        source_record_id,
                        resolved,
                    )
                    created_entities += int(created)
                    events.extend(_entity_events(
                        run_id,
                        source.external_id,
                        extractor.manifest.module_id,
                        subject,
                        created,
                    ))
                    object_entity = None
                    if assertion.object_ref is not None:
                        object_entity, created = self._resolve_reference(
                            assertion.object_ref,
                            assertion.provenance,
                            assertion.confidence,
                            assertion.extraction_method,
                            assertion.module_id,
                            assertion.module_version,
                            source_record_id,
                            resolved,
                        )
                        created_entities += int(created)
                        events.extend(_entity_events(
                            run_id,
                            source.external_id,
                            extractor.manifest.module_id,
                            object_entity,
                            created,
                        ))
                    assertion_id, created = self.store.create_assertion(
                        subject_entity_id=subject.entity_id,
                        predicate=assertion.predicate,
                        object_entity_id=(
                            None if object_entity is None else object_entity.entity_id
                        ),
                        literal=assertion.literal,
                        source_record_id=source_record_id,
                        provenance=assertion.provenance.to_dict(),
                        confidence=assertion.confidence,
                        extraction_method=assertion.extraction_method,
                        status=assertion.status,
                        extraction_module_id=assertion.module_id,
                        extraction_module_version=assertion.module_version,
                        index_run_id=run_id,
                        document_id=document_id,
                    )
                    created_assertions += int(created)
                    if created:
                        events.append(Event(
                            EventType.ASSERTION_CREATED,
                            {"index_run_id": run_id, "assertion_id": assertion_id},
                            extractor.manifest.module_id,
                        ))
                self.store.supersede_source_module_assertions(
                    source_record_id=source_record_id,
                    module_id=extractor.manifest.module_id,
                    current_index_run_id=run_id,
                )
                self.store.mark_processing_complete(
                    document_id=document_id,
                    module_id=extractor.manifest.module_id,
                    module_version=extractor.manifest.version,
                    configuration_hash=configuration_hash,
                    processing_context_hash=processing_context_hash,
                    index_run_id=run_id,
                    entity_count=len(result.entities),
                    assertion_count=len(result.assertions),
                    warnings=result.warnings,
                )
            stats["entities"] += created_entities
            stats["assertions"] += created_assertions
            for event in events:
                self._emit(event, stats)
            self._resolve_operational_issue(
                run_id=run_id,
                code="MODULE_FAILURE",
                source_id=source.source_id,
                external_id=source.external_id,
                module_id=extractor.manifest.module_id,
            )
        except Exception as exc:  # noqa: BLE001 - optional module isolation
            module_id = (
                exc.module_id
                if isinstance(exc, ModuleExecutionError)
                else extractor.manifest.module_id
            )
            stats["module_failures"] += 1
            detail = f"{module_id} failed for {source.external_id}: {type(exc).__name__}"
            errors.append(detail)
            self._operational_issue(
                run_id=run_id,
                code="MODULE_FAILURE",
                source_id=source.source_id,
                external_id=source.external_id,
                module_id=module_id,
                error=detail,
                stats=stats,
                source_record_id=source_record_id,
            )

    def _select_parser(
        self,
        source: SourceRecord,
        run_id: str,
        stats: dict[str, int],
        errors: list[str],
        source_record_id: str,
    ) -> tuple[ParserModule | None, str | None]:
        candidates = []
        descriptor = source.document_source()
        for module in self.registry.enabled_modules(ModuleType.PARSER):
            if not isinstance(module, ParserModule):
                continue
            try:
                if module.supports(descriptor):
                    candidates.append(module)
            except Exception as exc:  # noqa: BLE001 - parser routing boundary
                stats["module_failures"] += 1
                detail = f"{module.manifest.module_id} supports failed ({type(exc).__name__})"
                errors.append(detail)
                self._operational_issue(
                    run_id=run_id,
                    code="MODULE_FAILURE",
                    source_id=source.source_id,
                    external_id=source.external_id,
                    module_id=module.manifest.module_id,
                    error=detail,
                    stats=stats,
                    source_record_id=source_record_id,
                )
        if not candidates:
            return None, None
        priority = min(module.priority for module in candidates)
        preferred = [module for module in candidates if module.priority == priority]
        if len(preferred) > 1:
            module_ids = ", ".join(sorted(module.manifest.module_id for module in preferred))
            return None, f"ambiguous parser selection for {source.external_id}: {module_ids}"
        return preferred[0], None

    def _extractors(self) -> list[ExtractorModule]:
        values = []
        for module_type in (
            ModuleType.ENTITY_EXTRACTOR,
            ModuleType.RELATIONSHIP_EXTRACTOR,
        ):
            values.extend(
                module
                for module in self.registry.enabled_modules(module_type)
                if isinstance(module, ExtractorModule)
            )
        return values

    def _resolvers(self) -> list[ResolverModule]:
        values = [
            module
            for module in self.registry.enabled_modules(ModuleType.RESOLVER)
            if isinstance(module, ResolverModule)
        ]
        return sorted(values, key=lambda module: (module.order, module.manifest.module_id))

    def _resolve_reference(
        self,
        reference: EntityReference,
        provenance: Provenance,
        confidence: float,
        extraction_method: str,
        module_id: str,
        module_version: str,
        source_record_id: str,
        resolved: dict[tuple[Any, ...], EntityRecord],
    ) -> tuple[EntityRecord, bool]:
        key = _reference_key(reference)
        if key in resolved:
            return resolved[key], False
        candidate = EntityCandidate(
            reference=reference,
            subtype=None,
            aliases=(),
            provenance=provenance,
            confidence=confidence,
            extraction_method=extraction_method,
            module_id=module_id,
            module_version=module_version,
        )
        entity, created = self._resolve_candidate(candidate, source_record_id)
        resolved[key] = entity
        return entity, created

    def _resolve_candidate(
        self,
        candidate: EntityCandidate,
        source_record_id: str,
    ) -> tuple[EntityRecord, bool]:
        entity = None
        for resolver in self._resolvers():
            try:
                proposed = resolver.resolve(candidate, self._entity_reader)
            except Exception as exc:
                raise ModuleExecutionError(
                    resolver.manifest.module_id,
                    "resolution",
                    exc,
                ) from exc
            candidate_identifier = candidate.reference.identifier
            if (
                proposed is not None
                and candidate_identifier is not None
                and proposed.identifier is not None
                and proposed.identifier != candidate_identifier
            ):
                continue
            if proposed is not None:
                entity = proposed
                break
        created = entity is None
        if entity is None:
            canonical_name = candidate.reference.name or candidate.reference.identifier or ""
            entity = self.store.create_entity(
                entity_type=candidate.reference.entity_type,
                canonical_name=canonical_name,
                normalized_name=normalize_name(canonical_name),
                subtype=candidate.subtype,
                identifier=candidate.reference.identifier,
                metadata={
                    "first_observed": {
                        "provenance": candidate.provenance.to_dict(),
                        "module_id": candidate.module_id,
                        "module_version": candidate.module_version,
                    }
                },
            )
        else:
            entity = self.store.enrich_entity(
                entity.entity_id,
                identifier=candidate.reference.identifier,
                subtype=candidate.subtype,
            )
        for alias in sorted(set(candidate.aliases)):
            self.store.add_alias(
                entity_id=entity.entity_id,
                alias=alias,
                normalized_alias=normalize_name(alias),
                source_record_id=source_record_id,
            )
        return entity, created

    def _evaluate_issues(
        self,
        run_id: str,
        stats: dict[str, int],
        errors: list[str],
    ) -> None:
        for module in self.registry.enabled_modules(ModuleType.ISSUE_RULE):
            if not isinstance(module, IssueRuleModule):
                continue
            try:
                drafts = module.evaluate(self._issue_reader)
                active = set()
                for draft in drafts:
                    active.add(draft.fingerprint)
                    issue_id, created = self.store.create_issue(
                        code=draft.code,
                        severity=draft.severity.value,
                        entity_id=draft.entity_id,
                        source_record_id=draft.source_record_id,
                        assertion_ids=draft.assertion_ids,
                        evidence=draft.evidence,
                        rule_module_id=module.manifest.module_id,
                        rule_version=module.manifest.version,
                        fingerprint=draft.fingerprint,
                        index_run_id=run_id,
                    )
                    stats["issues"] += int(created)
                    if created:
                        self._emit(
                            Event(
                                EventType.ISSUE_CREATED,
                                {"index_run_id": run_id, "issue_id": issue_id},
                                module.manifest.module_id,
                            ),
                            stats,
                        )
                self.store.resolve_issues_not_seen(
                    module.manifest.module_id,
                    run_id,
                    active,
                )
            except Exception as exc:  # noqa: BLE001 - optional issue rule isolation
                stats["module_failures"] += 1
                errors.append(
                    f"{module.manifest.module_id} failed: {type(exc).__name__}"
                )

    def _operational_issue(
        self,
        *,
        run_id: str,
        code: str,
        source_id: str,
        external_id: str,
        module_id: str,
        error: str,
        stats: dict[str, int],
        source_record_id: str | None = None,
    ) -> None:
        identity, fingerprint = _operational_identity(
            code,
            source_id,
            external_id,
            module_id,
        )
        _, created = self.store.create_issue(
            code=code,
            severity="ERROR",
            entity_id=None,
            source_record_id=source_record_id,
            assertion_ids=(),
            evidence={**identity, "module_id": module_id, "error": error[:500]},
            rule_module_id="core.indexing",
            rule_version=CORE_API_VERSION,
            fingerprint=fingerprint,
            index_run_id=run_id,
        )
        stats["issues"] += int(created)

    def _resolve_operational_issue(
        self,
        *,
        run_id: str,
        code: str,
        source_id: str,
        external_id: str,
        module_id: str,
    ) -> None:
        _, fingerprint = _operational_identity(
            code,
            source_id,
            external_id,
            module_id,
        )
        self.store.resolve_issue_fingerprint(fingerprint, run_id)

    def _emit(self, event: Event, stats: dict[str, int]) -> None:
        failures = self.events.emit(event)
        stats["hook_failures"] += len(failures)
        for failure in failures:
            self.store.record_audit_event(
                event_type="MODULE_HOOK_FAILURE",
                actor="core.indexing",
                target_type="module",
                target_id=failure.owner,
                detail={
                    "event_type": event.event_type.value,
                    "error": failure.error[:500],
                },
            )


def _empty_stats() -> dict[str, int]:
    return {
        "discovered": 0,
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "deleted": 0,
        "parsed": 0,
        "failed": 0,
        "entities": 0,
        "assertions": 0,
        "issues": 0,
        "module_failures": 0,
        "hook_failures": 0,
        "planned_files": 0,
        "planned_bytes": 0,
        "processed_files": 0,
    }


def _check_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise OperationCancelled("index run cancelled by operator")


def _report(
    progress: Callable[[Mapping[str, Any]], None] | None,
    **value: Any,
) -> None:
    if progress is not None:
        progress(value)


def _reference_key(reference: EntityReference) -> tuple[Any, ...]:
    return (
        reference.entity_type.value,
        reference.identifier,
        normalize_name(reference.name or ""),
    )


def _processing_context_hash(snapshot: list[dict[str, Any]]) -> str:
    intelligence_types = {
        ModuleType.CLASSIFIER.value,
        ModuleType.DOMAIN.value,
        ModuleType.RESOLVER.value,
    }
    values = [
        {
            "module_id": item["module_id"],
            "version": item["version"],
            "configuration_hash": item["configuration_hash"],
        }
        for item in snapshot
        if item["enabled"] and item["module_type"] in intelligence_types
    ]
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _source_configuration_hash(source: SourceDefinition) -> str:
    value = {
        "connector_module_id": source.connector_module_id,
        "configuration": dict(source.configuration),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_extraction_result(
    extractor: ExtractorModule,
    result: ExtractionResult,
) -> None:
    for candidate in result.entities:
        if (
            candidate.module_id != extractor.manifest.module_id
            or candidate.module_version != extractor.manifest.version
        ):
            raise ValueError("extractor returned an entity candidate with false module metadata")
    for assertion in result.assertions:
        if (
            assertion.module_id != extractor.manifest.module_id
            or assertion.module_version != extractor.manifest.version
        ):
            raise ValueError("extractor returned an assertion with false module metadata")


def _validate_discovery_batch(
    batch: DiscoveryBatch,
    source: SourceDefinition,
) -> None:
    external_ids = [item.record.external_id for item in batch.sources]
    if len(external_ids) != len(set(external_ids)):
        raise ValueError("connector returned duplicate external IDs")
    if any(not external_id for external_id in external_ids):
        raise ValueError("connector returned an empty external ID")
    if any(item.record.source_id != source.source_id for item in batch.sources):
        raise ValueError("connector returned a record for a different source instance")


def _entity_events(
    run_id: str,
    external_id: str,
    module_id: str,
    entity: EntityRecord,
    created: bool,
) -> list[Event]:
    events = [Event(
        EventType.ENTITY_CANDIDATE_FOUND,
        {
            "index_run_id": run_id,
            "entity_id": entity.entity_id,
            "external_id": external_id,
        },
        module_id,
    )]
    if created:
        events.append(Event(
            EventType.ENTITY_CREATED,
            {"index_run_id": run_id, "entity_id": entity.entity_id},
            module_id,
        ))
    return events


def _operational_identity(
    code: str,
    source_id: str,
    external_id: str,
    module_id: str,
) -> tuple[dict[str, str], str]:
    identity = {
        "code": code,
        "source_id": source_id,
        "external_id": external_id,
    }
    if code == "MODULE_FAILURE":
        identity["module_id"] = module_id
    fingerprint = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return identity, fingerprint


def _error_summary(errors: list[str]) -> str | None:
    if not errors:
        return None
    bounded = [" ".join(value.split())[:500] for value in errors[:20]]
    return " | ".join(bounded)[:4000]
