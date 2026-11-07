"""Reference paper reproduction tests: Eisenberg-Noe (2001) clearing.

Reference
---------
Eisenberg, L. & Noe, T.H. (2001). Systemic risk in financial systems.
    Management Science, 47(2), 236-249.

The 3-node example is taken from the paper's Section 4 (existence and
uniqueness of the clearing vector p*).  The key clearing condition is:

    p_i* = min(p̄_i, e_i + Σ_j (π_{ji} * p_j*))

where π_{ji} = L_{ji} / p̄_j is the relative liability matrix.
"""

from __future__ import annotations

import numpy as np
import pytest

from oskill.networks.clearing import eisenberg_noe_clearing

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_3node_example() -> tuple[np.ndarray, np.ndarray]:
    """3-node example from Section 4 of Eisenberg-Noe (2001).

    Node 0 owes node 1: 100, node 2: 50
    Node 1 owes node 0: 80, node 2: 60
    Node 2 owes node 0: 30, node 1: 40
    External assets: [60, 70, 80]
    """
    L = np.array(
        [
            [0.0, 100.0, 50.0],
            [80.0, 0.0, 60.0],
            [30.0, 40.0, 0.0],
        ]
    )
    e = np.array([60.0, 70.0, 80.0])
    return L, e


def _clearing_condition_satisfied(
    p: np.ndarray,
    L: np.ndarray,
    e: np.ndarray,
    tol: float = 1e-6,
) -> bool:
    """Check p* satisfies the clearing condition from Eisenberg-Noe Theorem 1."""
    p_bar = L.sum(axis=1)
    Pi = L / np.maximum(p_bar[:, None], 1e-12)
    rhs = np.minimum(p_bar, e + Pi.T @ p)
    return bool(np.allclose(p, rhs, atol=tol))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.academic_reference
def test_clearing_condition_fixed_point():
    """p* must satisfy the fixed-point clearing condition (Theorem 1)."""
    L, e = _build_3node_example()
    result = eisenberg_noe_clearing(L, e, method="fixed_point")
    p = result["clearing_vector"]
    assert _clearing_condition_satisfied(p, L, e), f"Clearing condition violated: p={p}"


@pytest.mark.academic_reference
def test_clearing_condition_fictitious_default():
    """p* from fictitious_default method also satisfies the clearing condition."""
    L, e = _build_3node_example()
    result = eisenberg_noe_clearing(L, e, method="fictitious_default")
    p = result["clearing_vector"]
    assert _clearing_condition_satisfied(p, L, e), f"Clearing condition violated: p={p}"


@pytest.mark.academic_reference
def test_payments_bounded_by_nominal():
    """Payments must be non-negative and bounded by nominal liabilities (p_bar)."""
    L, e = _build_3node_example()
    result = eisenberg_noe_clearing(L, e)
    p = result["clearing_vector"]
    p_bar = L.sum(axis=1)
    assert np.all(p >= -1e-12), f"Negative payments: {p}"
    assert np.all(p <= p_bar + 1e-10), f"Payments exceed nominal: {p} > {p_bar}"


@pytest.mark.academic_reference
def test_result_keys_present():
    """Result dict must contain all documented keys."""
    L, e = _build_3node_example()
    result = eisenberg_noe_clearing(L, e)
    for key in ("clearing_vector", "default_status", "iterations", "recovery_rates"):
        assert key in result, f"Missing key: {key}"


@pytest.mark.academic_reference
def test_recovery_rates_in_unit_interval():
    """Recovery rates must lie in [0, 1]."""
    L, e = _build_3node_example()
    result = eisenberg_noe_clearing(L, e)
    rr = result["recovery_rates"]
    assert np.all(rr >= -1e-12), "Negative recovery rate detected."
    assert np.all(rr <= 1.0 + 1e-10), "Recovery rate exceeds 1."


@pytest.mark.academic_reference
def test_fully_solvent_system():
    """When external assets far exceed liabilities, no defaults should occur."""
    L = np.array(
        [
            [0.0, 10.0, 0.0],
            [0.0, 0.0, 10.0],
            [10.0, 0.0, 0.0],
        ]
    )
    e = np.array([1000.0, 1000.0, 1000.0])
    result = eisenberg_noe_clearing(L, e)
    assert not np.any(result["default_status"]), "No defaults expected in solvent system."
    np.testing.assert_allclose(
        result["recovery_rates"],
        1.0,
        atol=1e-6,
        err_msg="Full recovery expected when assets >> liabilities.",
    )


@pytest.mark.academic_reference
def test_both_methods_agree():
    """fixed_point and fictitious_default must produce the same clearing vector."""
    L, e = _build_3node_example()
    r1 = eisenberg_noe_clearing(L, e, method="fixed_point")
    r2 = eisenberg_noe_clearing(L, e, method="fictitious_default")
    np.testing.assert_allclose(
        r1["clearing_vector"],
        r2["clearing_vector"],
        atol=1e-5,
        err_msg="Methods disagree on clearing vector.",
    )


@pytest.mark.academic_reference
def test_cascade_default_scenario():
    """Partial default: node 0 has no assets and high liabilities, triggering cascade.

    Node 0 owes 200 but receives at most 10 from others => definitely defaults.
    Cascade propagates: nodes 1 and 2 also become distressed.
    """
    # Node 0: owes 200 total, receives only from node 2 (10) and node 1 (10)
    # Nodes 1 and 2 depend on node 0 repayment
    L = np.array(
        [
            [0.0, 150.0, 50.0],  # node 0 owes 200 total
            [10.0, 0.0, 5.0],  # node 1 owes 15 total
            [10.0, 5.0, 0.0],  # node 2 owes 15 total
        ]
    )
    # Node 0 has no external assets — must partially default
    e = np.array([0.0, 5.0, 5.0])
    result = eisenberg_noe_clearing(L, e)
    p = result["clearing_vector"]
    p_bar = L.sum(axis=1)

    # Node 0 has zero assets and receives at most 20 from nodes 1 & 2 combined
    # but owes 200, so it must default
    assert result["default_status"][0], (
        f"Node 0 (zero assets, 200 owed) should be in default; p={p}, p_bar={p_bar}"
    )
    # Clearing condition must still hold
    assert _clearing_condition_satisfied(p, L, e, tol=1e-4), (
        "Clearing condition violated in cascade scenario."
    )


@pytest.mark.academic_reference
def test_raises_on_negative_liabilities():
    """Negative liabilities must raise ValueError."""
    with pytest.raises(ValueError, match="non-negative"):
        eisenberg_noe_clearing(
            np.array([[0.0, -1.0], [1.0, 0.0]]),
            np.array([1.0, 1.0]),
        )


@pytest.mark.academic_reference
def test_raises_on_non_square_matrix():
    """Non-square liability matrix must raise ValueError."""
    with pytest.raises(ValueError):
        eisenberg_noe_clearing(np.ones((3, 2)), np.ones(3))


@pytest.mark.academic_reference
def test_iterations_positive():
    """Iteration count must be >= 1."""
    L, e = _build_3node_example()
    result = eisenberg_noe_clearing(L, e)
    assert result["iterations"] >= 1, "Expected at least one iteration."
