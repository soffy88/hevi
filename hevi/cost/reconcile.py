"""成本治理闭环 —— estimate → reserve → reconcile 三阶段。

对标 OpenMontage 的 CostTracker(estimate → reserve → reconcile + observe/warn/cap 三模式)。
Hevi 已有 hevi/cost/tracker.py(HeviCostTracker,基于 obase.CostTracker)和 circuit_breaker.py
(三层预算熔断),但缺 **reserve + reconcile** 闭环——目前只有 estimate 和 post-hoc check,
没有"预扣 → 实际花多少就记多少 → 差值退回"的精确记账。

本模块补上这一环,与既有 HeviCostTracker 协作(不替换):
  1. estimate_cost() 预估
  2. reserve_budget() 预扣(锁定资金,防超支)
  3. reconcile_cost() 实际结算(多退少补)

用法:
    from hevi.cost.reconcile import CostLedger
    ledger = CostLedger(pool)
    entry_id = await ledger.estimate(task_id, provider="happyhorse", duration_s=10.0)
    await ledger.reserve(entry_id)
    # ... 实际生成 ...
    await ledger.reconcile(entry_id, actual_usd=0.12, actual_duration_s=8.5)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class EntryStatus(StrEnum):
    ESTIMATED = "estimated"
    RESERVED = "reserved"
    RECONCILED = "reconciled"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


class BudgetMode(StrEnum):
    OBSERVE = "observe"     # 只记录,不阻断
    WARN = "warn"           # 超支时 log warning
    CAP = "cap"             # 超支时 raise,阻断执行

    def __str__(self) -> str:
        return self.value


@dataclass
class CostEntry:
    id: str
    task_id: str
    provider: str
    category: str            # "video" / "audio" / "image" / "llm" / "enhancement"
    estimated_usd: float
    reserved_usd: float = 0.0
    actual_usd: float = 0.0
    status: EntryStatus = EntryStatus.ESTIMATED
    duration_s: float = 0.0
    actual_duration_s: float = 0.0
    created_at: datetime | None = None
    reconciled_at: datetime | None = None
    notes: str = ""


class CostLedger:
    """成本账本 —— estimate/reserve/reconcile 三阶段闭环。"""

    def __init__(self, pool: Any, *, budget_usd: float = 10.0, mode: BudgetMode = BudgetMode.WARN):
        self.pool = pool
        self.budget_usd = budget_usd
        self.mode = mode
        self._entries: dict[str, CostEntry] = {}  # 内存缓存,生产用 DB

    async def estimate(
        self,
        task_id: str,
        *,
        provider: str,
        category: str = "video",
        duration_s: float = 0.0,
        price_per_s: float = 0.14,
        notes: str = "",
    ) -> str:
        """预估成本,返回 entry_id。"""
        est = duration_s * price_per_s
        entry = CostEntry(
            id=str(uuid.uuid4()),
            task_id=task_id,
            provider=provider,
            category=category,
            estimated_usd=round(est, 4),
            duration_s=duration_s,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            notes=notes,
        )

        # 预算检查
        total_reserved = sum(e.reserved_usd for e in self._entries.values()
                            if e.status == EntryStatus.RESERVED)
        remaining = self.budget_usd - total_reserved
        if est > remaining:
            if self.mode == BudgetMode.CAP:
                raise BudgetExceededError(
                    f"Estimated ${est:.4f} exceeds remaining budget ${remaining:.4f}"
                )
            if self.mode == BudgetMode.WARN:
                logger.warning("Budget warning: estimated $%.4f, remaining $%.4f", est, remaining)

        self._entries[entry.id] = entry
        return entry.id

    async def reserve(self, entry_id: str) -> None:
        """预扣预算(锁定资金)。"""
        entry = self._entries.get(entry_id)
        if not entry:
            raise ValueError(f"Cost entry {entry_id} not found")
        if entry.status != EntryStatus.ESTIMATED:
            raise ValueError(f"Cannot reserve entry in status {entry.status}")

        entry.reserved_usd = entry.estimated_usd
        entry.status = EntryStatus.RESERVED

    async def reconcile(
        self,
        entry_id: str,
        *,
        actual_usd: float,
        actual_duration_s: float = 0.0,
        notes: str = "",
    ) -> CostEntry:
        """实际结算:多退少补。"""
        entry = self._entries.get(entry_id)
        if not entry:
            raise ValueError(f"Cost entry {entry_id} not found")
        if entry.status not in (EntryStatus.RESERVED, EntryStatus.ESTIMATED):
            raise ValueError(f"Cannot reconcile entry in status {entry.status}")

        entry.actual_usd = round(actual_usd, 4)
        entry.actual_duration_s = actual_duration_s
        entry.status = EntryStatus.RECONCILED
        entry.reconciled_at = datetime.now(UTC).replace(tzinfo=None)
        if notes:
            entry.notes = f"{entry.notes}; {notes}" if entry.notes else notes

        delta = entry.actual_usd - entry.reserved_usd
        if abs(delta) > 0.001:
            logger.info(
                "Cost reconcile %s: reserved=$%.4f actual=$%.4f delta=$%+.4f",
                entry_id, entry.reserved_usd, entry.actual_usd, delta,
            )

        return entry

    async def cancel(self, entry_id: str) -> None:
        """取消预扣(释放预算)。"""
        entry = self._entries.get(entry_id)
        if entry:
            entry.status = EntryStatus.CANCELLED
            entry.reserved_usd = 0.0

    def get_task_spend(self, task_id: str) -> dict[str, float]:
        """获取某任务的累计花费。"""
        entries = [e for e in self._entries.values() if e.task_id == task_id]
        return {
            "estimated": sum(e.estimated_usd for e in entries),
            "reserved": sum(e.reserved_usd for e in entries if e.status == EntryStatus.RESERVED),
            "actual": sum(e.actual_usd for e in entries if e.status == EntryStatus.RECONCILED),
        }

    def get_remaining_budget(self) -> float:
        """获取剩余预算。"""
        total_reserved = sum(
            e.reserved_usd for e in self._entries.values()
            if e.status == EntryStatus.RESERVED
        )
        total_actual = sum(
            e.actual_usd for e in self._entries.values()
            if e.status == EntryStatus.RECONCILED
        )
        return self.budget_usd - max(total_reserved, total_actual)


class BudgetExceededError(Exception):
    """预算超支(CAP 模式下抛出)。"""
