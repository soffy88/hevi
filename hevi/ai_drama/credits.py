"""Credit ledger and per-episode budget guard.

Every paid generation appends one line to ``credit_ledger.jsonl`` before the
request and one settlement line after it.  The episode cap is configurable
(``AI_DRAMA_BUDGET_CNY``, default 30).  A request that would cross the cap is
refused before any network call; OfflineProvider is always free.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_BUDGET_CNY = 30.0

# Prices are per output second.  They are ESTIMATES for planning only, not
# vendor quotes: the vendor price pages change and RunningHub prices depend on
# the workflow/machine.  Replace with measured values before paying.
PRICE_TABLE_CNY = {
    "offline": 0.0,
    "offline_kenburns": 0.0,
    "runninghub_h3": 0.30,
    "minimax_h3_api": 0.60,
    "wan": 0.0,
}

PRICE_STATUS = {
    "offline": "free",
    "offline_kenburns": "free",
    "runninghub_h3": "estimate",
    "minimax_h3_api": "estimate",
    "wan": "unpriced",
}


class BudgetExceeded(RuntimeError):
    pass


def budget_cap() -> float:
    try:
        return max(0.0, float(os.environ.get("AI_DRAMA_BUDGET_CNY", DEFAULT_BUDGET_CNY)))
    except ValueError:
        return DEFAULT_BUDGET_CNY


def price_for(provider: str, seconds: float) -> dict[str, Any]:
    raw = os.environ.get("AI_DRAMA_PRICES", "")
    table = dict(PRICE_TABLE_CNY)
    if raw.strip():
        with contextlib.suppress(Exception):
            table.update({str(k): float(v) for k, v in json.loads(raw).items()})
    per_second = float(table.get(provider, 0.0))
    return {
        "provider": provider,
        "per_second_cny": per_second,
        "estimated_cny": round(per_second * max(0.0, seconds), 4),
        "price_status": "configured" if raw.strip() else PRICE_STATUS.get(provider, "unpriced"),
    }


class CreditLedger:
    def __init__(self, path: str | Path, *, episode_id: str = "", cap_cny: float | None = None) -> None:
        self.path = Path(path)
        self.episode_id = episode_id
        self.cap = budget_cap() if cap_cny is None else max(0.0, cap_cny)
        self._lock = threading.Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def spent(self) -> float:
        total = 0.0
        for row in self._read():
            if row.get("episode_id") not in (None, "", self.episode_id):
                continue
            if row.get("kind") == "settle":
                total += float(row.get("charged_cny") or 0.0)
        return round(total, 4)

    def remaining(self) -> float:
        return round(max(0.0, self.cap - self.spent()), 4)

    def _append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row.setdefault("episode_id", self.episode_id)
        row.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def reserve(self, provider: str, seconds: float, *, ref: str = "") -> dict[str, Any]:
        price = price_for(provider, seconds)
        with self._lock:
            remaining = self.remaining()
            if price["estimated_cny"] > remaining + 1e-9:
                self._append({
                    "kind": "refused",
                    "provider": provider,
                    "seconds": seconds,
                    "estimated_cny": price["estimated_cny"],
                    "remaining_cny": remaining,
                    "ref": ref,
                    "reason": "episode budget cap",
                })
                raise BudgetExceeded(
                    f"预算不足：本集剩余 {remaining:.2f} 元，本次预计 {price['estimated_cny']:.2f} 元"
                )
            self._append({
                "kind": "reserve",
                "provider": provider,
                "seconds": seconds,
                "estimated_cny": price["estimated_cny"],
                "remaining_cny": remaining,
                "price_status": price["price_status"],
                "ref": ref,
            })
            return price

    def settle(self, provider: str, seconds: float, *, actual_cny: float | None = None, ref: str = "",
               success: bool = True, note: str = "") -> dict[str, Any]:
        price = price_for(provider, seconds)
        charged = price["estimated_cny"] if actual_cny is None else max(0.0, float(actual_cny))
        if not success:
            charged = 0.0
        with self._lock:
            self._append({
                "kind": "settle",
                "provider": provider,
                "seconds": seconds,
                "charged_cny": round(charged, 4),
                "price_status": price["price_status"],
                "success": success,
                "ref": ref,
                "note": note,
            })
        return {"charged_cny": round(charged, 4), "remaining_cny": self.remaining()}

    def report(self) -> dict[str, Any]:
        return {
            "ledger": str(self.path),
            "episode_id": self.episode_id,
            "cap_cny": self.cap,
            "spent_cny": self.spent(),
            "remaining_cny": self.remaining(),
            "rows": len(self._read()),
        }
