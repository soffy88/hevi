"""候选股票池 v3 — candidate_pool_builder + 深度过滤 + 百分位排名 (oskill B10)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import oprim
import pandas as pd  # type: ignore[import-untyped]
from oprim.apply_screen_filter import ScreenRule, apply_screen_filter
from pydantic import BaseModel

from oskill._exceptions import OskillError
from oskill.screening import candidate_pool_builder


class CandidateUniverseResult(BaseModel):
    """candidate_universe_builder_v3 结果.

    Attributes:
        candidates:     最终候选列表 (经 veto 过滤 + 重排).
        score_percentiles: 各候选分数百分位.
        dropped_by_veto: 被 veto 淘汰数.
        stats:          来自 candidate_pool_builder 的统计.
    """

    candidates: list[dict[str, Any]]
    score_percentiles: list[float]
    dropped_by_veto: int
    stats: dict[str, Any]


def candidate_universe_builder_v3(
    *,
    universe: list[dict[str, Any]],
    scoring_fn: Callable[[dict[str, Any]], float],
    filter_rules: list[Callable[[dict[str, Any]], bool]] | None = None,
    screen_rules: list[ScreenRule] | None = None,
    top_n: int = 30,
    min_score: float = 0.0,
) -> CandidateUniverseResult:
    """Build an enhanced candidate pool with oprim-level screening and percentile ranking.

    Internal oprim composition:
    - oprim.apply_screen_filter  (applies structured ScreenRule objects post-pool)
    - oprim.percentile_rank      (cross-sectional ranking of final candidate scores)

    Sibling oskill (depth-1):
    - oskill.candidate_pool_builder  (initial pool: scoring, basic filtering, top_n)
      Note: NOT recursive — candidate_pool_builder does not call this oskill.

    Args:
        universe:      Full candidate universe as list of dicts.
        scoring_fn:    Scoring callable (candidate → float).
        filter_rules:  Simple boolean filter functions passed to ``candidate_pool_builder``.
        screen_rules:  :class:`~oprim.apply_screen_filter.ScreenRule` objects for structured veto.
        top_n:         Max candidates from the initial pool.
        min_score:     Minimum score from the initial pool.

    Returns:
        :class:`CandidateUniverseResult`.

    Raises:
        OskillError: If ``universe`` is empty.

    Example:
        >>> u = [{"symbol": f"s{i}", "score": i} for i in range(50)]
        >>> r = candidate_universe_builder_v3(universe=u, scoring_fn=lambda x: x["score"])
        >>> len(r.candidates) <= 30
        True
    """
    if not universe:
        raise OskillError("universe must not be empty")

    pool_result = candidate_pool_builder(
        universe=universe,
        scoring_fn=scoring_fn,
        filter_rules=filter_rules,
        top_n=top_n,
        min_score=min_score,
    )
    pool_candidates = pool_result.get("candidates", [])

    if screen_rules and pool_candidates:
        screen_df = pd.DataFrame(pool_candidates)
        screen_result = apply_screen_filter(candidates=screen_df, rules=screen_rules)
        passed_set = set(screen_result.passed)
        dropped = len(pool_candidates) - len(screen_result.passed)
        final_candidates = [c for c in pool_candidates if c.get("symbol") in passed_set]
    else:
        dropped = 0
        final_candidates = pool_candidates

    if len(final_candidates) >= 2:
        scores = [scoring_fn(c) for c in final_candidates]
        pct_vals = oprim.percentile_rank(pd.DataFrame({"v": scores}), method="cross_sectional")[
            "v"
        ].tolist()
        score_percentiles = [round(float(p), 4) for p in pct_vals]
    else:
        score_percentiles = [50.0] * len(final_candidates)

    return CandidateUniverseResult(
        candidates=final_candidates,
        score_percentiles=score_percentiles,
        dropped_by_veto=dropped,
        stats=pool_result.get("stats", {}),
    )
