"""Exact identifier resolver."""

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


class IdentifierResolver(ResolverModule):
    order = 10
    manifest = ModuleManifest(
        module_id="resolver.identifier",
        name="Exact Identifier Resolver",
        version="0.1.0",
        module_type=ModuleType.RESOLVER,
        description="Resolves exact identifiers before less strict matching stages.",
        capabilities=(ModuleCapability("resolver.entity", "1.0.0"),),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def resolve(
        self, candidate: EntityCandidate, repository: EntityRepository
    ) -> EntityRecord | None:
        identifier = candidate.reference.identifier
        if not identifier:
            return None
        return repository.find_entity_by_identifier(
            candidate.reference.entity_type.value, identifier
        )
