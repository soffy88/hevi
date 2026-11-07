"""Bayesian Vector Autoregression (BVAR) with Minnesota and Normal-Wishart priors."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _ar1_residual_variance(series: np.ndarray) -> float:
    """Fit AR(1) and return residual variance for Minnesota prior scaling."""
    T = len(series)
    if T < 3:
        return float(np.var(series, ddof=1)) + 1e-8
    y = series[1:]
    x = series[:-1]
    beta = np.dot(x, y) / (np.dot(x, x) + 1e-10)
    resid = y - beta * x
    return float(np.var(resid, ddof=1)) + 1e-8


def _build_lag_matrix(data: np.ndarray, p: int) -> tuple[np.ndarray, np.ndarray]:
    """Build lagged design matrix Z and effective Y for a VAR(p) model."""
    T, K = data.shape
    T_eff = T - p
    # Each row: [1, y_{t-1}.T, ..., y_{t-p}.T]
    Z = np.ones((T_eff, K * p + 1))
    for lag in range(1, p + 1):
        start = (lag - 1) * K + 1
        end = lag * K + 1
        Z[:, start:end] = data[p - lag : T - lag]
    Y_eff = data[p:, :]
    return Z, Y_eff


def _impulse_responses(
    A_mean: np.ndarray, Sigma: np.ndarray, K: int, p: int, horizon: int = 10
) -> np.ndarray:
    """Compute structural impulse responses via Cholesky decomposition of Sigma."""
    try:
        P = np.linalg.cholesky(Sigma)
    except np.linalg.LinAlgError:
        P = np.diag(np.sqrt(np.abs(np.diag(Sigma))) + 1e-8)

    # A_mean shape (K, K*p+1): strip constant, get companion
    A_coef = A_mean[:, 1:].reshape(K, p, K)  # (K, p, K)

    # IR[h] indexed as [shock_var, response_var] after h steps
    IR = np.zeros((K, K, horizon))
    Phi = [np.zeros((K, K)) for _ in range(horizon + p)]
    Phi[0] = np.eye(K)

    for h in range(1, horizon + p):
        for lag in range(1, p + 1):
            if h - lag >= 0:
                Phi[h] = Phi[h] + A_coef[:, lag - 1, :].T @ Phi[h - lag]

    for h in range(horizon):
        IR[:, :, h] = (Phi[h] @ P).T  # IR[shock, response, h]

    return IR


def _fevd(IR: np.ndarray, K: int, horizon: int) -> np.ndarray:
    """Forecast Error Variance Decomposition from impulse responses."""
    FEVD = np.zeros((K, K, horizon))
    for h in range(1, horizon + 1):
        mse = np.zeros((K, K))  # mse[response, shock] accumulated
        for s in range(h):
            for shock in range(K):
                for resp in range(K):
                    mse[resp, shock] += IR[shock, resp, s] ** 2
        total = mse.sum(axis=1, keepdims=True)
        total = np.where(total < 1e-14, 1.0, total)
        FEVD[:, :, h - 1] = mse / total
    return FEVD


def bayesian_var(
    data: np.ndarray | pd.DataFrame,
    *,
    p_lag: int = 1,
    prior: str = "minnesota",
    minnesota_lambda: float = 0.1,
    minnesota_decay: float = 1.0,
    n_mcmc_samples: int = 1000,
    seed: int | None = None,
) -> dict[str, Any]:
    """Bayesian Vector Autoregression (BVAR).

    Model: Y_t = c + A_1*Y_{t-1} + ... + A_p*Y_{t-p} + eps_t, eps_t ~ N(0, Sigma)

    Args:
        data: (T, K) time series matrix.
        p_lag: Number of lags.
        prior: "minnesota", "normal_wishart", or "uninformative".
        minnesota_lambda: Overall tightness for Minnesota prior.
        minnesota_decay: Lag-decay exponent for Minnesota prior.
        n_mcmc_samples: Number of MCMC draws (currently unused; uses closed-form).
        seed: Random seed.

    Returns:
        Dict with posterior_coefficients_mean, posterior_coefficients_samples,
        posterior_sigma_mean, posterior_sigma_samples, impulse_responses,
        forecast_error_variance_decomp, log_marginal_likelihood.

    Reference:
        Karlsson (2013); Doan, Litterman, Sims (1984).
    """

    if isinstance(data, pd.DataFrame):
        data_arr = data.values.astype(np.float64)
    else:
        data_arr = np.asarray(data, dtype=np.float64)
    if data_arr.ndim == 1:
        data_arr = data_arr.reshape(-1, 1)

    T, K = data_arr.shape
    p = p_lag
    Z, Y_eff = _build_lag_matrix(data_arr, p)
    T_eff = Y_eff.shape[0]
    n_coef = K * p + 1  # number of regressors per equation

    # OLS estimates
    ZTZ = Z.T @ Z
    ZTY = Z.T @ Y_eff
    try:
        A_ols = np.linalg.solve(ZTZ + 1e-10 * np.eye(n_coef), ZTY).T  # (K, n_coef)
    except np.linalg.LinAlgError:
        A_ols = np.zeros((K, n_coef))

    resid_ols = Y_eff - Z @ A_ols.T
    Sigma_ols = (resid_ols.T @ resid_ols) / max(T_eff - n_coef, 1)

    if prior == "uninformative":
        A_post = A_ols
        Sigma_post = Sigma_ols
        log_ml = _log_ml_ols(Y_eff, Z, A_ols, Sigma_ols, T_eff, K, n_coef)
    else:
        # Build Minnesota prior precision (diagonal, equation-by-equation)
        sigma_i = np.array([_ar1_residual_variance(data_arr[:, i]) for i in range(K)])

        # Prior mean A0: own-lag-1 = 1, everything else = 0
        A0 = np.zeros((K, n_coef))
        for i in range(K):
            own_lag1_idx = 1 + i  # column index in Z for variable i, lag 1
            A0[i, own_lag1_idx] = 1.0

        # Prior precision (diagonal) for each element of vec(A)
        V0_diag = np.zeros(n_coef)
        V0_diag[0] = 1e6  # constant: diffuse

        for lag in range(1, p + 1):
            for j in range(K):
                col_idx = 1 + (lag - 1) * K + j
                for i in range(K):
                    # We'll store per-equation later; for simplicity use mean
                    pass

        # Build per-equation prior precision matrices
        V0_list = []
        for i in range(K):
            v_diag = np.zeros(n_coef)
            v_diag[0] = 1.0 / 1e6  # diffuse constant
            for lag in range(1, p + 1):
                for j in range(K):
                    col_idx = 1 + (lag - 1) * K + j
                    scale = (minnesota_lambda / (lag**minnesota_decay)) ** 2
                    if i == j:
                        var_ij = scale / sigma_i[i]
                    else:
                        var_ij = scale * sigma_i[j] / sigma_i[i]
                    v_diag[col_idx] = var_ij
            V0_list.append(np.diag(v_diag))

        # Posterior for each equation independently (equation-by-equation OLS with prior)
        A_post = np.zeros((K, n_coef))
        Sigma_post_diag = np.zeros(K)
        log_ml = 0.0

        for i in range(K):
            yi = Y_eff[:, i]
            m0_i = A0[i]
            V0_i = V0_list[i]
            S0_i = np.diag(1.0 / (np.diag(V0_i) + 1e-14))  # precision

            SN_i = S0_i + Z.T @ Z
            mN_i = np.linalg.solve(SN_i, S0_i @ m0_i + Z.T @ yi)
            A_post[i] = mN_i

            # Noise posterior
            aN_i = 1.0 + T_eff / 2.0
            bN_i = (
                1.0
                + 0.5 * (yi - Z @ mN_i) @ (yi - Z @ mN_i)
                + 0.5 * (mN_i - m0_i) @ S0_i @ (mN_i - m0_i)
            )
            Sigma_post_diag[i] = bN_i / (aN_i - 1.0)

            from scipy.special import gammaln

            _, logdet0 = np.linalg.slogdet(S0_i)
            _, logdetN = np.linalg.slogdet(SN_i)
            log_ml += (
                gammaln(aN_i)
                - gammaln(1.0)
                + 1.0 * np.log(1.0)
                - aN_i * np.log(bN_i)
                + 0.5 * logdet0
                - 0.5 * logdetN
                - T_eff / 2.0 * np.log(2.0 * np.pi)
            )

        # Reconstruct Sigma_post as diagonal (approximation; full NW would use Wishart)
        Sigma_post = np.diag(Sigma_post_diag) + np.diag(np.diag(Sigma_ols)) * 0.0
        # Use OLS cross-terms for off-diagonal structure
        Sigma_post = Sigma_ols.copy()
        np.fill_diagonal(Sigma_post, Sigma_post_diag)

        if prior == "normal_wishart":
            # For Normal-Wishart, use full joint conjugate posterior
            nu0 = K + 2
            S0_nw = np.eye(K)
            nu_post = nu0 + T_eff
            S_post_nw = S0_nw + resid_ols.T @ resid_ols
            Sigma_post = S_post_nw / (nu_post + K + 1)
            # Keep A_post from Minnesota/equation-by-equation above
            log_ml = _log_ml_ols(Y_eff, Z, A_post, Sigma_post, T_eff, K, n_coef)

    IR = _impulse_responses(A_post, Sigma_post, K, p, horizon=10)
    FEVD = _fevd(IR, K, 10)

    return {
        "posterior_coefficients_mean": A_post,
        "posterior_coefficients_samples": None,
        "posterior_sigma_mean": Sigma_post,
        "posterior_sigma_samples": None,
        "impulse_responses": IR,
        "forecast_error_variance_decomp": FEVD,
        "log_marginal_likelihood": float(log_ml),
    }


def _log_ml_ols(
    Y_eff: np.ndarray,
    Z: np.ndarray,
    A: np.ndarray,
    Sigma: np.ndarray,
    T_eff: int,
    K: int,
    n_coef: int,
) -> float:
    """Gaussian log-likelihood as proxy for log marginal likelihood under flat prior."""
    resid = Y_eff - Z @ A.T
    try:
        sign, logdet = np.linalg.slogdet(Sigma + 1e-10 * np.eye(K))
        if sign <= 0:
            logdet = 0.0
    except Exception:
        logdet = 0.0
    ll = -0.5 * T_eff * (K * np.log(2.0 * np.pi) + logdet)
    Sigma_inv = np.linalg.inv(Sigma + 1e-10 * np.eye(K))
    ll -= 0.5 * np.einsum("ti,ij,tj->", resid, Sigma_inv, resid)
    return float(ll)
