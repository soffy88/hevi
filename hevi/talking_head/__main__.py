"""``python -m hevi.talking_head`` entry point (thin wrapper over pipeline.main)."""

from __future__ import annotations

from hevi.talking_head.pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())
