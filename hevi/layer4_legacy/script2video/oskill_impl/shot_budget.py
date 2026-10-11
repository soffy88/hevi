"""Shot budgeting oskill: target duration to shot count allocation.

3O Pillar: oskill.shot_budget
"""

from __future__ import annotations


def shot_budget_for_duration(
    target_duration_s: float,
    *,
    min_shot_s: float = 3.0,
    max_shot_s: float = 5.0,
) -> int:
    """Calculate target / maximum shot count given desired total duration.

    By default, each shot spans 3 to 5 seconds (average 4.0 seconds).
    E.g.:
      - 30s target -> ~7-8 shots
      - 60s target -> ~15 shots
      - 90s target -> ~22 shots

    Args:
        target_duration_s: Desired total video length in seconds.
        min_shot_s: Minimum duration per shot (default 3.0).
        max_shot_s: Maximum duration per shot (default 5.0).

    Returns:
        int: Maximum/recommended shot budget.
    """
    if target_duration_s <= 0:
        return 1
    avg_shot_s = max(1.0, (min_shot_s + max_shot_s) / 2.0)
    count = int(round(target_duration_s / avg_shot_s))
    return max(1, count)
