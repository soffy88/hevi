"""CPT portfolio analytical solution (Bernard-Ghossoub 2010)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import scipy.optimize

try:
    from oprim.behavioral.cpt import cpt_value_function
    from oprim.behavioral.llad import large_loss_aversion_degree
    from oprim.behavioral.weighting import probability_weighting_function
except ImportError:
    large_loss_aversion_degree = None  # type: ignore[assignment]
    cpt_value_function = None  # type: ignore[assignment]
    probability_weighting_function = None  # type: ignore[assignment]


def _fallback_cpt_value(
    x: np.ndarray,
    *,
    reference_point: float = 0.0,
    alpha: float = 0.88,
    beta: float = 0.88,
    loss_aversion: float = 2.25,
) -> np.ndarray:
    d = np.asarray(x, dtype=float) - reference_point
    return np.where(d >= 0, np.abs(d) ** alpha, -loss_aversion * np.abs(d) ** beta)


def _fallback_pwf(p: np.ndarray, *, gamma: float = 0.61) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-10, 1 - 1e-10)
    return p**gamma / (p**gamma + (1 - p) ** gamma) ** (1.0 / gamma)


def _cpt_portfolio_value(
    w: float,
    returns: np.ndarray,
    reference_return: float,
    risk_free_rate: float,
    alpha: float,
    beta: float,
    loss_aversion: float,
    gamma_gain: float,
    gamma_loss: float,
) -> float:
    """Compute the CPT value of a portfolio with weight w in risky asset."""
    port_r = (1.0 - w) * risk_free_rate + w * returns  # shape (T,)
    T = len(port_r)

    # Sort for rank-dependent weighting
    sorted_idx = np.argsort(port_r)
    sorted_r = port_r[sorted_idx]

    # Uniform empirical probabilities
    probs = np.full(T, 1.0 / T)

    # Cumulative decumulative probs for CPT weighting
    cum_probs = np.cumsum(probs)
    decum_probs = 1.0 - np.concatenate([[0.0], cum_probs[:-1]])

    # Gain / loss split relative to reference
    values = _fallback_cpt_value(
        sorted_r,
        reference_point=reference_return,
        alpha=alpha,
        beta=beta,
        loss_aversion=loss_aversion,
    )

    # Approximate CPT value using mean weighted utility (simplified)
    gain_mask = sorted_r >= reference_return
    loss_mask = ~gain_mask

    cpt_val = 0.0
    if np.any(gain_mask):
        # Probability weighting for gains (decumulative)
        w_gain = _fallback_pwf(decum_probs[gain_mask], gamma=gamma_gain)
        w_gain_next = _fallback_pwf(decum_probs[gain_mask] - probs[gain_mask], gamma=gamma_gain)
        w_gain_next = np.clip(w_gain_next, 0.0, None)
        pi_gain = w_gain - w_gain_next
        cpt_val += float(np.sum(pi_gain * values[gain_mask]))

    if np.any(loss_mask):
        # Probability weighting for losses (cumulative)
        w_loss = _fallback_pwf(cum_probs[loss_mask], gamma=gamma_loss)
        w_loss_prev = _fallback_pwf(cum_probs[loss_mask] - probs[loss_mask], gamma=gamma_loss)
        w_loss_prev = np.clip(w_loss_prev, 0.0, None)
        pi_loss = w_loss - w_loss_prev
        cpt_val += float(np.sum(pi_loss * values[loss_mask]))

    return cpt_val


def cpt_portfolio_analytical(
    returns: np.ndarray,
    reference_return: float,
    *,
    alpha: float = 0.88,
    beta: float = 0.88,
    loss_aversion: float = 2.25,
    gamma_gain: float = 0.61,
    gamma_loss: float = 0.69,
    risk_free_rate: float = 0.0,
    case: Literal["piecewise_linear", "auto"] = "auto",
) -> dict[str, Any]:
    """CPT portfolio analytical solution (Bernard-Ghossoub 2010).

    Parameters
    ----------
    returns : np.ndarray
        Asset returns, shape (T,) or (T, 1). Minimum 30 samples.
    reference_return : float
        Reference return (aspiration level) for CPT evaluation.
    alpha : float
        Gain curvature of the CPT value function. Must be in (0, 1].
    beta : float
        Loss curvature of the CPT value function. Must be in (0, 1].
    loss_aversion : float
        Loss aversion coefficient lambda. Must be >= 1.
    gamma_gain : float
        Probability weighting curvature for gains.
    gamma_loss : float
        Probability weighting curvature for losses.
    risk_free_rate : float
        Risk-free rate used in portfolio construction.
    case : {"piecewise_linear", "auto"}
        "piecewise_linear" forces the closed-form solution (valid when alpha=beta=1).
        "auto" selects based on parameters.

    Returns
    -------
    dict with keys:
        - ``weight_optimal``: float, optimal portfolio weight in risky asset.
        - ``cpt_value``: float, CPT value at optimal weight.
        - ``llad``: float, Large Loss Aversion Degree.
        - ``well_posed``: bool or None, whether the CPT problem is well-posed.
        - ``comparative_statics``: dict of sensitivity analysis.
        - ``closed_form_used``: bool, whether a closed-form solution was used.
    """
    returns = np.asarray(returns, dtype=float).ravel()
    T = len(returns)
    if T < 30:
        raise ValueError(f"returns must have at least 30 samples, got {T}")

    # --- LLAD diagnostic ---
    if large_loss_aversion_degree is not None:
        llad_result = large_loss_aversion_degree(
            alpha=alpha, beta=beta, loss_aversion=loss_aversion
        )
        llad_val = llad_result["llad"]
        well_posed = llad_result["well_posed"]
    else:
        llad_val = (beta / alpha) * loss_aversion ** (1.0 / beta)
        well_posed = None

    # --- Determine solution method ---
    use_closed_form = (case == "piecewise_linear") or (
        case == "auto" and abs(alpha - 1.0) < 1e-8 and abs(beta - 1.0) < 1e-8
    )

    if use_closed_form:
        # Piecewise linear (alpha=beta=1): simple closed-form weight
        w_star = float(
            np.clip(
                (reference_return - risk_free_rate) / (np.std(returns) + 1e-8),
                -3.0,
                3.0,
            )
        )
    else:
        # Numerical optimization via scipy
        def objective(w: float) -> float:
            return -_cpt_portfolio_value(
                w,
                returns,
                reference_return,
                risk_free_rate,
                alpha,
                beta,
                loss_aversion,
                gamma_gain,
                gamma_loss,
            )

        result = scipy.optimize.minimize_scalar(objective, bounds=(-3.0, 3.0), method="bounded")
        w_star = float(result.x)

    # --- CPT value at optimal weight ---
    cpt_val = _cpt_portfolio_value(
        w_star,
        returns,
        reference_return,
        risk_free_rate,
        alpha,
        beta,
        loss_aversion,
        gamma_gain,
        gamma_loss,
    )

    # --- Comparative statics: vary key params by ±10% ---
    statics: dict[str, dict[str, float]] = {}
    for param_name, base_val in [
        ("alpha", alpha),
        ("beta", beta),
        ("loss_aversion", loss_aversion),
    ]:
        statics[param_name] = {}
        for direction, scale in [("plus_10pct", 1.1), ("minus_10pct", 0.9)]:
            new_val = base_val * scale
            # Clamp to valid ranges
            if param_name in ("alpha", "beta"):
                new_val = float(np.clip(new_val, 1e-4, 1.0))
            else:
                new_val = max(1.0, new_val)

            kwargs: dict[str, float] = {
                "alpha": alpha,
                "beta": beta,
                "loss_aversion": loss_aversion,
            }
            kwargs[param_name] = new_val

            def _obj_cs(w: float, kw: dict[str, float] = kwargs) -> float:
                return -_cpt_portfolio_value(
                    w,
                    returns,
                    reference_return,
                    risk_free_rate,
                    kw["alpha"],
                    kw["beta"],
                    kw["loss_aversion"],
                    gamma_gain,
                    gamma_loss,
                )

            res_cs = scipy.optimize.minimize_scalar(_obj_cs, bounds=(-3.0, 3.0), method="bounded")
            statics[param_name][direction] = float(res_cs.x)

    return {
        "weight_optimal": w_star,
        "cpt_value": cpt_val,
        "llad": llad_val,
        "well_posed": well_posed,
        "comparative_statics": statics,
        "closed_form_used": use_closed_form,
    }
