"""Deterministic entity resolver modules."""

from smart_lab_index.modules.resolvers.alias import AliasResolver
from smart_lab_index.modules.resolvers.identifier import IdentifierResolver
from smart_lab_index.modules.resolvers.normalized_name import NormalizedNameResolver

__all__ = ["AliasResolver", "IdentifierResolver", "NormalizedNameResolver"]
