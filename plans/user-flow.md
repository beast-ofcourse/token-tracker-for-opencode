# OpenCode Token Tracker — User Flow

This file describes the app from the user's point of view. A non-technical reader should understand the whole app from this file alone. All times are local. All money is in the configured currency (default USD).

---

## Persona: the solo OpenCode user

The user runs OpenCode in a terminal all day across several projects. They want to know, without effort: how much have I spent this month, where did it go, and am I about to blow my budget?

---

## Journey 1 — First run: install, configure, start the dashboard

**Entry point:** a terminal in the project directory.

1. The user installs dependencies once: `pip install -r requirements.txt` and `pip install -r requirements-dev.txt`.
2. The user copies the example config: `copy config.example.json config.json` (Windows) or `cp config.example.json config.json`. The default config already points at the right DB path and has a $20/month budget, so editing is optional.
3. The user starts the dashboard: `python -m tracker serve`.
4. The terminal prints: `Dashboard running at http://127.0.0.1:8765  (Ctrl+C to stop)`.
5. The user opens that URL in a browser.

**What they see:** the dashboard loads with the Sentry Incident Room look — deep purple-black canvas, uppercase labels, lime accents. Left sidebar with the project rail and budget progress; main column with a stat strip (Tokens, Cost, Sessions, Budget remaining), a token-volume chart, spend-by-model bars, and the **Token events** incident stream ordered by cost.

**Failure paths:**
- **Config missing:** the tool uses built-in defaults and prints a note: `config.json not found — using defaults (budget $20/month, db ~/.local/share/opencode/opencode.db)`.
- **DB not found:** the dashboard shows a friendly error banner: `OpenCode database not found at <path>. Set OPENCODE_DB or edit config.json.` The page still renders; cards show `--`.
- **Port busy:** the tool prints `Port 8765 is in use — try --port 9000` and exits with a non-zero code.
- **Dependencies missing:** `python -m tracker` prints `Missing dependency: fastapi. Run: pip install -r requirements.txt`.

---

## Journey 2 — The monthly overview (the main screen)

**Entry point:** dashboard already open.

1. The user sees the **sidebar**: brand, nav (Monitor, Usage, Events, Budget, Models), the **project rail** (each real project with a colored dot), and a footer with the budget progress bar and `synced 2 min ago`.
2. The **stat strip** shows four cards: `Tokens (month)`, `Cost (month)`, `Sessions`, `Budget remaining` (`$7.66 of $20.00`).
3. The **Budget panel** shows: a progress bar (green < 80%, amber 80–99%, red ≥ 100%), the month name (`August 2026`), and a projection line: `On track: projected $18.50 by month end` or `Over budget: projected $24.10 by month end`.
4. The **Token volume** chart shows per-day bars for the current month — input (purple) vs output (coral).
5. The **Spend by model** panel shows progress bars per model with cost and share.
6. The **Token events** stream lists sessions as incident cards ordered by cost, each with a severity dot (high/med/low), title, model, token count, and cost.
7. The **KPI row** shows: largest single event, events over the high threshold, and average cost per event.

**Failure paths:**
- **Everything is free:** all cost figures show `$0.00` and the budget bar sits at 0%. The dashboard shows a subtle note: `All models free — showing token usage.` Tokens are still fully displayed.
- **No sessions this month:** the charts are empty with a friendly empty state: `No usage yet this month.` The budget panel shows `$0.00 spent`.
- **Budget exceeded:** the budget bar turns red, the card shows `Budget exceeded by $4.10`, and a warning banner appears at the top of the page: `Budget exceeded — consider switching models or pausing.`

---

## Journey 3 — Where did the tokens go? (breakdowns)

**Entry point:** dashboard, breakdown section.

1. The user clicks the **By project** tab. They see a table: project path, sessions, tokens, cost, share of total.
2. They click **By model** — same shape, grouped by `provider/model` (e.g., `opencode/deepseek-v4-flash-free`).
3. They click **By agent** — grouped by agent (`architect`, `swe-pro`, `plan`, ...).
4. They click **By day** — a table of the current budget month with tokens and cost per day.
5. Each breakdown row is clickable and filters the session list below to that value.

**Failure paths:**
- **Unknown model:** rows show `unknown model` and are flagged `unpriced` — cost shows `—` instead of a number, with a tooltip `Add pricing for this model in config.json`.
- **Empty breakdown:** a value with no sessions shows `0` / `$0.00`.

---

## Journey 4 — Browsing and filtering sessions

**Entry point:** dashboard, session list section.

1. The **Token events** list shows sessions as incident cards ordered by cost: severity dot + label, title, model, token count, cost.
2. **Severity chips** (`All / High / Med / Low`) filter by cost — thresholds configurable (default high = $5, med = $1).
3. They type in the **search box** to filter by title text.
4. They pick a **project** (sidebar rail or dropdown), **model**, or **agent** from dropdown filters (populated from the data).
5. They pick a **date range** (from/to).
6. The list updates immediately; the footer shows e.g. `37 sessions · page 1 of 2` (counts drift as OpenCode runs).
7. They click **Export CSV** and the browser downloads `sessions.csv` with the same filtered rows.

**Failure paths:**
- **No matches:** the table shows `No sessions match your filters.` with a `Clear filters` button.
- **Empty session rows:** sessions with 0 tokens and no model (aborted/empty sessions) are hidden by default; a toggle `Show empty sessions` reveals them.

---

## Journey 5 — Session detail

**Entry:** click a session row.

1. The incident expands in place showing: title, project path, model, agent, created/updated times, the session token breakdown (input / output / reasoning / cache read / cache write), and computed cost.
2. Below it, a **per-message breakdown** lists each message: role (USER/MODEL), model, token count, and cost — so an expensive session can be traced to individual messages.
3. The user collapses it by clicking the incident again.

**Failure paths:**
- **Session deleted while viewing:** the panel shows `Session no longer available.` and closes on refresh.

---

## Journey 6 — CLI: quick terminal summary

**Entry point:** any terminal.

```
python -m tracker summary
```

Prints:

```
OpenCode usage — August 2026
  Spend:            $12.34  (budget $20.00, 61.7%)
  Projected:        $18.50 by month end
  Tokens:           6.9M in / 585K out / 14K reasoning / 20M cache read
  Sessions:         37 (2 unpriced)
  Top project:      SWE-pro-Agents  $6.10
  Top model:        opencode/deepseek-v4-flash-free  $0.00 (free)
```

*(Example output — counts drift as OpenCode runs.)*

1. `python -m tracker summary --month 2026-07` shows a past month.
2. `python -m tracker summary --json` prints the same data as JSON (for scripting).
3. `python -m tracker sessions --csv out.csv` writes the session list to a CSV file and prints `Wrote 37 sessions to out.csv`.
4. `python -m tracker serve --port 9000` starts the dashboard on another port.

**Failure paths:**
- **No data:** prints `No sessions found.` and exits 0.
- **Bad month format:** prints `Invalid month '2026-13'. Use YYYY-MM.` and exits 2.
- **Unwritable CSV path:** prints `Cannot write out.csv: <reason>` and exits 1.

---

## Journey 7 — Configuring budget and pricing

**Entry:** edit `config.json` in any editor (budget, pricing, and refresh-interval changes apply on the next poll — no restart needed).

```json
{
  "db_path": "~/.local/share/opencode/opencode.db",
  "budget": { "monthly": 20.0, "currency": "USD", "reset_day": 1 },
  "pricing": {
    "openai/gpt-4o": { "input": 2.50, "output": 10.00, "cache_read": 1.25, "cache_write": 2.50 }
  },
  "server": { "host": "127.0.0.1", "port": 8765 },
  "refresh_seconds": 30
}
```

1. The user raises the budget to `$50` and saves.
2. Within one refresh cycle the dashboard shows the new budget.
3. The user adds a pricing entry for a model they use; sessions of that model now show real cost instead of `unpriced`.

**Failure paths:**
- **Invalid JSON:** the tool prints `config.json is not valid JSON: <error>` and falls back to defaults.
- **Unknown keys:** ignored with a warning printed once at startup.

---

## Journey 9 — Auto-refresh (near real time)

**Entry:** dashboard left open while the user works in OpenCode.

1. Every 30 seconds the dashboard re-polls the API.
2. When a new OpenCode session finishes, the summary cards, charts, and session list update without a page reload.
3. The sidebar footer shows `synced 12:04:31` with a green dot, or `offline · last sync 12:04:31` with a red dot if the server is unreachable.

**Failure paths:**
- **Server stopped:** the dashboard keeps showing the last data, the footer dot turns red, and a banner says `Dashboard server unreachable — retrying…`. It recovers automatically when the server is back.
- **DB locked/unavailable:** the API returns a 503 with a JSON error; the dashboard shows `Database temporarily unavailable` and keeps polling.

---

## Journey 10 — First-run with a fresh OpenCode install

**Entry:** user has never run OpenCode, so `opencode.db` does not exist.

1. The dashboard renders with all cards at `--` / `$0.00`.
2. A banner explains: `No OpenCode data found. Run OpenCode once to create usage data.`
3. Once the user runs OpenCode and a session completes, the next poll populates the dashboard.

---

## ASCII diagram — main journey (monthly overview)

```
open terminal
      |
      v
python -m tracker serve
      |
      v
browser -> http://127.0.0.1:8765
      |
      v
stat strip (tokens / cost / sessions / budget)
      |
      +-- budget panel (bar + projection + alert)
      |
      +-- token volume chart + spend by model
      |
      +-- breakdowns (project / model / agent / day)
      |
      +-- incident stream (severity chips + search + filters)
      |
      +-- expandable incident detail (per-message trace)
      |
      v
auto-refresh every 30s while OpenCode runs
```
