"""Tests for Eisenberg-Noe clearing model."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.networks.clearing import eisenberg_noe_clearing


@pytest.fixture
def simple_3node():
    """3-bank network with one interconnected bank."""
    L = np.array(
        [
            [0.0, 50.0, 0.0],
            [0.0, 0.0, 50.0],
            [30.0, 0.0, 0.0],
        ]
    )
    e = np.array([60.0, 30.0, 20.0])
    return L, e


def test_no_liabilities_clearing_zero():
    L = np.zeros((3, 3))
    e = np.array([10.0, 20.0, 30.0])
    result = eisenberg_noe_clearing(L, e)
    assert np.allclose(result["clearing_vector"], 0.0)


def test_full_assets_no_default():
    """When assets >> liabilities, all banks fully pay."""
    L = np.array([[0.0, 10.0], [10.0, 0.0]])
    e = np.array([1000.0, 1000.0])
    result = eisenberg_noe_clearing(L, e)
    assert np.allclose(result["clearing_vector"], [10.0, 10.0])
    assert not np.any(result["default_status"])


def test_single_default_propagates(simple_3node):
    L, e = simple_3node
    e_stressed = e.copy()
    e_stressed[0] = 0.0  # Bank 0 has no external assets
    result = eisenberg_noe_clearing(L, e_stressed)
    # With no assets, bank 0 cannot fully pay
    assert result["clearing_vector"][0] < L[0].sum()


def test_recovery_rates_in_0_1(simple_3node):
    L, e = simple_3node
    result = eisenberg_noe_clearing(L, e)
    rr = result["recovery_rates"]
    assert np.all(rr >= -1e-9)
    assert np.all(rr <= 1.0 + 1e-9)


def test_default_status_boolean(simple_3node):
    L, e = simple_3node
    result = eisenberg_noe_clearing(L, e)
    assert result["default_status"].dtype == bool


def test_fixed_point_method(simple_3node):
    L, e = simple_3node
    result = eisenberg_noe_clearing(L, e, method="fixed_point")
    assert "clearing_vector" in result
    assert result["iterations"] >= 1


def test_fictitious_default_method(simple_3node):
    L, e = simple_3node
    result = eisenberg_noe_clearing(L, e, method="fictitious_default")
    cv = result["clearing_vector"]
    assert cv.shape == (3,)
    assert np.all(cv >= 0)


def test_full_default_stress():
    """Bank with no assets and large liabilities should default."""
    L = np.array([[0.0, 100.0], [0.0, 0.0]])
    e = np.array([0.0, 0.0])
    result = eisenberg_noe_clearing(L, e)
    # Bank 0 owes 100 but has nothing
    assert result["clearing_vector"][0] == pytest.approx(0.0, abs=1e-6)
    assert result["default_status"][0]


def test_negative_liabilities_raises():
    L = np.array([[0.0, -5.0], [5.0, 0.0]])
    e = np.array([10.0, 10.0])
    with pytest.raises(ValueError, match="non-negative"):
        eisenberg_noe_clearing(L, e)


def test_negative_assets_raises():
    L = np.array([[0.0, 5.0], [5.0, 0.0]])
    e = np.array([-1.0, 10.0])
    with pytest.raises(ValueError, match="non-negative"):
        eisenberg_noe_clearing(L, e)


def test_iterations_returned(simple_3node):
    L, e = simple_3node
    result = eisenberg_noe_clearing(L, e)
    assert isinstance(result["iterations"], int)
    assert result["iterations"] >= 1
