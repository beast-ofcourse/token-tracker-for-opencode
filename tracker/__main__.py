"""Entry point for `python -m tracker` — delegates to the CLI (T-015)."""

from __future__ import annotations

from tracker.cli import main

if __name__ == "__main__":
    main()
