"""Tests for tracker.store (T-005 session model and parsing)."""

import json
import sqlite3
from datetime import datetime, timezone

from tracker.store import (
    Message,
    Session,
    fetch_messages,
    fetch_projects,
    fetch_session,
    fetch_sessions,
    parse_model,
)

MODEL_FREE_JSON = json.dumps(
    {"id": "deepseek-v4-flash-free", "providerID": "opencode", "variant": "high"}
)
from conftest import row_conn


def _ms(year: int, month: int, day: int, hour: int = 12) -> int:
    """Epoch milliseconds for a UTC datetime (fixture timestamps are in ms)."""
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def _conn(fixture_db) -> sqlite3.Connection:
    return row_conn(fixture_db)


# --- parse_model -----------------------------------------------------------


def test_parse_model_real_model_json():
    assert parse_model(MODEL_FREE_JSON) == ("opencode/deepseek-v4-flash-free", "high")


def test_parse_model_null_is_unknown():
    assert parse_model(None) == ("unknown", None)


def test_parse_model_missing_variant():
    assert parse_model('{"id": "gpt-4o", "providerID": "openai"}') == ("openai/gpt-4o", None)


def test_parse_model_unparseable_is_unknown():
    for bad in ("", "not json", "{}", '{"id": "x"}', '{"providerID": "p"}',
                "[1, 2]", '{"id": 5, "providerID": "p"}', '{"id": "x", "providerID": ""}'):
        assert parse_model(bad) == ("unknown", None)


# --- fetch_sessions --------------------------------------------------------


def test_fetch_sessions_model_keys_for_free_and_paid(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn)
    finally:
        conn.close()
    by_id = {s.id: s for s in sessions}
    assert isinstance(by_id["sess-001"], Session)
    assert by_id["sess-001"].model_key == "opencode/deepseek-v4-flash-free"
    assert by_id["sess-001"].model_variant == "high"
    assert by_id["sess-001"].cost_db == 0.0
    assert by_id["sess-001"].tokens == {
        "input": 1_250_000,
        "output": 85_000,
        "reasoning": 120_000,
        "cache_read": 3_400_000,
        "cache_write": 120_000,
    }
    assert by_id["sess-002"].model_key == "openai/gpt-4o"
    assert by_id["sess-002"].model_variant == "high"
    assert by_id["sess-002"].cost_db == 2.75


def test_fetch_sessions_timestamps(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn)
    finally:
        conn.close()
    by_id = {s.id: s for s in sessions}
    assert by_id["sess-001"].created_ms == _ms(2026, 6, 3, 9)
    assert by_id["sess-001"].updated_ms == _ms(2026, 6, 3, 11)
    assert by_id["sess-001"].archived_ms is None
    assert by_id["sess-002"].archived_ms == _ms(2026, 6, 7, 10)


def test_fetch_sessions_excludes_empty_by_default(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn)
        assert "sess-003" not in {s.id for s in sessions}
        with_empty = fetch_sessions(conn, include_empty=True)
    finally:
        conn.close()
    assert "sess-003" in {s.id for s in with_empty}
    empty = next(s for s in with_empty if s.id == "sess-003")
    assert empty.model_key == "unknown"
    assert empty.model_variant is None
    assert empty.agent is None
    assert empty.tokens == {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}


def test_fetch_sessions_orders_by_updated_desc(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn)
    finally:
        conn.close()
    assert [s.id for s in sessions] == [
        "sess-012", "sess-011", "sess-010", "sess-009", "sess-008",
        "sess-007", "sess-006", "sess-005", "sess-004", "sess-002",
        "sess-001",
    ]


def test_fetch_sessions_filter_by_project(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn, project="proj-web-app")
    finally:
        conn.close()
    assert {s.id for s in sessions} == {"sess-004", "sess-005", "sess-009", "sess-012"}


def test_fetch_sessions_filter_by_model(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn, model="opencode/deepseek-v4-flash-free")
    finally:
        conn.close()
    assert [s.id for s in sessions] == ["sess-010", "sess-007", "sess-001"]


def test_fetch_sessions_filter_by_agent(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn, agent="architect")
    finally:
        conn.close()
    assert {s.id for s in sessions} == {"sess-002", "sess-008", "sess-011"}


def test_fetch_sessions_filter_by_date_range(fixture_db):
    conn = _conn(fixture_db)
    try:
        july = fetch_sessions(conn, from_ms=_ms(2026, 7, 1, 0))
        june = fetch_sessions(conn, to_ms=_ms(2026, 6, 30, 23))
        both = fetch_sessions(conn, from_ms=_ms(2026, 6, 10, 0), to_ms=_ms(2026, 6, 22, 23))
    finally:
        conn.close()
    assert {s.id for s in july} == {"sess-009", "sess-010", "sess-011", "sess-012"}
    # sess-003 is empty and excluded even though it falls in the range.
    assert {s.id for s in june} == {
        "sess-001", "sess-002", "sess-004", "sess-005", "sess-006", "sess-007", "sess-008",
    }
    assert {s.id for s in both} == {"sess-004", "sess-005", "sess-006", "sess-007"}


def test_fetch_sessions_q_filter_case_insensitive(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn, q="CHECKOUT")
    finally:
        conn.close()
    assert {s.id for s in sessions} == {"sess-004", "sess-009"}


def test_fetch_sessions_q_filter_is_literal(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(conn, q="%")
    finally:
        conn.close()
    assert sessions == []


def test_fetch_sessions_combined_filters(fixture_db):
    conn = _conn(fixture_db)
    try:
        sessions = fetch_sessions(
            conn,
            project="proj-global",
            agent="build",
            model="opencode/deepseek-v4-flash-free",
        )
    finally:
        conn.close()
    assert {s.id for s in sessions} == {"sess-001", "sess-010"}


def test_fetch_sessions_model_filter_with_limit_and_offset(fixture_db):
    conn = _conn(fixture_db)
    try:
        page1 = fetch_sessions(conn, model="opencode/deepseek-v4-flash-free", limit=2)
        page2 = fetch_sessions(conn, model="opencode/deepseek-v4-flash-free", limit=2, offset=2)
    finally:
        conn.close()
    # 3 free-model sessions exist; limit must apply AFTER the model filter.
    assert [s.id for s in page1] == ["sess-010", "sess-007"]
    assert [s.id for s in page2] == ["sess-001"]


# --- fetch_projects --------------------------------------------------------


def test_fetch_projects_maps_worktree(fixture_db):
    conn = _conn(fixture_db)
    try:
        projects = fetch_projects(conn)
    finally:
        conn.close()
    assert projects["proj-global"] == "/"
    assert projects["proj-web-app"] == r"C:\Users\Bhavin\projects\web-app"
    assert projects["proj-cli"] == r"C:\Users\Bhavin\projects\cli"


def test_fetch_projects_falls_back_to_name(fixture_db):
    conn = _conn(fixture_db)
    try:
        conn.execute(
            "INSERT INTO project (id, worktree, name) VALUES ('proj-null', NULL, 'null-name')"
        )
        conn.commit()
        projects = fetch_projects(conn)
    finally:
        conn.close()
    assert projects["proj-null"] == "null-name"


# --- fetch_messages --------------------------------------------------------


def test_fetch_messages_parses_fixture(fixture_db):
    conn = _conn(fixture_db)
    try:
        messages = fetch_messages(conn, "sess-002")
    finally:
        conn.close()
    assert [m.id for m in messages] == ["msg-001", "msg-002"]
    assert all(isinstance(m, Message) for m in messages)

    first, second = messages
    assert first.role == "user"
    assert first.model_key == "openai/gpt-4o"
    assert first.tokens == {
        "input": 1200, "output": 300, "reasoning": 0, "cache_read": 800, "cache_write": 100,
    }
    assert first.cost == 0.0042
    assert first.finish is None

    assert second.role == "assistant"
    assert second.model_key == "openai/gpt-4o"
    assert second.tokens == {
        "input": 0, "output": 900, "reasoning": 0, "cache_read": 0, "cache_write": 0,
    }
    assert second.cost == 0.00225
    assert second.finish == "stop"


def test_fetch_messages_skips_rows_without_tokens(fixture_db):
    conn = _conn(fixture_db)
    try:
        conn.execute(
            "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
            ("msg-003", "sess-002", json.dumps({"role": "user", "cost": 0.0})),
        )
        conn.execute(
            "INSERT INTO message (id, session_id, data) VALUES (?, ?, ?)",
            ("msg-004", "sess-002", "not json"),
        )
        conn.commit()
        messages = fetch_messages(conn, "sess-002")
    finally:
        conn.close()
    assert [m.id for m in messages] == ["msg-001", "msg-002"]


def test_fetch_messages_unknown_session(fixture_db):
    conn = _conn(fixture_db)
    try:
        assert fetch_messages(conn, "no-such-session") == []
    finally:
        conn.close()


def test_null_time_created_treated_as_epoch_zero_and_excluded_from_ranges(fixture_db):
    """T-016: NULL time_created -> 0; a date-range filter excludes it."""
    conn = _conn(fixture_db)
    try:
        conn.execute(
            "INSERT INTO session (id, project_id, title, model, agent, cost,"
            " tokens_input, tokens_output, tokens_reasoning, tokens_cache_read,"
            " tokens_cache_write, time_created, time_updated, time_archived)"
            " VALUES ('sess-null-ts', 'proj-a', 'no timestamp', NULL, NULL, 0,"
            " 100, 0, 0, 0, 0, NULL, 0, NULL)"
        )
        conn.commit()
        all_sessions = fetch_sessions(conn, include_empty=True)
        null_ts = next(s for s in all_sessions if s.id == "sess-null-ts")
        assert null_ts.created_ms == 0
        ranged = fetch_sessions(conn, from_ms=1_700_000_000_000)
        assert all(s.id != "sess-null-ts" for s in ranged)
    finally:
        conn.close()


# --- fetch_session (direct id lookup) ---------------------------------------


def test_fetch_session_returns_matching_session(fixture_db):
    conn = _conn(fixture_db)
    try:
        session = fetch_session(conn, "sess-002")
    finally:
        conn.close()
    assert session is not None
    assert session.id == "sess-002"
    assert session.model_key == "openai/gpt-4o"


def test_fetch_session_returns_none_for_unknown_id(fixture_db):
    conn = _conn(fixture_db)
    try:
        assert fetch_session(conn, "no-such-session") is None
    finally:
        conn.close()


def test_fetch_session_includes_empty_aborted_session(fixture_db):
    """Unlike fetch_sessions (which excludes empties by default), the direct
    lookup returns a session by id regardless of whether it is empty."""
    conn = _conn(fixture_db)
    try:
        empties = [
            s.id for s in fetch_sessions(conn, include_empty=True)
            if s.model_key == "unknown" and sum(s.tokens.values()) == 0
        ]
        assert empties, "fixture should contain an empty session"
        assert fetch_session(conn, empties[0]) is not None
    finally:
        conn.close()
