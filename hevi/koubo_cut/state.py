"""Ledger helpers for koubo_cut."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def new_ledger(*, seed: int = 42, out_dir: Path) -> dict[str, Any]:
    return {"line": "koubo_cut", "seed": seed, "out_dir": str(out_dir), "status": "running"}


def finalize_status(ledger: dict[str, Any], status: str) -> None:
    ledger["status"] = status
    ledger["finalized"] = True
