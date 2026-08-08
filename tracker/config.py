"""Configuration loading for the OpenCode Token Tracker.

`load_config` reads a JSON config file (default: `config.json` in the current
directory) into typed dataclasses. A missing file, invalid JSON, or a
non-object root never crashes — it prints a note to stderr and returns
defaults. Unknown keys are ignored with a warning.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Price:
    """Pricing for one model, in USD per 1M tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float


@dataclass
class Budget:
    """Monthly spend budget."""

    monthly: float
    currency: str = "USD"
    reset_day: int = 1


@dataclass
class Severity:
    """Cost thresholds (in currency) that split sessions into high/med/low."""

    high_cost: float = 5.0
    med_cost: float = 1.0


@dataclass
class Config:
    db_path: Path
    budget: Budget
    severity: Severity
    pricing: dict[str, Price]
    server_host: str
    server_port: int
    refresh_seconds: int


# Built-in pricing for common models (USD per 1M tokens). Config-file entries
# override these per model; models whose id ends with `-free` are priced 0.
DEFAULT_PRICING: dict[str, Price] = {
    "openai/gpt-4o": Price(2.50, 10.00, 1.25, 2.50),
    "openai/gpt-4o-mini": Price(0.15, 0.60, 0.075, 0.15),
    "anthropic/claude-sonnet-4": Price(3.00, 15.00, 0.30, 3.00),
    "anthropic/claude-opus-4": Price(15.00, 75.00, 1.50, 15.00),
    "google/gemini-2.5-pro": Price(1.25, 10.00, 0.3125, 1.25),
    "deepseek/deepseek-chat": Price(0.27, 1.10, 0.07, 0.27),
    "opencode/deepseek-v4-flash-free": Price(0.0, 0.0, 0.0, 0.0),
}

_TOP_LEVEL_KEYS = {"db_path", "budget", "severity", "pricing", "server", "refresh_seconds"}
_BUDGET_KEYS = {"monthly", "currency", "reset_day"}
_SEVERITY_KEYS = {"high_cost", "med_cost"}
_SERVER_KEYS = {"host", "port"}
_PRICE_KEYS = {"input", "output", "cache_read", "cache_write"}


def _default_db_path() -> Path:
    """Default DB path, overridable via the OPENCODE_DB environment variable."""
    env = os.environ.get("OPENCODE_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local/share/opencode/opencode.db"


def _default_config() -> Config:
    return Config(
        db_path=_default_db_path(),
        budget=Budget(20.0, "USD", 1),
        severity=Severity(5.0, 1.0),
        pricing=dict(DEFAULT_PRICING),
        server_host="127.0.0.1",
        server_port=8765,
        refresh_seconds=30,
    )


def _warn(path: Path, message: str) -> None:
    print(f"{path}: {message}", file=sys.stderr)


def _warn_unknown(path: Path, data: dict, known: set[str]) -> None:
    for key in data:
        if key not in known:
            _warn(path, f"ignoring unknown key '{key}'")


def _as_float(path: Path, value, default: float, what: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        _warn(path, f"'{what}' is not a number, using {default}")
        return default


def _as_int(path: Path, value, default: int, what: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        _warn(path, f"'{what}' is not an integer, using {default}")
        return default


def load_config(path: Path | None = None) -> Config:
    """Load config from a JSON file, falling back to defaults on any problem.

    The default path is `config.json` in the current directory. A missing
    file, invalid JSON, or a non-object root prints a note to stderr and
    returns defaults. Unknown keys are ignored with a warning. The
    OPENCODE_DB environment variable overrides `db_path` from any source.
    """
    cfg_path = Path(path) if path is not None else Path("config.json")
    cfg = _default_config()

    if not cfg_path.exists():
        print(
            f"{cfg_path} not found - using defaults "
            f"(budget ${cfg.budget.monthly:g}/month, db {cfg.db_path})",
            file=sys.stderr,
        )
        return cfg

    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        print(f"{cfg_path} is not valid JSON: {exc}", file=sys.stderr)
        return cfg

    if not isinstance(raw, dict):
        print(f"{cfg_path} is not valid JSON: expected an object at the top level", file=sys.stderr)
        return cfg

    _warn_unknown(cfg_path, raw, _TOP_LEVEL_KEYS)

    if "db_path" in raw:
        cfg.db_path = Path(str(raw["db_path"])).expanduser()
    env_db = os.environ.get("OPENCODE_DB")
    if env_db:
        cfg.db_path = Path(env_db).expanduser()

    if isinstance(raw.get("budget"), dict):
        budget = raw["budget"]
        _warn_unknown(cfg_path, budget, _BUDGET_KEYS)
        cfg.budget = Budget(
            monthly=_as_float(cfg_path, budget.get("monthly", cfg.budget.monthly), cfg.budget.monthly, "budget.monthly"),
            currency=str(budget.get("currency", cfg.budget.currency)),
            reset_day=_as_int(cfg_path, budget.get("reset_day", cfg.budget.reset_day), cfg.budget.reset_day, "budget.reset_day"),
        )
    elif "budget" in raw:
        _warn(cfg_path, "'budget' must be an object, ignoring")

    if isinstance(raw.get("severity"), dict):
        severity = raw["severity"]
        _warn_unknown(cfg_path, severity, _SEVERITY_KEYS)
        cfg.severity = Severity(
            high_cost=_as_float(cfg_path, severity.get("high_cost", cfg.severity.high_cost), cfg.severity.high_cost, "severity.high_cost"),
            med_cost=_as_float(cfg_path, severity.get("med_cost", cfg.severity.med_cost), cfg.severity.med_cost, "severity.med_cost"),
        )
    elif "severity" in raw:
        _warn(cfg_path, "'severity' must be an object, ignoring")

    if isinstance(raw.get("server"), dict):
        server = raw["server"]
        _warn_unknown(cfg_path, server, _SERVER_KEYS)
        if "host" in server:
            cfg.server_host = str(server["host"])
        if "port" in server:
            cfg.server_port = _as_int(cfg_path, server["port"], cfg.server_port, "server.port")
    elif "server" in raw:
        _warn(cfg_path, "'server' must be an object, ignoring")

    if "refresh_seconds" in raw:
        cfg.refresh_seconds = _as_int(cfg_path, raw["refresh_seconds"], cfg.refresh_seconds, "refresh_seconds")

    if isinstance(raw.get("pricing"), dict):
        for model_key, entry in raw["pricing"].items():
            if not isinstance(entry, dict):
                _warn(cfg_path, f"ignoring pricing entry '{model_key}' (expected an object)")
                continue
            _warn_unknown(cfg_path, entry, _PRICE_KEYS)
            cfg.pricing[str(model_key)] = Price(
                input=_as_float(cfg_path, entry.get("input", 0.0), 0.0, f"pricing.{model_key}.input"),
                output=_as_float(cfg_path, entry.get("output", 0.0), 0.0, f"pricing.{model_key}.output"),
                cache_read=_as_float(cfg_path, entry.get("cache_read", 0.0), 0.0, f"pricing.{model_key}.cache_read"),
                cache_write=_as_float(cfg_path, entry.get("cache_write", 0.0), 0.0, f"pricing.{model_key}.cache_write"),
            )
    elif "pricing" in raw:
        _warn(cfg_path, "'pricing' must be an object, ignoring")

    return cfg