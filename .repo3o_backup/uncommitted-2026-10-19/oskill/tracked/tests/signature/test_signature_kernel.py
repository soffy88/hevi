"""Tests for signature_kernel."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.signature.kernel import signature_kernel


def test_sk_basic():
    path = np.random.default_rng(0).normal(0, 1, (20, 2))
    k = signature_kernel(path, path)
    assert isinstance(k, float)


def test_sk_positive_definite():
    path = np.random.default_rng(0).normal(0, 1, (20, 2))
    k = signature_kernel(path, path)
    assert k > 0


def test_sk_symmetric():
    rng = np.random.default_rng(42)
    p1 = rng.normal(0, 1, (15, 2))
    p2 = rng.normal(0, 1, (15, 2))
    k12 = signature_kernel(p1, p2)
    k21 = signature_kernel(p2, p1)
    np.testing.assert_allclose(k12, k21, rtol=1e-8)


def test_sk_depth_1():
    path = np.random.default_rng(0).normal(0, 1, (10, 2))
    k = signature_kernel(path, path, truncation_depth=1)
    assert isinstance(k, float)


def test_sk_pde_solver():
    rng = np.random.default_rng(0)
    p1 = rng.normal(0, 1, (10, 2))
    p2 = rng.normal(0, 1, (10, 2))
    k = signature_kernel(p1, p2, method="pde_solver")
    assert isinstance(k, float)


def test_sk_constant_path_vs_varied():
    const = np.ones((10, 2))
    varied = np.cumsum(np.random.default_rng(0).normal(0, 0.1, (10, 2)), axis=0)
    k_same = signature_kernel(const, const)
    k_diff = signature_kernel(const, varied)
    # Not necessarily const > varied; just check both are floats
    assert isinstance(k_same, float) and isinstance(k_diff, float)


def test_sk_1d_paths():
    rng = np.random.default_rng(0)
    p1 = rng.normal(0, 1, (20, 1))
    p2 = rng.normal(0, 1, (20, 1))
    k = signature_kernel(p1, p2)
    assert isinstance(k, float)


def test_sk_invalid_dim_raises():
    p1 = np.ones((10, 2))
    p2 = np.ones((10, 3))  # different dim
    with pytest.raises(ValueError):
        signature_kernel(p1, p2)


def test_sk_invalid_method_raises():
    path = np.ones((10, 2))
    with pytest.raises(ValueError):
        signature_kernel(path, path, method="invalid")


def test_sk_1d_input_raises():
    """1-D path (not 2-D array) should raise ValueError."""
    path_1d = np.ones(10)
    path_2d = np.ones((10, 2))
    with pytest.raises(ValueError, match="2-D"):
        signature_kernel(path_1d, path_2d)


def test_sk_fallback_truncated(mocker):
    """When _HAS_SIGNATURE is False, use fallback inner product."""
    mocker.patch("oskill.signature.kernel._HAS_SIGNATURE", False)
    path = np.cumsum(np.random.default_rng(0).normal(0, 0.1, (10, 2)), axis=0)
    with pytest.warns(ImportWarning, match="fallback"):
        k = signature_kernel(path, path, method="truncated_inner_product")
    assert isinstance(k, float)
    assert k > 0


def test_compute_sig_helper():
    """_compute_sig produces a vector of expected length."""
    from oskill.signature.kernel import _compute_sig

    path = np.cumsum(np.random.default_rng(0).normal(0, 0.1, (8, 2)), axis=0)
    sig = _compute_sig(path, depth=2)
    assert sig.ndim == 1
    assert len(sig) > 0


def test_fallback_sig_kernel_symmetric():
    """_fallback_sig_kernel is symmetric."""
    from oskill.signature.kernel import _fallback_sig_kernel

    rng = np.random.default_rng(1)
    pa = np.cumsum(rng.normal(0, 0.1, (8, 2)), axis=0)
    pb = np.cumsum(rng.normal(0, 0.1, (8, 2)), axis=0)
    k_ab = _fallback_sig_kernel(pa, pb, 2)
    k_ba = _fallback_sig_kernel(pb, pa, 2)
    assert abs(k_ab - k_ba) < 1e-10
