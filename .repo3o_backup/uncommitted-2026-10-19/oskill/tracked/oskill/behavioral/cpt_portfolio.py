"""CPT portfolio optimization using Cumulative Prospect Theory."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from scipy.optimize import differential_evolution, minimize

try:
    from oprim.behavioral.cpt import cpt_value_function
    from oprim.behavioral.weighting import probability_weighting_function
except ImportError:

    def cpt_value_function(  # type: ignore[misc]
        x,
        *,
        reference_point: float = 0.0,
        alpha: float = 0.88,
        beta: float = 0.88,
        loss_aversion: float = 2.25,
    ) -> np.ndarray:
        d = np.asarray(x) - reference_point
        return np.where(d >= 0, np.abs(d) ** alpha, -loss_aversion * np.abs(d) ** beta)

    def probability_weighting_function(  # type: ignore[misc]
        p,
        *,
        form: str = "tk",
        gamma_gain: float = 0.61,
        gamma_loss: float = 0.69,
        delta: float = 1.0,
        side: str = "gain",
    ) -> np.ndarray:
        gamma = gamma_gain if side == "gain" else gamma_loss
        p = np.asarray(p)
        safe_p = np.clip(p, 1e-10, 1 - 1e-10)
        return safe_p**gamma / (safe_p**gamma + (1 - safe_p) ** gamma) ** (1.0 / gamma)


def _compute_empirical_metrics(port_returns: np.ndarray) -> dict[str, float]:
    """Compute Sharpe, max drawdown, VaR 95%."""
    mean_r = np.mean(port_returns)
    std_r = np.std(port_returns, ddof=1)
    sharpe = mean_r / std_r if std_r > 1e-12 else 0.0

    cum = np.cumprod(1 + port_returns)
    rolling_max = np.maximum.accumulate(cum)
    drawdown = (cum - rolling_max) / rolling_max
    max_drawdown = float(np.min(drawdown))

    var_95 = float(np.percentile(port_returns, 5))

    return {"sharpe": float(sharpe), "max_drawdown": max_drawdown, "var_95": var_95}


def _cpt_objective(
    w: np.ndarray,
    returns: np.ndarray,
    *,
    alpha: float,
    beta: float,
    loss_aversion: float,
    gamma_gain: float,
    gamma_loss: float,
    reference_return: float,
) -> float:
    """Compute negative CPT value for minimization."""
    T, _N = returns.shape
    R = returns @ w
    gains_mask = R >= reference_return
    losses_mask = ~gains_mask

    n_gain = int(np.sum(gains_mask))
    n_loss = T - n_gain

    p_gain = n_gain / T
    p_loss = n_loss / T

    cpt_val = 0.0
    if n_gain > 0:
        w_gain = float(
            probability_weighting_function(
                p_gain, side="gain", gamma_gain=gamma_gain, gamma_loss=gamma_loss
            )
        )
        v_gains = cpt_value_function(
            R[gains_mask],
            reference_point=reference_return,
            alpha=alpha,
            beta=beta,
            loss_aversion=loss_aversion,
        )
        cpt_val += w_gain * float(np.mean(v_gains))

    if n_loss > 0:
        w_loss = float(
            probability_weighting_function(
                p_loss, side="loss", gamma_gain=gamma_gain, gamma_loss=gamma_loss
            )
        )
        v_losses = cpt_value_function(
            R[losses_mask],
            reference_point=reference_return,
            alpha=alpha,
            beta=beta,
            loss_aversion=loss_aversion,
        )
        cpt_val += w_loss * float(np.mean(v_losses))

    return -cpt_val  # negate for minimization


def cpt_portfolio_optimize(
    returns: np.ndarray,
    *,
    alpha: float = 0.88,
    beta: float = 0.88,
    loss_aversion: float = 2.25,
    gamma_gain: float = 0.61,
    gamma_loss: float = 0.69,
    reference_return: float = 0.0,
    n_long_short: tuple[int, int] | None = None,
    solver: Literal["scipy_de", "scipy_slsqp"] = "scipy_de",
) -> dict[str, Any]:
    """Optimize portfolio weights under Cumulative Prospect Theory preferences.

    Parameters
    ----------
    returns:
        Array of shape (T, N) with T >= 10, N >= 2.
    alpha:
        Power for gains in CPT value function.
    beta:
        Power for losses in CPT value function.
    loss_aversion:
        Loss aversion coefficient lambda.
    gamma_gain:
        Probability weighting curvature for gains.
    gamma_loss:
        Probability weighting curvature for losses.
    reference_return:
        Reference point for gains/losses.
    n_long_short:
        If provided, (n_long, n_short) — top n_long positive and n_short negative
        allocations after optimization (applied as post-processing).
    solver:
        Optimization backend.

    Returns
    -------
    dict with keys: weights, cpt_value, convergence, empirical_metrics.
    """
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2:
        raise ValueError("returns must be 2-D array of shape (T, N)")
    T, N = returns.shape
    if T < 10:
        raise ValueError(f"Need T >= 10 observations, got {T}")
    if N < 2:
        raise ValueError(f"Need N >= 2 assets, got {N}")

    kwargs = dict(
        alpha=alpha,
        beta=beta,
        loss_aversion=loss_aversion,
        gamma_gain=gamma_gain,
        gamma_loss=gamma_loss,
        reference_return=reference_return,
    )

    obj = lambda w: _cpt_objective(w, returns, **kwargs)  # noqa: E731

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = [(-1.0, 1.0)] * N
    w0 = np.ones(N) / N

    if solver == "scipy_slsqp":
        result = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        w_opt = result.x
        convergence = {
            "success": bool(result.success),
            "message": result.message,
            "nit": int(result.nit),
        }
    else:  # scipy_de

        def penalized_obj(w: np.ndarray) -> float:
            penalty = 1e4 * (np.sum(w) - 1.0) ** 2
            return obj(w) + penalty

        result = differential_evolution(
            penalized_obj, bounds=bounds, seed=42, maxiter=300, tol=1e-6, workers=1
        )
        w_opt = result.x
        # Project to sum=1
        w_opt = w_opt / (np.sum(w_opt) + 1e-12)
        convergence = {
            "success": bool(result.success),
            "message": result.message,
            "nit": int(result.nit),
        }

    # Apply long/short constraint as post-processing
    if n_long_short is not None:
        n_long, n_short = n_long_short
        ranked = np.argsort(w_opt)
        mask = np.zeros(N)
        # Top n_long positive
        mask[ranked[-(n_long):]] = w_opt[ranked[-(n_long):]]
        # Bottom n_short negative
        mask[ranked[:n_short]] = w_opt[ranked[:n_short]]
        w_opt = mask
        s = np.sum(w_opt)
        if abs(s) > 1e-12:
            w_opt = w_opt / s

    # Compute final CPT value
    cpt_val = -_cpt_objective(w_opt, returns, **kwargs)
    port_returns = returns @ w_opt
    empirical_metrics = _compute_empirical_metrics(port_returns)

    # Optional fingerprint
    fingerprint = None
    try:
        from oprim import canonical_json, sha256_hash  # type: ignore[import]

        fingerprint = sha256_hash(canonical_json({"cpt_value": float(cpt_val), "n": N}))
    except Exception:
        pass

    return {
        "weights": w_opt,
        "cpt_value": float(cpt_val),
        "convergence": convergence,
        "empirical_metrics": empirical_metrics,
        "fingerprint": fingerprint,
    }
