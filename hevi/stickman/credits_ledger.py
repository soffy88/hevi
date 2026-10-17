"""stickman.credits_ledger —— Flow 积分台账。

规格：
- 月度总配额：1000 积分
- 每日配额：50 积分
- 每条 Flow 生成耗费预估：15 积分 / 条
- 余额估算、消耗流水与告警提示（月度剩余 < 100 或 每日剩余 < 15 时报警）。
- 安全契约：Hevi 服务器纯本地离线台账，绝不自动登录 Google 账号或调用 Flow/Gemini API。
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MONTHLY_QUOTA = 1000
DAILY_QUOTA = 50
CREDITS_PER_CLIP = 15
MONTHLY_WARN_THRESHOLD = 100
DAILY_WARN_THRESHOLD = 15


class InsufficientCreditsError(RuntimeError):
    """积分不足异常。"""


@dataclass
class TransactionRecord:
    timestamp: str
    proposal_id: str
    clip_count: int
    credits_spent: int
    monthly_remaining: int
    daily_remaining: int
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "proposal_id": self.proposal_id,
            "clip_count": self.clip_count,
            "credits_spent": self.credits_spent,
            "monthly_remaining": self.monthly_remaining,
            "daily_remaining": self.daily_remaining,
            "note": self.note,
        }


class CreditsLedger:
    def __init__(
        self,
        ledger_file: str | Path | None = None,
        *,
        monthly_quota: int = MONTHLY_QUOTA,
        daily_quota: int = DAILY_QUOTA,
    ):
        self.ledger_file = Path(ledger_file) if ledger_file else None
        self.monthly_quota = monthly_quota
        self.daily_quota = daily_quota
        self.monthly_spent = 0
        self.daily_spent = 0
        self.current_date = datetime.date.today().isoformat()
        self.transactions: list[TransactionRecord] = []

        if self.ledger_file and self.ledger_file.exists():
            self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.ledger_file.read_text(encoding="utf-8"))
            self.monthly_quota = data.get("monthly_quota", MONTHLY_QUOTA)
            self.daily_quota = data.get("daily_quota", DAILY_QUOTA)
            self.monthly_spent = data.get("monthly_spent", 0)
            self.daily_spent = data.get("daily_spent", 0)
            self.current_date = data.get("current_date", datetime.date.today().isoformat())
            # 跨天重置当日配额
            today = datetime.date.today().isoformat()
            if self.current_date != today:
                self.daily_spent = 0
                self.current_date = today

            self.transactions = [
                TransactionRecord(**tx) for tx in data.get("transactions", [])
            ]
        except Exception:
            pass

    def save(self) -> None:
        if not self.ledger_file:
            return
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "monthly_quota": self.monthly_quota,
            "daily_quota": self.daily_quota,
            "monthly_spent": self.monthly_spent,
            "daily_spent": self.daily_spent,
            "current_date": self.current_date,
            "monthly_remaining": self.monthly_remaining,
            "daily_remaining": self.daily_remaining,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "server_policy": "NO_GOOGLE_AUTO_LOGIN_NO_REMOTE_FLOW_API",
        }
        self.ledger_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def monthly_remaining(self) -> int:
        return max(0, self.monthly_quota - self.monthly_spent)

    @property
    def daily_remaining(self) -> int:
        today = datetime.date.today().isoformat()
        if self.current_date != today:
            return self.daily_quota
        return max(0, self.daily_quota - self.daily_spent)

    def check_warnings(self) -> list[str]:
        warnings = []
        if self.monthly_remaining < MONTHLY_WARN_THRESHOLD:
            warnings.append(
                f"【积分预警】月度积分余额不足 100 点（当前剩余: {self.monthly_remaining} 点）！"
            )
        if self.daily_remaining < DAILY_WARN_THRESHOLD:
            warnings.append(
                f"【积分预警】今日积分余额不足 15 点（当前剩余: {self.daily_remaining} 点），不够生成 1 条新分镜！"
            )
        return warnings

    def record_consumption(
        self,
        proposal_id: str,
        clip_count: int,
        *,
        cost_per_clip: int = CREDITS_PER_CLIP,
        note: str = "",
        enforce_quota: bool = False,
    ) -> dict[str, Any]:
        """记录任务包导出消耗。"""
        today = datetime.date.today().isoformat()
        if self.current_date != today:
            self.daily_spent = 0
            self.current_date = today

        total_cost = clip_count * cost_per_clip

        if enforce_quota:
            if total_cost > self.daily_remaining:
                raise InsufficientCreditsError(
                    f"今日积分不足：需要 {total_cost} 点，今日剩余 {self.daily_remaining} 点"
                )
            if total_cost > self.monthly_remaining:
                raise InsufficientCreditsError(
                    f"月度积分不足：需要 {total_cost} 点，月度剩余 {self.monthly_remaining} 点"
                )

        self.monthly_spent += total_cost
        self.daily_spent += total_cost

        tx = TransactionRecord(
            timestamp=datetime.datetime.now().isoformat(),
            proposal_id=proposal_id,
            clip_count=clip_count,
            credits_spent=total_cost,
            monthly_remaining=self.monthly_remaining,
            daily_remaining=self.daily_remaining,
            note=note,
        )
        self.transactions.append(tx)
        self.save()

        warnings = self.check_warnings()

        return {
            "proposal_id": proposal_id,
            "clip_count": clip_count,
            "cost_per_clip": cost_per_clip,
            "total_cost": total_cost,
            "monthly_remaining": self.monthly_remaining,
            "daily_remaining": self.daily_remaining,
            "warnings": warnings,
            "policy": "Hevi 服务器绝不自动登录谷歌或调用 Flow/Gemini API",
        }

    def get_summary(self) -> dict[str, Any]:
        return {
            "monthly_quota": self.monthly_quota,
            "monthly_spent": self.monthly_spent,
            "monthly_remaining": self.monthly_remaining,
            "daily_quota": self.daily_quota,
            "daily_spent": self.daily_spent,
            "daily_remaining": self.daily_remaining,
            "warnings": self.check_warnings(),
            "transaction_count": len(self.transactions),
            "policy": "Hevi 服务器绝不自动登录谷歌或调用 Flow/Gemini API",
        }
