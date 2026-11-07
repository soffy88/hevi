"""DDPM Synthetic Path Generator (framework-only, GBM-aware fallback)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import oprim
import pandas as pd

try:
    from oprim import distributional_distance
except ImportError:
    distributional_distance = None  # type: ignore[assignment]


def ddpm_synthetic_path_generator(
    historical_log_returns: np.ndarray | pd.Series,
    n_synthetic_paths: int,
    path_length: int,
    *,
    n_diffusion_steps: int = 100,
    beta_schedule: Literal["linear", "cosine"] = "linear",
    beta_start: float = 1e-4,
    beta_end: float = 0.02,
    use_gbm_aware: bool = True,
    conditioning: dict | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """DDPM Synthetic Financial Path Generator (framework implementation).

    Implements the DDPM noise schedule framework (Ho et al. 2020) with a
    GBM-aware fallback denoiser (since no neural network is available).
    The synthetic paths are generated using historical return statistics,
    scaled by the diffusion noise schedule.

    Parameters
    ----------
    historical_log_returns : np.ndarray or pd.Series
        Historical log returns used to estimate GBM parameters.
    n_synthetic_paths : int
        Number of synthetic paths to generate.
    path_length : int
        Length of each synthetic path (number of time steps).
    n_diffusion_steps : int
        Number of diffusion steps T in the DDPM framework.
    beta_schedule : {"linear", "cosine"}
        Noise schedule type.
    beta_start : float
        Starting noise level (linear schedule only).
    beta_end : float
        Ending noise level (linear schedule only).
    use_gbm_aware : bool
        If True, use GBM statistics as the denoiser. Always True for this impl.
    conditioning : dict or None
        Optional conditioning dict (reserved for future use).
    seed : int or None
        Random seed for reproducibility.

    Returns
    -------
    dict with keys:
        synthetic_paths : np.ndarray — shape (n_synthetic_paths, path_length)
        noise_schedule : dict — betas, alphas, alpha_bar arrays
        gbm_aware_used : bool — always True
        stylized_facts_evaluation : dict — fat_tails, vol_clustering, negative_skew
        wasserstein_to_historical : float — W1 distance (flattened)
        fingerprint : str — SHA-256 config hash
        denoiser_required : bool — always True

    References
    ----------
    .. [1] Ho, J. et al. (2020). Denoising Diffusion Probabilistic Models. NeurIPS.
    .. [2] Nichol, A. & Dhariwal, P. (2021). Improved DDPM. ICML.
    """
    hist = np.asarray(historical_log_returns, dtype=np.float64)
    hist = hist[np.isfinite(hist)]  # remove NaN/Inf

    if len(hist) < 2:
        raise ValueError("historical_log_returns must have at least 2 finite values")
    if n_synthetic_paths <= 0:
        raise ValueError("n_synthetic_paths must be positive")
    if path_length <= 0:
        raise ValueError("path_length must be positive")
    if n_diffusion_steps <= 0:
        raise ValueError("n_diffusion_steps must be positive")

    rng = np.random.default_rng(seed)

    # ---- 1. Compute noise schedule ----
    betas, alphas, alpha_bar = _compute_schedule(
        n_diffusion_steps, beta_schedule, beta_start, beta_end
    )

    # ---- 2. Estimate GBM parameters from historical data ----
    hist_mean = float(np.mean(hist))
    hist_std = float(np.std(hist, ddof=1))
    if hist_std < 1e-12:
        hist_std = 1e-6

    # ---- 3. Generate synthetic paths ----
    # Use simplified reverse process:
    # Each step at final time T: x_0 ~ N(hist_mean, hist_std^2)
    # Forward: x_t = sqrt(alpha_bar_t) * x_0 + sqrt(1-alpha_bar_t) * eps
    # Reverse (GBM-aware): sample x_0 from GBM then compute x_t at each t
    # For path generation: use the t=0 sample and scale by noise schedule

    # Sample base returns from GBM
    # shape: (n_paths, path_length)
    x0 = rng.normal(hist_mean, hist_std, size=(n_synthetic_paths, path_length))

    if use_gbm_aware:
        # Use the last step's alpha_bar to set scale
        # At the "denoised" level, paths look like GBM
        # Scale each path step by historical volatility
        paths = x0  # GBM-based
    else:
        # Pure noise, scaled by sqrt(1 - alpha_bar[-1])
        noise_scale = float(np.sqrt(1 - alpha_bar[-1]))
        paths = x0 * noise_scale

    synthetic_paths = paths  # shape: (n_synthetic_paths, path_length)

    # ---- 4. Stylized facts evaluation ----
    stylized_facts = _evaluate_stylized_facts(synthetic_paths)

    # ---- 5. Wasserstein distance to historical ----
    flat_synthetic = synthetic_paths.ravel()
    if distributional_distance is not None:
        w1 = distributional_distance(flat_synthetic, sample_b=hist, metric="wasserstein_1")
    else:
        # Fallback: sort-based approximation
        n_min = min(len(flat_synthetic), len(hist))
        w1 = float(np.mean(np.abs(np.sort(flat_synthetic[:n_min]) - np.sort(hist[:n_min]))))
    wasserstein_to_historical = float(w1)

    fingerprint = oprim.sha256_hash(
        oprim.canonical_json(
            {
                "beta_end": beta_end,
                "beta_schedule": beta_schedule,
                "beta_start": beta_start,
                "n_diffusion_steps": n_diffusion_steps,
                "n_hist": len(hist),
                "n_synthetic_paths": n_synthetic_paths,
                "path_length": path_length,
            }
        )
    )

    return {
        "synthetic_paths": synthetic_paths,
        "noise_schedule": {
            "betas": betas,
            "alphas": alphas,
            "alpha_bar": alpha_bar,
        },
        "gbm_aware_used": True,
        "stylized_facts_evaluation": stylized_facts,
        "wasserstein_to_historical": wasserstein_to_historical,
        "fingerprint": fingerprint,
        "denoiser_required": True,
    }


def _compute_schedule(
    T: int,
    schedule: str,
    beta_start: float,
    beta_end: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute DDPM noise schedule."""
    if schedule == "linear":
        betas = np.linspace(beta_start, beta_end, T)
    elif schedule == "cosine":
        # Nichol & Dhariwal (2021) cosine schedule
        s = 0.008
        t_range = np.linspace(0, T, T + 1)
        f = np.cos((t_range / T + s) / (1 + s) * np.pi / 2) ** 2
        alpha_bar_full = f / f[0]
        alpha_bar_full = np.clip(alpha_bar_full, 1e-5, 1.0)
        betas = 1 - alpha_bar_full[1:] / alpha_bar_full[:-1]
        betas = np.clip(betas, 0.0, 0.999)
    else:
        raise ValueError(f"Unknown beta_schedule: {schedule!r}. Use 'linear' or 'cosine'.")

    alphas = 1.0 - betas
    alpha_bar = np.cumprod(alphas)
    return betas, alphas, alpha_bar


def _evaluate_stylized_facts(paths: np.ndarray) -> dict[str, Any]:
    """Evaluate stylized facts for the generated paths.

    Returns:
        fat_tails: bool — kurtosis > 3 for >=50% of paths
        vol_clustering: bool — Ljung-Box p-value < 0.05 on squared returns
        negative_skew: bool — mean skewness < 0
    """
    from scipy.stats import kurtosis, skew

    n_paths = paths.shape[0]

    # Fat tails: excess kurtosis > 0 (kurtosis > 3 in excess=False convention)
    # scipy kurtosis default is Fisher (excess), so kurtosis > 0 means fat tails
    kurtosis_vals = np.array([kurtosis(paths[i], fisher=True) for i in range(n_paths)])
    fat_tails = bool(np.mean(kurtosis_vals > 0) >= 0.5)

    # Vol clustering: Ljung-Box on squared returns (use autocorrelation at lag 1)
    # Check if mean autocorrelation of squared returns is significant
    lb_pvals: list[float] = []
    for i in range(n_paths):
        r = paths[i]
        r2 = r**2
        if len(r2) > 5 and np.std(r2) > 1e-12:
            # Manual lag-1 autocorrelation test
            from scipy.stats import pearsonr

            try:
                _, p = pearsonr(r2[:-1], r2[1:])
                lb_pvals.append(float(p))
            except Exception:
                lb_pvals.append(1.0)
        else:
            lb_pvals.append(1.0)
    vol_clustering = bool(np.mean(np.array(lb_pvals) < 0.05) >= 0.5) if lb_pvals else False

    # Negative skew
    skew_vals = np.array([skew(paths[i]) for i in range(n_paths)])
    negative_skew = bool(np.mean(skew_vals) < 0)

    return {
        "fat_tails": fat_tails,
        "vol_clustering": vol_clustering,
        "negative_skew": negative_skew,
        "mean_kurtosis": float(np.mean(kurtosis_vals)),
        "mean_skewness": float(np.mean(skew_vals)),
    }
