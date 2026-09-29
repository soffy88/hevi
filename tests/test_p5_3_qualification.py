"""HEVI P5.3 — qualification, promotion, and deprecation tests."""

from __future__ import annotations

from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.qualification import (
    can_promote,
    deprecate_recipe,
    is_stale_qualification_evidence,
    promote_recipe,
    qualification_summary,
)
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.schema import DeprecationReason, QualificationEvidence, QualificationState


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def test_cannot_promote_without_usage() -> None:
    lib = _lib()
    eligible, _reason = can_promote(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")
    assert eligible is False
    assert "INSUFFICIENT_USAGE" in _reason


def test_cannot_promote_with_failures() -> None:
    lib = _lib()
    lib.record_outcome("COMPOSITION.CENTERED_HERO", "1.0.0", {"status": "FAIL"})
    lib.record_outcome("COMPOSITION.CENTERED_HERO", "1.0.0", {"status": "PASS"})
    lib.record_outcome("COMPOSITION.CENTERED_HERO", "1.0.0", {"status": "PASS"})
    eligible, _reason = can_promote(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")
    assert eligible is False
    assert "HARD_FAILURES" in _reason


def test_can_promote_with_sufficient_usage() -> None:
    lib = _lib()
    for _ in range(3):
        lib.record_outcome("COMPOSITION.CENTERED_HERO", "1.0.0", {"status": "PASS"})
    eligible, _reason = can_promote(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")
    assert eligible is True


def test_promote_recipe() -> None:
    lib = _lib()
    for _ in range(3):
        lib.record_outcome("COMPOSITION.CENTERED_HERO", "1.0.0", {"status": "PASS"})
    success, _msg = promote_recipe(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")
    assert success is True
    assert lib.get_version("COMPOSITION.CENTERED_HERO", "1.0.0").qualification_state is QualificationState.QUALIFIED


def test_deprecate_recipe() -> None:
    lib = _lib()
    success, _msg = deprecate_recipe(
        lib, "COMPOSITION.CENTERED_HERO", "1.0.0", DeprecationReason.OVERUSE
    )
    assert success is True
    assert lib.get_version("COMPOSITION.CENTERED_HERO", "1.0.0").qualification_state is QualificationState.DEPRECATED


def test_stale_qualification_evidence() -> None:
    e = QualificationEvidence(usage_count=0)
    assert is_stale_qualification_evidence(e) is True
    e2 = QualificationEvidence(usage_count=5)
    assert is_stale_qualification_evidence(e2) is False


def test_qualification_summary() -> None:
    lib = _lib()
    summary = qualification_summary(lib)
    assert summary["total"] == lib.stats().total_recipes
    assert summary["experimental"] > 0


def test_no_self_promotion() -> None:
    """A recipe cannot promote itself; promotion requires external evidence."""
    lib = _lib()
    # Even with outcomes, the recipe must be EXPERIMENTAL to promote
    for _ in range(5):
        lib.record_outcome("COMPOSITION.CENTERED_HERO", "1.0.0", {"status": "PASS"})
    promote_recipe(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")
    # Now it's QUALIFIED, so can_promote should fail
    eligible, _reason = can_promote(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")
    assert eligible is False
    assert "NOT_EXPERIMENTAL" in _reason
