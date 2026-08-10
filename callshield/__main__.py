"""Allow execution as ``python -m callshield``."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":  # pragma: no cover - trivial entry
    raise SystemExit(main())
