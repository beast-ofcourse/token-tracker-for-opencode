"""Unit tests for tracker.config."""

import json
from pathlib import Path

from tracker.config import Budget, Price, Severity, load_config


def _missing_config(tmp_path) -> Path:
    return tmp_path / "no-such-config.json"


def test_defaults_when_file_missing(tmp_path, capsys):
    cfg = load_config(_missing_config(tmp_path))
    err = capsys.readouterr().err
    assert "not found" in err
    assert "using defaults" in err
    assert cfg.db_path == Path.home() / ".local/share/opencode/opencode.db"
    assert cfg.budget == Budget(20.0, "USD", 1)
    assert cfg.severity == Severity(5.0, 1.0)
    assert cfg.server_host == "127.0.0.1"
    assert cfg.server_port == 8765
    assert cfg.refresh_seconds == 30


def test_env_override_of_db_path(tmp_path, monkeypatch):
    env_db = tmp_path / "env.db"
    monkeypatch.setenv("OPENCODE_DB", str(env_db))
    cfg = load_config(_missing_config(tmp_path))
    assert cfg.db_path == env_db


def test_env_override_beats_config_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"db_path": str(tmp_path / "from-file.db")}), encoding="utf-8")
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "from-env.db"))
    cfg = load_config(cfg_file)
    assert cfg.db_path == tmp_path / "from-env.db"


def test_invalid_json_prints_note_and_returns_defaults(tmp_path, capsys):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{ this is not json", encoding="utf-8")
    cfg = load_config(cfg_file)
    err = capsys.readouterr().err
    assert "is not valid JSON" in err
    assert cfg.db_path == Path.home() / ".local/share/opencode/opencode.db"
    assert cfg.budget == Budget(20.0, "USD", 1)
    assert cfg.server_port == 8765


def test_unknown_keys_ignored_with_warning(tmp_path, capsys):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "bogus_top": 1,
                "budget": {"monthly": 50.0, "nonsense": True},
                "server": {"host": "0.0.0.0", "port": 9000, "extra": 1},
                "pricing": {
                    "openai/gpt-4o": {
                        "input": 1.0,
                        "output": 2.0,
                        "cache_read": 0.5,
                        "cache_write": 1.0,
                        "weird": 3,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    err = capsys.readouterr().err
    for key in ("bogus_top", "nonsense", "extra", "weird"):
        assert f"ignoring unknown key '{key}'" in err
    assert cfg.budget.monthly == 50.0
    assert cfg.server_host == "0.0.0.0"
    assert cfg.server_port == 9000
    assert cfg.pricing["openai/gpt-4o"] == Price(1.0, 2.0, 0.5, 1.0)


def test_free_model_pricing_is_zero(tmp_path):
    cfg = load_config(_missing_config(tmp_path))
    assert cfg.pricing["opencode/deepseek-v4-flash-free"] == Price(0.0, 0.0, 0.0, 0.0)


def test_severity_defaults(tmp_path):
    cfg = load_config(_missing_config(tmp_path))
    assert cfg.severity == Severity(5.0, 1.0)


def test_json_to_dataclass_mapping(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "db_path": "~/custom/opencode.db",
                "budget": {"monthly": 50.0, "currency": "EUR", "reset_day": 3},
                "severity": {"high_cost": 10.0, "med_cost": 2.0},
                "pricing": {
                    "openai/gpt-4o": {"input": 2.5, "output": 10.0, "cache_read": 1.25, "cache_write": 2.5}
                },
                "server": {"host": "0.0.0.0", "port": 9000},
                "refresh_seconds": 60,
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.db_path == Path.home() / "custom/opencode.db"
    assert cfg.budget == Budget(50.0, "EUR", 3)
    assert cfg.severity == Severity(10.0, 2.0)
    assert cfg.pricing["openai/gpt-4o"] == Price(2.5, 10.0, 1.25, 2.5)
    assert cfg.server_host == "0.0.0.0"
    assert cfg.server_port == 9000
    assert cfg.refresh_seconds == 60


def test_pricing_overrides_defaults(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "pricing": {
                    "openai/gpt-4o": {"input": 9.0, "output": 9.0, "cache_read": 9.0, "cache_write": 9.0}
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.pricing["openai/gpt-4o"] == Price(9.0, 9.0, 9.0, 9.0)
    # Models not mentioned in the file keep their built-in prices.
    assert cfg.pricing["deepseek/deepseek-chat"].input == 0.27


def test_partial_pricing_entry_defaults_missing_to_zero(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"pricing": {"custom/model": {"input": 1.0}}}), encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.pricing["custom/model"] == Price(1.0, 0.0, 0.0, 0.0)