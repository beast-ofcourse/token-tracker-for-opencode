# Token Tracker for OpenCode

[![Version](https://img.shields.io/npm/v/opencode-token-tracker-cli)](https://www.npmjs.com/package/opencode-token-tracker-cli)
[![Downloads](https://img.shields.io/npm/dm/opencode-token-tracker-cli)](https://www.npmjs.com/package/opencode-token-tracker-cli)
[![CI](https://img.shields.io/github/actions/workflow/status/beast-ofcourse/token-tracker-for-opencode/ci.yml)](https://github.com/beast-ofcourse/token-tracker-for-opencode/actions)

A local, read-only dashboard and CLI that tracks OpenCode's token usage, cost, and budget — directly from OpenCode's own SQLite database. No plugins, no hooks, no cloud.

![Dashboard dark theme](dashboard-dark-check.png)

## Why this exists

OpenCode stores detailed session data in a local SQLite database, but there's no built-in way to see how much you're spending across sessions, models, and projects. Token Tracker reads that database and turns it into a clean dashboard with cost tracking, budget alerts, and per-model breakdowns.

## Features

- **Web dashboard** — dark/light theme, auto-refreshes every 30s, responsive on mobile
- **Stacked token charts** — input, output, reasoning, cache read/write over time
- **Cost tracking** — per-model and per-project cost breakdowns with configurable pricing
- **Budget alerts** — monthly budget with 80% warning and 100% exceeded thresholds
- **Cache efficiency metrics** — hit rate, output ratio, reasoning overhead
- **Session activity** — recent sessions with model, agent, token counts, and cost
- **CLI summary** — monthly spend and token totals in the terminal
- **CSV export** — session data exportable for spreadsheet analysis
- **Dual install** — pip (Python) or npm (bundled Python wrapper)

## Quick start

### Python (recommended)

```bash
pip install -r requirements.txt
python -m tracker serve
```

Dashboard opens at `http://127.0.0.1:8765`.

### npm

```bash
npm install -g opencode-token-tracker-cli
tracker serve
```

Or without installing:

```bash
npx opencode-token-tracker-cli serve
```

> The `serve` command needs Python web dependencies. Install once with `pip install -r requirements.txt`.

## CLI usage

```bash
python -m tracker summary                    # current month summary
python -m tracker summary --month 2026-07    # specific month
python -m tracker summary --json             # JSON output
python -m tracker sessions --csv out.csv     # export sessions to CSV
python -m tracker serve --port 9000          # custom port
```

With npm:

```bash
tracker summary
tracker sessions --csv sessions.csv
tracker serve --port 9000
```

## Configuration

Copy the example config and edit as needed:

```bash
cp config.example.json config.json     # Unix/Mac
copy config.example.json config.json   # Windows
```

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

**Pricing** is USD per 1M tokens. Models ending in `-free` price at $0 automatically. Unknown models use the DB's cost column as fallback.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `OPENCODE_DB` | Override database path | `~/.local/share/opencode/opencode.db` |
| `TRACKER_PYTHON` | Python interpreter for npm wrapper | system Python |

## How it works

1. Reads `~/.local/share/opencode/opencode.db` in **read-only** mode (WAL-safe)
2. If WAL access fails, falls back to a snapshot copy in a temp directory
3. Computes costs from your pricing table (DB cost column is 0 for free models)
4. Serves a static dashboard via FastAPI + Uvicorn
5. Dashboard polls the API every 30s for live updates

## Dashboard sections

| Section | Description |
|---|---|
| **Stat cards** | Total tokens, total cost, sessions, budget progress |
| **Token usage over time** | Stacked bar chart (input/output/reasoning/cache) |
| **Cost over time** | Line chart of cost trends (hidden when all free) |
| **Token composition** | Doughnut chart of token type breakdown |
| **Cache efficiency** | Hit rate, output ratio, reasoning overhead, cache write |
| **Cost / tokens by model** | Horizontal bar charts |
| **Usage by project / agent** | Horizontal bar charts |
| **Session activity** | Bar chart of session counts over time |
| **Model / Project / Agent breakdown** | Detailed tables with percentages |
| **Recent sessions** | Last 20 sessions with model, agent, tokens, cost |

## Budget tracking

Monthly budget with configurable reset day (default: 1st of month).

- **< 80%** — green (on track)
- **80–100%** — amber warning
- **> 100%** — red exceeded

Month-end projection: `spent / elapsed_days × total_days`.

## Troubleshooting

| Issue | Fix |
|---|---|
| DB not found | Set `OPENCODE_DB` or fix `db_path` in `config.json` |
| Port busy | Try `--port 9000` |
| WAL read-only failure | Tool auto-falls back to snapshot copy in temp dir |
| Missing dependency | Run `pip install -r requirements.txt` |

## Development

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m tracker serve          # start dev server
python -m pytest                 # run tests
```

## Project structure

```text
tracker/          Python package (CLI, API, DB, pricing, aggregation, dashboard)
bin/tracker.js    npm wrapper entry point
config.example.json
```

## Requirements

- Python 3.11+
- OpenCode installed (provides the SQLite database)

## License

MIT
