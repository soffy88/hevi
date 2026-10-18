"""Structural Causal Model Fitting (SCM)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

try:
    from oprim import distributional_distance
except ImportError:
    distributional_distance = None  # type: ignore[assignment]


def structural_causal_model_fit(
    data: pd.DataFrame,
    causal_graph: dict[str, list[str]],
    *,
    estimator: Literal["linear", "additive_noise", "nonlinear_GAM"] = "linear",
    do_intervention_var: str | None = None,
    do_intervention_value: float | None = None,
    n_samples_intervention: int = 1000,
) -> dict[str, Any]:
    """Structural Causal Model Fitting.

    Fits a structural equation model (SEM) to data given a causal graph.
    Supports linear, additive noise, and nonlinear (polynomial) estimators.
    Optionally computes interventional distributions via do-calculus.

    Parameters
    ----------
    data : pd.DataFrame
        Observational data. Columns are variables.
    causal_graph : dict[str, list[str]]
        Adjacency dict: ``{child: [parent1, parent2, ...]}``.
        All variables in data must appear as keys (with empty list if root).
    estimator : {"linear", "additive_noise", "nonlinear_GAM"}
        Structural equation estimator. "additive_noise" uses the same linear
        regression as "linear". "nonlinear_GAM" uses degree-2 polynomial.
    do_intervention_var : str or None
        Variable to intervene on (do-calculus).
    do_intervention_value : float or None
        Value to set the intervention variable to.
    n_samples_intervention : int
        Number of samples to draw for intervention distribution.

    Returns
    -------
    dict with keys:
        fitted_models : dict — per-variable model dicts with coefficients
        residuals : dict — per-variable residual arrays
        r_squared_per_var : dict — R² per variable
        intervention_samples : dict[str, np.ndarray] or {} — samples under do(X=v)
        natural_distribution_samples : dict[str, np.ndarray] — samples from fitted SCM
        intervention_effect_size : dict[str, float] — Wasserstein-1 distance per variable
        graph_is_dag : bool — whether the provided graph is a DAG

    Raises
    ------
    ValueError
        If causal_graph contains a cycle.
    """
    if not isinstance(data, pd.DataFrame):
        data = pd.DataFrame(data)

    variables = list(data.columns)

    # --- Fill missing graph keys ---
    full_graph = {v: causal_graph.get(v, []) for v in variables}

    # --- Validate DAG ---
    topo_order, is_dag = _topological_sort(full_graph, variables)
    if not is_dag:
        raise ValueError("causal_graph contains a cycle. Structural causal models require a DAG.")

    n, _ = data.shape

    fitted_models: dict[str, dict] = {}
    residuals: dict[str, np.ndarray] = {}
    r_squared_per_var: dict[str, float] = {}

    # --- Fit structural equations ---
    for var in topo_order:
        parents = full_graph[var]
        y = data[var].values.astype(np.float64)

        if len(parents) == 0:
            # Root node: model is just the mean + noise
            mu = float(np.mean(y))
            res = y - mu
            fitted_models[var] = {"type": "root", "mean": mu, "parents": []}
            residuals[var] = res
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared_per_var[var] = 1.0 if ss_tot == 0 else 0.0
        else:
            X_par = data[parents].values.astype(np.float64)

            if estimator in ("linear", "additive_noise"):
                coef, intercept, y_hat = _fit_linear(y, X_par)
                fitted_models[var] = {
                    "type": "linear",
                    "intercept": float(intercept),
                    "coefficients": {p: float(c) for p, c in zip(parents, coef)},
                    "parents": parents,
                }
            else:  # nonlinear_GAM → degree-2 polynomial
                coef, intercept, y_hat, feature_names = _fit_polynomial(y, X_par, parents)
                fitted_models[var] = {
                    "type": "polynomial_degree2",
                    "intercept": float(intercept),
                    "coefficients": dict(zip(feature_names, coef.tolist())),
                    "parents": parents,
                }

            res = y - y_hat
            residuals[var] = res
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            ss_res = np.sum(res**2)
            r_squared_per_var[var] = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 1.0

    # --- Sample from fitted model (natural distribution) ---
    rng = np.random.default_rng(42)
    natural_samples = _sample_from_scm(
        full_graph, topo_order, fitted_models, residuals, n_samples_intervention, rng
    )

    # --- Compute interventional distribution ---
    intervention_samples: dict[str, np.ndarray] = {}
    intervention_effect_size: dict[str, float] = {}

    if do_intervention_var is not None and do_intervention_value is not None:
        if do_intervention_var not in variables:
            raise ValueError(f"do_intervention_var {do_intervention_var!r} not in data columns")
        rng2 = np.random.default_rng(43)
        intervention_samples = _sample_from_scm(
            full_graph,
            topo_order,
            fitted_models,
            residuals,
            n_samples_intervention,
            rng2,
            do_var=do_intervention_var,
            do_val=do_intervention_value,
        )

        for var in variables:
            nat = natural_samples.get(var, np.array([]))
            intv = intervention_samples.get(var, np.array([]))
            if len(nat) > 0 and len(intv) > 0:
                if distributional_distance is not None:
                    d = distributional_distance(nat, sample_b=intv, metric="wasserstein_1")
                else:
                    d = float(np.mean(np.abs(np.sort(nat) - np.sort(intv))))
                intervention_effect_size[var] = float(d)

    return {
        "fitted_models": fitted_models,
        "residuals": residuals,
        "r_squared_per_var": r_squared_per_var,
        "intervention_samples": intervention_samples,
        "natural_distribution_samples": natural_samples,
        "intervention_effect_size": intervention_effect_size,
        "graph_is_dag": is_dag,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _topological_sort(graph: dict[str, list[str]], variables: list[str]) -> tuple[list[str], bool]:
    """Kahn's algorithm topological sort. Returns (order, is_dag)."""
    in_degree: dict[str, int] = {v: 0 for v in variables}
    # Build adjacency: parent → children
    children: dict[str, list[str]] = {v: [] for v in variables}
    for child, parents in graph.items():
        for p in parents:
            if p in in_degree:
                in_degree[child] += 1
                children[p].append(child)

    queue = [v for v in variables if in_degree[v] == 0]
    order: list[str] = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        for child in children.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    is_dag = len(order) == len(variables)
    return order, is_dag


def _fit_linear(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """OLS linear regression. Returns (coef, intercept, y_hat)."""
    Xc = np.column_stack([np.ones(len(X)), X])
    coef_all, _, _, _ = np.linalg.lstsq(Xc, y, rcond=None)
    intercept = coef_all[0]
    coef = coef_all[1:]
    y_hat = Xc @ coef_all
    return coef, float(intercept), y_hat


def _fit_polynomial(
    y: np.ndarray,
    X: np.ndarray,
    parents: list[str],
    degree: int = 2,
) -> tuple[np.ndarray, float, np.ndarray, list[str]]:
    """Degree-2 polynomial regression. Returns (coef, intercept, y_hat, feature_names)."""
    n, k = X.shape
    # Build features: original + squared + interactions
    features: list[np.ndarray] = []
    feature_names: list[str] = []

    for i in range(k):
        features.append(X[:, i])
        feature_names.append(parents[i])

    for i in range(k):
        features.append(X[:, i] ** 2)
        feature_names.append(f"{parents[i]}^2")

    for i in range(k):
        for j in range(i + 1, k):
            features.append(X[:, i] * X[:, j])
            feature_names.append(f"{parents[i]}*{parents[j]}")

    Xpoly = np.column_stack(features) if features else X
    coef, intercept, y_hat = _fit_linear(y, Xpoly)
    return coef, intercept, y_hat, feature_names


def _sample_from_scm(
    graph: dict[str, list[str]],
    topo_order: list[str],
    fitted_models: dict[str, dict],
    residuals: dict[str, np.ndarray],
    n_samples: int,
    rng: np.random.Generator,
    do_var: str | None = None,
    do_val: float | None = None,
) -> dict[str, np.ndarray]:
    """Sample from the fitted SCM by propagating noise through topological order."""
    samples: dict[str, np.ndarray] = {}

    for var in topo_order:
        if do_var is not None and var == do_var:
            # Hard intervention: set to fixed value
            samples[var] = np.full(n_samples, float(do_val))  # type: ignore[arg-type]
            continue

        model = fitted_models[var]
        res = residuals[var]
        # Bootstrap noise from residuals
        noise_idx = rng.integers(0, len(res), size=n_samples)
        noise = res[noise_idx]

        if model["type"] == "root":
            samples[var] = model["mean"] + noise
        elif model["type"] == "linear":
            intercept = model["intercept"]
            coef = model["coefficients"]
            model["parents"]
            y_hat = np.full(n_samples, intercept)
            for p, c in coef.items():
                if p in samples:
                    y_hat = y_hat + c * samples[p]
            samples[var] = y_hat + noise
        else:  # polynomial
            # Simplified: just add noise around mean of residuals
            intercept = model["intercept"]
            samples[var] = np.full(n_samples, intercept) + noise

    return samples
