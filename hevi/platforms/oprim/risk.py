"""oprim:风险识别原子。不得 import oskill / omodul。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from hevi.platforms.schemas import RiskCategory, RiskLevel

# ─── 风控冷却阶梯 ───


_COOLDOWNS: dict[RiskCategory, int] = {
    RiskCategory.RISK: 30,      # 30 分钟
    RiskCategory.AUTH: 120,     # 2 小时
    RiskCategory.NETWORK: 360,  # 6 小时
    RiskCategory.UNKNOWN: 60,   # 1 小时
}


def cooldown_for_error(risk_category: str, duration_minutes: int | None = None) -> dict[str, Any]:
    """根据错误类型计算风控冷却时间。

    对应 CreatorHub 风控系统的冷却阶梯规则：
    - RISK(403/429/461/471): 30分钟冷却
    - AUTH: 2小时冷却
    - NETWORK: 6小时冷却
    """
    now = datetime.now()
    if risk_category == "risk":
        minutes = duration_minutes or 30
    elif risk_category == "auth":
        minutes = duration_minutes or 120
    elif risk_category == "network":
        minutes = duration_minutes or 360
    else:
        minutes = 60  # 默认1小时

    return {
        "level": "cool",
        "expires_at": now + timedelta(minutes=minutes),
        "category": risk_category,
        "minutes": minutes,
    }


def cooldown_minutes_for(category: RiskCategory) -> int:
    """返回某风险类别的冷却分钟数。"""
    return _COOLDOWNS.get(category, 60)


def is_risk_status(status: str) -> bool:
    """判断账号状态是否处于风控。"""
    return status in ("cool", "warn", "blocked")


def next_risk_check_time(category: RiskCategory, now: datetime | None = None) -> datetime:
    """计算下一次风控探测时间。

    轻读取间隔 ≥60s，冷却结束后主动验证。
    """
    now = now or datetime.now()
    minutes = cooldown_minutes_for(category)
    return now + timedelta(minutes=minutes)


def progressive_recovery_steps(current_level: str) -> list[str]:
    """返回渐进恢复阶梯。

    normal -> cool -> warn -> blocked 依次降级，
    恢复时 block->warn->normal 逐步解除。
    """
    order = [RiskLevel.NORMAL.value, RiskLevel.COOL.value,
             RiskLevel.WARN.value, RiskLevel.BLOCKED.value]
    try:
        idx = order.index(current_level)
    except ValueError:
        return order
    # 恢复方向：从当前往 normal 走，每步降一级
    return order[: idx + 1][::-1]


def classify_auth_failure(status_code: int) -> RiskCategory:
    """根据 HTTP 状态码分类风控类型。"""
    if status_code in (403, 429, 461, 471):
        return RiskCategory.RISK
    if status_code in (401, 402, 405):
        return RiskCategory.AUTH
    if status_code >= 500 or status_code == 0:
        return RiskCategory.NETWORK
    return RiskCategory.UNKNOWN