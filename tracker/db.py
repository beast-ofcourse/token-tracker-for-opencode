"""Read-only database access for the OpenCode Token Tracker.

The OpenCode database is a SQLite database in WAL mode, actively written by
OpenCode. This module never writes to it: connections are opened with the
`mode=ro` URI flag plus `PRAGMA query_only = ON`. If the read-only open fails
(e.g. a WAL-mode database whose `-shm` file is missing on Windows), a
snapshot copy of the database and its WAL files is opened instead.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote

from tracker.config import Config

# Temp dirs created by the snapshot fallback. Removed when the connection
# closes; the atexit handler is a safety net for connections that never close.
_TEMP_DIRS: set[Path] = set()


@atexit.register
def _cleanup_temp_dirs() -> None:
    for temp_dir in list(_TEMP_DIRS):
        shutil.rmtree(temp_dir, ignore_errors=True)
        _TEMP_DIRS.discard(temp_dir)


class DbNotFoundError(FileNotFoundError):
    """Raised when the OpenCode database file does not exist."""


class _SnapshotConnection(sqlite3.Connection):
    """A connection whose snapshot temp dir is removed when it closes."""

    def __init__(self, *args, temp_dir: Path | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._temp_dir = temp_dir

    def close(self) -> None:
        super().close()
        if self._temp_dir is not None:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            _TEMP_DIRS.discard(self._temp_dir)
            self._temp_dir = None


def resolve_db_path(config: Config) -> Path:
    """Resolve the database path: expand `~` and honor the OPENCODE_DB env var."""
    env = os.environ.get("OPENCODE_DB")
    if env:
        return Path(env).expanduser()
    return config.db_path.expanduser()


def _set_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row


def _force_open(conn: sqlite3.Connection) -> None:
    """Force the lazy database open so read-only failures surface immediately.

    `sqlite3.connect` opens the file lazily; the pragmas above are pure
    connection settings and never touch the files. The first real statement
    is what fails when the database cannot be opened read-only (e.g. a WAL
    database whose `-shm` file is missing), so run one before returning.
    """
    conn.execute("SELECT count(*) FROM sqlite_master")


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"file:{quote(str(db_path))}?mode=ro", uri=True, check_same_thread=False
    )
    _set_pragmas(conn)
    _force_open(conn)
    return conn


def _open_snapshot(db_path: Path) -> sqlite3.Connection:
    """Copy the database (and any WAL files) to a temp dir and open the copy read-only."""
    temp_dir = Path(tempfile.mkdtemp(prefix="opencode-tracker-"))
    _TEMP_DIRS.add(temp_dir)
    try:
        for suffix in ("", "-wal", "-shm"):
            src = db_path.parent / (db_path.name + suffix)
            if src.exists():
                shutil.copy2(src, temp_dir / (db_path.name + suffix))
        conn = _SnapshotConnection(
            f"file:{quote(str(temp_dir / db_path.name))}?mode=ro",
            uri=True,
            check_same_thread=False,
            temp_dir=temp_dir,
        )
        _set_pragmas(conn)
        _force_open(conn)
        return conn
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _TEMP_DIRS.discard(temp_dir)
        raise


def open_connection(db_path: Path) -> sqlite3.Connection:
    """Open the OpenCode database read-only.

    Raises `DbNotFoundError` (never a raw sqlite error) when the database file
    does not exist. If the read-only open fails for any other reason — e.g. a
    WAL-mode database whose `-shm` file is missing on Windows — falls back to
    a snapshot copy in a temp dir, cleaned up when the connection closes.
    """
    if not db_path.exists():
        raise DbNotFoundError(
            f"OpenCode database not found: {db_path}. "
            "Check the db_path in config.json or the OPENCODE_DB environment variable."
        )
    try:
        return _connect_read_only(db_path)
    except sqlite3.Error:
        return _open_snapshot(db_path)