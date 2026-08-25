"""oskill:风控技能。组合 oprim.risk + oprim.extract + oprim.login。

对应 CreatorHub 的 app/risk.py + app/risk_admin.py 逻辑。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.platforms.oprim.risk import (
    classify_auth_failure,
    cooldown_for_error,
    progressive_recovery_steps,
)
from hevi.platforms.schemas import AccountProfile, classify_platform_error

logger = logging.getLogger(__name__)


# ─── 风控控制器 ───


class RiskController:
    """账号风控管理器。

    对应 CreatorHub 的风控中心：账号冷却、恢复调度、出口熔断。
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.risk_log_dir = self.base_dir / "risk"
        self.risk_log_dir.mkdir(parents=True, exist_ok=True)

    def check_account_risk(self, account: AccountProfile) -> dict[str, Any]:
        """检查账号风控状态。

        返回: {"ok": bool, "level": str, "expires_at": datetime | None, "reason": str}
        """
        if not account.is_available():
            return {
                "ok": False,
                "level": "blocked",
                "expires_at": None,
                "reason": f"账号状态: {account.status}",
            }

        if account.risk_level in ("cool", "warn"):
            if account.risk_until and datetime.now() < account.risk_until:
                return {
                    "ok": False,
                    "level": account.risk_level,
                    "expires_at": account.risk_until,
                    "reason": account.risk_reason,
                }
            # 冷却已过期，尝试恢复
            return {
                "ok": True,
                "level": "normal",
                "expires_at": None,
                "reason": "冷却已过期",
            }

        return {"ok": True, "level": "normal", "expires_at": None, "reason": ""}

    def apply_cooldown(self, account: AccountProfile, error: Exception | str) -> AccountProfile:
        """根据错误应用冷却。"""
        category, signal = classify_auth_failure(getattr(error, "status_code", 0))
        if isinstance(error, str):
            category, signal = classify_auth_failure(0)  # 根据错误文本判断
            category, _ = classify_platform_error(error)

        category_name = category.value if hasattr(category, "value") else str(category)
        cooldown = cooldown_for_error(category_name)
        account.risk_level = cooldown["level"]
        account.risk_until = cooldown["expires_at"]
        account.risk_reason = signal
        account.last_check_at = datetime.now()
        return account

    def schedule_recovery(self, account: AccountProfile) -> list[str]:
        """安排恢复探测步骤。"""
        return progressive_recovery_steps(account.risk_level)


def check_account_risk(account: AccountProfile) -> dict[str, Any]:
    """检查账号风控状态（独立函数）。"""
    controller = RiskController(Path("data"))
    return controller.check_account_risk(account)


def apply_cooldown(account: AccountProfile, error: Exception | str) -> AccountProfile:
    """应用冷却（独立函数）。"""
    controller = RiskController(Path("data"))
    return controller.apply_cooldown(account, error)


def schedule_recovery(account: AccountProfile) -> list[str]:
    """安排恢复（独立函数）。"""
    controller = RiskController(Path("data"))
    return controller.schedule_recovery(account)
