"""HEVI P5.3 — metrics tests: coverage, diversity, qualification counts."""

from __future__ import annotations

from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.metrics import compute_metrics
from hevi.production.p5_3.recipes import load_all_recipes


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def test_recipe_coverage_is_full() -> None:
    lib = _lib()
    metrics = compute_metrics(lib)
    assert metrics["RECIPE_COVERAGE"] == 1.0


def test_family_diversity_is_nonzero() -> None:
    lib = _lib()
    metrics = compute_metrics(lib)
    assert metrics["RECIPE_FAMILY_DIVERSITY"] > 0.0


def test_qualified_count_initially_zero() -> None:
    lib = _lib()
    metrics = compute_metrics(lib)
    assert metrics["QUALIFIED_RECIPE_COUNT"] == 0
    assert metrics["EXPERIMENTAL_RECIPE_COUNT"] > 0


def test_reference_derived_count() -> None:
    lib = _lib()
    metrics = compute_metrics(lib)
    # Initially all recipes are hand_crafted, so reference_derived is 0
    assert metrics["REFERENCE_DERIVED_RECIPE_COUNT"] == 0


def test_p5_1_rates_not_measurable() -> None:
    """P5.1 blocked: rates must be NOT_MEASURABLE, not 0."""
    lib = _lib()
    metrics = compute_metrics(lib)
    assert metrics["P5_1_ACCEPT_RATE"] == "NOT_MEASURABLE"
    assert metrics["P5_1_REJECT_RATE"] == "NOT_MEASURABLE"


def test_repetition_rate_initially_zero() -> None:
    lib = _lib()
    metrics = compute_metrics(lib)
    assert metrics["RECIPE_REPETITION_RATE"] == 0.0
