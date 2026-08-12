"""Stable identity normalization owned by LabOverlay Core."""

from __future__ import annotations

import re
import unicodedata


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", normalized)
