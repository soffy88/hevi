"""Validation submodule.

Phase 1 functions (re-exported from legacy module):
    cpcv_pipeline, walk_forward_optimization, regime_aware_rolling

Phase 2 additions:
    probability_of_backtest_overfitting, deflated_sharpe_ratio
"""

# Re-export oprim at package level for backward compatibility with mock patches
# (tests mock oskill.validation.oprim.*)
import oprim  # noqa: F401

# Phase 1 legacy imports (preserve backward compatibility)
from oskill.validation._legacy import (
    cpcv_pipeline,
    regime_aware_rolling,
    walk_forward_optimization,
)

# Phase 6C additions
from oskill.validation.csv import combinatorially_symmetric_cv
from oskill.validation.deflated_sharpe import deflated_sharpe_ratio
from oskill.validation.full_cpcv import full_combinatorial_purged_cv
from oskill.validation.haircut import haircut_sharpe

# Phase 2 additions
from oskill.validation.pbo import probability_of_backtest_overfitting
from oskill.validation.trial_correction import bonferroni_holm_correction

__all__ = [
    # Phase 1
    "walk_forward_optimization",
    "cpcv_pipeline",
    "regime_aware_rolling",
    # Phase 2
    "probability_of_backtest_overfitting",
    "deflated_sharpe_ratio",
    # Phase 6C
    "combinatorially_symmetric_cv",
    "haircut_sharpe",
    "full_combinatorial_purged_cv",
    "bonferroni_holm_correction",
]
