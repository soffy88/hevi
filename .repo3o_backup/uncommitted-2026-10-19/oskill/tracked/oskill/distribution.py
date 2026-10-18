"""Group 3: Distribution & Anomaly skills."""

from __future__ import annotations

import warnings
from typing import Literal

import numpy as np
import oprim
import pandas as pd


def distribution_shift_test(
    sample_a: np.ndarray,
    sample_b: np.ndarray,
    *,
    methods: list[Literal["ks", "wasserstein", "jsd"]] | None = None,
    voting: Literal["majority", "any", "all"] = "majority",
    alpha: float = 0.05,
    wasserstein_threshold_ratio: float = 0.1,
    jsd_threshold: float = 0.1,
    compute_summary: bool = True,
) -> dict:
    """Multi-method distribution shift detection with voting.

    Calls:
        oprim.kolmogorov_smirnov_test, oprim.wasserstein_distance,
        oprim.symmetric_kl_divergence, oprim.distribution_summary

    Args:
        sample_a: First sample.
        sample_b: Second sample.
        methods: Methods to use. Default: ["ks", "wasserstein", "jsd"].
        voting: Voting strategy.
        alpha: Significance level for KS test.
        wasserstein_threshold_ratio: Wasserstein threshold as ratio of max std.
        jsd_threshold: JSD threshold for shift detection.
        compute_summary: Whether to compute distribution summaries.

    Returns:
        Dict with shift_detected, votes, individual_tests, summaries.

    Raises:
        ValueError: If samples are empty.
    """
    if methods is None:
        methods = ["ks", "wasserstein", "jsd"]

    sample_a = np.asarray(sample_a, dtype=np.float64)
    sample_b = np.asarray(sample_b, dtype=np.float64)
    sample_a = sample_a[~np.isnan(sample_a)]
    sample_b = sample_b[~np.isnan(sample_b)]

    if len(sample_a) == 0 or len(sample_b) == 0:
        raise ValueError("Samples must not be empty after removing NaN")

    if len(sample_a) < 20 or len(sample_b) < 20:
        warnings.warn("Sample size < 20 may give unreliable results", stacklevel=2)

    votes: dict[str, bool] = {}
    individual_tests: dict[str, dict] = {}

    for method in methods:
        if method == "ks":
            ks_result = oprim.kolmogorov_smirnov_test(sample_a, sample_b=sample_b)
            detected = ks_result["p_value"] < alpha
            votes["ks"] = detected
            individual_tests["ks"] = {
                "statistic": ks_result["statistic"],
                "p_value": ks_result["p_value"],
                "detected": detected,
            }
        elif method == "wasserstein":
            w_dist = oprim.wasserstein_distance(sample_a, v=sample_b)
            threshold = wasserstein_threshold_ratio * max(np.std(sample_a), np.std(sample_b))
            detected = w_dist > threshold
            votes["wasserstein"] = detected
            individual_tests["wasserstein"] = {
                "distance": w_dist,
                "threshold": threshold,
                "detected": detected,
            }
        elif method == "jsd":
            # Convert to histograms for JSD
            n_bins = min(50, max(10, int(np.sqrt(min(len(sample_a), len(sample_b))))))
            all_data = np.concatenate([sample_a, sample_b])
            bins = np.linspace(all_data.min(), all_data.max(), n_bins + 1)
            hist_a, _ = np.histogram(sample_a, bins=bins)
            hist_b, _ = np.histogram(sample_b, bins=bins)
            # Remove bins where both are zero to avoid degenerate JSD
            nonzero = (hist_a > 0) | (hist_b > 0)
            hist_a = hist_a[nonzero].astype(np.float64)
            hist_b = hist_b[nonzero].astype(np.float64)
            # Normalize to probability distributions
            hist_a = hist_a / hist_a.sum()
            hist_b = hist_b / hist_b.sum()
            # Let oprim handle epsilon internally
            jsd_val = oprim.symmetric_kl_divergence(hist_a, q=hist_b, mode="js")
            detected = jsd_val > jsd_threshold
            votes["jsd"] = detected
            individual_tests["jsd"] = {
                "jsd": jsd_val,
                "threshold": jsd_threshold,
                "detected": detected,
            }

    # Voting
    n_detected = sum(votes.values())
    n_methods = len(votes)
    if voting == "majority":
        shift_detected = n_detected > n_methods / 2
    elif voting == "any":
        shift_detected = n_detected > 0
    else:  # "all"
        shift_detected = n_detected == n_methods

    # Summaries
    summary_a = oprim.distribution_summary(sample_a) if compute_summary else None
    summary_b = oprim.distribution_summary(sample_b) if compute_summary else None

    return {
        "shift_detected": bool(shift_detected),
        "voting": voting,
        "votes": votes,
        "individual_tests": individual_tests,
        "sample_a_summary": summary_a,
        "sample_b_summary": summary_b,
        "n_a": len(sample_a),
        "n_b": len(sample_b),
    }


def detect_outliers_robust(
    data: np.ndarray,
    *,
    methods: list[Literal["zscore", "iqr", "mahalanobis"]] | None = None,
    voting: Literal["majority", "any", "all"] = "any",
    thresholds: dict | None = None,
    return_diagnostics: bool = True,
) -> dict:
    """Robust multi-method outlier detection with voting.

    Calls:
        oprim.zscore_normalize, oprim.distribution_summary

    Args:
        data: Input data (1D or 2D).
        methods: Detection methods. Default: ["zscore", "iqr"].
        voting: Voting strategy.
        thresholds: Custom thresholds. Default: zscore=3.0, iqr_factor=1.5, mahalanobis=3.0.
        return_diagnostics: Whether to return per-method diagnostics.

    Returns:
        Dict with outlier_mask, n_outliers, votes, thresholds_used, diagnostics.

    Raises:
        ValueError: If data is empty or all NaN.
    """
    if methods is None:
        methods = ["zscore", "iqr"]

    data = np.asarray(data, dtype=np.float64)
    if data.ndim == 1:
        data_2d = data.reshape(-1, 1)
    else:
        data_2d = data

    if data_2d.size == 0:
        raise ValueError("data must not be empty")
    if np.all(np.isnan(data_2d)):
        raise ValueError("data must not be all NaN")
    if data_2d.shape[0] < 2:
        raise ValueError("data must have at least 2 observations")

    # Default thresholds
    default_thresholds = {"zscore": 3.0, "iqr_factor": 1.5, "mahalanobis": 3.0}
    thresholds_used = {**default_thresholds, **(thresholds or {})}

    n_obs = data_2d.shape[0]
    votes_dict: dict[str, np.ndarray] = {}
    diagnostics: dict[str, dict] = {}

    for method in methods:
        if method == "zscore":
            # Use oprim.zscore_normalize (expanding mode for full-sample z-score)
            oprim.zscore_normalize(
                pd.DataFrame(data_2d), window=None, min_periods=1, clip_extreme=None
            )
            # Take the last row's z-score (which uses all data) - or compute directly
            # Actually for outlier detection we want full-sample z-score
            mean = np.nanmean(data_2d, axis=0)
            std = np.nanstd(data_2d, axis=0, ddof=1)
            std[std < 1e-15] = 1.0
            z = np.abs((data_2d - mean) / std)
            mask = np.any(z > thresholds_used["zscore"], axis=1)
            votes_dict["zscore"] = mask
            if return_diagnostics:
                diagnostics["zscore"] = {
                    "max_zscore": float(np.nanmax(z)),
                    "threshold": thresholds_used["zscore"],
                }

        elif method == "iqr":
            # Use oprim.distribution_summary to get quartiles
            masks_per_col = []
            for col in range(data_2d.shape[1]):
                col_data = data_2d[:, col]
                valid = col_data[~np.isnan(col_data)]
                summary = oprim.distribution_summary(valid, percentiles=[0.25, 0.75])
                q1 = summary["q_0.25"]
                q3 = summary["q_0.75"]
                iqr = q3 - q1
                factor = thresholds_used["iqr_factor"]
                lower = q1 - factor * iqr
                upper = q3 + factor * iqr
                col_mask = (col_data < lower) | (col_data > upper)
                masks_per_col.append(col_mask)
            mask = np.any(np.column_stack(masks_per_col), axis=1)
            votes_dict["iqr"] = mask
            if return_diagnostics:
                diagnostics["iqr"] = {
                    "iqr_factor": thresholds_used["iqr_factor"],
                }

        elif method == "mahalanobis":
            if data_2d.shape[1] == 1:
                # 1D: equivalent to zscore
                mean = np.nanmean(data_2d, axis=0)
                std = np.nanstd(data_2d, axis=0, ddof=1)
                std[std < 1e-15] = 1.0
                z = np.abs((data_2d - mean) / std)
                mask = np.any(z > thresholds_used["mahalanobis"], axis=1)
            else:
                # Multi-D: use sklearn MinCovDet
                from sklearn.covariance import MinCovDet

                valid_mask = ~np.any(np.isnan(data_2d), axis=1)
                valid_data = data_2d[valid_mask]
                mcd = MinCovDet().fit(valid_data)
                mahal_dist = mcd.mahalanobis(data_2d)
                mask = mahal_dist > thresholds_used["mahalanobis"] ** 2
            votes_dict["mahalanobis"] = mask
            if return_diagnostics:
                diagnostics["mahalanobis"] = {
                    "threshold": thresholds_used["mahalanobis"],
                }

    # Voting
    all_masks = np.column_stack(list(votes_dict.values()))
    n_methods = all_masks.shape[1]
    if voting == "any":
        outlier_mask = np.any(all_masks, axis=1)
    elif voting == "majority":
        outlier_mask = np.sum(all_masks, axis=1) > n_methods / 2
    else:  # "all"
        outlier_mask = np.all(all_masks, axis=1)

    return {
        "outlier_mask": outlier_mask,
        "n_outliers": int(outlier_mask.sum()),
        "n_total": n_obs,
        "voting": voting,
        "votes": votes_dict,
        "thresholds_used": thresholds_used,
        "diagnostics": diagnostics if return_diagnostics else None,
    }


def bootstrap_distribution(
    data: np.ndarray,
    statistic: callable,
    *,
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    method: Literal["percentile", "bca", "basic"] = "percentile",
    include_density: bool = False,
    density_n_points: int = 200,
    random_state: int | None = None,
) -> dict:
    """Bootstrap distribution of any statistic with full description.

    Calls:
        oprim.bootstrap_ci, oprim.distribution_summary, oprim.kde_density (optional)

    Args:
        data: Input data array.
        statistic: Function that computes a scalar from an array.
        n_bootstrap: Number of bootstrap resamples.
        confidence_level: CI confidence level.
        method: CI method.
        include_density: Whether to compute KDE density.
        density_n_points: Number of points for density estimation.
        random_state: Random seed.

    Returns:
        Dict with point_estimate, samples, ci, summary, density.

    Raises:
        ValueError: If data is empty.
    """
    data = np.asarray(data, dtype=np.float64)
    valid = data[~np.isnan(data)]
    if valid.size == 0:
        raise ValueError("data must not be empty or all NaN")

    # Point estimate
    point_estimate = float(statistic(valid))

    # Single bootstrap pass: generate samples and compute CI from them
    rng = np.random.default_rng(random_state)
    indices = rng.integers(0, len(valid), size=(n_bootstrap, len(valid)))
    samples = np.array([statistic(valid[idx]) for idx in indices])

    # Compute CI from bootstrap samples
    if method == "percentile":
        alpha = 1 - confidence_level
        ci_low = float(np.percentile(samples, 100 * alpha / 2))
        ci_high = float(np.percentile(samples, 100 * (1 - alpha / 2)))
    elif method == "basic":
        alpha = 1 - confidence_level
        q_low = np.percentile(samples, 100 * alpha / 2)
        q_high = np.percentile(samples, 100 * (1 - alpha / 2))
        ci_low = float(2 * point_estimate - q_high)
        ci_high = float(2 * point_estimate - q_low)
    else:
        # BCa requires jackknife - delegate to oprim.bootstrap_ci
        ci_result = oprim.bootstrap_ci(
            valid,
            statistic_fn=statistic,
            n_bootstrap=n_bootstrap,
            confidence_level=confidence_level,
            method=method,
            random_state=random_state,
        )
        ci_low = float(ci_result["ci_lower"])
        ci_high = float(ci_result["ci_upper"])

    # Use oprim.distribution_summary
    summary = oprim.distribution_summary(samples)

    # Optional density
    density = None
    if include_density:
        eval_points = np.linspace(samples.min(), samples.max(), density_n_points)
        density = oprim.kde_density(samples, eval_points=eval_points)

    return {
        "point_estimate": point_estimate,
        "samples": samples,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "confidence_level": confidence_level,
        "method": method,
        "summary": summary,
        "density": density,
        "n_bootstrap": n_bootstrap,
        "n_obs": len(valid),
    }
