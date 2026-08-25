"""Estimate-vs-actual calibration used for the P90 cost SLO."""

from __future__ import annotations

import math
from typing import Any

from obase.persistence import PgPool


def relative_error(estimated: float, actual: float) -> float:
    """Absolute relative error against actual spend.

    Zero/zero is a perfect estimate.  A zero actual with a non-zero estimate
    is a 100% miss so it still contributes to the tail.
    """

    if actual == 0.0 and estimated == 0.0:
        return 0.0
    if actual == 0.0:
        return 1.0
    return abs(float(estimated) - float(actual)) / abs(float(actual))


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * q) - 1)
    return ordered[min(index, len(ordered) - 1)]


def p90_relative_error(pairs: list[tuple[float, float]]) -> float:
    return percentile([relative_error(estimated, actual) for estimated, actual in pairs], 0.90)


async def load_settled_cost_pairs(pool: PgPool, *, limit: int = 1000) -> list[tuple[float, float]]:
    """Load (estimated, actual) pairs from settled production tasks."""

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                COALESCE((config_json->>'estimated_usd')::float8, 0) AS estimated_usd,
                COALESCE((config_json->>'actual_usd')::float8, 0) AS actual_usd
            FROM video_tasks
            WHERE status = 'completed'
              AND config_json ? 'estimated_usd'
              AND config_json ? 'actual_usd'
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [(float(row["estimated_usd"]), float(row["actual_usd"])) for row in rows]


def summarize_calibration(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    errors = [relative_error(estimated, actual) for estimated, actual in pairs]
    return {
        "samples": len(pairs),
        "p50": percentile(errors, 0.50),
        "p90": percentile(errors, 0.90),
        "max": max(errors) if errors else 0.0,
        "slo": 0.20,
        "passed": percentile(errors, 0.90) < 0.20 if errors else True,
    }


__all__ = [
    "load_settled_cost_pairs",
    "p90_relative_error",
    "percentile",
    "relative_error",
    "summarize_calibration",
]
