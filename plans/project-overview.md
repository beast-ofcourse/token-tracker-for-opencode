# OpenCode Token Tracker — Project Overview

## One-line summary

A local, read-only dashboard and CLI that tracks OpenCode's token usage, spend, and budget by reading OpenCode's own SQLite database — no plugins, no hooks, no cloud.

## Problem & opportunity

OpenCode (the AI coding agent) records rich per-session usage data — tokens in/out/reasoning/cache, model, agent, provider, cost — in a local SQLite database (`~/.local/share/opencode/opencode.db`), but it has **no built-in way to see the big picture**: how much you've spent this month, which projects or models burn the most tokens, whether you're on track against a budget. This tool is that surface. It reads the live database read-only, computes cost from a user-maintained pricing table (the DB's own `cost` column is 0 for free models and unreliable for paid ones), and produces a local dashboard plus a CLI.

## Users & personas

- **Primary persona — the solo OpenCode user (this user).** Runs OpenCode daily across projects, uses free and paid models, wants to know monthly spend, per-project burn, and budget health at a glance. Comfortable with a terminal and a browser; not interested in a SaaS account or cloud sync.
- **Secondary persona — the power user / team lead.** Wants CSV export and per-session drill-down to report or allocate costs. Same tool, same data — no extra roles.

There are **no roles or permissions** — it is a single-user local tool.

## Goals / Non-goals

### Goals

- Read OpenCode's local SQLite database **read-only**, safely, while OpenCode is running (WAL mode).
- Compute cost from a **user-configurable pricing table** (per provider/model, per token bucket), because the DB's `cost` column is 0 for free models.
- Show a **local web dashboard** (localhost only) with: monthly summary, spend vs. budget, breakdowns by project / model / agent / day, and a filterable session list.
- Provide a **CLI** for quick terminal summaries and CSV export.
- Track a **monthly budget** with 80% warning and 100% exceeded alerts, plus a month-end projection.
- Auto-refresh the dashboard so it reflects OpenCode usage in near real time.
- Show a **per-message token breakdown** inside each session (click-to-expand), so expensive sessions can be traced to individual messages.

### Non-goals (binding)

- **No writes to OpenCode data.** The tool never modifies `opencode.db` or any OpenCode file.
- **No plugin/hook integration.** No OpenCode plugin, no TUI embedding, no interception of requests.
- **No cloud, no accounts, no auth.** Localhost-only; no telemetry; no sync.
- **No message text rendering in v1.** Per-message token/cost breakdown IS in v1 (data is in the `message` table); rendering message text is deferred to v2.
- **No background daemon.** The server runs when you run it.
- **No multi-user or team features.**
- **No TUI dashboard** in v1 (web dashboard + CLI only).

## In scope / Out of scope

### In scope

- Read-only access to `opencode.db` (with WAL-safe fallback).
- Pricing table config (JSON) with sensible defaults for common providers; free models priced at 0.
- Cost computation: `input`, `output`, `reasoning` (priced as input), `cache_read` (discounted), `cache_write` (premium).
- Aggregations: totals, by project, by model, by agent, by day; monthly budget math.
- Per-message token/cost breakdown per session (from the `message` table).
- Web dashboard: stat strip, token-volume chart, spend-by-model bars, budget panel, incident stream (sessions ordered by cost with severity chips), filters, click-to-expand session detail with per-message token breakdown.
- CLI: `summary`, `sessions`, `serve` commands; CSV export.
- Config: JSON file, DB path, pricing, budget, port, refresh interval.

### Out of scope

- Anything that changes OpenCode data.
- Cloud sync, multi-device, accounts.
- TUI, plugins, hooks.
- Message text rendering (v2).
- Alerting beyond in-page warnings (no email/desktop notifications in v1).

## Stack & key decisions

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | `sqlite3` is stdlib; user already has Python; boring and proven |
| API server | FastAPI + uvicorn | Boring, proven, async, free `/docs`; trivial static-file serving |
| Frontend | Vanilla JS + hand-rolled SVG charts (no chart library) | Matches the chosen Sentry-incident reference; no build step, no node toolchain |
| Fonts | Rubik + JetBrains Mono (vendored woff2, system fallbacks) | The reference design's typography; offline-safe |
| Config | JSON file (`config.json`, `--config` override) | No config-library dependency; human-editable |
| Data access | Fresh read-only SQLite connection per request; snapshot-copy fallback if WAL read-only fails | Never locks or corrupts the live DB; each request sees latest state |
| Cost source | Computed from pricing table; fall back to DB `cost` when model unpriced and DB cost > 0 | DB `cost` is 0 for free models; pricing table is the single source of truth for budget math |
| Budget | Monthly, configurable reset day (default 1st), USD label | Simple, matches how people think about spend |
| Refresh | Dashboard polls API every N seconds (default 30); each API call opens a fresh connection | Real-time without a daemon |
| Port | 127.0.0.1:8765 (configurable) | Localhost-only by design; uncommon port avoids clashes |
| Packaging | `pyproject.toml`, run via `python -m tracker` | No install needed; works from the repo |

## Spec record (11 areas)

1. **Product & business** — see Problem & opportunity, Goals/Non-goals. Success metric: the user can answer "how much did I spend this month, and where?" in under 10 seconds from the dashboard. MVP = dashboard + CLI + budget; later = per-message drill-down, TUI.
2. **Users & personas** — see Users & personas. Single user, no roles.
3. **Platform & delivery** — Local web app (localhost) + CLI. Windows primary (this machine), cross-platform Python. No offline needs beyond localhost.
4. **Core features** — see In scope. The 4 must-have journeys: (a) see monthly spend vs budget, (b) see per-project/model/agent breakdown, (c) browse/filter sessions, (d) CLI summary + CSV export.
5. **Stack** — see Stack & key decisions.
6. **Data** — Entities: `session` (id, project_id, title, model JSON, agent, cost, tokens_input/output/reasoning/cache_read/cache_write, time_created/updated/archived), `project` (id, worktree, name), `message` (id, session_id, data JSON with per-message tokens/cost — used for the per-message breakdown). Persistence: read-only from OpenCode's SQLite. Import/export: CSV export of sessions.
7. **Auth & security** — No accounts. Localhost-only binding. Read-only DB access. No secrets stored (config holds no credentials). No PII beyond project paths/titles already in the DB.
8. **Scale & reliability** — Single user; tens of thousands of sessions max (current DB: e.g., 37 sessions, 1.5k messages — counts drift as OpenCode runs). Aggregation in Python over fetched rows is fine at this scale. Uptime: local tool, no SLA. Budget: $0 (free models) — the tool must handle zero-cost gracefully. Timeline: v1 in this session.
9. **Integrations** — None external. Reads OpenCode's local SQLite DB only. No webhooks, no OAuth, no external APIs.
10. **Design** — Sentry Incident Room (reference: `sketches/004-sentry-incident`): deep purple-black canvas (`#1f1633`/`#150f23`), Rubik 400-700 + JetBrains Mono for IDs/token counts, uppercase 0.2px-letter-spaced labels, lime `#c2ef4e` accents used once per section, left project rail, incident stream ordered by cost with severity chips (all/high/med/low), click-to-expand per-message token breakdown, budget progress, overlay toasts, inset-shadow buttons. Details in `user-flow.md`.
11. **Deployment & ops** — Local only: `python -m tracker serve`. No CI/CD, no monitoring, no remote ops. `git init` + `.gitignore` for version control.

## Architecture at a glance

```
+----------------------+        read-only SQLite (WAL-safe)
|  OpenCode (live)     | <--------------------------------+
|  opencode.db         |                                  |
+----------------------+                                  |
                                                          |
+---------------------------------------------------------+---------+
|  tracker (Python package)                                          |
|  config.py -> db.py -> store.py -> pricing.py -> aggregate.py      |
|  api.py (FastAPI, 127.0.0.1:8765)   cli.py (summary/sessions/serve)|
+--------------------------------------------------------------------+
        | JSON API (polled every 30s)
        v
+------------------------------+
|  Dashboard (web/index.html)  |  stat strip . SVG charts . budget .
|  vanilla JS + SVG (no libs)  |  incident stream . filters . detail
+------------------------------+
```

Data flow: the dashboard polls the API; each API request opens a fresh read-only connection to `opencode.db` (or snapshot-copies to temp), reads `session` and `message` rows, parses the `model` JSON, computes costs via the pricing engine, aggregates, and returns JSON. The CLI uses the same pipeline.

## Key risks & unknowns

- **WAL read-only access on Windows.** Opening a WAL-mode DB read-only while OpenCode holds it can fail if the `-shm` file is missing. Mitigation: snapshot-copy fallback (copy `opencode.db`, `-wal`, `-shm` to temp, open the copy). Verified on this machine: `-shm` exists and read-only open works.
- **Pricing accuracy.** Prices change; the pricing table is user-maintained. Unknown models are flagged "unpriced" rather than silently priced at 0.
- **Schema drift.** OpenCode's schema may change between versions. Mitigation: defensive parsing (missing columns -> defaults), and the tool reads only well-known columns.
- **Zero-cost reality.** Today all costs are $0. The tool must not look broken when everything is free — it shows tokens prominently and cost as $0.00 with a "free model" note.
- **Offline fonts.** The reference uses Google Fonts; the tool vendors the woff2 files (like Chart.js) with system fallbacks so the dashboard works offline.

## Assumptions (YOLO decision record)

- Stack: Python 3.11+ / FastAPI / uvicorn / vanilla JS + hand-rolled SVG charts / vendored Rubik + JetBrains Mono / JSON config. No Node, no build step.
- Data source: `~/.local/share/opencode/opencode.db` (env override `OPENCODE_DB`), read-only, WAL-safe.
- Cost: computed from pricing table; DB `cost` used only as fallback for unpriced models with cost > 0.
- Budget: monthly, reset day 1 (configurable), USD, 80% warn / 100% exceeded, month-end projection.
- Port: 127.0.0.1:8765 (configurable). No auth.
- Refresh: dashboard polls every 30s (configurable); API opens a fresh connection per request.
- Scope: v1 = dashboard + CLI + CSV export + per-message token breakdown. v2 = message text rendering, TUI, notifications.
- Design: the dashboard follows `sketches/004-sentry-incident` (the user's chosen reference). Severity thresholds are cost-based and configurable (`severity.high_cost` / `severity.med_cost`).
- The project directory is not yet a git repo -> v1 initializes git.
- The user's DB currently has ~40 sessions across 3 projects (incl. `global`), all free models; counts drift as OpenCode runs, so the tool must handle zero-cost data gracefully.

## Project definition of done

- `python -m tracker serve` starts a dashboard at `http://127.0.0.1:8765` that shows: monthly spend vs budget, totals, per-project/model/agent/day breakdowns, an incident stream with severity chips, and click-to-expand session detail with per-message token breakdown — all computed from the live OpenCode DB.
- `python -m tracker summary` prints a monthly summary in the terminal; `python -m tracker sessions --csv out.csv` exports sessions.
- The tool never writes to OpenCode data; all access is read-only.
- `pytest` passes; README documents setup, config, and usage.
