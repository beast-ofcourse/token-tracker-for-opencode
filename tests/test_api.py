"""Tests for tracker.api (T-008 FastAPI skeleton: /api/health, /api/summary;
T-009 sessions endpoints and CSV export; T-010 breakdown, config, static
serving; T-010b week/month breakdown buckets).

Expected values are hand-computed from the T-003 fixture: 12 sessions across
June + July 2026, priced with the fixture config (gpt-4o input 2.50, output
10.00, cache_read 1.25, cache_write 2.50 per 1M tokens). The empty session
(sess-003) is excluded by `fetch_sessions` unless include_empty is set.
"""

import calendar
import csv
import io
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from conftest import fixture_config

from tracker.api import create_app


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    """Epoch milliseconds for a UTC datetime (fixture timestamps are in ms)."""
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def test_health_ok(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_degraded_when_db_missing(tmp_path):
    config = fixture_config(tmp_path)
    config.db_path = tmp_path / "missing.db"
    client = TestClient(create_app(config))
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
    assert "error" in body


def test_summary_totals_and_budget_shape(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get(
        "/api/summary",
        params={"from": _ms(2026, 6, 1), "to": _ms(2026, 8, 1)},
    )
    assert response.status_code == 200
    data = response.json()

    assert set(data) == {"totals", "by_model", "by_project", "by_agent", "by_day", "budget"}

    totals = data["totals"]
    assert totals["sessions"] == 11  # 12 fixture sessions minus the empty one
    assert totals["cost"] == pytest.approx(146.0759)
    assert totals["unpriced_sessions"] == 0

    budget = data["budget"]
    assert budget["monthly"] == 20.0
    assert budget["currency"] == "USD"
    assert budget["spent"] == pytest.approx(146.0759)
    assert budget["remaining"] == pytest.approx(20.0 - 146.0759)
    assert budget["percent"] == pytest.approx(146.0759 / 20.0 * 100)
    assert budget["alert"] == "exceeded"
    assert isinstance(budget["projected"], float)


def test_summary_from_to_filters_spend(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get(
        "/api/summary",
        params={"from": _ms(2026, 7, 1), "to": _ms(2026, 8, 1)},
    )
    assert response.status_code == 200
    data = response.json()
    # July-only: sess-009 (28.325) + sess-010 (free) + sess-011 (92.25) + sess-012 (0.3443).
    assert data["totals"]["sessions"] == 4
    assert data["totals"]["cost"] == pytest.approx(120.9193)
    assert data["budget"]["spent"] == pytest.approx(120.9193)


def test_summary_defaults_to_current_budget_month(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get("/api/summary")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"totals", "by_model", "by_project", "by_agent", "by_day", "budget"}
    now = datetime.now(timezone.utc)
    assert len(data["by_day"]) == calendar.monthrange(now.year, now.month)[1]


def test_summary_503_when_db_missing(tmp_path):
    config = fixture_config(tmp_path)
    config.db_path = tmp_path / "missing.db"
    client = TestClient(create_app(config))
    response = client.get("/api/summary")
    assert response.status_code == 503
    assert "error" in response.json()


def test_sessions_list_filters_and_pagination(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))

    first = client.get("/api/sessions", params={"limit": 5})
    assert first.status_code == 200
    data = first.json()
    assert data["total"] == 11  # 12 fixture sessions minus the empty one
    assert len(data["items"]) == 5
    assert set(data["items"][0]) == {
        "id", "title", "project", "model", "agent", "tokens",
        "cost", "unpriced", "created_at", "updated_at",
    }

    second = client.get("/api/sessions", params={"limit": 5, "offset": 5}).json()
    assert second["total"] == 11
    assert len(second["items"]) == 5
    assert [s["id"] for s in second["items"]] != [s["id"] for s in data["items"]]

    # project filter
    web = client.get("/api/sessions", params={"project": "proj-web-app"}).json()
    assert web["total"] == 4
    assert {s["id"] for s in web["items"]} == {"sess-004", "sess-005", "sess-009", "sess-012"}

    # model filter
    gpt4o = client.get("/api/sessions", params={"model": "openai/gpt-4o"}).json()
    assert gpt4o["total"] == 2
    assert {s["id"] for s in gpt4o["items"]} == {"sess-002", "sess-009"}

    # agent filter
    architects = client.get("/api/sessions", params={"agent": "architect"}).json()
    assert architects["total"] == 3
    assert {s["id"] for s in architects["items"]} == {"sess-002", "sess-008", "sess-011"}

    # include_empty brings the aborted session back
    everything = client.get("/api/sessions", params={"include_empty": "true"}).json()
    assert everything["total"] == 12

    # time range: July only
    july = client.get(
        "/api/sessions",
        params={"from": _ms(2026, 7, 1), "to": _ms(2026, 8, 1)},
    ).json()
    assert july["total"] == 4
    assert {s["id"] for s in july["items"]} == {"sess-009", "sess-010", "sess-011", "sess-012"}


def test_sessions_q_filters_by_title(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))

    data = client.get("/api/sessions", params={"q": "fix"}).json()
    assert data["total"] == 2
    assert {s["id"] for s in data["items"]} == {"sess-001", "sess-005"}

    # case-insensitive
    upper = client.get("/api/sessions", params={"q": "CHECKOUT"}).json()
    assert upper["total"] == 2
    assert {s["id"] for s in upper["items"]} == {"sess-004", "sess-009"}

    # literal: '%' is not a wildcard
    pct = client.get("/api/sessions", params={"q": "%"}).json()
    assert pct["total"] == 0


def test_sessions_sort_by_cost_desc(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    data = client.get("/api/sessions", params={"sort": "cost"}).json()
    assert data["total"] == 11
    ids = [s["id"] for s in data["items"]]
    assert ids == [
        "sess-011", "sess-009", "sess-004", "sess-008", "sess-002",
        "sess-006", "sess-005", "sess-012", "sess-010", "sess-007", "sess-001",
    ]
    costs = [s["cost"] for s in data["items"]]
    assert costs == sorted(costs, reverse=True)
    # sess-011 is the opus session: 92.25
    assert data["items"][0]["cost"] == pytest.approx(92.25)


def test_session_detail_returns_message_count(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get("/api/sessions/sess-002")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "sess-002"
    assert data["title"] == "Add API design"
    assert data["project"] == "/"
    assert data["model"] == "openai/gpt-4o"
    assert data["agent"] == "architect"
    assert data["tokens"] == {
        "input": 500_000, "output": 120_000, "reasoning": 0,
        "cache_read": 1_000_000, "cache_write": 50_000,
    }
    assert data["cost"] == pytest.approx(3.825)
    assert data["unpriced"] is False
    assert data["created_at"] == "2026-06-05T14:00:00+00:00"
    assert data["updated_at"] == "2026-06-05T16:00:00+00:00"
    assert data["message_count"] == 2

    # the aborted session exists too, with no messages
    empty = client.get("/api/sessions/sess-003").json()
    assert empty["message_count"] == 0

    missing = client.get("/api/sessions/sess-999")
    assert missing.status_code == 404
    assert "error" in missing.json()


def test_session_messages_endpoint(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get("/api/sessions/sess-002/messages")
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 2
    assert messages[0] == {
        "role": "user",
        "model": "openai/gpt-4o",
        "tokens": {
            "input": 1200, "output": 300, "reasoning": 0,
            "cache_read": 800, "cache_write": 100,
        },
        "cost": 0.0042,
        "finish": None,
    }
    assert messages[1]["role"] == "assistant"
    assert messages[1]["finish"] == "stop"

    missing = client.get("/api/sessions/sess-999/messages")
    assert missing.status_code == 404
    assert "error" in missing.json()


def test_export_csv_header_and_injection_guard(tmp_path):
    config = fixture_config(tmp_path)
    conn = sqlite3.connect(config.db_path)
    conn.execute(
        """INSERT INTO session (id, project_id, title, model, agent, cost,
           tokens_input, tokens_output, tokens_reasoning, tokens_cache_read,
           tokens_cache_write, time_created, time_updated, time_archived)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "sess-evil", "proj-global", '=HYPERLINK("http://evil.example")',
            '{"id": "gpt-4o", "providerID": "openai"}', "build",
            0.0, 100, 0, 0, 0, 0, _ms(2026, 7, 1), _ms(2026, 7, 1), None,
        ),
    )
    conn.commit()
    conn.close()

    client = TestClient(create_app(config))
    response = client.get("/api/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="sessions.csv"'

    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == [
        "id", "title", "project", "model", "agent",
        "created_at", "updated_at",
        "tokens_input", "tokens_output", "tokens_reasoning",
        "tokens_cache_read", "tokens_cache_write",
        "cost", "unpriced",
    ]
    # 11 fixture sessions + the injected one, minus the empty session
    assert len(rows) == 13

    evil = next(row for row in rows if row[0] == "sess-evil")
    assert evil[1] == "'=HYPERLINK(\"http://evil.example\")"

    paid = next(row for row in rows if row[0] == "sess-002")
    assert paid[1] == "Add API design"
    assert paid[2] == "/"
    assert paid[3] == "openai/gpt-4o"
    assert paid[4] == "architect"
    assert paid[12] == "3.825"
    assert paid[13] == "false"


# --- T-010: breakdown, config, static serving ------------------------------

def test_breakdown_each_group_by_returns_rows(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    params = {"from": _ms(2026, 6, 1), "to": _ms(2026, 8, 1)}
    for group_by in ("project", "model", "agent", "day", "week", "month"):
        response = client.get("/api/breakdown", params={"group_by": group_by, **params})
        assert response.status_code == 200
        rows = response.json()["rows"]
        assert rows, f"{group_by} breakdown should not be empty"
        for row in rows:
            assert set(row) == {"key", "label", "sessions", "tokens", "cost"}
            assert row["sessions"] >= 0
            assert row["cost"] >= 0
            assert set(row["tokens"]) == {
                "input", "output", "reasoning", "cache_read", "cache_write",
            }

    # session counts add up to the 11 non-empty fixture sessions
    for group_by in ("project", "model", "agent"):
        rows = client.get(
            "/api/breakdown", params={"group_by": group_by, **params}
        ).json()["rows"]
        assert sum(row["sessions"] for row in rows) == 11

    # known model row: gpt-4o = sess-002 (3.825) + sess-009 (28.325)
    model_rows = client.get(
        "/api/breakdown", params={"group_by": "model", **params}
    ).json()["rows"]
    gpt4o = next(row for row in model_rows if row["key"] == "openai/gpt-4o")
    assert gpt4o["sessions"] == 2
    assert gpt4o["cost"] == pytest.approx(32.15)


def test_breakdown_day_rows_are_zero_filled_dates(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get(
        "/api/breakdown",
        params={"group_by": "day", "from": _ms(2026, 6, 1), "to": _ms(2026, 8, 1)},
    )
    assert response.status_code == 200
    rows = response.json()["rows"]
    # June (30) + July (31), zero-filled over the whole range
    assert len(rows) == 61
    assert all(row["key"] == row["label"] for row in rows)
    assert all(len(row["key"]) == 10 for row in rows)  # YYYY-MM-DD
    assert rows[0]["key"] == "2026-06-01"
    assert rows[-1]["key"] == "2026-07-31"
    assert sum(row["sessions"] for row in rows) == 11
    # a day with no sessions is present with zeros
    assert rows[1]["sessions"] == 0
    assert rows[1]["cost"] == 0.0


def test_breakdown_invalid_group_by_422(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get("/api/breakdown", params={"group_by": "bogus"})
    assert response.status_code == 422
    # plausible-but-unimplemented group_bys must be rejected too
    for group_by in ("year", "hour"):
        assert (
            client.get("/api/breakdown", params={"group_by": group_by}).status_code
            == 422
        )


def test_breakdown_week_buckets_iso_weeks(tmp_path):
    """T-010b: week buckets use ISO YYYY-Www keys and Monday %b %d labels.

    Hand-computed from the fixture: sessions fall on 2026-06-03/05 (W23),
    06-10/14 (W24), 06-18 (W25), 06-22/27 (W26), 07-02/05 (W27), 07-09 (W28),
    07-15 (W29); sorted by cost desc.
    """
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get(
        "/api/breakdown",
        params={"group_by": "week", "from": _ms(2026, 6, 1), "to": _ms(2026, 8, 1)},
    )
    assert response.status_code == 200
    rows = response.json()["rows"]

    assert [row["key"] for row in rows] == [
        "2026-W28", "2026-W27", "2026-W24", "2026-W26", "2026-W23", "2026-W25", "2026-W29",
    ]
    assert [row["label"] for row in rows] == [
        "Jul 06", "Jun 29", "Jun 08", "Jun 22", "Jun 01", "Jun 15", "Jul 13",
    ]
    # 11 non-empty fixture sessions across 7 distinct weeks, none dropped
    assert sum(row["sessions"] for row in rows) == 11
    assert all(len(row["key"]) == 8 for row in rows)  # YYYY-Www

    by_key = {row["key"]: row for row in rows}
    assert by_key["2026-W28"]["sessions"] == 1  # sess-011 opus: 92.25
    assert by_key["2026-W28"]["cost"] == pytest.approx(92.25)
    assert by_key["2026-W27"]["sessions"] == 2  # sess-009 gpt-4o + sess-010 free
    assert by_key["2026-W27"]["cost"] == pytest.approx(28.325)
    assert by_key["2026-W24"]["sessions"] == 2  # sess-004 sonnet + sess-005 deepseek
    assert by_key["2026-W24"]["cost"] == pytest.approx(13.4100 + 0.3531)
    assert by_key["2026-W23"]["sessions"] == 2  # sess-001 free + sess-002 gpt-4o
    assert by_key["2026-W23"]["cost"] == pytest.approx(3.825)
    # token totals in the gpt-4o week add up across the two sessions
    assert by_key["2026-W23"]["tokens"] == {
        "input": 1_750_000, "output": 205_000, "reasoning": 120_000,
        "cache_read": 4_400_000, "cache_write": 170_000,
    }


def test_breakdown_month_buckets(tmp_path):
    """T-010b: month buckets use YYYY-MM keys and %b %Y labels, cost desc."""
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get(
        "/api/breakdown",
        params={"group_by": "month", "from": _ms(2026, 6, 1), "to": _ms(2026, 8, 1)},
    )
    assert response.status_code == 200
    rows = response.json()["rows"]

    assert [row["key"] for row in rows] == ["2026-07", "2026-06"]
    assert [row["label"] for row in rows] == ["Jul 2026", "Jun 2026"]
    assert sum(row["sessions"] for row in rows) == 11

    july, june = rows
    assert july["sessions"] == 4
    assert july["cost"] == pytest.approx(120.9193)  # 28.325 + 0.0 + 92.25 + 0.3443
    assert june["sessions"] == 7
    assert june["cost"] == pytest.approx(25.1566)


def test_breakdown_week_month_no_zero_fill(tmp_path):
    """T-010b: week/month buckets never emit empty buckets (unlike `day`)."""
    client = TestClient(create_app(fixture_config(tmp_path)))
    params = {"from": _ms(2026, 6, 1), "to": _ms(2026, 8, 1)}
    week_rows = client.get("/api/breakdown", params={"group_by": "week", **params}).json()["rows"]
    month_rows = client.get("/api/breakdown", params={"group_by": "month", **params}).json()["rows"]

    # 61 calendar days in the range, but only 7 weeks / 2 months have sessions
    assert len(week_rows) == 7
    assert len(month_rows) == 2
    assert all(row["sessions"] > 0 for row in week_rows)
    assert all(row["sessions"] > 0 for row in month_rows)
    # weeks between the last June session and the July sessions are absent:
    # no week with 2026-W30 (Jul 20-26) or a zero-session 2026-W31/32
    assert all(row["key"] != "2026-W30" for row in week_rows)
    assert all(row["cost"] > 0 or row["key"] == "2026-W29" for row in week_rows)


def test_config_endpoint_returns_sanitized_config(tmp_path):
    config = fixture_config(tmp_path)
    client = TestClient(create_app(config))
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "db_path", "budget", "pricing", "server_host", "server_port", "refresh_seconds",
    }
    assert data["db_path"] == str(config.db_path)
    assert data["budget"] == {"monthly": 20.0, "currency": "USD", "reset_day": 1}
    assert data["server_host"] == "127.0.0.1"
    assert data["server_port"] == 8765
    assert data["refresh_seconds"] == 30
    assert data["pricing"]["openai/gpt-4o"] == {
        "input": 2.5, "output": 10.0, "cache_read": 1.25, "cache_write": 2.5,
    }


def test_root_serves_dashboard_html(tmp_path):
    client = TestClient(create_app(fixture_config(tmp_path)))
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>OpenCode Token Tracker</title>" in response.text
def test_concurrent_requests_succeed(tmp_path):
    """Regression: concurrent requests used to 500 with a thread-bound sqlite3
    connection (get_db dependency and endpoint run in different threadpool
    workers). Fixed with check_same_thread=False in tracker/db.py."""
    from concurrent.futures import ThreadPoolExecutor

    client = TestClient(create_app(fixture_config(tmp_path)))
    urls = [
        "/api/breakdown?group_by=model",
        "/api/breakdown?group_by=day",
        "/api/breakdown?group_by=month",
        "/api/breakdown?group_by=week",
    ]

    def get(url: str):
        return client.get(url).status_code

    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        statuses = list(pool.map(get, urls))
    assert statuses == [200, 200, 200, 200]

def test_static_traversal_returns_404(tmp_path):
    """T-017: static serving must not escape web/ (FastAPI StaticFiles default)."""
    client = TestClient(create_app(fixture_config(tmp_path)))
    for path in ("/../pyproject.toml", "/%2e%2e/pyproject.toml", "/..%2fpyproject.toml"):
        response = client.get(path)
        assert response.status_code == 404, path
