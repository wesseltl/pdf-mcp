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
        version="0.2.0",
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
                "match_headers_any": [
                    "location_id", "location_name", "room_id", "room_number",
                    "room_name", "site_id", "building_id",
                ],
                "match_all": ["location"],
                "fields": {
                    "location": [
                        "location_id", "location", "location_name", "room_id",
                        "room_number", "room_name", "site_id", "building_id",
                    ],
                    "name": ["name", "location_name", "room_name", "site_name", "building_name"],
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
                        "alias_fields": ["name"],
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
                    "asset_tag",
                    "inventory_number",
                    "inventory_no",
                    "equipment_number",
                    "equipment_no",
                    "instrument_number",
                    "instrument_no",
                    "device_id",
                    "tag_number",
                ],
                "match_all": ["asset"],
                "fields": {
                    "asset": [
                        "asset_id", "asset", "asset_tag", "inventory_number", "inventory_no",
                        "equipment_id", "equipment", "equipment_number", "equipment_no",
                        "instrument_id", "instrument_number", "instrument_no", "device_id",
                        "tag_number",
                    ],
                    "name": ["name", "asset_name", "equipment_name", "instrument_name"],
                    "subtype": ["subtype", "asset_type", "equipment_type", "category", "type"],
                    "location": [
                        "location", "location_id", "room", "room_number", "room_name",
                        "storage_location",
                    ],
                    "serial_number": ["serial_number", "serial_no", "serial", "s_n"],
                    "manufacturer": ["manufacturer", "make", "vendor"],
                    "model": ["model", "model_number", "model_no"],
                    "status": ["status", "state", "equipment_status"],
                    "calibration_due": [
                        "calibration_due", "next_calibration", "next_calibration_date",
                    ],
                    "maintenance_due": [
                        "maintenance_due", "service_due", "next_service", "next_maintenance",
                    ],
                },
                "entities": [
                    {
                        "ref": "asset",
                        "type": "ASSET",
                        "name_field": "name",
                        "identifier_field": "asset",
                        "fallback_name_field": "asset",
                        "subtype_field": "subtype",
                        "alias_fields": ["name"],
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
                "literals": [
                    {"subject_ref": "asset", "predicate": "serial_number", "field": "serial_number"},
                    {"subject_ref": "asset", "predicate": "manufacturer", "field": "manufacturer"},
                    {"subject_ref": "asset", "predicate": "model", "field": "model"},
                    {"subject_ref": "asset", "predicate": "status", "field": "status"},
                    {"subject_ref": "asset", "predicate": "calibration_due", "field": "calibration_due"},
                    {"subject_ref": "asset", "predicate": "maintenance_due", "field": "maintenance_due"},
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
                    "asset": [
                        "asset_id", "asset", "asset_tag", "equipment_id", "equipment",
                        "equipment_number", "instrument_id", "instrument_number", "device_id",
                    ],
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
            {
                "rule_id": "general-lab-people-v1",
                "match_headers_any": [
                    "person", "person_name", "employee", "employee_name", "email",
                ],
                "match_all": ["person"],
                "fields": {
                    "person": ["person", "person_name", "name", "employee", "employee_name"],
                    "person_id": ["person_id", "employee_id", "user_id", "email"],
                    "email": ["email", "email_address"],
                    "title": ["title", "job_title", "role"],
                    "unit": ["department", "department_name", "unit", "team", "group"],
                },
                "entities": [
                    {
                        "ref": "person",
                        "type": "PERSON",
                        "name_field": "person",
                        "identifier_field": "person_id",
                        "alias_fields": ["email"],
                    },
                    {
                        "ref": "unit",
                        "type": "ORGANIZATIONAL_UNIT",
                        "name_field": "unit",
                        "identifier_field": "unit",
                        "optional": True,
                    },
                ],
                "relationships": [
                    {
                        "subject_ref": "person",
                        "predicate": "member_of",
                        "object_ref": "unit",
                        "optional": True,
                    }
                ],
                "literals": [
                    {"subject_ref": "person", "predicate": "email", "field": "email"},
                    {"subject_ref": "person", "predicate": "job_title", "field": "title"},
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
