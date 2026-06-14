from dataclasses import dataclass

from hevi.core.config import settings
from hevi.cost.estimator import CostEstimate


class CostLimitExceeded(Exception):
    """Raised when cost exceeds configured limits."""

    pass


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
