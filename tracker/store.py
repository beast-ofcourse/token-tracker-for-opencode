"""Session and message models plus parsing for the OpenCode Token Tracker (T-005).

Reads the OpenCode `session`, `project`, and `message` tables (schema in the
shared contract, tests/conftest.py) into typed dataclasses. All queries are
read-only; callers pass a connection from `tracker.db.open_connection` (or a
plain `sqlite3` connection in tests).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

#: Token bucket keys shared by Session and Message.
TOKEN_KEYS = ("input", "output", "reasoning", "cache_read", "cache_write")


@dataclass
class Session:
    """One row of the `session` table, with the model JSON parsed."""

    id: str
    project_id: str | None
    title: str | None
    model_key: str  # "provider/model", or "unknown"
    model_variant: str | None
    agent: str | None
    cost_db: float
    tokens: dict[str, int]
    created_ms: int
    updated_ms: int
    archived_ms: int | None


@dataclass
class Message:
    """One row of the `message` table, with the data JSON parsed."""

    id: str
    role: str | None
    model_key: str
    tokens: dict[str, int]
    cost: float
    finish: str | None


def parse_model(model_json: str | None) -> tuple[str, str | None]:
    """Parse a `session.model` JSON blob into `(provider/model, variant)`.

    Returns `("unknown", None)` for NULL, unparseable JSON, or JSON without
    usable string `id`/`providerID` fields.
    """
    if model_json is None:
        return ("unknown", None)
    try:
        data = json.loads(model_json)
    except (json.JSONDecodeError, TypeError):
        return ("unknown", None)
    if not isinstance(data, dict):
        return ("unknown", None)
    provider = data.get("providerID")
    model_id = data.get("id")
    if not isinstance(provider, str) or not provider:
        return ("unknown", None)
    if not isinstance(model_id, str) or not model_id:
        return ("unknown", None)
    variant = data.get("variant")
    return (f"{provider}/{model_id}", variant if isinstance(variant, str) else None)


def _row_to_session(row: sqlite3.Row) -> Session:
    """Convert a `session` SELECT row into a Session."""
    model_key, model_variant = parse_model(row["model"])
    return Session(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        model_key=model_key,
        model_variant=model_variant,
        agent=row["agent"],
        cost_db=row["cost"] or 0.0,
        tokens={
            "input": row["tokens_input"] or 0,
            "output": row["tokens_output"] or 0,
            "reasoning": row["tokens_reasoning"] or 0,
            "cache_read": row["tokens_cache_read"] or 0,
            "cache_write": row["tokens_cache_write"] or 0,
        },
        created_ms=row["time_created"] or 0,
        updated_ms=row["time_updated"] or 0,
        archived_ms=row["time_archived"],
    )


def _is_empty_session(row: sqlite3.Row) -> bool:
    """True for an aborted session: NULL model and all five token buckets 0."""
    return row["model"] is None and not any(
        row[k]
        for k in (
            "tokens_input",
            "tokens_output",
            "tokens_reasoning",
            "tokens_cache_read",
            "tokens_cache_write",
        )
    )


_SESSION_COLUMNS = (
    "id, project_id, title, model, agent, cost,"
    " tokens_input, tokens_output, tokens_reasoning, tokens_cache_read,"
    " tokens_cache_write, time_created, time_updated, time_archived"
)


def fetch_sessions(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    q: str | None = None,
    from_ms: int | None = None,
    to_ms: int | None = None,
    include_empty: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[Session]:
    """Fetch sessions ordered by `time_updated DESC`, with optional filters.

    The project_id, agent, `q` (title substring, case-insensitive and
    literal), and time_created range filters run in SQL. The `model` filter
    runs in Python on the parsed `model_key` (exact match — the stored JSON
    has no `/` between provider and id, so LIKE on the column cannot work).
    `limit`/`offset` are applied in Python AFTER the model filter, so
    pagination never silently skips matching rows. Empty sessions (NULL
    model, all tokens 0) are excluded unless `include_empty=True`.
    """
    where: list[str] = []
    params: list = []
    if project is not None:
        where.append("project_id = ?")
        params.append(project)
    if agent is not None:
        where.append("agent = ?")
        params.append(agent)
    if q is not None:
        # instr() treats the pattern literally (no LIKE wildcards), and
        # lower() on both sides makes the match case-insensitive.
        where.append("instr(lower(title), lower(?)) > 0")
        params.append(q)
    if from_ms is not None:
        where.append("time_created >= ?")
        params.append(from_ms)
    if to_ms is not None:
        where.append("time_created <= ?")
        params.append(to_ms)

    sql = f"SELECT {_SESSION_COLUMNS} FROM session"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # id ASC tiebreaker keeps pagination deterministic on equal timestamps.
    sql += " ORDER BY time_updated DESC, id ASC"

    sessions: list[Session] = []
    for row in conn.execute(sql, params).fetchall():
        session = _row_to_session(row)
        if model is not None and session.model_key != model:
            continue
        if not include_empty and _is_empty_session(row):
            continue
        sessions.append(session)

    if offset:
        sessions = sessions[offset:]
    if limit is not None:
        sessions = sessions[:limit]
    return sessions


def fetch_session(conn: sqlite3.Connection, session_id: str) -> Session | None:
    """Look up one session by id, or None. Includes empty/aborted sessions by construction."""
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM session WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_session(row) if row is not None else None


def fetch_projects(conn: sqlite3.Connection) -> dict[str, str]:
    """Map `project_id` to its worktree path, falling back to the name."""
    return {
        row["id"]: row["worktree"] or row["name"]
        for row in conn.execute("SELECT id, worktree, name FROM project").fetchall()
    }


def fetch_messages(conn: sqlite3.Connection, session_id: str) -> list[Message]:
    """Fetch a session's messages in insertion order (rowid ASC).

    The `message` table has no timestamp column, so ordering falls back to
    rowid (insertion order). Rows whose `data` JSON has no `tokens` object
    are skipped.
    """
    messages: list[Message] = []
    rows = conn.execute(
        "SELECT id, data FROM message WHERE session_id = ? ORDER BY rowid ASC",
        (session_id,),
    ).fetchall()
    for row in rows:
        try:
            data = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        tokens = data.get("tokens")
        if not isinstance(tokens, dict):
            continue
        cache = tokens.get("cache")
        if not isinstance(cache, dict):
            cache = {}
        model_id = data.get("modelID")
        provider = data.get("providerID")
        if isinstance(model_id, str) and model_id and isinstance(provider, str) and provider:
            model_key = f"{provider}/{model_id}"
        else:
            model_key = "unknown"
        messages.append(
            Message(
                id=row["id"],
                role=data.get("role"),
                model_key=model_key,
                tokens={
                    "input": tokens.get("input") or 0,
                    "output": tokens.get("output") or 0,
                    "reasoning": tokens.get("reasoning") or 0,
                    "cache_read": cache.get("read") or 0,
                    "cache_write": cache.get("write") or 0,
                },
                cost=data.get("cost") or 0.0,
                finish=data.get("finish"),
            )
        )
    return messages