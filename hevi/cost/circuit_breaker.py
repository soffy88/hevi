from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from hevi.core.config import settings
from hevi.cost.estimator import CostEstimate


class CostLimitExceeded(Exception):
    """Raised when cost exceeds configured limits."""


@dataclass
class CostLimit:
    max_per_task_usd: float = settings.cost_limit_per_task_usd
    max_per_task_seconds: float = settings.max_duration_per_task_s


async def check_before_run(estimate: CostEstimate, limit: CostLimit | None = None) -> None:
    """Pre-run check based on estimate."""
    effective_limit = limit or CostLimit()
    if estimate.total_usd > effective_limit.max_per_task_usd:
        raise CostLimitExceeded(
            f"Estimated cost ${estimate.total_usd:.2f} "
            f"exceeds limit ${effective_limit.max_per_task_usd:.2f}"
        )


async def monitor_during_run(current_cost_usd: float, limit: CostLimit | None = None) -> None:
    """Check actual cost during runtime."""
    effective_limit = limit or CostLimit()
    if current_cost_usd > effective_limit.max_per_task_usd:
        raise CostLimitExceeded(
            f"Actual cost ${current_cost_usd:.2f} has "
            f"exceeded limit ${effective_limit.max_per_task_usd:.2f}"
        )


@dataclass
class CostTracker:
    """跨多次调用的累计花费。check_before_run 只查单笔 estimate 够不够格——挡不住
    "很多笔单价很低的调用叠加超支"(例如身份包构建单张云端兜底图 ~$0.01,远低于 $20
    熔断线,但一个角色十几张、三个角色叠起来仍可能失控)。调用方在同一个 run 里复用
    同一个 CostTracker 实例,每笔要花钱的调用前都过一次 check_and_reserve。
    """

    spent_usd: float = 0.0

    async def check_and_reserve(self, amount_usd: float, limit: CostLimit | None = None) -> None:
        """把这笔预计花费计入累计前先检查会不会超线;不超才真正累计。"""
        effective_limit = limit or CostLimit()
        prospective = self.spent_usd + amount_usd
        if prospective > effective_limit.max_per_task_usd:
            raise CostLimitExceeded(
                f"Cumulative cost ${prospective:.2f} (adding ${amount_usd:.2f}) would "
                f"exceed limit ${effective_limit.max_per_task_usd:.2f}"
            )
        self.spent_usd = prospective


async def get_todays_spend_usd(pool: Any) -> float:
    """今日(UTC)已产生的实际花费之和——查 video_tasks.config_json->>'actual_usd'
    (task_service.run_task 完成时写入的真实花费,不是估价)。取不到/非数值的记 0,不报错。
    """
    from obase.persistence import query

    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    rows = await query(
        pool,
        sql=(
            "SELECT COALESCE(SUM((config_json->>'actual_usd')::float8), 0) AS total "
            "FROM video_tasks WHERE created_at >= $1 "
            "AND config_json->>'actual_usd' IS NOT NULL"
        ),
        params=[today_start],
    )
    return float(rows[0]["total"]) if rows else 0.0


async def check_daily_budget(
    pool: Any, *, additional_usd: float = 0.0, daily_budget_usd: float | None = None
) -> None:
    """三层预算熔断第3层(HEVI 路线图 Phase1 #30):全局每日聚合上限,独立于单任务
    CostLimit(第1层)和用户 credit 余额(第2层,BillingService)。

    `daily_budget_usd` 为 None(默认取 settings.daily_budget_usd,同样可以是 None)→
    不做这层检查,直接放行——这条线没有客观默认值,得部署方自己按实际预算配置。
    """
    limit = daily_budget_usd if daily_budget_usd is not None else settings.daily_budget_usd
    if limit is None:
        return
    spent_today = await get_todays_spend_usd(pool)
    prospective = spent_today + additional_usd
    if prospective > limit:
        raise CostLimitExceeded(
            f"全局日预算 ${limit:.2f} 将被突破(今日已花 ${spent_today:.2f}"
            f" + 本次预计 ${additional_usd:.2f})"
        )


async def get_series_spend_usd(pool: Any, *, series_id: str) -> float:
    """某个 Series(季)从第一集到现在的实际花费之和——查该 series_id 下所有
    video_tasks.config_json->>'actual_usd',同 get_todays_spend_usd 的做法。
    """
    from obase.persistence import query

    rows = await query(
        pool,
        sql=(
            "SELECT COALESCE(SUM((config_json->>'actual_usd')::float8), 0) AS total "
            "FROM video_tasks WHERE series_id = $1 "
            "AND config_json->>'actual_usd' IS NOT NULL"
        ),
        params=[series_id],
    )
    return float(rows[0]["total"]) if rows else 0.0


async def check_series_budget(
    pool: Any,
    *,
    series_id: str,
    additional_usd: float = 0.0,
    series_budget_usd: float | None = None,
) -> None:
    """SPEC-001 §6:季级预算熔断,独立于单任务 CostLimit(第1层)/用户 credit(第2层)/
    全局日预算(第3层)——这层按 series_id 聚合"这一季从第一集到现在总共花了多少",
    不是"今天"。短剧/漫剧一季是长任务大预算,防的是"规划了 60 集、跑到第 40 集烧穿"。

    `series_budget_usd` 为 None → 不做这层检查(该季没配预算上限,直接放行)——跟
    `check_daily_budget` 一样,没有客观默认值,得调用方显式配置。
    """
    if series_budget_usd is None:
        return
    spent = await get_series_spend_usd(pool, series_id=series_id)
    prospective = spent + additional_usd
    if prospective > series_budget_usd:
        raise CostLimitExceeded(
            f"季预算 ${series_budget_usd:.2f} 将被突破(该季已花 ${spent:.2f}"
            f" + 本次预计 ${additional_usd:.2f})"
        )
