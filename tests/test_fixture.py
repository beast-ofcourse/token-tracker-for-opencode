"""Smoke tests for the T-003 fixture database builder (tests/conftest.py)."""

import json
import sqlite3

from conftest import fixture_config


def test_fixture_db_has_10_plus_sessions(fixture_db):
    conn = sqlite3.connect(fixture_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM session").fetchone()[0]
    finally:
        conn.close()
    assert count >= 10


def test_fixture_db_integrity_ok(fixture_db):
    conn = sqlite3.connect(fixture_db)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    assert result == "ok"


def test_fixture_config_pricing_contains_gpt4o(tmp_path):
    cfg = fixture_config(tmp_path)
    assert cfg.db_path == tmp_path / "opencode.db"
    assert cfg.db_path.exists()
    price = cfg.pricing["openai/gpt-4o"]
    assert (price.input, price.output, price.cache_read, price.cache_write) == (
        2.50,
        10.00,
        1.25,
        2.50,
    )


def test_fixture_db_required_content(fixture_db):
    """The fixture DB contains the sessions/rows the contract requires."""
    conn = sqlite3.connect(fixture_db)
    try:
        project_count = conn.execute("SELECT COUNT(*) FROM project").fetchone()[0]
        message_count = conn.execute("SELECT COUNT(*) FROM message").fetchone()[0]
        month_count = conn.execute(
            "SELECT COUNT(DISTINCT strftime('%Y-%m', time_created / 1000, 'unixepoch')) FROM session"
        ).fetchone()[0]
        model_keys = [
            f"{data['providerID']}/{data['id']}"
            for (model_json,) in conn.execute(
                "SELECT model FROM session WHERE model IS NOT NULL"
            ).fetchall()
            for data in [json.loads(model_json)]
        ]
        empty_count = conn.execute(
            """SELECT COUNT(*) FROM session
               WHERE model IS NULL AND tokens_input = 0 AND tokens_output = 0
                 AND tokens_reasoning = 0 AND tokens_cache_read = 0
                 AND tokens_cache_write = 0"""
        ).fetchone()[0]
        null_agent_count = conn.execute(
            "SELECT COUNT(*) FROM session WHERE agent IS NULL"
        ).fetchone()[0]
        global_worktree = conn.execute(
            "SELECT worktree FROM project WHERE name = 'global'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert project_count == 3
    assert message_count == 2
    assert month_count == 2
    assert "opencode/deepseek-v4-flash-free" in model_keys
    assert "openai/gpt-4o" in model_keys
    assert empty_count >= 1
    assert null_agent_count >= 1
    assert global_worktree == "/"