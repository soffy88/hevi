"""Distributional reinforcement learning loss functions."""

from oskill.distributional_rl.iqn import implicit_quantile_loss
from oskill.distributional_rl.quantile_regression import quantile_regression_loss

__all__ = [
    "quantile_regression_loss",
    "implicit_quantile_loss",
]
