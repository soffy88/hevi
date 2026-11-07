"""Calibration against known sample pairs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.judge.pairwise import run_pairwise


def calibrate(backend, pairs, *, work_dir=None) -> dict[str, Any]:
    results = []
    wins = 0
    total = 0
    for old, new in pairs:
        total += 1
        cmp = run_pairwise(backend, old, new, work_dir=work_dir)
        ok = cmp.winner == "B" and cmp.consistent
        if ok:
            wins += 1
        results.append({"old": str(old), "new": str(new), "winner": cmp.winner,
                        "consistent": cmp.consistent, "expected_win": ok})
    rate = (wins / total) if total else 0.0
    return {"total": total, "wins": wins, "consistency_rate": rate, "results": results}
