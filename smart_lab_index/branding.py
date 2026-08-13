"""Stable product identity shared by runtime and release tooling."""

from __future__ import annotations

PRODUCT_NAME = "LabOverlay"
PRODUCT_SLUG = "laboverlay"
PRODUCT_DESCRIPTION = "The local-first knowledge layer for laboratories."
CLI_NAME = PRODUCT_SLUG
APP_CLI_NAME = f"{PRODUCT_SLUG}-app"

# These identifiers remain supported so existing installations and integrations work.
LEGACY_PRODUCT_NAME = "Smart Lab Index"
LEGACY_PRODUCT_SLUG = "smart-lab-index"
