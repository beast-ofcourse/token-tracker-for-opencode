"""Tests for tracker.cli (T-015 CLI commands: summary, sessions, serve)."""

import json
import socket

import pytest

from tracker.cli import main


def _write_config(tmp_path, db_path) -> str:
    """Write a minimal config.json pointing at the fixture DB; return its path."""
    config = {
        "db_path": str(db_path),
        "budget": {"monthly": 20.0, "currency": "USD", "reset_day": 1},
        "pricing": {
            "openai/gpt-4o": {
                "input": 2.50, "output": 10.00, "cache_read": 1.25, "cache_write": 2.50,
            }
        },
        "server": {"host": "127.0.0.1", "port": 8765},
        "refresh_seconds": 30,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return str(path)


def test_summary_prints_expected_fields(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    with pytest.raises(SystemExit) as exc:
        main(["summary", "--month", "2026-07", "--config", cfg])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "OpenCode usage" in out
    assert "Spend:" in out
    assert "Projected:" in out
    assert "Tokens:" in out
    assert "Sessions:" in out
    assert "Top project:" in out
    assert "Top model:" in out


def test_summary_json_is_valid_json(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    with pytest.raises(SystemExit) as excinfo:
        main(["summary", "--month", "2026-07", "--json", "--config", cfg])
    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert "totals" in data and "budget" in data and "by_model" in data


def test_summary_invalid_month_exits_2(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    with pytest.raises(SystemExit) as excinfo:
        main(["summary", "--month", "2026-13", "--config", cfg])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "Invalid month '2026-13'. Use YYYY-MM." in err


def test_summary_past_month(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    with pytest.raises(SystemExit) as excinfo:
        main(["summary", "--month", "2026-07", "--json", "--config", cfg])
    assert excinfo.value.code == 0
    data = json.loads(capsys.readouterr().out)
    # Fixture: 4 sessions in July 2026, gpt-4o priced -> cost 120.9193.
    assert data["totals"]["sessions"] == 4
    assert data["totals"]["cost"] == pytest.approx(120.9193, abs=1e-3)


def test_sessions_csv_writes_file_with_header(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    csv_path = tmp_path / "out.csv"
    with pytest.raises(SystemExit) as excinfo:
        main(["sessions", "--csv", str(csv_path), "--config", cfg])
    assert excinfo.value.code == 0
    assert "Wrote 11 sessions to" in capsys.readouterr().out
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("id,title,project,model,agent,created_at")
    assert len(lines) == 12  # header + 11 sessions


def test_sessions_csv_escapes_injection(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    csv_path = tmp_path / "out.csv"
    with pytest.raises(SystemExit):
        main(["sessions", "--csv", str(csv_path), "--config", cfg])
    # Fixture has no malicious titles; verify the guard helper directly instead.
    from tracker.csvutil import csv_safe

    assert csv_safe("=HYPERLINK(x)") == "'=HYPERLINK(x)"
    assert csv_safe("plain") == "plain"


def test_sessions_unwritable_csv_exits_1(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    bad_path = tmp_path / "no_such_dir" / "out.csv"
    with pytest.raises(SystemExit) as excinfo:
        main(["sessions", "--csv", str(bad_path), "--config", cfg])
    assert excinfo.value.code == 1
    assert "Cannot write" in capsys.readouterr().err


def test_sessions_no_data_exits_0(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    with pytest.raises(SystemExit) as excinfo:
        main(["sessions", "--from", "2030-01-01", "--to", "2030-01-02", "--config", cfg])
    assert excinfo.value.code == 0
    assert "No sessions found." in capsys.readouterr().out


def test_serve_port_busy_exits_1(tmp_path, fixture_db, capsys):
    cfg = _write_config(tmp_path, tmp_path / "opencode.db")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        with pytest.raises(SystemExit) as excinfo:
            main(["serve", "--port", str(port), "--config", cfg])
    assert excinfo.value.code == 1
    assert f"Port {port} is in use" in capsys.readouterr().err


# --- _month_bounds_for_arg (month string -> epoch-ms bounds) ----------------

from tracker.cli import _month_bounds_for_arg


def test_month_bounds_for_arg_valid_month():
    start, end = _month_bounds_for_arg("2026-07", reset_day=1)
    # 2026-07-01 00:00:00 UTC -> 2026-08-01 00:00:00 UTC
    assert start == 1_782_864_000_000
    assert end == 1_785_542_400_000


def test_month_bounds_for_arg_rejects_malformed():
    for bad in ("2026-13", "2026-00", "202607", "abcd-ef", "2026-7"):
        with pytest.raises(ValueError):
            _month_bounds_for_arg(bad, reset_day=1)


def test_month_bounds_for_arg_respects_reset_day():
    # With reset_day=15, the "July" window runs 2026-07-15 through 2026-08-15.
    start, end = _month_bounds_for_arg("2026-07", reset_day=15)
    assert start == 1_784_073_600_000  # 2026-07-15 00:00:00 UTC
    assert end == 1_786_752_000_000  # 2026-08-15 00:00:00 UTC