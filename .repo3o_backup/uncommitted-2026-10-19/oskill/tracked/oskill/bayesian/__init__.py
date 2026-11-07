"""Bayesian inference submodule."""

from oskill.bayesian.gp_regression import gaussian_process_regression
from oskill.bayesian.hierarchical import hierarchical_bayes_normal
from oskill.bayesian.linear_regression import bayesian_linear_regression
from oskill.bayesian.posterior_diagnostics import posterior_diagnostics
from oskill.bayesian.var import bayesian_var

__all__ = [
    "bayesian_linear_regression",
    "bayesian_var",
    "gaussian_process_regression",
    "hierarchical_bayes_normal",
    "posterior_diagnostics",
]
