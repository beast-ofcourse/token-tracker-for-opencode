"""FastAPI application for the OpenCode Token Tracker (T-008, T-009, T-010).

`create_app` builds the read-only API: a health check, the monthly summary,
the breakdown and sanitized-config endpoints, the session
list/detail/messages endpoints, and CSV export. Every request that reads
the database opens a fresh read-only connection via the `get_db` dependency
(from `tracker.db.open_connection`) and closes it when the request
finishes. A database that cannot be opened surfaces as HTTP 503 with
`{"error": ...}`; unexpected errors fall through to FastAPI's default 500.
Static files under `web/` are mounted at `/` last, so every `/api` route
takes precedence over the dashboard.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from tracker import __version__
from tracker.aggregate import month_bounds, summarize
from tracker.config import Config, Price
from tracker.csvutil import render_sessions_csv
from tracker.db import open_connection
from tracker.pricing import compute_cost
from tracker.store import (
    TOKEN_KEYS,
    Session,
    fetch_messages,
    fetch_projects,
    fetch_session,
    fetch_sessions,
)


class DbUnavailableError(Exception):
    """Raised when the OpenCode database cannot be opened for a request."""


def _iso(ms: int) -> str:
    """Epoch milliseconds as an ISO-8601 UTC string."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _session_dict(session: Session, projects: dict[str, str], cost: float, unpriced: bool) -> dict:
    """The API shape for one session: project path, tokens, and computed cost."""
    return {
        "id": session.id,
        "title": session.title,
        "project": projects.get(session.project_id) if session.project_id else None,
        "model": session.model_key,
        "agent": session.agent,
        "tokens": dict(session.tokens),
        "cost": cost,
        "unpriced": unpriced,
        "created_at": _iso(session.created_ms),
        "updated_at": _iso(session.updated_ms),
    }


def _time_bucket_rows(
    sessions: list[Session],
    pricing: dict[str, Price],
    group_by: Literal["week", "month"],
) -> list[dict]:
    """Group sessions into week/month buckets: `{key, label, sessions, tokens, cost}`.

    `week` buckets by ISO week â€” key `YYYY-Www` (e.g. `2026-W32`), label the
    Monday of that week formatted `%b %d` (e.g. `Jun 01`); `month` buckets by
    calendar month â€” key `YYYY-MM`, label `%b %Y` (e.g. `Jun 2026`). Sessions
    are attributed by their UTC `created_ms`. Only buckets with sessions
    appear (no zero-fill). Rows sort by cost desc, then key asc â€” the same
    order `aggregate._group` uses for the other breakdowns.
    """
    rows_by_key: dict[str, dict] = {}
    for session in sessions:
        created = datetime.fromtimestamp(
            session.created_ms / 1000, tz=timezone.utc
        ).date()
        if group_by == "week":
            iso = created.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
            label = (created - timedelta(days=created.weekday())).strftime("%b %d")
        else:
            key = f"{created.year:04d}-{created.month:02d}"
            label = created.strftime("%b %Y")
        row = rows_by_key.get(key)
        if row is None:
            row = {
                "key": key,
                "label": label,
                "sessions": 0,
                "tokens": {token_key: 0 for token_key in TOKEN_KEYS},
                "cost": 0.0,
            }
            rows_by_key[key] = row
        row["sessions"] += 1
        for token_key in TOKEN_KEYS:
            row["tokens"][token_key] += session.tokens.get(token_key, 0)
        row["cost"] += compute_cost(session, pricing)[0]
    rows = list(rows_by_key.values())
    rows.sort(key=lambda row: (-row["cost"], row["key"]))
    return rows


def create_app(config: Config) -> FastAPI:
    """Build the FastAPI app serving the tracker's read-only API."""
    app = FastAPI(title="OpenCode Token Tracker", version=__version__)

    @app.exception_handler(DbUnavailableError)
    def _db_unavailable(request: Request, exc: DbUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": str(exc)})

    def get_db() -> sqlite3.Connection:
        """Per-request dependency: a fresh read-only connection, closed after the request."""
        try:
            conn = open_connection(config.db_path)
        except Exception as exc:
            raise DbUnavailableError(str(exc)) from exc
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/api/health")
    def health() -> dict:
        """Report whether the app and its database are reachable."""
        try:
            with closing(open_connection(config.db_path)) as conn:
                conn.execute("SELECT 1")
        except Exception as exc:
            return {"status": "degraded", "db": "error", "error": str(exc)}
        return {"status": "ok", "db": "ok"}

    @app.get("/api/summary")
    def summary(
        from_ms: int | None = Query(default=None, alias="from"),
        to_ms: int | None = Query(default=None, alias="to"),
        conn: sqlite3.Connection = Depends(get_db),
    ) -> dict:
        """Aggregate sessions into the summary dict (totals, breakdowns, budget).

        `from`/`to` are optional epoch-ms timestamps; when either is missing
        they default to the budget month containing now, so `budget.spent`
        reflects the current month only â€” never all-time spend.
        """
        now = datetime.now(timezone.utc)
        if from_ms is None or to_ms is None:
            from_ms, to_ms = month_bounds(now, config.budget.reset_day)
        sessions = fetch_sessions(conn, from_ms=from_ms, to_ms=to_ms)
        projects = fetch_projects(conn)
        return summarize(
            sessions,
            projects,
            config.pricing,
            now,
            config.budget,
            severity=config.severity,
            from_ms=from_ms,
            to_ms=to_ms,
        )

    @app.get("/api/breakdown")
    def breakdown(
        group_by: Literal["project", "model", "agent", "day", "week", "month"],
        from_ms: int | None = Query(default=None, alias="from"),
        to_ms: int | None = Query(default=None, alias="to"),
        conn: sqlite3.Connection = Depends(get_db),
    ) -> dict:
        """Breakdown rows grouped by project, model, agent, day, week, or month.

        `from`/`to` default to the budget month containing now, exactly like
        `/api/summary`; an invalid `group_by` is rejected with 422. The
        project/model/agent rows are `summarize`'s sections as-is (already
        `{key, label, sessions, tokens, cost}`, sorted by cost desc); `day`
        rows map the zero-filled `by_day` series into the same shape with
        `key`/`label` = `YYYY-MM-DD` and a per-day session count. `week` and
        `month` rows bucket sessions by their UTC `created_ms` â€” ISO week
        (`YYYY-Www`, label = the Monday's `%b %d`) and calendar month
        (`YYYY-MM`, label `%b %Y`) â€” with no zero-fill: only buckets that
        contain sessions appear, sorted by cost desc (key asc on ties).
        """
        now = datetime.now(timezone.utc)
        if from_ms is None or to_ms is None:
            from_ms, to_ms = month_bounds(now, config.budget.reset_day)
        sessions = fetch_sessions(conn, from_ms=from_ms, to_ms=to_ms)
        projects = fetch_projects(conn)
        summary = summarize(
            sessions,
            projects,
            config.pricing,
            now,
            config.budget,
            severity=config.severity,
            from_ms=from_ms,
            to_ms=to_ms,
        )
        if group_by == "day":
            counts: dict[str, int] = {}
            for session in sessions:
                day = (
                    datetime.fromtimestamp(session.created_ms / 1000, tz=timezone.utc)
                    .date()
                    .isoformat()
                )
                counts[day] = counts.get(day, 0) + 1
            rows = [
                {
                    "key": entry["day"],
                    "label": entry["day"],
                    "sessions": counts.get(entry["day"], 0),
                    "tokens": entry["tokens"],
                    "cost": entry["cost"],
                }
                for entry in summary["by_day"]
            ]
        elif group_by in ("week", "month"):
            rows = _time_bucket_rows(sessions, config.pricing, group_by)
        else:
            rows = summary[f"by_{group_by}"]
        return {"rows": rows}

    @app.get("/api/config")
    def config_endpoint() -> dict:
        """Sanitized configuration for the dashboard.

        Built field-by-field from the `Config` object â€” never the raw config
        file â€” so the shape is stable and nothing unrequested leaks.
        """
        return {
            "db_path": str(config.db_path),
            "budget": {
                "monthly": config.budget.monthly,
                "currency": config.budget.currency,
                "reset_day": config.budget.reset_day,
            },
            "pricing": {
                model: {
                    "input": price.input,
                    "output": price.output,
                    "cache_read": price.cache_read,
                    "cache_write": price.cache_write,
                }
                for model, price in config.pricing.items()
            },
            "server_host": config.server_host,
            "server_port": config.server_port,
            "refresh_seconds": config.refresh_seconds,
        }

    @app.get("/api/sessions")
    def sessions(
        project: str | None = None,
        model: str | None = None,
        agent: str | None = None,
        q: str | None = None,
        from_ms: int | None = Query(default=None, alias="from"),
        to_ms: int | None = Query(default=None, alias="to"),
        include_empty: bool = False,
        limit: int | None = Query(default=None, ge=0),
        offset: int = Query(default=0, ge=0),
        sort: str = Query(default="updated", pattern="^(updated|cost)$"),
        conn: sqlite3.Connection = Depends(get_db),
    ) -> dict:
        """List sessions with filters, pagination, and optional cost sorting.

        `total` counts every session matching the filters *before*
        limit/offset so the client can paginate. `sort=cost` orders by
        computed cost descending; the default `updated` order is
        `fetch_sessions`'s time_updated DESC. `q` is a literal,
        case-insensitive title substring (handled in SQL by `fetch_sessions`).
        """
        all_sessions = fetch_sessions(
            conn,
            project=project,
            model=model,
            agent=agent,
            q=q,
            from_ms=from_ms,
            to_ms=to_ms,
            include_empty=include_empty,
        )
        projects = fetch_projects(conn)
        total = len(all_sessions)

        if sort == "cost":
            # Sorting by cost requires computing every session's cost first.
            costs = [compute_cost(s, config.pricing) for s in all_sessions]
            order = sorted(
                range(len(all_sessions)),
                key=lambda i: (-costs[i][0], -all_sessions[i].updated_ms, all_sessions[i].id),
            )
            all_sessions = [all_sessions[i] for i in order]

        # Slice to the page BEFORE computing costs in the default path, so we
        # only price the sessions we actually return.
        page = all_sessions[offset : offset + limit] if limit is not None else all_sessions[offset:]
        page_costs = [compute_cost(s, config.pricing) for s in page]
        return {
            "total": total,
            "items": [
                _session_dict(s, projects, cost, unpriced)
                for s, (cost, unpriced) in zip(page, page_costs)
            ],
        }

    @app.get("/api/sessions/{session_id}")
    def session_detail(
        session_id: str,
        conn: sqlite3.Connection = Depends(get_db),
    ) -> dict:
        """One session plus its message count; 404 when the id is unknown."""
        session = fetch_session(conn, session_id)
        if session is None:
            return JSONResponse(
                status_code=404, content={"error": f"session '{session_id}' not found"}
            )
        cost, unpriced = compute_cost(session, config.pricing)
        count = conn.execute(
            "SELECT COUNT(*) FROM message WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        data = _session_dict(session, fetch_projects(conn), cost, unpriced)
        data["message_count"] = count
        return data

    @app.get("/api/sessions/{session_id}/messages")
    def session_messages(
        session_id: str,
        conn: sqlite3.Connection = Depends(get_db),
    ) -> dict:
        """A session's messages in insertion order; 404 when the session is unknown."""
        if fetch_session(conn, session_id) is None:
            return JSONResponse(
                status_code=404, content={"error": f"session '{session_id}' not found"}
            )
        return {
            "messages": [
                {
                    "role": m.role,
                    "model": m.model_key,
                    "tokens": dict(m.tokens),
                    "cost": m.cost,
                    "finish": m.finish,
                }
                for m in fetch_messages(conn, session_id)
            ]
        }

    @app.get("/api/export.csv")
    def export_csv(
        project: str | None = None,
        model: str | None = None,
        agent: str | None = None,
        q: str | None = None,
        from_ms: int | None = Query(default=None, alias="from"),
        to_ms: int | None = Query(default=None, alias="to"),
        include_empty: bool = False,
        conn: sqlite3.Connection = Depends(get_db),
    ) -> Response:
        """Download every matching session as CSV (same filters as /api/sessions)."""
        sessions = fetch_sessions(
            conn,
            project=project,
            model=model,
            agent=agent,
            q=q,
            from_ms=from_ms,
            to_ms=to_ms,
            include_empty=include_empty,
        )
        projects = fetch_projects(conn)
        return Response(
            content=render_sessions_csv(sessions, projects, config.pricing),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="sessions.csv"'},
        )

    # Static dashboard. Mounted LAST so every /api route above wins over it.
    # Resolved from the package location so `tracker serve` works from any CWD
    # and from any install mode (source checkout, pip wheel, npm bundle) —
    # package-data ships the assets inside the `tracker` package.
    web_dir = Path(__file__).resolve().parent / "web"
    if not web_dir.is_dir():
        raise RuntimeError(
            f"web dashboard directory not found at {web_dir}; "
            "install the package completely (the `web/` folder is required)."
        )
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app