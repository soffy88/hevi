"""Plot-line forecasting for hevi (story branching before writing).

Clean-room original: generates isolated future branches from the current
story state, compares them side by side, and adopts one into a branch
plan file without touching the canon. Forked staleness is handled via
the story state's hash (see ``hevi.storybranch.core``).
"""

from __future__ import annotations

from hevi.storybranch.core import (
    Branch,
    Forecast,
    StoryState,
    adopt_branch,
    build_comparison,
    compute_story_hash,
    default_generator,
    forecast_branches,
    is_stale,
    load_branch_plan,
    load_forecast,
    placeholder_generator,
    save_branch_plan,
    save_forecast,
    staleness_report,
    validate_branch_payload,
    verify_forecast_file,
)

__all__ = [
    "Branch",
    "Forecast",
    "StoryState",
    "adopt_branch",
    "build_comparison",
    "compute_story_hash",
    "default_generator",
    "forecast_branches",
    "is_stale",
    "load_branch_plan",
    "load_forecast",
    "placeholder_generator",
    "save_branch_plan",
    "save_forecast",
    "staleness_report",
    "validate_branch_payload",
    "verify_forecast_file",
]
