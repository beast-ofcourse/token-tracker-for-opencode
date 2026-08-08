# OpenCode Token Tracker — Build Tasks

Execution owner: **SWE Pro**. SWE Pro dispatches each task to a fresh subagent, reviews the result (spec compliance, then code quality), and marks it done only when the Verify command passes. Tasks in the same phase with no shared files and no ordering dependency may be dispatched in parallel.

**Project root:** the directory containing this file (`plans/`). All paths below are relative to the project root.

**Shared context every task needs (restated in each task where relevant):**

- OpenCode's database lives at `~/.local/share/opencode/opencode.db` (on this machine: `C:\Users\Bhavin\.local\share\opencode\opencode.db`). It is a SQLite database in WAL mode, actively written by OpenCode. The tool must NEVER write to it.
- The `session` table has columns: `id TEXT`, `project_id TEXT`, `title TEXT`, `model TEXT` (a JSON string like `{"id":"deepseek-v4-flash-free","providerID":"opencode","variant":"high"}` or NULL), `agent TEXT`, `cost REAL`, `tokens_input INTEGER`, `tokens_output INTEGER`, `tokens_reasoning INTEGER`, `tokens_cache_read INTEGER`, `tokens_cache_write INTEGER`, `time_created INTEGER`, `time_updated INTEGER`, `time_archived INTEGER`. Timestamps are epoch **milliseconds**.
- The `project` table has `id TEXT`, `worktree TEXT`, `name TEXT`.
- The `message` table has `id`, `session_id`, `data TEXT` (JSON with `role`, `tokens {total, input, output, reasoning, cache {read, write}}`, `cost`, `modelID`, `providerID`, `finish`) — used for the per-message token breakdown.
- Model key format: `provider/model` (e.g., `opencode/deepseek-v4-flash-free`). A model whose id ends with `-free` is free (cost 0).
- Cost is computed from a pricing table, NOT read from the DB `cost` column (which is 0 for free models).
- Python 3.11+. Dependencies: `fastapi`, `uvicorn` (in `requirements.txt`). Dev dependencies: `pytest`, `httpx` (in `requirements-dev.txt`).

---

## Phase 0 — Foundations

### T-001 — Repo scaffold and git init

**Build:**
- Create `pyproject.toml` with project name `opencode-token-tracker`, `requires-python = ">=3.11"`, dependencies `fastapi` and `uvicorn`, optional dev dependencies `pytest` and `httpx`, and a `[project.scripts]` entry `opencode-token-tracker = "tracker.cli:main"`.
- Create `requirements.txt` containing `fastapi` and `uvicorn`.
- Create `requirements-dev.txt` containing `pytest` and `httpx`.
- Create the `tracker/` package directory with an empty `tracker/__init__.py`.
- Create `.gitignore` covering: `__pycache__/`, `*.pyc`, `.venv/`, `config.json`, `*.csv`, `.pytest_cache/`.
- Create an empty `README.md` (content filled in T-018).
- Run `git init` in the project root and make an initial commit of the scaffold.
- Install dependencies: `pip install -r requirements.txt -r requirements-dev.txt` (required before the acceptance import check).

**Acceptance criteria:**
- `python -c "import tracker"` succeeds from the project root.
- `python -c "import fastapi, uvicorn, pytest, httpx"` succeeds (dependencies installed).
- `git status` shows a clean working tree after the initial commit.
- `pyproject.toml` parses as valid TOML.

**Verify:** `python -c "import tracker, fastapi, uvicorn, pytest, httpx"; git status --short; git log --oneline -1`

---

### T-002: Config module and example config

**Build:**
- Create `tracker/config.py` with:
  - A `Config` dataclass: `db_path: Path`, `budget: Budget`, `severity: Severity`, `pricing: dict[str, Price]`, `server_host: str`, `server_port: int`, `refresh_seconds: int`.
  - A `Budget` dataclass: `monthly: float`, `currency: str = "USD"`, `reset_day: int = 1`.
  - A `Severity` dataclass: `high_cost: float = 5.0`, `med_cost: float = 1.0` (cost thresholds in currency).
  - A `Price` dataclass: `input: float`, `output: float`, `cache_read: float`, `cache_write: float` (USD per 1M tokens).
  - `load_config(path: Path | None) -> Config`: loads the JSON file if it exists; otherwise returns defaults and prints a note to stderr. Invalid JSON prints `config.json is not valid JSON: <error>` to stderr and returns defaults (never crashes). Unknown keys are ignored with a warning. JSON-to-dataclass mapping: `server.host` -> `server_host`, `server.port` -> `server_port`, `budget.monthly` -> `budget.monthly`, `budget.currency` -> `budget.currency`, `budget.reset_day` -> `budget.reset_day`, `severity.high_cost` -> `severity.high_cost`, `severity.med_cost` -> `severity.med_cost`, `pricing` keys `provider/model` -> `Price` objects.
  - Defaults: `db_path = Path.home() / ".local/share/opencode/opencode.db"` (overridable by env var `OPENCODE_DB`), `budget = Budget(20.0, "USD", 1)`, `severity = Severity(5.0, 1.0)`, `server_host = "127.0.0.1"`, `server_port = 8765`, `refresh_seconds = 30`.
  - A built-in default pricing table for common models (e.g., `openai/gpt-4o`, `openai/gpt-4o-mini`, `anthropic/claude-sonnet-4`, `anthropic/claude-opus-4`, `google/gemini-2.5-pro`, `deepseek/deepseek-chat`) with realistic per-1M prices. Models whose id ends with `-free` are priced 0.
- Create `config.example.json` at the project root mirroring the schema in `user-flow.md` Journey 7, with `db_path`, `budget`, `pricing`, `server`, `refresh_seconds`.
- Create `tests/test_config.py` with unit tests: defaults when file missing; env override of db path; invalid JSON prints a note and returns defaults; unknown keys ignored; free-model pricing is 0; severity defaults (5.0/1.0).

**Acceptance criteria:**
- `pytest tests/test_config.py` passes.
- `python -c "from tracker.config import load_config; c = load_config(); print(c.db_path)"` prints the default DB path.

**Verify:** `python -m pytest tests/test_config.py -q`

---

## Phase 1 — Data layer

### T-003: Test fixture database builder

**Build:**
- Create `tests/conftest.py` with a fixture `fixture_db(tmp_path)` that builds a small synthetic OpenCode database at `tmp_path/opencode.db` using `sqlite3` with the exact schema from the shared contract (tables `session`, `project`, `message`; only the columns listed there).
- The fixture must contain at least: 3 projects (one named `global` with worktree `/`), 12 sessions spanning two calendar months, including: a free model session (`opencode/deepseek-v4-flash-free`), a paid model session (`openai/gpt-4o`), an empty/aborted session (NULL model, all tokens 0), a session with NULL agent, and sessions with realistic token counts (some in the millions). `message` table gets 2 rows referencing one session.
- Provide a helper `fixture_config(tmp_path)` returning a `Config` whose `db_path` points at the fixture DB and whose pricing includes `openai/gpt-4o` at known prices (e.g., input 2.50, output 10.00, cache_read 1.25, cache_write 2.50).

**Acceptance criteria:**
- A test that opens the fixture DB and counts 10+ sessions passes.
- The fixture DB opens with `sqlite3.connect` and `PRAGMA integrity_check` returns `ok`.

**Verify:** `python -m pytest tests/conftest.py -q` (or a smoke test importing the fixtures)

---

### T-004: Read-only database access (db.py)

**Build:**
- Create `tracker/db.py` with:
  - `resolve_db_path(config: Config) -> Path`: expands `~`, honors `OPENCODE_DB` env override, returns the path.
  - `open_connection(db_path: Path) -> sqlite3.Connection`: opens the DB **read-only** using the URI form `sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)` where `quote` is `urllib.parse.quote` (percent-encode the path so spaces/`?`/`#` work). Set `PRAGMA busy_timeout = 5000` and `PRAGMA query_only = ON`.
  - If the read-only open raises (e.g., WAL `-shm` missing on Windows), fall back to a **snapshot copy**: copy `opencode.db`, `opencode.db-wal`, `opencode.db-shm` (whichever exist) into a fresh `tempfile.mkdtemp()` directory, open the copy read-only, and return the connection. The temp dir is cleaned up when the connection closes (register via `atexit` or a wrapper).
  - `open_connection` must never raise for a missing DB file — it raises `DbNotFoundError` with a helpful message.
- Create `tests/test_db.py`: read-only open works on the fixture DB; a write attempt raises `sqlite3.OperationalError` (proving read-only); `DbNotFoundError` raised for a missing path; snapshot fallback works when the `-shm` file is absent (simulate by deleting it from a copied fixture).

**Acceptance criteria:**
- `pytest tests/test_db.py` passes.
- Opening the real user DB read-only succeeds on this machine (manual check: `python -c "from tracker.db import open_connection; from tracker.config import load_config; c=load_config(); conn=open_connection(c.db_path); print(conn.execute('select count(*) from session').fetchone())"`).

**Verify:** `python -m pytest tests/test_db.py -q`

---

### T-005: Session model and parsing (store.py)

**Build:**
- Create `tracker/store.py` with:
  - A `Session` dataclass: `id`, `project_id`, `title`, `model_key` (str, `provider/model` or `"unknown"`), `model_variant` (str | None), `agent` (str | None), `cost_db` (float), `tokens` (dict with keys `input`, `output`, `reasoning`, `cache_read`, `cache_write`), `created_ms`, `updated_ms`, `archived_ms` (int | None).
  - `parse_model(model_json: str | None) -> tuple[str, str | None]`: parses the JSON `{"id": ..., "providerID": ..., "variant": ...}` into `(provider/model, variant)`; returns `("unknown", None)` for NULL or unparseable JSON.
  - `fetch_sessions(conn, *, project: str | None = None, model: str | None = None, agent: str | None = None, q: str | None = None, from_ms: int | None = None, to_ms: int | None = None, include_empty: bool = False, limit: int | None = None, offset: int = 0) -> list[Session]`: SELECTs from `session` with optional WHERE filters on `project_id`, `model` (exact match on the parsed `model_key`, e.g. `opencode/deepseek-v4-flash-free`; filter in Python after fetching — do NOT use LIKE on the JSON column, the stored JSON has no `/` between provider and id), `agent`, and `time_created` range; orders by `time_updated DESC`. **Filtering order:** apply the SQL filters (project_id, agent, `q` title LIKE, time_created range) in SQL, then apply the `model` filter in Python on the parsed `model_key`, THEN apply `limit`/`offset` in Python — never SQL LIMIT before the model filter, or pagination silently returns wrong pages. An **empty session** is one where all five token columns are 0 AND `model` is NULL — excluded unless `include_empty=True`.
  - `fetch_projects(conn) -> dict[str, str]`: maps `project_id` to `worktree` (fall back to `name`).
  - A `Message` dataclass: `id`, `role` (str | None), `model_key` (str), `tokens` (dict with keys `input`, `output`, `reasoning`, `cache_read`, `cache_write`), `cost` (float), `finish` (str | None).
  - `fetch_messages(conn, session_id: str) -> list[Message]`: SELECTs from `message` WHERE `session_id = ?`, parses each `data` JSON (`role`, `tokens` with `input`/`output`/`reasoning`/`cache.read`/`cache.write`, `cost`, `modelID`/`providerID`, `finish`); rows without a `tokens` object are skipped; ordered by `time_created ASC`.
- Create `tests/test_store.py` using the T-003 fixture: parsing of a real model JSON; NULL model -> `unknown`; filtering by project/model/agent/date (including model key `opencode/deepseek-v4-flash-free`); empty-session exclusion; ordering; model filter + limit returns exactly `limit` rows of that model; `fetch_messages` parses the fixture's message rows with correct tokens/cost.

**Acceptance criteria:**
- `pytest tests/test_store.py` passes.
- `fetch_sessions` returns `Session` objects with correct `model_key` for the fixture's free and paid sessions.

**Verify:** `python -m pytest tests/test_store.py -q`

---

### T-006: Pricing and cost computation (pricing.py)

**Build:**
- Create `tracker/pricing.py` with:
  - `price_for(model_key: str, pricing: dict[str, Price]) -> Price | None`: exact match on `provider/model` first (an explicit user price always wins); if no exact match and the model id ends with `-free`, return `Price(0, 0, 0, 0)`; otherwise None.
  - `compute_cost(session: Session, pricing: dict[str, Price]) -> tuple[float, bool]`: returns `(cost, unpriced)`. Cost = `input * price.input + output * price.output + reasoning * price.input + cache_read * price.cache_read + cache_write * price.cache_write`, all divided by 1_000_000. If `price_for` returns None: if `session.cost_db > 0`, return `(session.cost_db, True)`; else `(0.0, True)`.
  - `format_tokens(n: int) -> str`: human formatting (`1.2M`, `585K`, `1234`).
- Create `tests/test_pricing.py`: free model costs 0 and is not unpriced; an explicitly-priced `-free` model uses the explicit price; paid model computes the exact expected cost for known token counts; unknown model with `cost_db=0` returns `(0.0, True)`; unknown model with `cost_db>0` returns the DB cost; reasoning priced as input; cache buckets priced correctly.

**Acceptance criteria:**
- `pytest tests/test_pricing.py` passes.
- For a session with 1,000,000 input tokens on `openai/gpt-4o` (input 2.50), cost is exactly 2.50.

**Verify:** `python -m pytest tests/test_pricing.py -q`

---

### T-007: Aggregation and budget math (aggregate.py)

**Build:**
- Create `tracker/aggregate.py` with:
  - `month_bounds(now: datetime, reset_day: int) -> tuple[int, int]` and `month_bounds_for(year: int, month: int, reset_day: int) -> tuple[int, int]`: epoch-ms start and end of a budget month (month starts on `reset_day`, clamped to `min(reset_day, days_in_month)`; if `reset_day` > 1, the month runs from that day to the day before it next month). `month_bounds` delegates to `month_bounds_for` with the current year/month. Projection definition: `elapsed_days` = days from month start to today (>= 1), `total_days` = days in the budget month. `by_day` covers the current budget month (or the requested from/to range) — never a fixed 30 days.
  - `summarize(sessions: list[Session], projects: dict[str, str], pricing: dict[str, Price], now: datetime, budget: Budget) -> dict`: returns a dict with:
    - `totals`: `cost`, `tokens` (input/output/reasoning/cache_read/cache_write), `sessions`, `unpriced_sessions`, `largest_session` (`{id, title, cost, model}` or null), `avg_cost`, `events_over_high` (count of sessions with cost >= `severity.high_cost`).
    - `by_model`, `by_project`, `by_agent`: lists of `{key, label, sessions, tokens, cost}` sorted by cost desc (projects labeled by worktree path).
    - `by_day`: list of `{day: "YYYY-MM-DD", cost, tokens}` for the current budget month (or the requested from/to range), zero-filled.
    - `budget`: `{monthly, currency, spent, remaining, percent, projected, alert}` where `alert` is `"ok" | "warn" | "exceeded"` (warn at >= 80%, exceeded at >= 100%), and `projected = spent / elapsed_days * total_days`.
  - `format_cost(x: float) -> str`: `$12.34` style, `$0.00` for zero.
- Create `tests/test_aggregate.py`: totals match hand-computed values from the fixture; by_model/by_project/by_agent grouping; by_day zero-filling; budget math for ok/warn/exceeded; projection formula.

**Acceptance:**
- `pytest tests/test_aggregate.py` passes.
- `summarize` on the fixture returns a budget `alert` of `"ok"` when spent < 80% of budget.

**Verify:** `python -m pytest tests/test_aggregate.py -q`

---

## Phase 2 — API

### T-008: FastAPI app skeleton, /api/health, /api/summary

**Build:**
- Create `tracker/api.py` with:
  - `create_app(config: Config) -> FastAPI`: builds the app with a per-request dependency that opens a fresh read-only connection (T-004) and closes it after the request.
  - `GET /api/health` -> `{"status": "ok", "db": "ok"}` or `{"status": "degraded", "db": "error", "error": "..."}` if the DB cannot be opened.
  - `GET /api/summary?from=&to=` (optional ms timestamps; default = current budget month) -> the `summarize` dict from T-007, with `totals`, `by_model`, `by_project`, `by_agent`, `by_day`, `budget`. The endpoint MUST compute the month bounds via `month_bounds` and pass `from_ms`/`to_ms` to `fetch_sessions`, so `budget.spent` reflects the current month only — never all-time spend.
  - Errors: DB open failure -> HTTP 503 with `{"error": "..."}`; unexpected errors -> HTTP 500.
- Create `tracker/__main__.py` with a minimal `serve` entry that calls `uvicorn.run(create_app(load_config()), host=..., port=...)` (full CLI in T-015).
- Create `tests/test_api.py` using `fastapi.testclient.TestClient` against the fixture DB: health ok; summary returns the expected totals and budget shape; 503 when the DB path is missing.

**Acceptance:**
- `pytest tests/test_api.py` passes.
- `python -m tracker serve` starts and `curl http://127.0.0.1:8765/api/health` returns `{"status":"ok","db":"ok"}`.

**Verify (PowerShell):**
```powershell
python -m pytest tests/test_api.py -q
$p = Start-Process python -ArgumentList '-m','tracker','serve' -PassThru
Start-Sleep -Seconds 2
if ($p.HasExited) { Write-Error 'Server failed to start'; exit 1 }
curl.exe -s http://127.0.0.1:8765/api/health
Stop-Process -Id $p.Id
```

---

### T-009: Sessions endpoints and CSV export

**Build:**
- In `tracker/api.py` add:
  - `GET /api/sessions?project=&model=&agent=&q=&from=&to=&include_empty=&limit=&offset=&sort=updated|cost` -> `{"total": N, "items": [session dicts]}` (`sort=cost` orders by computed cost desc; default `updated`). `q` filters by title substring (case-insensitive, literal — escape `%`/`_` in the pattern or use `instr(lower(title), lower(?)) > 0`; pass through to `fetch_sessions`). Each session dict: `id`, `title`, `project` (worktree path), `model`, `agent`, `tokens` (5 buckets), `cost`, `unpriced`, `created_at` (ISO), `updated_at` (ISO).
  - `GET /api/sessions/{session_id}` -> the session dict plus `message_count` (COUNT from `message` table).
  - `GET /api/sessions/{session_id}/messages` -> `{"messages": [{role, model, tokens, cost, finish}]}` from `fetch_messages`; 404 if the session does not exist.
  - `GET /api/export.csv` with the same filters as `/api/sessions` -> `text/csv` download with columns: `id,title,project,model,agent,created_at,updated_at,tokens_input,tokens_output,tokens_reasoning,tokens_cache_read,tokens_cache_write,cost,unpriced`. CSV cells starting with `=`, `+`, `-`, `@` must be prefixed with a single quote (CSV injection guard).
- Extend `tests/test_api.py`: sessions list respects filters and pagination; the `q` title filter returns only matching titles; `sort=cost` orders by cost desc; session detail returns message_count; the messages endpoint returns the fixture's messages; CSV export returns the right header and escapes a malicious title.

**Acceptance:**
- `pytest tests/test_api.py` passes.
- `curl -s "http://127.0.0.1:8765/api/sessions?limit=5"` returns 5 sessions.

**Verify:** `python -m pytest tests/test_api.py -q`

---

### T-010: Breakdown, config, and static serving

**Build:**
- In `tracker/api.py` add:
  - `GET /api/breakdown?group_by=project|model|agent|day&from=&to=` -> `{"rows": [{key, label, sessions, tokens, cost}]}` (for `day`, `key` is `YYYY-MM-DD`). Default `from`/`to` = the same month bounds as `/api/summary`.
  - `GET /api/config` -> sanitized config: `{db_path, budget, pricing, server_host, server_port, refresh_seconds}` (no secrets exist in config; still, never echo raw file contents).
  - Mount static files: `app.mount("/", StaticFiles(directory="web", html=True), name="web")` so `http://127.0.0.1:8765/` serves `web/index.html`. The mount must be added LAST so API routes take precedence.
- Extend `tests/test_api.py`: breakdown by each group_by returns rows; `/` serves the dashboard HTML (create a placeholder `web/index.html` with `<title>OpenCode Token Tracker</title>` if it does not exist yet).

**Acceptance:**
- `pytest tests/test_api.py` passes.
- `curl -s http://127.0.0.1:8765/` returns the dashboard HTML.

**Verify:** `python -m pytest tests/test_api.py -q`

---

## Phase 3 — Dashboard

### T-011: Dashboard shell (index.html + style.css)

**Build:**
- Create `web/index.html` and `web/style.css` implementing the **Sentry Incident Room** design from `sketches/004-sentry-incident` (the user's chosen reference), adapted to real data:
  - Palette: `--bg: #1f1633`, `--bg-deep: #150f23`, `--border: #362d59`, `--border-strong: #584674`, `--purple: #6a5fc1`, `--deep-violet: #422082`, `--lime: #c2ef4e`, `--coral: #ffb287`, `--red: #ff5f5f`, `--amber: #ffbc6e`, `--muted: #a99ec4`, `--dim: #7d7395`.
  - Typography: Rubik (400/500/600/700) for UI, JetBrains Mono (400/500) for IDs and token counts; uppercase + 0.2px letter-spacing labels everywhere (signature pattern).
  - Layout: left sidebar (brand, nav sections, project rail with colored dots, footer with budget progress bar + sync status), main column (topbar with title + `Export CSV`, stat strip of 4 cards, token-volume chart panel, spend-by-model panel, token-events panel with severity chips, KPI row).
  - Components: severity filter chips, incident cards (severity dot + label, title, model, tokens, cost), click-to-expand detail container, overlay toast, inset-shadow buttons, empty-state and error-banner containers.
- Vendor fonts: download Rubik (400/500/600/700) and JetBrains Mono (400/500) woff2 files into `web/vendor/fonts/` (Google Fonts CSS API or direct woff2 URLs), declare `@font-face` with system fallbacks (`system-ui, -apple-system, 'Segoe UI', Roboto` / `ui-monospace, SFMono-Regular, Menlo`). If a font download fails, the task fails — no CDN fonts; the dashboard must work fully offline.
- NO chart library: charts are hand-rolled SVG (see T-012). Do not reference or vendor Chart.js.
- Reference `app.js` from `index.html`. `app.js` may be an empty stub in this task.

**Acceptance:**
- Opening `http://127.0.0.1:8765/` renders the full layout with all sections visible and no console errors (beyond missing data).
- `web/vendor/fonts/` contains the vendored woff2 files (Rubik + JetBrains Mono).

**Verify:** start the server, open the page in a browser, check the console; `Test-Path web/vendor/fonts`

---

### T-010b: Breakdown week/month buckets (added by user revision 2026-08-08)

**Build:**
- In `tracker/api.py` extend `GET /api/breakdown` to accept `group_by=week|month` in addition to `project|model|agent|day`:
  - `week`: buckets by ISO week, key `"YYYY-Www"` (e.g. `2026-W32`), label human-readable (e.g. `Aug 3`), NO zero-fill — only weeks with sessions appear.
  - `month`: buckets by calendar month, key `"YYYY-MM"`, label `Aug 2026`, NO zero-fill.
  - Both return the same row shape `{key, label, sessions, tokens, cost}`.
- Extend `tests/test_api.py`: week and month bucketing returns correct keys/labels/costs for the fixture (fixture spans June + July 2026).

**Acceptance:** `pytest tests/test_api.py` passes; `curl "http://127.0.0.1:8765/api/breakdown?group_by=month"` returns month rows.

**Verify:** `python -m pytest tests/test_api.py -q`

---

### T-011 (REVISED by user 2026-08-08): Minimalist dashboard shell (index.html + style.css)

**Build:**
- REWRITE `web/index.html` and `web/style.css` as a modern minimalist dashboard. The Sentry Incident Room design is abandoned. No budget panel, no stat cards, no incident stream, no filters, no session detail.
- Content: header (app name, theme toggle button, sync status dot), a range selector (Daily / Weekly / Monthly / All time), one token-usage chart panel (stacked input/output bars), one per-model chart panel (horizontal bars), empty states, error banner, toast.
- **Themes:** full dark theme AND full light theme via CSS custom properties on `:root` / `[data-theme="light"]`; a toggle button switches `data-theme` on `<html>`; persist choice in `localStorage`; respect `prefers-color-scheme` as the default when no stored choice. Both themes must look polished: generous whitespace, one accent color, big numbers, subtle borders, no clutter.
- Typography: Rubik (400/500/600/700) + JetBrains Mono (400/500) — reuse the already-vendored `web/vendor/fonts/` woff2 files; keep `@font-face` with system fallbacks.
- No chart library — hand-rolled SVG (T-012). Reference `app.js` (stub OK).
- Keep IDs: `#chart`, `#chartEmpty`, `#modelSplit`, `#modelEmpty`, `#errorBanner`, `#toast`, `#syncDot`, `#syncText`, `#themeToggle`, `#rangeTabs`, `#exportBtn` (export button optional — remove if not needed).

**Acceptance:** page renders both themes with no console errors; toggle switches theme and persists; fonts load from `web/vendor/fonts/` only.

**Verify:** headless browser check (both themes, no console errors, no failed requests); `Test-Path web/vendor/fonts`.

---

### T-012: Summary cards and charts (app.js part 1)

**Build:**
- Implement in `web/app.js`:
  - `fetchSummary()`: GET `/api/summary`, render the stat strip (4 cards: `Tokens (month)`, `Cost (month)`, `Sessions`, `Budget remaining`), the budget panel (progress bar width = `percent`, color green/amber/red, projection line, alert banner), and the KPI row (`largest_session`, `events_over_high`, `avg_cost`).
  - **Token volume chart** (hand-rolled SVG, matching the reference): per-day bars for the current month from `by_day` — input (purple) and output (coral) stacked; `<title>` tooltips with exact counts.
  - **Spend by model** (progress bars): from `by_model` (top 5) — name, share %, cost.
  - `formatMoney(x)`: `$12.34`; `formatTokens(n)`: `1.2M`, `585K`, `1234` (match tracker.pricing.format_tokens behavior: M >= 1_000_000, K >= 10_000, one decimal dropped when .0).
  - Handle the "all free" case: when total cost is 0 but tokens > 0, show a note `All models free — showing token usage.`
  - Unpriced display rule: render `cost` when it is a number > 0; show `—` only when `unpriced` is true and cost is 0.
  - Handle empty data: show empty-state text in charts instead of rendering empty charts.
- Create `tests/` is not needed for JS; verify manually.

**Acceptance:** With the server running against the real DB, the dashboard shows real numbers in cards and charts; with the fixture DB (via a temporary config), charts render with data.

**Verify:** browser check against the real DB; `python -m tracker serve` running.

---

### T-012 (REVISED 2026-08-08): Range selector, charts, theme toggle (app.js)

**Build:**
- Implement in `web/app.js`:
  - **Range selector** (Daily / Weekly / Monthly / All time tabs):
    - Daily: `from = now - 29 days`, `group_by=day`
    - Weekly: `from = now - 11 weeks`, `group_by=week`
    - Monthly: `from = now - 11 months`, `group_by=month`
    - All time: `from = 0`, `group_by=month`
    - All ranges: `to = now`. Fetch `GET /api/breakdown?group_by=...&from=...&to=...` for the chart AND `GET /api/breakdown?group_by=model&from=...&to=...` for the per-model panel.
  - **Token usage chart**: hand-rolled SVG stacked bars — input (one color) + output (another) per bucket; `<title>` tooltips with exact counts; axis labels (bucket label under each bar or sparse labels); empty state when no data.
  - **Per-model panel**: horizontal bars per model — model name, token count (formatTokens), share % of total tokens; sorted desc; empty state.
  - `formatTokens(n)`: `1.2M`, `585K`, `1234` (M >= 1_000_000, K >= 10_000, drop `.0`).
  - **Theme toggle**: switch `data-theme` on `<html>`, persist in `localStorage`, default from `prefers-color-scheme`.
  - **Auto-refresh**: poll every 30s (from `/api/config` `refresh_seconds`); on failure keep last data, show red sync dot + `Offline · last update HH:MM:SS`; recover on next success (green `Live · updated HH:MM:SS`).
  - Error banner on API failure: `Dashboard server unreachable — retrying…`; 503: `Database temporarily unavailable`.
  - No chart library — hand-rolled SVG only.
- The old T-012/T-013/T-013b/T-013c/T-014 content (stat cards, budget panel, incident stream, filters, session detail, breakdown tables, toasts) is CANCELLED — do not build any of it.

**Acceptance:** switching tabs changes the chart granularity and refetches; theme toggle switches and persists; per-model panel matches the range; auto-refresh updates data; server stop keeps last data + red dot, recovers on restart.

**Verify:** browser check against the real DB (all four tabs, both themes, stop/start server).

---

## Phase 4 — CLI

### T-015: CLI commands (cli.py)

**Build:**
- Create `tracker/cli.py` with `main(argv=None)` and a `tracker/__main__.py` that calls it. Commands:
  - `summary [--month YYYY-MM] [--project X] [--json]`: prints the monthly summary exactly in the format shown in `user-flow.md` Journey 6 (Spend, Projected, Tokens, Sessions, Top project, Top model). `--json` prints the `summarize` dict as JSON. Invalid month -> stderr `Invalid month 'X'. Use YYYY-MM.` and exit code 2. No data -> `No sessions found.` exit 0.
  - `sessions [--csv PATH] [--project X] [--model M] [--agent A] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--include-empty]`: prints a table of sessions (id, title, project, model, tokens, cost) or writes CSV with the same columns as `/api/export.csv`. Unwritable path -> stderr `Cannot write <path>: <reason>` exit 1.
  - `serve [--port N] [--host H] [--config PATH]`: starts the FastAPI app (reuse T-008's entrypoint). Port busy -> stderr `Port N is in use — try --port 9000` exit 1.
  - Global `--config PATH` flag for all commands.
  - Wrap the fastapi/uvicorn imports in `main()`; on `ImportError` print `Missing dependency: fastapi. Run: pip install -r requirements.txt` to stderr and exit 1.
- Create `tests/test_cli.py` (use `subprocess` or call `main` with `capsys`): summary prints expected fields; `--json` is valid JSON; invalid month exits 2; sessions CSV writes a file with the header; port-busy path exits 1.

**Acceptance:**
- `pytest tests/test_cli.py` passes.
- `python -m tracker summary` prints a sensible summary against the real DB.

**Verify:** `python -m pytest tests/test_cli.py -q; python -m tracker summary`

---

## Phase 5 — Hardening

### T-016: Error handling and edge cases

**Build:**
- Audit and fix error paths across the codebase:
  - Missing DB file -> dashboard banner + CLI message (already covered; verify end-to-end).
  - WAL read-only failure -> snapshot fallback works (verify with a test that deletes `-shm`).
  - Corrupt model JSON -> `unknown` model, no crash.
  - `time_created` NULL or 0 -> treated as epoch 0, excluded from month bounds.
  - Token counts NULL -> treated as 0.
  - Very large numbers -> `formatTokens` handles millions/billions.
  - Empty DB (no sessions) -> summary returns zeros, dashboard shows empty states.
  - Config with `budget.monthly = 0` -> budget disabled (percent 0, alert `ok`, no division by zero).
- Add tests for each edge case in the appropriate test file.

**Acceptance:** `pytest` passes with the new edge-case tests; manual run against a copy of the real DB with `-shm` removed works. **Manual verify (real trigger path, OpenCode STOPPED):** stop OpenCode, temporarily rename `opencode.db-shm`, run the snapshot fallback, confirm the copy opens and session counts match, then restore the file. Note: the fallback's real-world trigger (shm missing while OpenCode runs) is inherently hard to test; the copied-fixture test remains the automated coverage.

**Verify:** `python -m pytest -q`

---

### T-017: Security pass

**Build:**
- Verify and enforce:
  - Server binds `127.0.0.1` by default (config `server_host`); never `0.0.0.0` unless explicitly configured.
  - All DB access is read-only (`mode=ro` + `PRAGMA query_only=ON`); no code path writes to the OpenCode DB.
  - No secrets in config or logs (config holds no credentials; ensure error messages never echo env vars).
  - CSV injection guard present in both `/api/export.csv` and the CLI CSV writer (shared helper).
  - Static file serving cannot escape `web/` (FastAPI `StaticFiles` default behavior — add a test that `GET /../pyproject.toml` and `GET /%2e%2e/pyproject.toml` return 404; use `curl --path-as-is` — httpx normalizes dot segments before the URL is sent, so it cannot exercise the raw path).
  - No `eval`, no shell interpolation of user input.
- Add tests for the traversal and CSV-injection cases.

**Acceptance:** `pytest` passes; a manual `curl` of traversal paths returns 404; code review finds no write path to the OpenCode DB.

**Verify:** `python -m pytest -q`

---

### T-018: README and final verification

**Build:**
- Write `README.md` covering: what the tool does (one paragraph), install (`pip install -r requirements.txt` and `pip install -r requirements-dev.txt`), config (`copy config.example.json config.json` + the config schema), usage (`python -m tracker serve`, `summary`, `sessions --csv`), how cost is computed (pricing table, free models), the budget model, the design reference (`sketches/004-sentry-incident`), troubleshooting (DB not found, port busy, WAL issues), and the v2 roadmap (message text rendering, TUI).
- Run the full test suite and fix any remaining failures.
- Final smoke test against the real DB: `python -m tracker summary` and `python -m tracker serve` + browser check of the dashboard.

**Acceptance:**
- `pytest` is fully green.
- README instructions work from a clean checkout (deps install, config copy, serve, summary).
- The dashboard renders real data from the user's DB.

**Verify:** `python -m pytest -q; python -m tracker summary`; then start `python -m tracker serve` in a separate terminal and verify the dashboard in a browser (do not chain `serve` in the same command — it blocks).

---

## Execution order and parallel dispatch

- T-001 -> T-002 -> T-003 -> T-004 -> T-005 -> T-006 -> T-007 -> T-008 -> T-009 -> T-010 -> T-010b -> T-011 -> T-012 -> T-015 -> T-016 -> T-017 -> T-018 (revised 2026-08-08: T-013/013b/013c/014 cancelled by user; T-010b added; T-011/T-012 revised to minimalist charts-only dashboard with dark/light themes).
- **Parallel candidates** (no shared files, no ordering dependency):
  - T-002 and T-003 (after T-001).
  - T-005 and T-006 (after T-004 and T-003).
  - T-009 and T-010 both edit `tracker/api.py` — **sequential**, do not parallelize.
  - T-010b edits `tracker/api.py` — sequential after T-010.
  - T-010b (backend) and T-011 (web shell) are independent — may run in parallel.
  - T-012 edits `web/app.js` — sequential after T-011.
- Every task is owned by SWE Pro: dispatch to a fresh subagent, review spec compliance then code quality, run the Verify command before marking done.
