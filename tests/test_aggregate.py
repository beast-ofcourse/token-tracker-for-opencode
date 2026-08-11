"""Tests for tracker.aggregate (T-007 aggregation and budget math).

Expected values are hand-computed from the T-003 fixture: 12 sessions across
June + July 2026, priced with the fixture config (gpt-4o input 2.50, output
10.00, cache_read 1.25, cache_write 2.50 per 1M tokens).
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from conftest import fixture_config, row_conn

from tracker.aggregate import format_cost, month_bounds, month_bounds_for, summarize
from tracker.config import Budget, Price, Severity
from tracker.store import Session, fetch_projects, fetch_sessions

#: gpt-4o pricing as configured in the fixture (USD per 1M tokens).
GPT4 = Price(input=2.50, output=10.00, cache_read=1.25, cache_write=2.50)


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    """Epoch milliseconds for a UTC datetime (fixture timestamps are in ms)."""
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def _now() -> datetime:
    return datetime(2026, 7, 20, 12, tzinfo=timezone.utc)


def _load(tmp_path):
    """All 12 fixture sessions (empty one included), project map, and pricing."""
    cfg = fixture_config(tmp_path)
    conn = row_conn(cfg.db_path)
    try:
        sessions = fetch_sessions(conn, include_empty=True)
        projects = fetch_projects(conn)
    finally:
        conn.close()
    return sessions, projects, cfg.pricing


def _gpt4o_session(created_ms: int, cost: float = 2.50) -> Session:
    """A gpt-4o session whose cost is `cost` (1M input tokens = 2.50)."""
    return Session(
        id="s1",
        project_id="proj-x",
        title="Single session",
        model_key="openai/gpt-4o",
        model_variant="high",
        agent="build",
        cost_db=0.0,
        tokens={"input": int(cost / 2.50 * 1_000_000), "output": 0,
                "reasoning": 0, "cache_read": 0, "cache_write": 0},
        created_ms=created_ms,
        updated_ms=created_ms,
        archived_ms=None,
    )


# --- month_bounds ----------------------------------------------------------


def test_month_bounds_for_reset_day_1():
    assert month_bounds_for(2026, 7, 1) == (_ms(2026, 7, 1), _ms(2026, 8, 1))


def test_month_bounds_for_reset_day_15():
    assert month_bounds_for(2026, 6, 15) == (_ms(2026, 6, 15), _ms(2026, 7, 15))


def test_month_bounds_for_reset_day_clamped_to_month_length():
    # reset_day 31 in a 28-day February starts on the 28th; the next month's
    # reset day is March 31, so the budget month runs Feb 28 -> Mar 31.
    assert month_bounds_for(2026, 2, 31) == (_ms(2026, 2, 28), _ms(2026, 3, 31))


def test_month_bounds_for_year_wrap():
    assert month_bounds_for(2026, 12, 1) == (_ms(2026, 12, 1), _ms(2027, 1, 1))


def test_month_bounds_delegates_to_month_bounds_for():
    assert month_bounds(_now(), 1) == month_bounds_for(2026, 7, 1)


# --- totals ----------------------------------------------------------------


def test_totals_match_hand_computed_values(tmp_path):
    sessions, projects, pricing = _load(tmp_path)
    summary = summarize(sessions, projects, pricing, _now(), Budget(monthly=20.0))
    totals = summary["totals"]

    assert totals["sessions"] == 12
    assert totals["cost"] == pytest.approx(146.0759)
    assert totals["tokens"] == {
        "input": 19_500_000,
        "output": 2_615_000,
        "reasoning": 1_060_000,
        "cache_read": 40_500_000,
        "cache_write": 1_480_000,
    }
    # Only the empty session (NULL model, cost_db 0) is unpriced.
    assert totals["unpriced_sessions"] == 1
    assert totals["largest_session"] == {
        "id": "sess-011",
        "title": "Design plugin API",
        "cost": pytest.approx(92.25),
        "model": "anthropic/claude-opus-4",
    }
    assert totals["avg_cost"] == pytest.approx(146.0759 / 12)
    # Costs >= 5.0: sess-004 (13.41), sess-008 (6.3625), sess-009 (28.325), sess-011 (92.25).
    assert totals["events_over_high"] == 4


def test_totals_empty_sessions_list():
    summary = summarize([], {}, {}, _now(), Budget(monthly=20.0))
    totals = summary["totals"]
    assert totals["sessions"] == 0
    assert totals["cost"] == 0.0
    assert totals["tokens"] == {
        "input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0,
    }
    assert totals["unpriced_sessions"] == 0
    assert totals["largest_session"] is None
    assert totals["avg_cost"] == 0.0
    assert totals["events_over_high"] == 0


def test_events_over_high_uses_severity_parameter(tmp_path):
    sessions, projects, pricing = _load(tmp_path)
    summary = summarize(
        sessions, projects, pricing, _now(), Budget(monthly=20.0),
        severity=Severity(high_cost=1.0),
    )
    # Costs >= 1.0: sess-002, 004, 006, 008, 009, 011 -> 6.
    assert summary["totals"]["events_over_high"] == 6


# --- grouping --------------------------------------------------------------


def test_by_model_grouping_sorted_by_cost_desc(tmp_path):
    sessions, projects, pricing = _load(tmp_path)
    by_model = summarize(sessions, projects, pricing, _now(), Budget(monthly=20.0))["by_model"]

    assert [row["key"] for row in by_model] == [
        "anthropic/claude-opus-4",
        "openai/gpt-4o",
        "anthropic/claude-sonnet-4",
        "google/gemini-2.5-pro",
        "openai/gpt-4o-mini",
        "deepseek/deepseek-chat",
        "opencode/deepseek-v4-flash-free",
        "unknown",
    ]
    assert by_model[0]["label"] == "anthropic/claude-opus-4"
    assert by_model[0]["sessions"] == 1
    assert by_model[0]["cost"] == pytest.approx(92.25)
    assert by_model[1]["cost"] == pytest.approx(32.15)  # sess-002 + sess-009
    assert by_model[1]["sessions"] == 2
    assert by_model[5]["cost"] == pytest.approx(0.6974)  # sess-005 + sess-012
    assert by_model[6]["cost"] == 0.0  # free model
    assert by_model[7]["key"] == "unknown"  # empty session
    assert by_model[7]["cost"] == 0.0


def test_by_project_labeled_by_worktree_path(tmp_path):
    sessions, projects, pricing = _load(tmp_path)
    by_project = summarize(sessions, projects, pricing, _now(), Budget(monthly=20.0))["by_project"]

    assert [row["key"] for row in by_project] == ["proj-cli", "proj-web-app", "proj-global"]
    assert by_project[0]["label"] == r"C:\Users\Bhavin\projects\cli"
    assert by_project[0]["cost"] == pytest.approx(92.25)
    assert by_project[1]["label"] == r"C:\Users\Bhavin\projects\web-app"
    assert by_project[1]["cost"] == pytest.approx(42.4324)
    assert by_project[2]["label"] == "/"
    assert by_project[2]["cost"] == pytest.approx(11.3935)


def test_by_agent_groups_null_agent_as_none(tmp_path):
    sessions, projects, pricing = _load(tmp_path)
    by_agent = summarize(sessions, projects, pricing, _now(), Budget(monthly=20.0))["by_agent"]

    assert [row["key"] for row in by_agent] == ["architect", "build", "(none)"]
    assert by_agent[0]["cost"] == pytest.approx(102.4375)
    assert by_agent[1]["cost"] == pytest.approx(30.2284)
    # sess-003 (empty) and sess-004 (NULL agent).
    assert by_agent[2]["sessions"] == 2
    assert by_agent[2]["cost"] == pytest.approx(13.41)


def test_grouping_token_totals(tmp_path):
    sessions, projects, pricing = _load(tmp_path)
    by_model = summarize(sessions, projects, pricing, _now(), Budget(monthly=20.0))["by_model"]
    gpt4o = next(row for row in by_model if row["key"] == "openai/gpt-4o")
    assert gpt4o["tokens"] == {
        "input": 5_000_000,  # sess-002 500K + sess-009 4.5M
        "output": 740_000,   # 120K + 620K
        "reasoning": 0,
        "cache_read": 9_000_000,  # 1M + 8M
        "cache_write": 400_000,   # 50K + 350K
    }


# --- by_day ----------------------------------------------------------------


def test_by_day_zero_filled_over_current_budget_month(tmp_path):
    sessions, projects, pricing = _load(tmp_path)
    by_day = summarize(sessions, projects, pricing, _now(), Budget(monthly=20.0))["by_day"]

    # July 2026 has 31 days; every day appears, zero-filled.
    assert len(by_day) == 31
    assert by_day[0]["day"] == "2026-07-01"
    assert by_day[30]["day"] == "2026-07-31"
    assert by_day[0]["cost"] == 0.0
    assert by_day[0]["tokens"] == {
        "input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0,
    }
    by_date = {row["day"]: row for row in by_day}
    assert by_date["2026-07-02"]["cost"] == pytest.approx(28.325)  # sess-009
    assert by_date["2026-07-05"]["cost"] == 0.0  # sess-010 is free
    assert by_date["2026-07-09"]["cost"] == pytest.approx(92.25)  # sess-011
    assert by_date["2026-07-15"]["cost"] == pytest.approx(0.3443)  # sess-012
    assert by_date["2026-07-02"]["tokens"]["input"] == 4_500_000


def test_by_day_custom_range(tmp_path):
    sessions, projects, pricing = _load(tmp_path)
    summary = summarize(
        sessions, projects, pricing, _now(), Budget(monthly=20.0),
        from_ms=_ms(2026, 6, 10), to_ms=_ms(2026, 6, 16),
    )
    by_day = summary["by_day"]
    # to_ms is exclusive: June 10..15 = 6 days.
    assert [row["day"] for row in by_day] == [
        "2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13", "2026-06-14", "2026-06-15",
    ]
    assert by_day[0]["cost"] == pytest.approx(13.41)  # sess-004
    assert by_day[4]["cost"] == pytest.approx(0.3531)  # sess-005 on June 14
    assert all(row["cost"] == 0.0 for row in by_day[1:4] + by_day[5:])


# --- budget ----------------------------------------------------------------


def test_budget_alert_ok_warn_exceeded():
    session = _gpt4o_session(_ms(2026, 7, 10))
    pricing = {"openai/gpt-4o": GPT4}
    projects = {"proj-x": "/x"}

    ok = summarize([session], projects, pricing, _now(), Budget(monthly=10.0))
    assert ok["budget"]["alert"] == "ok"
    assert ok["budget"]["percent"] == pytest.approx(25.0)
    assert ok["budget"]["remaining"] == pytest.approx(7.5)

    warn = summarize([session], projects, pricing, _now(), Budget(monthly=3.125))
    assert warn["budget"]["alert"] == "warn"
    assert warn["budget"]["percent"] == pytest.approx(80.0)

    exceeded = summarize([session], projects, pricing, _now(), Budget(monthly=2.5))
    assert exceeded["budget"]["alert"] == "exceeded"
    assert exceeded["budget"]["percent"] == pytest.approx(100.0)
    assert exceeded["budget"]["remaining"] == pytest.approx(0.0)


def test_budget_projection_formula():
    # now = July 20 -> elapsed 20 days (July 1..20), July has 31 days.
    session = _gpt4o_session(_ms(2026, 7, 10))
    pricing = {"openai/gpt-4o": GPT4}
    summary = summarize([session], {"proj-x": "/x"}, pricing, _now(), Budget(monthly=10.0))
    budget = summary["budget"]
    assert budget["spent"] == pytest.approx(2.50)
    assert budget["projected"] == pytest.approx(2.50 / 20 * 31)


def test_budget_zero_monthly_is_disabled():
    session = _gpt4o_session(_ms(2026, 7, 10))
    pricing = {"openai/gpt-4o": GPT4}
    summary = summarize([session], {"proj-x": "/x"}, pricing, _now(), Budget(monthly=0.0))
    budget = summary["budget"]
    assert budget["percent"] == 0.0
    assert budget["alert"] == "ok"


def test_budget_alert_ok_when_spent_below_80_percent(tmp_path):
    # Acceptance: summarize on the fixture returns alert "ok" when spent < 80%.
    sessions, projects, pricing = _load(tmp_path)
    summary = summarize(sessions, projects, pricing, _now(), Budget(monthly=1000.0))
    assert summary["budget"]["alert"] == "ok"
    assert summary["budget"]["spent"] == pytest.approx(146.0759)


# --- format_cost -----------------------------------------------------------


def test_format_cost():
    assert format_cost(12.34) == "$12.34"
    assert format_cost(0) == "$0.00"
    assert format_cost(3.5) == "$3.50"
    assert format_cost(92.25) == "$92.25"