"""Configured regular-expression relationship extraction from normalized text blocks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from smart_lab_index.core.domain import (
    AssertionCandidate,
    DocumentContent,
    EntityCandidate,
    EntityReference,
    EntityType,
    ExtractionResult,
)
from smart_lab_index.core.modules import (
    ExtractorModule,
    FileAccess,
    ModuleCapability,
    ModuleDependency,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
)


class RuleBasedExtractor(ExtractorModule):
    manifest = ModuleManifest(
        module_id="extractor.rules",
        name="Rule-based Text Extractor",
        version="0.1.0",
        module_type=ModuleType.RELATIONSHIP_EXTRACTOR,
        description="Applies configured deterministic relationship patterns to text blocks.",
        dependencies=(
            ModuleDependency(capability="domain.extraction_rules", minimum_version="1.0.0"),
        ),
        capabilities=(
            ModuleCapability("extractor.entities", "1.0.0"),
            ModuleCapability("extractor.relationships", "1.0.0"),
        ),
        configuration_schema={
            "type": "object",
            "required": ["rule_ids"],
            "additionalProperties": False,
            "properties": {
                "rule_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def __init__(self, rules: Sequence[Mapping[str, Any]]) -> None:
        self.rules = tuple((dict(rule), re.compile(str(rule["pattern"]), re.IGNORECASE))
                           for rule in rules)
        super().__init__({"rule_ids": [str(rule[0]["rule_id"]) for rule in self.rules]})

    def extract(self, document: DocumentContent) -> ExtractionResult:
        entities = []
        assertions = []
        for block in document.text_blocks:
            for rule, pattern in self.rules:
                for match in pattern.finditer(block.text):
                    subject_value = match.group("subject").strip()
                    object_value = match.group("object").strip()
                    subject = EntityReference(
                        entity_type=EntityType(rule["subject_type"]),
                        name=subject_value,
                        identifier=subject_value if rule.get("subject_is_identifier") else None,
                    )
                    object_ref = EntityReference(
                        entity_type=EntityType(rule["object_type"]),
                        name=object_value,
                        identifier=object_value if rule.get("object_is_identifier") else None,
                    )
                    for reference in (subject, object_ref):
                        entities.append(EntityCandidate(
                            reference=reference,
                            subtype=None,
                            aliases=(),
                            provenance=block.provenance,
                            confidence=0.9,
                            extraction_method=f"rule:{rule['rule_id']}",
                            module_id=self.manifest.module_id,
                            module_version=self.manifest.version,
                        ))
                    assertions.append(AssertionCandidate(
                        subject=subject,
                        predicate=rule["predicate"],
                        object_ref=object_ref,
                        provenance=block.provenance,
                        confidence=0.9,
                        extraction_method=f"rule:{rule['rule_id']}",
                        module_id=self.manifest.module_id,
                        module_version=self.manifest.version,
                    ))
        return ExtractionResult(entities=tuple(entities), assertions=tuple(assertions))
