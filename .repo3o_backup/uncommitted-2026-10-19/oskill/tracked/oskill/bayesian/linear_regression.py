"""Bayesian linear regression with conjugate (Normal-Inverse-Gamma) and MCMC (Gibbs) methods."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import invgamma


def _autocorr(x: np.ndarray, max_lag: int) -> np.ndarray:
    """Compute autocorrelation for lags 1..max_lag."""
    n = len(x)
    x_centered = x - x.mean()
    var = np.var(x_centered)
    if var < 1e-14:
        return np.zeros(max_lag)
    acf = np.correlate(x_centered, x_centered, mode="full")
    acf = acf[n - 1 :] / (var * n)
    return acf[1 : max_lag + 1]


def _effective_sample_size(samples: np.ndarray) -> float:
    """Estimate ESS from a 1-D chain via truncated autocorrelation sum."""
    n = len(samples)
    max_lag = min(n // 4, 100)
    rho = _autocorr(samples, max_lag)
    # Truncate at first non-positive autocorrelation
    cumsum = 0.0
    for r in rho:
        if r <= 0:
            break
        cumsum += r
    return float(n / (1.0 + 2.0 * cumsum))


def bayesian_linear_regression(
    X: np.ndarray | pd.DataFrame,
    y: np.ndarray | pd.Series,
    *,
    prior_mean: np.ndarray | None = None,
    prior_precision: np.ndarray | None = None,
    noise_prior_alpha: float = 1.0,
    noise_prior_beta: float = 1.0,
    method: str = "conjugate",
    n_mcmc_samples: int = 1000,
    seed: int | None = None,
) -> dict[str, Any]:
    """Bayesian linear regression with Normal-Inverse-Gamma conjugate prior.

    Supports closed-form conjugate inference and Gibbs MCMC sampling.

    Args:
        X: Design matrix (n, p). Intercept column prepended automatically if missing.
        y: Target vector (n,).
        prior_mean: Prior mean for coefficients, shape (p,). Defaults to zeros.
        prior_precision: Prior precision matrix (p, p). Defaults to 0.01 * I.
        noise_prior_alpha: Shape parameter for InvGamma noise prior.
        noise_prior_beta: Scale parameter for InvGamma noise prior.
        method: "conjugate" or "mcmc".
        n_mcmc_samples: Number of posterior samples (MCMC only).
        seed: Random seed.

    Returns:
        Dict with posterior_mean, posterior_covariance, posterior_samples,
        noise_variance_mean, noise_variance_samples, credible_intervals,
        effective_sample_size, log_marginal_likelihood.

    Reference:
        Bishop (2006), "Pattern Recognition and Machine Learning", Ch.3.
    """
    rng = np.random.default_rng(seed)

    if isinstance(X, pd.DataFrame):
        X_arr = X.values.astype(np.float64)
    else:
        X_arr = np.asarray(X, dtype=np.float64)
    if X_arr.ndim == 1:
        X_arr = X_arr.reshape(-1, 1)

    if isinstance(y, pd.Series):
        y_arr = y.values.astype(np.float64)
    else:
        y_arr = np.asarray(y, dtype=np.float64).ravel()

    n = len(y_arr)

    # Prepend intercept if the first column is not all-ones
    if not np.allclose(X_arr[:, 0], 1.0):
        X_arr = np.column_stack([np.ones(n), X_arr])

    p = X_arr.shape[1]

    # Defaults for priors
    m0 = np.zeros(p) if prior_mean is None else np.asarray(prior_mean, dtype=np.float64)
    S0 = (
        0.01 * np.eye(p)
        if prior_precision is None
        else np.asarray(prior_precision, dtype=np.float64)
    )

    # Posterior precision and mean (conjugate update ignoring sigma — see Bishop 3.50–3.54)
    SN = S0 + X_arr.T @ X_arr
    mN = np.linalg.solve(SN, S0 @ m0 + X_arr.T @ y_arr)
    posterior_cov = np.linalg.inv(SN)

    # Noise posterior parameters
    aN = noise_prior_alpha + n / 2.0
    bN = (
        noise_prior_beta
        + 0.5 * (y_arr - X_arr @ mN) @ (y_arr - X_arr @ mN)
        + 0.5 * (mN - m0) @ S0 @ (mN - m0)
    )

    noise_var_mean = bN / (aN - 1.0) if aN > 1.0 else bN / aN

    # Log marginal likelihood (Bishop 3.86 approximation; exact for known sigma)
    # Full Normal-Inverse-Gamma marginal:
    # log p(y) = log Z(S0,m0,a0,b0) - log Z(SN,mN,aN,bN) - n/2 * log(2*pi)
    # where log Z = a*log(b) + log Gamma(a) - 0.5*log|S| - a*log(b)
    # Combined into:
    sign0, logdet0 = np.linalg.slogdet(S0)
    signN, logdetN = np.linalg.slogdet(SN)
    from scipy.special import gammaln

    log_ml = (
        gammaln(aN)
        - gammaln(noise_prior_alpha)
        + noise_prior_alpha * np.log(noise_prior_beta)
        - aN * np.log(bN)
        + 0.5 * logdet0
        - 0.5 * logdetN
        - n / 2.0 * np.log(2.0 * np.pi)
    )

    # 95% credible intervals
    ci_lower = mN - 1.96 * np.sqrt(np.diag(posterior_cov))
    ci_upper = mN + 1.96 * np.sqrt(np.diag(posterior_cov))

    posterior_samples = None
    noise_var_samples = None
    ess = float(n_mcmc_samples)

    if method == "mcmc":
        n_warmup = 500
        total = n_mcmc_samples + n_warmup

        beta_chain = np.zeros((total, p))
        sigma2_chain = np.zeros(total)

        # Initialise
        beta_cur = mN.copy()
        sigma2_cur = float(noise_var_mean)

        SN_inv = posterior_cov  # precomputed

        for i in range(total):
            # Sample beta | sigma^2 ~ N(mN, sigma^2 * SN^{-1})
            L = np.linalg.cholesky(sigma2_cur * SN_inv)
            beta_cur = mN + L @ rng.standard_normal(p)

            # Sample sigma^2 | beta ~ InvGamma(aN, bN_cur)
            resid = y_arr - X_arr @ beta_cur
            bN_cur = (
                noise_prior_beta
                + 0.5 * resid @ resid
                + 0.5 * (beta_cur - m0) @ S0 @ (beta_cur - m0)
            )
            sigma2_cur = invgamma.rvs(aN, scale=bN_cur, random_state=rng.integers(0, 2**31))

            beta_chain[i] = beta_cur
            sigma2_chain[i] = sigma2_cur

        posterior_samples = beta_chain[n_warmup:]
        noise_var_samples = sigma2_chain[n_warmup:]

        # Update posterior estimates from MCMC
        mN = posterior_samples.mean(axis=0)
        posterior_cov = np.cov(posterior_samples.T)
        noise_var_mean = float(noise_var_samples.mean())

        ci_lower = np.percentile(posterior_samples, 2.5, axis=0)
        ci_upper = np.percentile(posterior_samples, 97.5, axis=0)

        # ESS from first parameter chain
        ess = _effective_sample_size(posterior_samples[:, 0])

    return {
        "posterior_mean": mN,
        "posterior_covariance": posterior_cov,
        "posterior_samples": posterior_samples,
        "noise_variance_mean": float(noise_var_mean),
        "noise_variance_samples": noise_var_samples,
        "credible_intervals": {"95%": {"lower": ci_lower, "upper": ci_upper}},
        "effective_sample_size": ess,
        "log_marginal_likelihood": float(log_ml),
    }
