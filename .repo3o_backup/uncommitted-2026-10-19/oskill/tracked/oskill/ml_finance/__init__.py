"""oskill.ml_finance — Financial ML workflows (López de Prado 2018)."""

from oskill.ml_finance.bet_sizing import bet_sizing
from oskill.ml_finance.cusum_filter import cusum_filter
from oskill.ml_finance.fractional_diff import fractional_differentiation
from oskill.ml_finance.meta_labeling import meta_labeling
from oskill.ml_finance.sample_weights import return_attribution_weights, sample_uniqueness_weights
from oskill.ml_finance.triple_barrier import triple_barrier_label

__all__ = [
    "triple_barrier_label",
    "meta_labeling",
    "sample_uniqueness_weights",
    "return_attribution_weights",
    "fractional_differentiation",
    "cusum_filter",
    "bet_sizing",
]
