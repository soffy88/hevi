"""Hierarchical Bayesian Normal model with Gibbs sampling."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import invgamma


def _ess_1d(chain: np.ndarray) -> int:
    """Estimate ESS from autocorrelation."""
    n = len(chain)
    if n < 4:
        return n
    x = chain - chain.mean()
    var = np.var(x)
    if var < 1e-14:
        return 1
    max_lag = min(n // 4, 100)
    acf = np.correlate(x, x, mode="full")
    acf = acf[n - 1 :] / (var * n)
    cumsum = 0.0
    for k in range(1, max_lag + 1):
        if acf[k] <= 0:
            break
        cumsum += acf[k]
    return max(1, int(n / (1.0 + 2.0 * cumsum)))


def hierarchical_bayes_normal(
    groups_data: dict[str, np.ndarray] | list[np.ndarray],
    *,
    population_prior_mean: float = 0.0,
    population_prior_std: float = 10.0,
    n_mcmc_samples: int = 2000,
    n_warmup: int = 1000,
    seed: int | None = None,
) -> dict[str, Any]:
    """Hierarchical Bayesian model for Normal data with partial pooling.

    Model:
        mu_g ~ N(theta, tau^2)
        y_{i,g} ~ N(mu_g, sigma_g^2)
    Priors:
        theta ~ N(population_prior_mean, population_prior_std^2)
        tau ~ HalfNormal(1)
        sigma_g ~ HalfNormal(1)

    Uses Gibbs sampling with a Metropolis-Hastings step for tau.

    Args:
        groups_data: Dict mapping group name -> 1-D array, or list of arrays.
        population_prior_mean: Prior mean for the population mean theta.
        population_prior_std: Prior std for theta.
        n_mcmc_samples: Posterior samples to retain.
        n_warmup: Warmup iterations to discard.
        seed: Random seed.

    Returns:
        Dict with group_means_samples, group_means_credible_intervals,
        population_mean_samples, population_std_samples,
        group_variances_samples, n_effective.

    Reference:
        Gelman et al. (2013), "Bayesian Data Analysis", Ch.5.
    """
    rng = np.random.default_rng(seed)

    # Normalise input to dict
    if isinstance(groups_data, dict):
        group_names = list(groups_data.keys())
        group_arrays = [np.asarray(groups_data[k], dtype=np.float64) for k in group_names]
    else:
        group_names = [f"group_{i}" for i in range(len(groups_data))]
        group_arrays = [np.asarray(g, dtype=np.float64) for g in groups_data]

    G = len(group_names)
    n_g = np.array([len(arr) for arr in group_arrays])
    sum_y = np.array([arr.sum() for arr in group_arrays])
    sum_y2 = np.array([(arr**2).sum() for arr in group_arrays])

    total_iters = n_warmup + n_mcmc_samples

    # Storage
    mu_chain = np.zeros((total_iters, G))
    theta_chain = np.zeros(total_iters)
    tau_chain = np.zeros(total_iters)
    sigma2_chain = np.zeros((total_iters, G))

    # Initialise
    mu_cur = np.array([arr.mean() if len(arr) > 0 else 0.0 for arr in group_arrays])
    theta_cur = float(mu_cur.mean())
    tau_cur = 1.0
    sigma2_cur = np.array(
        [max(np.var(arr, ddof=1) if len(arr) > 1 else 1.0, 1e-4) for arr in group_arrays]
    )

    prior_prec_theta = 1.0 / (population_prior_std**2)
    log_tau_cur = np.log(tau_cur)

    for it in range(total_iters):
        # 1. Sample mu_g | theta, tau, sigma_g, data
        for g in range(G):
            v_g2 = 1.0 / (n_g[g] / sigma2_cur[g] + 1.0 / tau_cur**2)
            m_g = v_g2 * (sum_y[g] / sigma2_cur[g] + theta_cur / tau_cur**2)
            mu_cur[g] = m_g + np.sqrt(v_g2) * rng.standard_normal()

        # 2. Sample theta | mu_g, tau
        prec_theta_post = prior_prec_theta + G / tau_cur**2
        mean_theta_post = (
            population_prior_mean * prior_prec_theta + mu_cur.sum() / tau_cur**2
        ) / prec_theta_post
        theta_cur = mean_theta_post + rng.standard_normal() / np.sqrt(prec_theta_post)

        # 3. Sample tau | mu_g, theta via log-normal MH
        log_tau_prop = log_tau_cur + 0.1 * rng.standard_normal()
        tau_prop = np.exp(log_tau_prop)

        def _log_tau_posterior(tau_val: float) -> float:
            if tau_val <= 0:
                return -np.inf
            # HalfNormal(1) log-density: -0.5*(tau/1)^2 + log(tau) adjustment
            log_prior = -0.5 * tau_val**2
            log_lik = -G * np.log(tau_val) - 0.5 * np.sum((mu_cur - theta_cur) ** 2) / tau_val**2
            return log_prior + log_lik

        log_accept = _log_tau_posterior(tau_prop) - _log_tau_posterior(tau_cur)
        if np.log(rng.uniform()) < log_accept:
            tau_cur = tau_prop
            log_tau_cur = log_tau_prop

        # 4. Sample sigma_g^2 | mu_g, data: InvGamma(n_g/2 + 1, sum((y-mu_g)^2)/2 + 1)
        for g in range(G):
            ss_g = sum_y2[g] - 2.0 * mu_cur[g] * sum_y[g] + n_g[g] * mu_cur[g] ** 2
            alpha_g = n_g[g] / 2.0 + 1.0
            beta_g = ss_g / 2.0 + 1.0
            sigma2_cur[g] = invgamma.rvs(alpha_g, scale=beta_g, random_state=rng.integers(0, 2**31))

        mu_chain[it] = mu_cur
        theta_chain[it] = theta_cur
        tau_chain[it] = tau_cur
        sigma2_chain[it] = sigma2_cur

    # Discard warmup
    mu_post = mu_chain[n_warmup:]
    theta_post = theta_chain[n_warmup:]
    tau_post = tau_chain[n_warmup:]
    sigma2_post = sigma2_chain[n_warmup:]

    group_means_samples = {group_names[g]: mu_post[:, g] for g in range(G)}
    group_variances_samples = {group_names[g]: sigma2_post[:, g] for g in range(G)}

    group_means_ci = {}
    for g in range(G):
        samples_g = mu_post[:, g]
        group_means_ci[group_names[g]] = {
            "mean": float(samples_g.mean()),
            "95_lower": float(np.percentile(samples_g, 2.5)),
            "95_upper": float(np.percentile(samples_g, 97.5)),
        }

    n_effective = _ess_1d(theta_post)

    return {
        "group_means_samples": group_means_samples,
        "group_means_credible_intervals": group_means_ci,
        "population_mean_samples": theta_post,
        "population_std_samples": tau_post,
        "group_variances_samples": group_variances_samples,
        "n_effective": n_effective,
    }
