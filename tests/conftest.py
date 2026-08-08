"""Shared pytest fixtures for the OpenCode Token Tracker test suite.

`fixture_db` builds a small synthetic OpenCode SQLite database at
`tmp_path/opencode.db` matching the shared schema contract (tables
`session`, `project`, `message`; only the columns listed there).
`fixture_config` is a plain helper (not a pytest fixture) returning a
`Config` whose `db_path` points at that database and whose pricing
includes `openai/gpt-4o` at known per-1M prices.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tracker.config import Budget, Config, DEFAULT_PRICING, Price, Severity

# --- Model JSON blobs (as stored in the `session.model` column) -----------

MODEL_FREE = {"id": "deepseek-v4-flash-free", "providerID": "opencode", "variant": "high"}
MODEL_GPT4O = {"id": "gpt-4o", "providerID": "openai", "variant": "high"}
MODEL_GPT4O_MINI = {"id": "gpt-4o-mini", "providerID": "openai", "variant": "high"}
MODEL_SONNET = {"id": "claude-sonnet-4", "providerID": "anthropic", "variant": "high"}
MODEL_OPUS = {"id": "claude-opus-4", "providerID": "anthropic", "variant": "high"}
MODEL_GEMINI = {"id": "gemini-2.5-pro", "providerID": "google", "variant": "high"}
MODEL_DEEPSEEK = {"id": "deepseek-chat", "providerID": "deepseek", "variant": "high"}


def _ms(year: int, month: int, day: int, hour: int = 12) -> int:
    """Epoch milliseconds for a UTC datetime (timestamps are stored in ms)."""
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


_SCHEMA = """
CREATE TABLE session (
    id TEXT,
    project_id TEXT,
    title TEXT,
    model TEXT,
    agent TEXT,
    cost REAL,
    tokens_input INTEGER,
    tokens_output INTEGER,
    tokens_reasoning INTEGER,
    tokens_cache_read INTEGER,
    tokens_cache_write INTEGER,
    time_created INTEGER,
    time_updated INTEGER,
    time_archived INTEGER
);

CREATE TABLE project (
    id TEXT,
    worktree TEXT,
    name TEXT
);

CREATE TABLE message (
    id TEXT,
    session_id TEXT,
    data TEXT
);
"""

_PROJECTS = [
    {"id": "proj-global", "worktree": "/", "name": "global"},
    {"id": "proj-web-app", "worktree": r"C:\Users\Bhavin\projects\web-app", "name": "web-app"},
    {"id": "proj-cli", "worktree": r"C:\Users\Bhavin\projects\cli", "name": "cli"},
]

# 12 sessions spanning two calendar months (June and July 2026), including:
# free-model sessions, paid gpt-4o sessions, an empty/aborted session
# (NULL model, all tokens 0), a session with NULL agent, and token counts
# in the millions.
_SESSIONS = [
    {
        "id": "sess-001",
        "project_id": "proj-global",
        "title": "Fix login redirect",
        "model": MODEL_FREE,
        "agent": "build",
        "cost": 0.0,
        "tokens_input": 1_250_000,
        "tokens_output": 85_000,
        "tokens_reasoning": 120_000,
        "tokens_cache_read": 3_400_000,
        "tokens_cache_write": 120_000,
        "time_created": _ms(2026, 6, 3, 9),
        "time_updated": _ms(2026, 6, 3, 11),
        "time_archived": None,
    },
    {
        "id": "sess-002",
        "project_id": "proj-global",
        "title": "Add API design",
        "model": MODEL_GPT4O,
        "agent": "architect",
        "cost": 2.75,
        "tokens_input": 500_000,
        "tokens_output": 120_000,
        "tokens_reasoning": 0,
        "tokens_cache_read": 1_000_000,
        "tokens_cache_write": 50_000,
        "time_created": _ms(2026, 6, 5, 14),
        "time_updated": _ms(2026, 6, 5, 16),
        "time_archived": _ms(2026, 6, 7, 10),
    },
    {
        "id": "sess-003",
        "project_id": "proj-global",
        "title": "Aborted session",
        "model": None,
        "agent": None,
        "cost": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
        "tokens_cache_read": 0,
        "tokens_cache_write": 0,
        "time_created": _ms(2026, 6, 7, 8),
        "time_updated": _ms(2026, 6, 7, 8),
        "time_archived": None,
    },
    {
        "id": "sess-004",
        "project_id": "proj-web-app",
        "title": "Refactor checkout flow",
        "model": MODEL_SONNET,
        "agent": None,
        "cost": 0.0,
        "tokens_input": 2_100_000,
        "tokens_output": 320_000,
        "tokens_reasoning": 150_000,
        "tokens_cache_read": 5_000_000,
        "tokens_cache_write": 120_000,
        "time_created": _ms(2026, 6, 10, 10),
        "time_updated": _ms(2026, 6, 10, 13),
        "time_archived": None,
    },
    {
        "id": "sess-005",
        "project_id": "proj-web-app",
        "title": "Fix chat bug",
        "model": MODEL_DEEPSEEK,
        "agent": "build",
        "cost": 0.0,
        "tokens_input": 800_000,
        "tokens_output": 60_000,
        "tokens_reasoning": 0,
        "tokens_cache_read": 900_000,
        "tokens_cache_write": 30_000,
        "time_created": _ms(2026, 6, 14, 15),
        "time_updated": _ms(2026, 6, 14, 16),
        "time_archived": None,
    },
    {
        "id": "sess-006",
        "project_id": "proj-global",
        "title": "Bulk import helper",
        "model": MODEL_GPT4O_MINI,
        "agent": "build",
        "cost": 0.0,
        "tokens_input": 3_200_000,
        "tokens_output": 410_000,
        "tokens_reasoning": 0,
        "tokens_cache_read": 6_000_000,
        "tokens_cache_write": 200_000,
        "time_created": _ms(2026, 6, 18, 9),
        "time_updated": _ms(2026, 6, 18, 12),
        "time_archived": None,
    },
    {
        "id": "sess-007",
        "project_id": "proj-cli",
        "title": "Add --json flag",
        "model": MODEL_FREE,
        "agent": "build",
        "cost": 0.0,
        "tokens_input": 950_000,
        "tokens_output": 120_000,
        "tokens_reasoning": 300_000,
        "tokens_cache_read": 1_500_000,
        "tokens_cache_write": 80_000,
        "time_created": _ms(2026, 6, 22, 11),
        "time_updated": _ms(2026, 6, 22, 13),
        "time_archived": None,
    },
    {
        "id": "sess-008",
        "project_id": "proj-global",
        "title": "Migrate to pydantic v2",
        "model": MODEL_GEMINI,
        "agent": "architect",
        "cost": 0.0,
        "tokens_input": 1_800_000,
        "tokens_output": 250_000,
        "tokens_reasoning": 90_000,
        "tokens_cache_read": 4_200_000,
        "tokens_cache_write": 150_000,
        "time_created": _ms(2026, 6, 27, 9),
        "time_updated": _ms(2026, 6, 27, 11),
        "time_archived": None,
    },
    {
        "id": "sess-009",
        "project_id": "proj-web-app",
        "title": "Checkout perf pass",
        "model": MODEL_GPT4O,
        "agent": "build",
        "cost": 0.0,
        "tokens_input": 4_500_000,
        "tokens_output": 620_000,
        "tokens_reasoning": 0,
        "tokens_cache_read": 8_000_000,
        "tokens_cache_write": 350_000,
        "time_created": _ms(2026, 7, 2, 10),
        "time_updated": _ms(2026, 7, 2, 14),
        "time_archived": None,
    },
    {
        "id": "sess-010",
        "project_id": "proj-global",
        "title": "Tidy open issues",
        "model": MODEL_FREE,
        "agent": "build",
        "cost": 0.0,
        "tokens_input": 1_100_000,
        "tokens_output": 95_000,
        "tokens_reasoning": 180_000,
        "tokens_cache_read": 2_800_000,
        "tokens_cache_write": 60_000,
        "time_created": _ms(2026, 7, 5, 9),
        "time_updated": _ms(2026, 7, 5, 10),
        "time_archived": None,
    },
    {
        "id": "sess-011",
        "project_id": "proj-cli",
        "title": "Design plugin API",
        "model": MODEL_OPUS,
        "agent": "architect",
        "cost": 0.0,
        "tokens_input": 2_600_000,
        "tokens_output": 480_000,
        "tokens_reasoning": 220_000,
        "tokens_cache_read": 6_500_000,
        "tokens_cache_write": 280_000,
        "time_created": _ms(2026, 7, 9, 13),
        "time_updated": _ms(2026, 7, 9, 17),
        "time_archived": None,
    },
    {
        "id": "sess-012",
        "project_id": "proj-web-app",
        "title": "Update dependencies",
        "model": MODEL_DEEPSEEK,
        "agent": "build",
        "cost": 0.0,
        "tokens_input": 700_000,
        "tokens_output": 55_000,
        "tokens_reasoning": 0,
        "tokens_cache_read": 1_200_000,
        "tokens_cache_write": 40_000,
        "time_created": _ms(2026, 7, 15, 9),
        "time_updated": _ms(2026, 7, 15, 10),
        "time_archived": None,
    },
]

# Two message rows referencing the paid session sess-002 (per-message
# token breakdown for the gpt-4o session).
_MESSAGES = [
    {
        "id": "msg-001",
        "session_id": "sess-002",
        "data": {
            "role": "user",
            "tokens": {
                "total": 1500,
                "input": 1200,
                "output": 300,
                "reasoning": 0,
                "cache": {"read": 800, "write": 100},
            },
            "cost": 0.0042,
            "modelID": "gpt-4o",
            "providerID": "openai",
            "finish": None,
        },
    },
    {
        "id": "msg-002",
        "session_id": "sess-002",
        "data": {
            "role": "assistant",
            "tokens": {
                "total": 900,
                "input": 0,
                "output": 900,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
            "cost": 0.00225,
            "modelID": "gpt-4o",
            "providerID": "openai",
            "finish": "stop",
        },
    },
]


def _build_database(db_path: Path) -> None:
    """Create the synthetic OpenCode database at `db_path`, overwriting any existing file."""
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.executemany(
            "INSERT INTO project (id, worktree, name) VALUES (:id, :worktree, :name)",
            _PROJECTS,
        )
        session_rows = [
            {**s, "model": json.dumps(s["model"]) if s["model"] is not None else None}
            for s in _SESSIONS
        ]
        conn.executemany(
            """INSERT INTO session (id, project_id, title, model, agent, cost,
               tokens_input, tokens_output, tokens_reasoning, tokens_cache_read,
               tokens_cache_write, time_created, time_updated, time_archived)
               VALUES (:id, :project_id, :title, :model, :agent, :cost,
               :tokens_input, :tokens_output, :tokens_reasoning, :tokens_cache_read,
               :tokens_cache_write, :time_created, :time_updated, :time_archived)""",
            session_rows,
        )
        conn.executemany(
            "INSERT INTO message (id, session_id, data) VALUES (:id, :session_id, :data)",
            [
                {"id": m["id"], "session_id": m["session_id"], "data": json.dumps(m["data"])}
                for m in _MESSAGES
            ],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fixture_db(tmp_path):
    """Build the synthetic OpenCode database and return its path."""
    db_path = tmp_path / "opencode.db"
    _build_database(db_path)
    return db_path


def fixture_config(tmp_path):
    """Return a Config pointing at a freshly built fixture database.

    Pricing includes `openai/gpt-4o` at known per-1M prices
    (input 2.50, output 10.00, cache_read 1.25, cache_write 2.50).
    """
    db_path = tmp_path / "opencode.db"
    _build_database(db_path)
    pricing = dict(DEFAULT_PRICING)
    pricing["openai/gpt-4o"] = Price(input=2.50, output=10.00, cache_read=1.25, cache_write=2.50)
    return Config(
        db_path=db_path,
        budget=Budget(monthly=20.0, currency="USD", reset_day=1),
        severity=Severity(high_cost=5.0, med_cost=1.0),
        pricing=pricing,
        server_host="127.0.0.1",
        server_port=8765,
        refresh_seconds=30,
    )