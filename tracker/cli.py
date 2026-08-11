"""Command-line interface for the OpenCode Token Tracker (T-015).

Commands: `summary` (monthly spend/tokens report), `sessions` (table or CSV
export), and `serve` (start the FastAPI dashboard). All commands accept a
global `--config PATH`. The fastapi/uvicorn imports are deferred into
`cmd_serve` so the rest of the CLI works without the web dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tracker.aggregate import format_cost, month_bounds, month_bounds_for, summarize
from tracker.config import Budget, Config, load_config
from tracker.csvutil import csv_safe, render_sessions_csv
from tracker.db import DbNotFoundError, open_connection, resolve_db_path
from tracker.pricing import compute_cost, format_tokens
from tracker.store import TOKEN_KEYS, fetch_projects, fetch_sessions

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_config_from_args(args: argparse.Namespace) -> Config:
    return load_config(Path(args.config) if args.config else None)


def _month_bounds_for_arg(value: str, reset_day: int) -> tuple[int, int]:
    """Epoch-ms bounds for a `YYYY-MM` argument; raises ValueError when malformed."""
    if not _MONTH_RE.match(value):
        raise ValueError(value)
    year, month = (int(part) for part in value.split("-"))
    if month < 1 or month > 12:
        raise ValueError(value)
    return month_bounds_for(year, month, reset_day)


def _day_bounds(value: str) -> tuple[int, int]:
    """Epoch-ms bounds for a `YYYY-MM-DD` argument; raises ValueError when malformed."""
    if not _DATE_RE.match(value):
        raise ValueError(value)
    year, month, day = (int(part) for part in value.split("-"))
    start = datetime(year, month, day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return (int(start.timestamp() * 1000), int(end.timestamp() * 1000))


def _print_monthly_summary(config: Config, summary: dict, month_label: str) -> None:
    """Print the Journey 6 summary format."""
    totals = summary["totals"]
    budget = summary["budget"]
    tokens = totals["tokens"]
    print(f"OpenCode usage - {month_label}")
    if budget["monthly"] > 0:
        print(
            f"  Spend:            {format_cost(totals['cost'])}  "
            f"(budget {format_cost(budget['monthly'])}, {budget['percent']:.1f}%)"
        )
    else:
        print(f"  Spend:            {format_cost(totals['cost'])}  (no budget set)")
    print(f"  Projected:        {format_cost(budget['projected'])} by month end")
    print(
        "  Tokens:           "
        f"{format_tokens(tokens['input'])} in / {format_tokens(tokens['output'])} out / "
        f"{format_tokens(tokens['reasoning'])} reasoning / "
        f"{format_tokens(tokens['cache_read'])} cache read"
    )
    sessions_line = f"  Sessions:         {totals['sessions']}"
    if totals["unpriced_sessions"]:
        sessions_line += f" ({totals['unpriced_sessions']} unpriced)"
    print(sessions_line)
    if summary["by_project"]:
        top_project = summary["by_project"][0]
        print(
            f"  Top project:      {top_project['label']}  {format_cost(top_project['cost'])}"
        )
    if summary["by_model"]:
        top_model = summary["by_model"][0]
        free_marker = " (free)" if top_model["cost"] == 0 else ""
        print(
            f"  Top model:        {top_model['label']}  "
            f"{format_cost(top_model['cost'])}{free_marker}"
        )


def cmd_summary(args: argparse.Namespace, config: Config) -> int:
    try:
        conn = open_connection(resolve_db_path(config))
    except DbNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    with conn:
        projects = fetch_projects(conn)
        now = _now()
        if args.month:
            try:
                from_ms, to_ms = _month_bounds_for_arg(args.month, config.budget.reset_day)
            except ValueError:
                print(f"Invalid month '{args.month}'. Use YYYY-MM.", file=sys.stderr)
                return 2
            year, month = (int(part) for part in args.month.split("-"))
            now = datetime(year, month, 15, tzinfo=timezone.utc)
        else:
            from_ms, to_ms = month_bounds(now, config.budget.reset_day)
        sessions = fetch_sessions(
            conn,
            project=args.project,
            from_ms=from_ms,
            to_ms=to_ms,
        )
        if not sessions:
            print("No sessions found.")
            return 0
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
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    month_label = args.month if args.month else now.strftime("%B %Y")
    _print_monthly_summary(config, summary, month_label)
    return 0


def cmd_sessions(args: argparse.Namespace, config: Config) -> int:
    try:
        conn = open_connection(resolve_db_path(config))
    except DbNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    with conn:
        projects = fetch_projects(conn)
        from_ms = to_ms = None
        if args.from_date:
            try:
                from_ms, _ = _day_bounds(args.from_date)
            except ValueError:
                print(f"Invalid date '{args.from_date}'. Use YYYY-MM-DD.", file=sys.stderr)
                return 2
        if args.to_date:
            try:
                _, to_ms = _day_bounds(args.to_date)
            except ValueError:
                print(f"Invalid date '{args.to_date}'. Use YYYY-MM-DD.", file=sys.stderr)
                return 2
        sessions = fetch_sessions(
            conn,
            project=args.project,
            model=args.model,
            agent=args.agent,
            from_ms=from_ms,
            to_ms=to_ms,
            include_empty=args.include_empty,
        )
        if args.csv:
            content = render_sessions_csv(sessions, projects, config.pricing)
            try:
                Path(args.csv).write_text(content, encoding="utf-8", newline="")
            except OSError as exc:
                print(f"Cannot write {args.csv}: {exc}", file=sys.stderr)
                return 1
            print(f"Wrote {len(sessions)} sessions to {args.csv}.")
            return 0
        if not sessions:
            print("No sessions found.")
            return 0
        for session in sessions:
            cost, _ = compute_cost(session, config.pricing)
            total_tokens = sum(session.tokens.get(k, 0) for k in TOKEN_KEYS)
            project = projects.get(session.project_id) if session.project_id else None
            print(
                f"{session.id}  {session.title or ''}  "
                f"{project or ''}  "
                f"{session.model_key}  {format_tokens(total_tokens)}  "
                f"{format_cost(cost)}"
            )
    return 0


def cmd_serve(args: argparse.Namespace, config: Config) -> int:
    try:
        import uvicorn

        from tracker.api import create_app
    except ImportError:
        print(
            "Missing dependency: fastapi. Run: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    host = args.host or config.server_host
    port = args.port or config.server_port
    # uvicorn logs "address already in use" and exits 0 instead of raising, so
    # probe the bind first to give the user a clear message and exit code.
    import socket

    probe = socket.socket()
    try:
        probe.bind((host, port))
    except OSError:
        print(f"Port {port} is in use - try --port 9000", file=sys.stderr)
        return 1
    finally:
        probe.close()
    try:
        uvicorn.run(create_app(config), host=host, port=port)
    except OSError:
        print(f"Port {port} is in use - try --port 9000", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tracker")
    parser.add_argument("--config", help="path to config.json (default: config.json in CWD)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="path to config.json (default: config.json in CWD)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_summary = sub.add_parser("summary", parents=[common], help="monthly spend and token summary")
    p_summary.add_argument("--month", help="YYYY-MM budget month (default: current)")
    p_summary.add_argument("--project", help="filter by project id")
    p_summary.add_argument("--json", action="store_true", help="print raw summary JSON")
    p_summary.set_defaults(func=cmd_summary)

    p_sessions = sub.add_parser("sessions", parents=[common], help="list sessions or export CSV")
    p_sessions.add_argument("--csv", help="write sessions to this CSV file")
    p_sessions.add_argument("--project", help="filter by project id")
    p_sessions.add_argument("--model", help="filter by model key, e.g. opencode/deepseek-v4-flash-free")
    p_sessions.add_argument("--agent", help="filter by agent")
    p_sessions.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", help="start date")
    p_sessions.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", help="end date")
    p_sessions.add_argument("--include-empty", action="store_true", help="include aborted/empty sessions")
    p_sessions.set_defaults(func=cmd_sessions)

    p_serve = sub.add_parser("serve", parents=[common], help="start the web dashboard")
    p_serve.add_argument("--port", type=int, help="port (default: config server.port)")
    p_serve.add_argument("--host", help="host (default: config server.host)")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _load_config_from_args(args)
    raise SystemExit(args.func(args, config))


if __name__ == "__main__":
    main()
