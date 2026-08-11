"""Alias resolver."""

from __future__ import annotations

from smart_lab_index.core.domain import EntityCandidate, EntityRecord
from smart_lab_index.core.modules import (
    EntityRepository,
    FileAccess,
    ModuleCapability,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
    ResolverModule,
)
from smart_lab_index.core.normalization import normalize_name


class AliasResolver(ResolverModule):
    order = 20
    manifest = ModuleManifest(
        module_id="resolver.alias",
        name="Alias Resolver",
        version="0.1.0",
        module_type=ModuleType.RESOLVER,
        description="Resolves configured and previously observed entity aliases.",
        capabilities=(ModuleCapability("resolver.entity", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def resolve(
        self, candidate: EntityCandidate, repository: EntityRepository
    ) -> EntityRecord | None:
        name = candidate.reference.name
        if not name:
            return None
        entity = repository.find_entity_by_alias(
            candidate.reference.entity_type.value, normalize_name(name)
        )
        if (
            entity is not None
            and candidate.reference.identifier is not None
            and entity.identifier is not None
            and entity.identifier != candidate.reference.identifier
        ):
            return None
        return entity
