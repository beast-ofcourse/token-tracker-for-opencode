# opencode-token-tracker-cli

A local, read-only dashboard and CLI that tracks OpenCode's token usage from OpenCode's own SQLite database. No plugins, no hooks, no cloud.

## What it does

Reads `~/.local/share/opencode/opencode.db` (read-only, WAL-safe) and shows:

- **Web dashboard** (`python -m tracker serve`) â€” minimalist dark/light dashboard with a range selector (Daily / Weekly / Monthly / All time), a stacked input/output token chart, and a per-model usage panel. Auto-refreshes every 30s.
- **CLI** â€” `summary` prints monthly spend/tokens; `sessions --csv` exports sessions.

Cost is computed from a user-maintained pricing table (the DB's `cost` column is 0 for free models). Free models (`*-free`) price at $0 automatically.

## Install

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for tests
```

Python 3.11+.

### npm package

The tool also ships as an npm package (the Python code is bundled inside):

```bash
npm install -g opencode-token-tracker-cli
tracker summary
tracker serve
```

Or without installing:

```bash
npx opencode-token-tracker-cli summary
```

The `serve` command needs the Python web dependencies once:

```bash
pip install -r requirements.txt
```

Set `TRACKER_PYTHON` to use a specific Python interpreter.

## Configure

```bash
copy config.example.json config.json   # Windows
cp config.example.json config.json     # Unix
```

Defaults work out of the box: DB path `~/.local/share/opencode/opencode.db` (override with `OPENCODE_DB` env var), budget $20/month, port 8765. Config schema:

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

Prices are USD per 1M tokens. An explicit entry always wins; a model id ending in `-free` is free when unpriced; unknown models are flagged `unpriced` (DB cost used as fallback when positive).

## Usage

```bash
python -m tracker serve                 # dashboard at http://127.0.0.1:8765
python -m tracker summary               # monthly summary in the terminal
python -m tracker summary --month 2026-07
python -m tracker summary --json
python -m tracker sessions --csv out.csv
python -m tracker serve --port 9000
```

## Budget

Monthly budget with configurable reset day (default 1st). 80% = warning, 100% = exceeded. Month-end projection = `spent / elapsed_days * total_days`.

## Design

Minimalist dashboard, dark + light themes (toggle in the header, persisted), Rubik + JetBrains Mono (vendored woff2, fully offline), hand-rolled SVG charts â€” no chart library, no build step.

## Troubleshooting

- **DB not found** â€” dashboard shows an error banner; set `OPENCODE_DB` or fix `db_path` in `config.json`.
- **Port busy** â€” `Port 8765 is in use - try --port 9000`.
- **WAL read-only failure** â€” the tool falls back to a snapshot copy of the DB + WAL files in a temp dir.
- **Missing dependency** â€” `Missing dependency: fastapi. Run: pip install -r requirements.txt`.

## Tests

```bash
python -m pytest
```

## Roadmap (v2)

- Message text rendering
- TUI dashboard
- Notifications