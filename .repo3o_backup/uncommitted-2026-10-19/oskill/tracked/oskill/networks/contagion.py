"""Interbank contagion simulation (Furfine 2003 and Rogers-Veraart)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np


def contagion_simulate(
    exposure_matrix: np.ndarray,
    initial_shock: np.ndarray,
    *,
    capital_buffer: np.ndarray,
    transmission_rule: Literal["furfine", "rogers_veraart"] = "furfine",
    fire_sale_intensity: float = 0.0,
    max_rounds: int = 20,
) -> dict[str, Any]:
    """Simulate interbank contagion cascade.

    Parameters
    ----------
    exposure_matrix:
        (N, N) matrix where entry [i, j] is institution i's exposure to j.
    initial_shock:
        (N,) vector of initial losses imposed on each institution.
    capital_buffer:
        (N,) vector of capital buffers; institution defaults if losses > buffer.
    transmission_rule:
        "furfine": direct exposure transmission with LGD=1.
        "rogers_veraart": use Eisenberg-Noe clearing to compute shortfalls.
    fire_sale_intensity:
        Additional loss multiplier applied on top of direct exposure (Furfine only).
    max_rounds:
        Maximum contagion rounds.

    Returns
    -------
    dict with keys: defaults_by_round, final_losses, total_defaults, cascade_size.
    """
    exposure_matrix = np.asarray(exposure_matrix, dtype=float)
    initial_shock = np.asarray(initial_shock, dtype=float)
    capital_buffer = np.asarray(capital_buffer, dtype=float)

    N = exposure_matrix.shape[0]
    losses = initial_shock.copy()
    all_defaults: set[int] = set()
    defaults_by_round: list[tuple[int, list[int]]] = []

    if transmission_rule == "rogers_veraart":
        # Use Eisenberg-Noe to find shortfalls from initial shock
        try:
            from oskill.networks.clearing import eisenberg_noe_clearing
        except ImportError:
            from .clearing import eisenberg_noe_clearing  # type: ignore[no-redef]

        # Build nominal liabilities from exposure matrix
        nominal_liabilities = exposure_matrix.copy()
        external_assets = np.maximum(capital_buffer - initial_shock, 0.0)

        en_result = eisenberg_noe_clearing(nominal_liabilities, external_assets)
        clearing_vector = en_result["clearing_vector"]
        L_total = nominal_liabilities.sum(axis=1)
        shortfalls = np.maximum(0.0, L_total - clearing_vector)

        # Use shortfalls as effective losses
        losses = shortfalls.copy()
        # Identify initial defaults
        new_defaults = {i for i in range(N) if losses[i] > capital_buffer[i]}
        if new_defaults:
            defaults_by_round.append((0, list(new_defaults)))
            all_defaults |= new_defaults

        # Propagate further with Furfine-like mechanism
        for rnd in range(1, max_rounds):
            round_defaults: set[int] = set()
            for i in all_defaults:
                for j in range(N):
                    if j not in all_defaults:
                        losses[j] += exposure_matrix[i, j]
            for j in range(N):
                if j not in all_defaults and losses[j] > capital_buffer[j]:
                    round_defaults.add(j)
            if not round_defaults:
                break
            defaults_by_round.append((rnd, list(round_defaults)))
            all_defaults |= round_defaults

    else:  # furfine
        lgd = 1.0
        for rnd in range(max_rounds):
            new_defaults: set[int] = {
                i for i in range(N) if losses[i] > capital_buffer[i] and i not in all_defaults
            }
            if not new_defaults:
                break
            for i in new_defaults:
                for j in range(N):
                    if j not in all_defaults:
                        direct = exposure_matrix[i, j] * lgd
                        fire_sale = fire_sale_intensity * exposure_matrix[i, j]
                        losses[j] += direct + fire_sale
            all_defaults |= new_defaults
            defaults_by_round.append((rnd, list(new_defaults)))

    cascade_size = max((len(d) for _, d in defaults_by_round), default=0)

    return {
        "defaults_by_round": defaults_by_round,
        "final_losses": losses,
        "total_defaults": len(all_defaults),
        "cascade_size": cascade_size,
    }
