"""Safety helpers for files that may be opened by spreadsheet software."""
from __future__ import annotations

import re


_ILLEGAL_SPREADSHEET_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def spreadsheet_safe(value):
    """Force formula-like document text to remain literal spreadsheet data."""
    if not isinstance(value, str) or not value:
        return value
    value = _ILLEGAL_SPREADSHEET_CONTROLS.sub(
        lambda match: f"\\x{ord(match.group()):02x}", value
    )
    stripped = value.lstrip(" \t\r\n")
    if value[0] in "\t\r\n" or stripped.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value
