"""Broad, customer-neutral terminology and deterministic rules for laboratories."""

from __future__ import annotations

from typing import Any

from smart_lab_index.core.modules import (
    DomainModule,
    FileAccess,
    ModuleCapability,
    ModuleManifest,
    ModuleType,
    NetworkAccess,
)


class GeneralLabDomain(DomainModule):
    manifest = ModuleManifest(
        module_id="domain.general_lab",
        name="General Laboratory Domain",
        version="0.1.0",
        module_type=ModuleType.DOMAIN,
        description="Broad laboratory terminology and deterministic extraction configuration.",
        capabilities=(
            ModuleCapability("domain.terminology", "1.0.0"),
            ModuleCapability("domain.extraction_rules", "1.0.0"),
        ),
        network_access=NetworkAccess.NONE,
        file_access=FileAccess.NONE,
    )

    def structured_rules(self) -> tuple[dict[str, Any], ...]:
        """Rules are data so customers can replace mappings without forking Core."""
        return (
            {
                "rule_id": "general-lab-locations-v1",
                "match_headers_any": ["location_id", "location_name", "room_id"],
                "match_all": ["location"],
                "fields": {
                    "location": ["location_id", "location", "location_name", "room_id"],
                    "name": ["name", "location_name"],
                    "subtype": ["subtype", "location_type", "type"],
                    "parent": ["parent", "parent_location", "parent_id"],
                },
                "entities": [
                    {
                        "ref": "location",
                        "type": "LOCATION",
                        "name_field": "name",
                        "identifier_field": "location",
                        "fallback_name_field": "location",
                        "subtype_field": "subtype",
                    },
                    {
                        "ref": "parent",
                        "type": "LOCATION",
                        "name_field": "parent",
                        "identifier_field": "parent",
                        "optional": True,
                    },
                ],
                "relationships": [
                    {
                        "subject_ref": "parent",
                        "predicate": "parent_of",
                        "object_ref": "location",
                        "optional": True,
                    }
                ],
            },
            {
                "rule_id": "general-lab-assets-v1",
                "match_headers_any": [
                    "asset_id",
                    "equipment_id",
                    "instrument_id",
                    "asset",
                    "equipment",
                ],
                "match_all": ["asset"],
                "fields": {
                    "asset": ["asset_id", "asset", "equipment_id", "equipment", "instrument_id"],
                    "name": ["name", "asset_name", "equipment_name", "instrument_name"],
                    "subtype": ["subtype", "asset_type", "equipment_type", "category", "type"],
                    "location": ["location", "location_id", "room"],
                },
                "entities": [
                    {
                        "ref": "asset",
                        "type": "ASSET",
                        "name_field": "name",
                        "identifier_field": "asset",
                        "fallback_name_field": "asset",
                        "subtype_field": "subtype",
                    },
                    {
                        "ref": "location",
                        "type": "LOCATION",
                        "name_field": "location",
                        "identifier_field": "location",
                        "optional": True,
                    },
                ],
                "relationships": [
                    {
                        "subject_ref": "asset",
                        "predicate": "located_in",
                        "object_ref": "location",
                        "optional": True,
                    }
                ],
            },
            {
                "rule_id": "general-lab-responsibilities-v1",
                "match_headers_any": [
                    "person",
                    "person_id",
                    "responsible_person",
                    "responsible",
                    "owner",
                ],
                "match_all": ["person", "asset"],
                "fields": {
                    "person": ["person", "responsible_person", "owner", "responsible"],
                    "person_id": ["person_id", "user_id"],
                    "asset": ["asset_id", "asset", "equipment_id", "equipment", "instrument_id"],
                    "relationship": ["relationship", "predicate", "role"],
                },
                "entities": [
                    {
                        "ref": "person",
                        "type": "PERSON",
                        "name_field": "person",
                        "identifier_field": "person_id",
                    },
                    {
                        "ref": "asset",
                        "type": "ASSET",
                        "name_field": "asset",
                        "identifier_field": "asset",
                    },
                ],
                "relationships": [
                    {
                        "subject_ref": "person",
                        "predicate": "responsible_for",
                        "predicate_field": "relationship",
                        "predicate_map": {
                            "responsible_for": "responsible_for",
                            "responsible for": "responsible_for",
                            "owner": "owns",
                            "owns": "owns",
                            "backup_for": "backup_for",
                            "backup for": "backup_for",
                        },
                        "object_ref": "asset",
                    }
                ],
            },
        )

    def text_relationship_rules(self) -> tuple[dict[str, Any], ...]:
        return ({
            "rule_id": "general-lab-located-in-text-v1",
            "pattern": (
                r"(?P<subject>[A-Za-z0-9][A-Za-z0-9._ -]{0,100}?)\s+"
                r"(?:is\s+)?located[ _]in\s+"
                r"(?P<object>[A-Za-z0-9][A-Za-z0-9._ -]{0,100}?)"
                r"(?:[.;]|$)"
            ),
            "subject_type": "ASSET",
            "object_type": "LOCATION",
            "predicate": "located_in",
            "subject_is_identifier": True,
            "object_is_identifier": True,
        },)
