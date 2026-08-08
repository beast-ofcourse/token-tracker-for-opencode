"""Aggregation and budget math for the OpenCode Token Tracker (T-007).

`summarize` turns a list of sessions into the summary dict the API and
dashboard consume: totals, per-model/project/agent breakdowns, a zero-filled
per-day series, and budget status with a month-end projection. Budget-month
boundaries follow the budget's `reset_day` (see `month_bounds_for`); all
timestamps are epoch milliseconds, interpreted in UTC.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone

from tracker.config import Budget, Price, Severity
from tracker.pricing import compute_cost
from tracker.store import TOKEN_KEYS, Session

#: Label used for sessions with no agent / no project in the breakdowns.
NONE_LABEL = "(none)"


def _utc_ms(dt: datetime) -> int:
    """Epoch milliseconds for a UTC datetime."""
    return int(dt.timestamp() * 1000)


def _as_utc(dt: datetime) -> datetime:
    """Interpret a naive datetime as UTC; convert aware datetimes to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def month_bounds_for(year: int, month: int, reset_day: int) -> tuple[int, int]:
    """Epoch-ms `(start, end)` of the budget month containing `year`/`month`.

    The month starts on `reset_day`, clamped to the month's length — a
    reset_day of 31 in a 30-day month starts on the 30th. The end is the
    start of the *next* budget month (exclusive), so with reset_day > 1 the
    month runs from that day to the day before it next month. A reset_day
    outside 1..31 is clamped into range.
    """
    reset = max(1, min(reset_day, 31))
    start_day = min(reset, calendar.monthrange(year, month)[1])
    start = datetime(year, month, start_day, tzinfo=timezone.utc)
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    end_day = min(reset, calendar.monthrange(next_year, next_month)[1])
    end = datetime(next_year, next_month, end_day, tzinfo=timezone.utc)
    return (_utc_ms(start), _utc_ms(end))


def month_bounds(now: datetime, reset_day: int) -> tuple[int, int]:
    """Epoch-ms bounds of the budget month containing `now` (UTC)."""
    return month_bounds_for(now.year, now.month, reset_day)


def _empty_tokens() -> dict[str, int]:
    return {key: 0 for key in TOKEN_KEYS}


def _group(
    sessions: list[Session],
    costs: list[float],
    key_of,
    label_of,
) -> list[dict]:
    """Group sessions by `key_of`, returning rows sorted by cost desc.

    Each row is `{key, label, sessions, tokens, cost}`; ties on cost are
    broken by key so the order is deterministic.
    """
    groups: dict[str, dict] = {}
    for session, cost in zip(sessions, costs):
        key = key_of(session)
        row = groups.get(key)
        if row is None:
            row = {
                "key": key,
                "label": label_of(key),
                "sessions": 0,
                "tokens": _empty_tokens(),
                "cost": 0.0,
            }
            groups[key] = row
        row["sessions"] += 1
        for token_key in TOKEN_KEYS:
            row["tokens"][token_key] += session.tokens.get(token_key, 0)
        row["cost"] += cost
    rows = list(groups.values())
    rows.sort(key=lambda row: (-row["cost"], row["key"]))
    return rows


def summarize(
    sessions: list[Session],
    projects: dict[str, str],
    pricing: dict[str, Price],
    now: datetime,
    budget: Budget,
    severity: Severity = Severity(),
    from_ms: int | None = None,
    to_ms: int | None = None,
) -> dict:
    """Aggregate sessions into the summary dict consumed by the API/dashboard.

    `severity` supplies the high-cost threshold for `totals.events_over_high`;
    it is passed explicitly (default `Severity()`, high_cost 5.0) rather than
    read from config so the function stays pure. `from_ms`/`to_ms` bound the
    zero-filled `by_day` series (`to_ms` exclusive, matching `month_bounds`);
    when omitted they default to the budget month containing `now`. Sessions
    are attributed to days by their UTC `created_ms`. The caller is expected
    to pass sessions already filtered to the desired range (the API does this
    via `fetch_sessions`); `totals` covers exactly the sessions given.

    The budget projection always uses the budget month containing `now`:
    `elapsed_days` = days from month start to today (>= 1, capped at the
    month length) and `projected = spent / elapsed_days * total_days`.
    """
    now = _as_utc(now)
    if from_ms is None or to_ms is None:
        from_ms, to_ms = month_bounds(now, budget.reset_day)

    computed = [compute_cost(session, pricing) for session in sessions]
    costs = [cost for cost, _ in computed]
    total_cost = sum(costs)
    unpriced = sum(1 for _, is_unpriced in computed if is_unpriced)

    tokens = {
        key: sum(session.tokens.get(key, 0) for session in sessions)
        for key in TOKEN_KEYS
    }

    largest = None
    if sessions:
        best = max(range(len(sessions)), key=lambda i: costs[i])
        session = sessions[best]
        largest = {
            "id": session.id,
            "title": session.title,
            "cost": costs[best],
            "model": session.model_key,
        }

    totals = {
        "cost": total_cost,
        "tokens": tokens,
        "sessions": len(sessions),
        "unpriced_sessions": unpriced,
        "largest_session": largest,
        "avg_cost": total_cost / len(sessions) if sessions else 0.0,
        "events_over_high": sum(1 for cost in costs if cost >= severity.high_cost),
    }

    # --- per-day series, zero-filled over [from_ms, to_ms) -----------------
    start_date = datetime.fromtimestamp(from_ms / 1000, tz=timezone.utc).date()
    end_date = datetime.fromtimestamp((to_ms - 1) / 1000, tz=timezone.utc).date()
    day_cost: dict = {}
    day_tokens: dict = {}
    for session, cost in zip(sessions, costs):
        day = datetime.fromtimestamp(session.created_ms / 1000, tz=timezone.utc).date()
        if day < start_date or day > end_date:
            continue
        day_cost[day] = day_cost.get(day, 0.0) + cost
        bucket = day_tokens.setdefault(day, _empty_tokens())
        for token_key in TOKEN_KEYS:
            bucket[token_key] += session.tokens.get(token_key, 0)
    by_day: list[dict] = []
    day = start_date
    while day <= end_date:
        by_day.append(
            {
                "day": day.isoformat(),
                "cost": day_cost.get(day, 0.0),
                "tokens": day_tokens.get(day, _empty_tokens()),
            }
        )
        day += timedelta(days=1)

    # --- budget status and projection --------------------------------------
    monthly = budget.monthly
    percent = total_cost / monthly * 100 if monthly > 0 else 0.0
    if percent >= 100:
        alert = "exceeded"
    elif percent >= 80:
        alert = "warn"
    else:
        alert = "ok"

    start_ms, end_ms = month_bounds(now, budget.reset_day)
    start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    total_days = (end_dt - start_dt).days
    elapsed_days = (now - start_dt).days + 1
    elapsed_days = max(1, min(elapsed_days, total_days))
    projected = total_cost / elapsed_days * total_days

    return {
        "totals": totals,
        "by_model": _group(
            sessions, costs, lambda s: s.model_key, lambda key: key
        ),
        "by_project": _group(
            sessions,
            costs,
            lambda s: s.project_id or NONE_LABEL,
            lambda key: projects.get(key, key),
        ),
        "by_agent": _group(
            sessions, costs, lambda s: s.agent or NONE_LABEL, lambda key: key
        ),
        "by_day": by_day,
        "budget": {
            "monthly": budget.monthly,
            "currency": budget.currency,
            "spent": total_cost,
            "remaining": budget.monthly - total_cost,
            "percent": percent,
            "projected": projected,
            "alert": alert,
        },
    }


def format_cost(x: float) -> str:
    """Format a cost in USD: `$12.34`, `$0.00` for zero."""
    return f"${x:.2f}"