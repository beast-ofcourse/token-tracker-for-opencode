"""Shared CSV helpers for the OpenCode Token Tracker (T-015/T-017).

Used by both the API CSV export (`/api/export.csv`) and the CLI `sessions
--csv` writer so the injection guard lives in exactly one place.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from tracker.config import Price
from tracker.pricing import compute_cost


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


def render_sessions_csv(sessions, projects: dict[str, str], pricing: dict[str, Price]) -> str:
    """Render sessions to CSV with the shared columns and injection guard.

    Used by both ``/api/export.csv`` and ``tracker sessions --csv`` so the
    column order, formatting, and injection guard live in exactly one place.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id", "title", "project", "model", "agent", "created_at", "updated_at",
            "tokens_input", "tokens_output", "tokens_reasoning",
            "tokens_cache_read", "tokens_cache_write", "cost", "unpriced",
        ]
    )
    for session in sessions:
        cost, unpriced = compute_cost(session, pricing)
        created = datetime.fromtimestamp(session.created_ms / 1000, tz=timezone.utc)
        updated = datetime.fromtimestamp(session.updated_ms / 1000, tz=timezone.utc)
        tokens = session.tokens
        writer.writerow(
            [
                csv_safe(session.id),
                csv_safe(session.title),
                csv_safe(projects.get(session.project_id)),
                csv_safe(session.model_key),
                csv_safe(session.agent),
                csv_safe(created.isoformat()),
                csv_safe(updated.isoformat()),
                tokens.get("input", 0),
                tokens.get("output", 0),
                tokens.get("reasoning", 0),
                tokens.get("cache_read", 0),
                tokens.get("cache_write", 0),
                f"{cost:.4f}",
                "true" if unpriced else "false",
            ]
        )
    return buffer.getvalue()