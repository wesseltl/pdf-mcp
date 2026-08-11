"""Explicit module contracts and the built-in module registry."""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, BinaryIO, Protocol

from smart_lab_index import CORE_API_VERSION
from smart_lab_index.core.config import RuntimePolicy
from smart_lab_index.core.domain import (
    AssertionRecord,
    DiscoveryBatch,
    DocumentContent,
    DocumentSource,
    EntityCandidate,
    EntityRecord,
    ExtractionResult,
    IssueDraft,
    SourceDefinition,
    SourceRecord,
)
from smart_lab_index.core.events import EventBus


class ModuleError(RuntimeError):
    pass


class ModuleConfigurationError(ModuleError):
    pass


class ModuleDependencyError(ModuleError):
    pass


class NoEgressViolation(ModuleError):
    pass


class ModuleType(str, Enum):
    CONNECTOR = "CONNECTOR"
    PARSER = "PARSER"
    CLASSIFIER = "CLASSIFIER"
    ENTITY_EXTRACTOR = "ENTITY_EXTRACTOR"
    RELATIONSHIP_EXTRACTOR = "RELATIONSHIP_EXTRACTOR"
    RESOLVER = "RESOLVER"
    ISSUE_RULE = "ISSUE_RULE"
    INFERENCE = "INFERENCE"
    EMBEDDING = "EMBEDDING"
    SEARCH = "SEARCH"
    DOMAIN = "DOMAIN"
    UI = "UI"
    EXPORT = "EXPORT"


class ModuleHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"
    MISCONFIGURED = "MISCONFIGURED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class ModuleLifecycleState(str, Enum):
    INSTALLED = "INSTALLED"
    INITIALIZED = "INITIALIZED"
    STARTED = "STARTED"
    STOPPED = "STOPPED"
    BLOCKED = "BLOCKED"


class NetworkAccess(str, Enum):
    NONE = "NONE"
    LOOPBACK = "LOOPBACK"
    CONFIGURED_ENDPOINT = "CONFIGURED_ENDPOINT"
    INTERNET = "INTERNET"


class FileAccess(str, Enum):
    NONE = "NONE"
    READ = "READ"
    WRITE = "WRITE"


@dataclass(frozen=True)
class ModuleCapability:
    capability_id: str
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", self.capability_id):
            raise ValueError(f"invalid capability ID: {self.capability_id!r}")
        _version_tuple(self.version)

    def to_dict(self) -> dict[str, str]:
        return {"capability_id": self.capability_id, "version": self.version}


@dataclass(frozen=True)
class ModuleDependency:
    module_id: str | None = None
    capability: str | None = None
    minimum_version: str | None = None

    def __post_init__(self) -> None:
        if (self.module_id is None) == (self.capability is None):
            raise ValueError("a dependency needs exactly one module_id or capability")
        value = self.module_id or self.capability or ""
        if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", value):
            raise ValueError(f"invalid dependency ID: {value!r}")
        if self.minimum_version is not None:
            _version_tuple(self.minimum_version)

    def to_dict(self) -> dict[str, str]:
        value = {"minimum_version": self.minimum_version or ""}
        value["module_id" if self.module_id else "capability"] = (
            self.module_id or self.capability or ""
        )
        return value


@dataclass(frozen=True)
class ModuleManifest:
    module_id: str
    name: str
    version: str
    module_type: ModuleType
    description: str
    network_access: NetworkAccess
    file_access: FileAccess
    telemetry: bool = False
    automatic_downloads: bool = False
    uses_subprocesses: bool = False
    source_write_access: bool = False
    core_compatibility: str = ">=0.1.0,<1.0.0"
    dependencies: tuple[ModuleDependency, ...] = ()
    capabilities: tuple[ModuleCapability, ...] = ()
    configuration_schema: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "additionalProperties": False}
    )
    credentials_required: tuple[str, ...] = ()
    outbound_connections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", self.module_id):
            raise ValueError(f"invalid module ID: {self.module_id!r}")
        _version_tuple(self.version)
        if not self.capabilities:
            raise ValueError(f"module {self.module_id} must declare at least one capability")
        if self.network_access == NetworkAccess.NONE and self.outbound_connections:
            raise ValueError(
                f"module {self.module_id} declares outbound connections but no network access"
            )


@dataclass(frozen=True)
class ModuleHealth:
    state: ModuleHealthState
    detail: str = ""


@dataclass(frozen=True)
class ModuleContext:
    policy: RuntimePolicy
    events: EventBus


class EntityRepository(Protocol):
    def find_entity_by_identifier(
        self, entity_type: str, identifier: str
    ) -> EntityRecord | None: ...

    def find_entity_by_alias(self, entity_type: str, alias: str) -> EntityRecord | None: ...

    def find_entity_by_normalized_name(
        self, entity_type: str, normalized_name: str
    ) -> EntityRecord | None: ...


class IssueRepository(EntityRepository, Protocol):
    def get_entity(self, entity_id: str) -> EntityRecord | None: ...

    def list_active_assertions(self, predicate: str | None = None) -> list[AssertionRecord]: ...


class SmartLabModule(ABC):
    """Base lifecycle shared by built-in and future optional modules."""

    manifest: ModuleManifest

    def __init__(self, configuration: Mapping[str, Any] | None = None) -> None:
        self.configuration = dict(configuration or {})
        self._context: ModuleContext | None = None
        self._started = False

    def initialize(self, context: ModuleContext) -> None:
        self._context = context

    def validate_configuration(self) -> None:
        _validate_schema(self.configuration, self.manifest.configuration_schema, "configuration")

    def start(self) -> None:
        self.validate_configuration()
        self._started = True

    def health_check(self) -> ModuleHealth:
        if self._started:
            return ModuleHealth(ModuleHealthState.HEALTHY)
        return ModuleHealth(ModuleHealthState.DEGRADED, "module has not started")

    def stop(self) -> None:
        self._started = False


class ConnectorModule(SmartLabModule, ABC):
    @abstractmethod
    def validate_source(self, source: SourceDefinition) -> None:
        """Validate one source instance without mutating provider lifecycle state."""
        raise NotImplementedError

    @abstractmethod
    def source_identity(self, source: SourceDefinition) -> Mapping[str, Any]:
        """Return immutable identity fields used to prevent source ID reuse."""
        raise NotImplementedError

    @abstractmethod
    def discover(
        self,
        source: SourceDefinition,
        previous: Mapping[str, SourceRecord],
    ) -> DiscoveryBatch:
        raise NotImplementedError

    @abstractmethod
    def open_content(
        self,
        definition: SourceDefinition,
        source: SourceRecord,
    ) -> AbstractContextManager[BinaryIO]:
        """Open source bytes read-only; parsers never locate files or call vendor APIs."""
        raise NotImplementedError


class ParserModule(SmartLabModule, ABC):
    priority = 100

    @abstractmethod
    def supports(self, source: DocumentSource) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(self, source: DocumentSource, content: BinaryIO) -> DocumentContent:
        raise NotImplementedError


class ExtractorModule(SmartLabModule, ABC):
    @abstractmethod
    def extract(self, document: DocumentContent) -> ExtractionResult:
        raise NotImplementedError


class ResolverModule(SmartLabModule, ABC):
    @abstractmethod
    def resolve(
        self, candidate: EntityCandidate, repository: EntityRepository
    ) -> EntityRecord | None:
        raise NotImplementedError


class IssueRuleModule(SmartLabModule, ABC):
    @abstractmethod
    def evaluate(self, repository: IssueRepository) -> tuple[IssueDraft, ...]:
        raise NotImplementedError


class DomainModule(SmartLabModule, ABC):
    """Marker contract for domain packs that supply configuration, not Core types."""


@dataclass
class RegistryEntry:
    module: SmartLabModule
    enabled: bool
    blocked_reason: str = ""
    runtime_error: str = ""
    lifecycle: ModuleLifecycleState = ModuleLifecycleState.INSTALLED


class ModuleRegistry:
    """Own installed/enabled state and enforce dependency and no-egress rules."""

    def __init__(
        self,
        policy: RuntimePolicy | None = None,
        events: EventBus | None = None,
    ) -> None:
        self.policy = policy or RuntimePolicy()
        self.events = events or EventBus()
        self._entries: dict[str, RegistryEntry] = {}
        self._start_order: list[str] = []

    def register(self, module: SmartLabModule, *, enabled: bool = True) -> None:
        manifest = module.manifest
        if manifest.module_id in self._entries:
            raise ModuleError(f"module already installed: {manifest.module_id}")
        if not _version_matches(CORE_API_VERSION, manifest.core_compatibility):
            raise ModuleError(
                f"{manifest.module_id} is incompatible with Core {CORE_API_VERSION}"
            )
        blocked_reason = _policy_block_reason(self.policy, manifest)
        if blocked_reason:
            enabled = False
        if enabled:
            try:
                module.initialize(ModuleContext(policy=self.policy, events=self.events))
            except Exception as exc:
                raise ModuleError(f"{manifest.module_id} initialization failed") from exc
        self._entries[manifest.module_id] = RegistryEntry(
            module=module,
            enabled=enabled,
            blocked_reason=blocked_reason,
            lifecycle=(
                ModuleLifecycleState.BLOCKED
                if blocked_reason
                else (
                    ModuleLifecycleState.INITIALIZED
                    if enabled
                    else ModuleLifecycleState.INSTALLED
                )
            ),
        )

    def get(self, module_id: str) -> SmartLabModule:
        try:
            return self._entries[module_id].module
        except KeyError as exc:
            raise ModuleError(f"module is not installed: {module_id}") from exc

    def enable(self, module_id: str) -> None:
        entry = self._entry(module_id)
        blocked_reason = _policy_block_reason(self.policy, entry.module.manifest)
        if blocked_reason:
            raise NoEgressViolation(
                f"{module_id} is blocked by runtime policy: {blocked_reason}"
            )
        entry.blocked_reason = ""
        entry.runtime_error = ""
        entry.enabled = True
        if entry.module._context is None:
            try:
                entry.module.initialize(ModuleContext(policy=self.policy, events=self.events))
            except Exception as exc:
                entry.enabled = False
                raise ModuleError(f"{module_id} initialization failed") from exc
        entry.lifecycle = ModuleLifecycleState.INITIALIZED
        try:
            self._validate_dependencies_for(module_id)
        except ModuleDependencyError:
            entry.enabled = False
            raise

    def disable(self, module_id: str) -> None:
        target = self._entry(module_id)
        target_capabilities = {
            capability.capability_id
            for capability in target.module.manifest.capabilities
        }
        dependents = [
            candidate_id
            for candidate_id, entry in self._entries.items()
            if entry.enabled
            and any(
                dependency.module_id == module_id
                or (
                    dependency.capability in target_capabilities
                    and not self._alternative_capability_provider(
                        dependency,
                        excluded_module_id=module_id,
                    )
                )
                for dependency in entry.module.manifest.dependencies
            )
        ]
        if dependents:
            raise ModuleDependencyError(
                f"disable dependent modules first: {', '.join(sorted(dependents))}"
            )
        entry = self._entries[module_id]
        if entry.module._started:
            entry.module.stop()
        entry.lifecycle = ModuleLifecycleState.STOPPED
        entry.enabled = False

    def _alternative_capability_provider(
        self,
        dependency: ModuleDependency,
        *,
        excluded_module_id: str,
    ) -> bool:
        if dependency.capability is None:
            return False
        for candidate_id, entry in self._entries.items():
            if candidate_id == excluded_module_id or not entry.enabled or entry.runtime_error:
                continue
            for capability in entry.module.manifest.capabilities:
                if capability.capability_id != dependency.capability:
                    continue
                if dependency.minimum_version is None or _version_tuple(
                    capability.version
                ) >= _version_tuple(dependency.minimum_version):
                    return True
        return False

    def start_all(self) -> dict[str, str]:
        """Start enabled modules in dependency order and isolate startup failures."""
        pending = {
            module_id
            for module_id, entry in self._entries.items()
            if entry.enabled and not entry.module._started
        }
        errors: dict[str, str] = {}
        while pending:
            made_progress = False
            for module_id in sorted(pending):
                entry = self._entries[module_id]
                unmet = self._unmet_dependencies(entry.module.manifest)
                if unmet:
                    continue
                try:
                    entry.module.start()
                    entry.runtime_error = ""
                    entry.lifecycle = ModuleLifecycleState.STARTED
                    self._start_order.append(module_id)
                except ModuleConfigurationError as exc:
                    entry.runtime_error = _bounded_detail(str(exc))
                    entry.lifecycle = ModuleLifecycleState.STOPPED
                    errors[module_id] = entry.runtime_error
                except Exception as exc:  # noqa: BLE001 - isolate optional module startup
                    entry.runtime_error = f"{type(exc).__name__}: module start failed"
                    entry.lifecycle = ModuleLifecycleState.STOPPED
                    errors[module_id] = entry.runtime_error
                pending.remove(module_id)
                made_progress = True
                break
            if made_progress:
                continue
            for module_id in sorted(pending):
                detail = ", ".join(self._unmet_dependencies(
                    self._entries[module_id].module.manifest
                )) or "dependency cycle"
                self._entries[module_id].runtime_error = detail
                self._entries[module_id].lifecycle = ModuleLifecycleState.BLOCKED
                errors[module_id] = detail
            break
        return errors

    def stop_all(self) -> None:
        for module_id in reversed(self._start_order):
            module = self._entries[module_id].module
            if module._started:
                module.stop()
                self._entries[module_id].lifecycle = ModuleLifecycleState.STOPPED
        self._start_order.clear()

    def enabled_modules(self, module_type: ModuleType | None = None) -> list[SmartLabModule]:
        modules = [
            entry.module
            for entry in self._entries.values()
            if entry.enabled and not entry.runtime_error and entry.module._started
        ]
        if module_type is not None:
            modules = [module for module in modules if module.manifest.module_type == module_type]
        return sorted(modules, key=lambda module: module.manifest.module_id)

    def capability_providers(self, capability: str) -> list[SmartLabModule]:
        return [
            module
            for module in self.enabled_modules()
            if any(item.capability_id == capability for item in module.manifest.capabilities)
        ]

    def snapshot(self) -> list[dict[str, Any]]:
        values = []
        for module_id in sorted(self._entries):
            entry = self._entries[module_id]
            manifest = entry.module.manifest
            if not entry.enabled:
                health = ModuleHealth(
                    ModuleHealthState.DISABLED,
                    entry.blocked_reason or "disabled by configuration",
                )
            elif entry.runtime_error:
                health = ModuleHealth(ModuleHealthState.ERROR, entry.runtime_error)
            else:
                try:
                    health = entry.module.health_check()
                except Exception as exc:  # noqa: BLE001 - health checks must not break status
                    health = ModuleHealth(
                        ModuleHealthState.ERROR,
                        f"{type(exc).__name__}: health check failed",
                    )
            health = ModuleHealth(health.state, _safe_module_detail(entry.module, health.detail))
            redacted_configuration = _redact_configuration(
                entry.module.configuration,
                set(manifest.credentials_required),
            )
            values.append({
                "module_id": module_id,
                "name": manifest.name,
                "version": manifest.version,
                "module_type": manifest.module_type.value,
                "enabled": entry.enabled,
                "lifecycle": entry.lifecycle.value,
                "health": health.state.value,
                "health_detail": health.detail,
                "capabilities": [item.to_dict() for item in manifest.capabilities],
                "dependencies": [item.to_dict() for item in manifest.dependencies],
                "configuration": redacted_configuration,
                "configuration_hash": hashlib.sha256(
                    json.dumps(
                        redacted_configuration,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "security": {
                    "network_access": manifest.network_access.value,
                    "file_access": manifest.file_access.value,
                    "credentials_required": list(manifest.credentials_required),
                    "outbound_connections": list(manifest.outbound_connections),
                    "telemetry": manifest.telemetry,
                    "automatic_downloads": manifest.automatic_downloads,
                    "uses_subprocesses": manifest.uses_subprocesses,
                    "source_write_access": manifest.source_write_access,
                },
            })
        return values

    def _entry(self, module_id: str) -> RegistryEntry:
        try:
            return self._entries[module_id]
        except KeyError as exc:
            raise ModuleError(f"module is not installed: {module_id}") from exc

    def _validate_dependencies_for(self, module_id: str) -> None:
        unmet = self._unmet_dependencies(self._entries[module_id].module.manifest, started=False)
        if unmet:
            raise ModuleDependencyError(
                f"unmet dependencies for {module_id}: {', '.join(unmet)}"
            )

    def _unmet_dependencies(
        self, manifest: ModuleManifest, *, started: bool = True
    ) -> list[str]:
        unmet = []
        for dependency in manifest.dependencies:
            candidates: list[RegistryEntry]
            label: str
            if dependency.module_id:
                candidate = self._entries.get(dependency.module_id)
                candidates = [] if candidate is None else [candidate]
                label = dependency.module_id
            else:
                candidates = [
                    entry
                    for entry in self._entries.values()
                    if any(
                        capability.capability_id == dependency.capability
                        for capability in entry.module.manifest.capabilities
                    )
                ]
                label = f"capability:{dependency.capability}"
            usable = [
                candidate
                for candidate in candidates
                if candidate.enabled
                and not candidate.runtime_error
                and (not started or candidate.module._started)
                and (
                    dependency.minimum_version is None
                    or (
                        _version_tuple(candidate.module.manifest.version)
                        >= _version_tuple(dependency.minimum_version)
                        if dependency.module_id
                        else any(
                            capability.capability_id == dependency.capability
                            and _version_tuple(capability.version)
                            >= _version_tuple(dependency.minimum_version)
                            for capability in candidate.module.manifest.capabilities
                        )
                    )
                )
            ]
            if not usable:
                unmet.append(label)
        return unmet


def _version_tuple(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(f"version must use numeric major.minor.patch: {value!r}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _version_matches(version: str, specification: str) -> bool:
    current = _version_tuple(version)
    for clause in (part.strip() for part in specification.split(",")):
        if clause.startswith(">="):
            matches = current >= _version_tuple(clause[2:])
        elif clause.startswith(">"):
            matches = current > _version_tuple(clause[1:])
        elif clause.startswith("<="):
            matches = current <= _version_tuple(clause[2:])
        elif clause.startswith("<"):
            matches = current < _version_tuple(clause[1:])
        elif clause.startswith("=="):
            matches = current == _version_tuple(clause[2:])
        else:
            raise ValueError(f"unsupported compatibility clause: {clause!r}")
        if not matches:
            return False
    return True


def _validate_schema(value: Any, schema: Mapping[str, Any], path: str) -> None:
    """Validate the small JSON Schema subset used by built-in module configuration."""
    expected = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    if expected in type_map:
        expected_type = type_map[expected]
        if not isinstance(value, expected_type) or (
            expected in {"integer", "number"} and isinstance(value, bool)
        ):
            raise ModuleConfigurationError(f"{path} must be {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ModuleConfigurationError(f"{path} must be one of {schema['enum']}")
    if expected == "object":
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                raise ModuleConfigurationError(f"{path}.{required} is required")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ModuleConfigurationError(
                    f"{path} has unknown fields: {', '.join(unknown)}"
                )
        for key, item in value.items():
            if key in properties:
                _validate_schema(item, properties[key], f"{path}.{key}")
    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{path}[{index}]")


def _redact_configuration(value: Any, declared_secrets: set[str]) -> Any:
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).lower()
            is_secret = key in declared_secrets or any(
                marker in normalized for marker in ("password", "secret", "token", "api_key")
            )
            redacted[key] = "[REDACTED]" if is_secret else _redact_configuration(
                item, declared_secrets
            )
        return redacted
    if isinstance(value, list):
        return [_redact_configuration(item, declared_secrets) for item in value]
    return value


def _safe_module_detail(module: SmartLabModule, detail: str) -> str:
    value = detail
    redacted = _redact_configuration(
        module.configuration,
        set(module.manifest.credentials_required),
    )
    for secret in _redacted_values(module.configuration, redacted):
        value = value.replace(secret, "[REDACTED]")
    return _bounded_detail(value)


def _redacted_values(original: Any, redacted: Any) -> list[str]:
    if isinstance(original, Mapping) and isinstance(redacted, Mapping):
        values = []
        for key, item in original.items():
            if redacted.get(key) == "[REDACTED]":
                if isinstance(item, str) and item:
                    values.append(item)
            else:
                values.extend(_redacted_values(item, redacted.get(key)))
        return values
    if isinstance(original, list) and isinstance(redacted, list):
        values = []
        for item, redacted_item in zip(original, redacted, strict=True):
            values.extend(_redacted_values(item, redacted_item))
        return values
    return []


def _bounded_detail(value: str) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= 500 else f"{compact[:497]}..."


def _policy_block_reason(
    policy: RuntimePolicy,
    manifest: ModuleManifest,
) -> str:
    if manifest.source_write_access:
        return "source write access is not supported"
    if not policy.no_egress:
        return ""
    if manifest.network_access not in {NetworkAccess.NONE, NetworkAccess.LOOPBACK}:
        return "blocked by SMART_LAB_INDEX_NO_EGRESS"
    if manifest.telemetry:
        return "telemetry is blocked by SMART_LAB_INDEX_NO_EGRESS"
    if manifest.automatic_downloads:
        return "automatic downloads are blocked by SMART_LAB_INDEX_NO_EGRESS"
    return ""
