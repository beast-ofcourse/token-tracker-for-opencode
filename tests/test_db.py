"""Unit tests for tracker.db (T-004 read-only database access)."""

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

from tracker.config import Budget, Config, Severity
from tracker.db import DbNotFoundError, open_connection, resolve_db_path


def _config(db_path: Path) -> Config:
    return Config(
        db_path=db_path,
        budget=Budget(monthly=20.0, currency="USD", reset_day=1),
        severity=Severity(high_cost=5.0, med_cost=1.0),
        pricing={},
        server_host="127.0.0.1",
        server_port=8765,
        refresh_seconds=30,
    )


def test_read_only_open_works_on_fixture(fixture_db):
    conn = open_connection(fixture_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM session").fetchone()[0]
        assert count == 12
    finally:
        conn.close()


def test_write_attempt_raises_operational_error(fixture_db):
    conn = open_connection(fixture_db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE should_not_exist (x)")
    finally:
        conn.close()


def test_missing_db_raises_db_not_found(tmp_path):
    missing = tmp_path / "no-such.db"
    with pytest.raises(DbNotFoundError) as excinfo:
        open_connection(missing)
    message = str(excinfo.value)
    assert "not found" in message
    assert str(missing) in message


def test_resolve_db_path_expands_tilde(tmp_path):
    assert resolve_db_path(_config(Path("~/custom/opencode.db"))) == (
        Path.home() / "custom/opencode.db"
    )


def test_resolve_db_path_honors_env_override(tmp_path, monkeypatch):
    env_db = tmp_path / "env.db"
    monkeypatch.setenv("OPENCODE_DB", str(env_db))
    assert resolve_db_path(_config(Path("~/custom/opencode.db"))) == env_db


def test_resolve_db_path_env_override_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DB", "~/env-opencode.db")
    assert resolve_db_path(_config(Path("~/custom/opencode.db"))) == (
        Path.home() / "env-opencode.db"
    )


def _make_wal_copy(src_db: Path, dest_dir: Path) -> Path:
    """Copy `src_db` into `dest_dir` as a WAL-mode DB with a live `-wal` file.

    The `-wal`/`-shm` files are copied while the connection is still open:
    closing the last connection would checkpoint and delete them. Returns the
    directory holding the WAL-mode copy.
    """
    db = dest_dir / "opencode.db"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_db, db)
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO session (id, project_id, title, model, agent, cost,"
            " tokens_input, tokens_output, tokens_reasoning, tokens_cache_read,"
            " tokens_cache_write, time_created, time_updated, time_archived)"
            " VALUES ('sess-wal', 'proj-global', 'WAL probe', NULL, NULL, 0,"
            " 0, 0, 0, 0, 0, 0, 0, NULL)"
        )
        conn.commit()
        wal_dir = dest_dir / "wal-copy"
        wal_dir.mkdir()
        for name in ("opencode.db", "opencode.db-wal", "opencode.db-shm"):
            shutil.copy2(dest_dir / name, wal_dir / name)
    finally:
        conn.close()
    return wal_dir


def _deny_write(path: Path) -> None:
    """Make a directory unwritable (Windows ACL) so SQLite cannot recreate `-shm`."""
    subprocess.run(
        ["icacls", str(path), "/deny", "*S-1-1-0:(W)"],
        check=True,
        capture_output=True,
    )


def _allow_write(path: Path) -> None:
    subprocess.run(
        ["icacls", str(path), "/remove:d", "*S-1-1-0"],
        check=False,
        capture_output=True,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="WAL -shm trigger is Windows-specific")
def test_snapshot_fallback_when_shm_missing(tmp_path, fixture_db):
    """A WAL DB whose `-shm` is missing opens via a snapshot copy in a temp dir."""
    wal_dir = _make_wal_copy(fixture_db, tmp_path / "wal")
    (wal_dir / "opencode.db-shm").unlink()
    _deny_write(wal_dir)
    try:
        # Sanity: with the -shm gone and the directory unwritable, a plain
        # read-only open fails — this is the trigger for the fallback.
        # (sqlite3.connect is lazy; the real open happens on the first query.)
        with pytest.raises(sqlite3.OperationalError):
            conn = sqlite3.connect(
                "file:" + quote(str(wal_dir / "opencode.db")) + "?mode=ro", uri=True
            )
            conn.execute("SELECT 1")

        conn = open_connection(wal_dir / "opencode.db")
        try:
            main_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
            # The connection must be a snapshot copy, not the original file.
            assert main_file != wal_dir / "opencode.db"
            assert main_file.parent != wal_dir
            # 12 fixture sessions + the WAL probe row.
            assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 13
            # The snapshot connection is read-only too.
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE should_not_exist (x)")
            temp_dir = main_file.parent
        finally:
            conn.close()
        # The snapshot temp dir is cleaned up when the connection closes.
        assert not temp_dir.exists()
    finally:
        _allow_write(wal_dir)