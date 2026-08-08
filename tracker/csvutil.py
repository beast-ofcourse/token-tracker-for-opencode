"""Shared CSV helpers for the OpenCode Token Tracker (T-015/T-017).

Used by both the API CSV export (`/api/export.csv`) and the CLI `sessions
--csv` writer so the injection guard lives in exactly one place.
"""

from __future__ import annotations


def csv_safe(value) -> str:
    """Stringify a CSV cell, prefixing a quote when it starts with `=`, `+`, `-`, or `@`.

    Guards against CSV injection: a leading quote makes spreadsheet apps
    treat the cell as text instead of a formula.
    """
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text