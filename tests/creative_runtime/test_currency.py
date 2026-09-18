"""W2 gates: explicit 4-state currency, scoped invalidation, paid preservation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hevi.creative.layer4.currency import (
    ArtifactBasis,
    ArtifactCurrency,
    CurrencyError,
    CurrencyEvaluation,
    annotate_selections,
    assert_no_usable_loss,
    evaluate_all,
    evaluate_currency,
    invalidate_dependents,
)


def _basis(artifact_id: str = "vid-1", role: str = "final_video", **kw) -> ArtifactBasis:
    args: dict = {"dependency_revision": "graph@7", **kw}
    return ArtifactBasis(artifact_id=artifact_id, role=role, **args)


def test_current_when_provenance_matches() -> None:
    evaluation = evaluate_currency(_basis(), {"graph": "7"})
    assert evaluation.currency is ArtifactCurrency.CURRENT
    assert evaluation.usable is True
    assert evaluation.blocking_reason is None


def test_only_four_states_exist() -> None:
    assert {state.value for state in ArtifactCurrency} == {"current", "stale", "missing", "blocked"}


CURRENT_DEPS = {"graph": "7", "prompt": "1", "appearance": "a1", "voice": "v1", "subs": "s1"}


def _change_matrix() -> list[tuple[str, ArtifactBasis]]:
    """Fault injection: every upstream change class lands on STALE, never CURRENT.

    Callers must declare the full gating set; anything undeclared cannot
    flip currency (same contract as the presentation selector).
    """

    return [
        ("prompt change", _basis(dependency_revision="graph@7+prompt@2")),
        ("character change", _basis(dependency_revision="graph@7+appearance@a2")),
        ("voice change", _basis(dependency_revision="graph@7+voice@v2")),
        ("subtitle change", _basis(dependency_revision="graph@7+subs@s2")),
        ("manual replacement", _basis(dependency_revision="manual@user")),
        ("old selected version", _basis(dependency_revision="graph@6")),
    ]


@pytest.mark.parametrize("name,basis", _change_matrix())
def test_gate_false_current_zero(name: str, basis: ArtifactBasis) -> None:
    """FALSE_CURRENT=0: moved dependencies can never evaluate CURRENT."""

    evaluation = evaluate_currency(basis, CURRENT_DEPS)
    assert evaluation.currency is not ArtifactCurrency.CURRENT, name
    assert evaluation.currency is ArtifactCurrency.STALE, name
    assert evaluation.usable is True, name  # stale stays usable


def test_composite_revision_matches_when_all_gated_keys_agree() -> None:
    evaluation = evaluate_currency(
        _basis(dependency_revision="graph@7+prompt@1"), {"graph": "7", "prompt": "1"}
    )
    assert evaluation.currency is ArtifactCurrency.CURRENT


def test_failed_regeneration_keeps_old_usable() -> None:
    before = evaluate_all((_basis(),), {"graph": "7"})
    # regeneration produced nothing usable for the role: only a missing entry
    after = evaluate_all((_basis(exists=False, integrity_ok=False),), {"graph": "7"})
    assert after[0].currency is ArtifactCurrency.MISSING
    with pytest.raises(CurrencyError, match="CURRENCY_LOST_VALID_ARTIFACT:final_video"):
        assert_no_usable_loss(before, after, ("final_video",))


def test_gate_lost_valid_artifact_zero() -> None:
    """LOST_VALID_ARTIFACT=0: annotate path never drops entries."""

    first = evaluate_all((_basis("a"), _basis("b", role="tts")), {"graph": "7"})
    second = evaluate_all(
        (_basis("a", dependency_revision="graph@8"), _basis("b", role="tts")),
        {"graph": "7"},
    )
    assert_no_usable_loss(first, second, ("final_video", "tts"))
    annotated = annotate_selections(second)
    assert set(annotated) == {"a", "b"}
    assert annotated["a"]["currency"] == "stale"


def test_deleted_upstream_asset_is_blocked_not_missing() -> None:
    evaluation = evaluate_currency(
        _basis(
            basis_readable=False,
            basis_read_failure="appearance ref deleted upstream",
            blocking_reason="character appearance asset deleted",
            repair_action="restore appearance asset or rebind character, then regenerate explicitly",
        ),
        {"graph": "7"},
    )
    assert evaluation.currency is ArtifactCurrency.BLOCKED
    assert evaluation.blocking_reason == "character appearance asset deleted"
    assert "regenerate explicitly" in (evaluation.repair_action or "")
    assert evaluation.usable is False


def test_blocked_requires_reason_and_repair() -> None:
    with pytest.raises(ValidationError, match="CURRENCY_BLOCKED_NEEDS_REASON_AND_REPAIR"):
        CurrencyEvaluation(artifact_id="x", role="y", currency=ArtifactCurrency.BLOCKED, reason="r")
    with pytest.raises(ValidationError, match="CURRENCY_ONLY_BLOCKED_CARRIES_BLOCKING_REASON"):
        CurrencyEvaluation(
            artifact_id="x",
            role="y",
            currency=ArtifactCurrency.CURRENT,
            reason="r",
            blocking_reason="stray",
        )


def test_missing_only_when_needed() -> None:
    missing = evaluate_currency(_basis(exists=False, integrity_ok=False), {"graph": "7"})
    assert missing.currency is ArtifactCurrency.MISSING
    unneeded = evaluate_currency(
        _basis(exists=False, integrity_ok=False, needed=False), {"graph": "7"}
    )
    assert unneeded.currency is ArtifactCurrency.STALE  # prior record retained, not deleted
    assert_no_usable_loss((unneeded,), (unneeded,), ("final_video",))


def test_invalidation_is_scoped_not_project_wide() -> None:
    edges = (
        ("board-1", "appearance:anna"),
        ("clip-1", "appearance:anna"),
        ("present-1", "clip-1"),
        ("board-9", "appearance:bob"),
        ("clip-9", "appearance:bob"),
    )
    affected = invalidate_dependents(("appearance:anna",), edges)
    assert affected == ("board-1", "clip-1")
    assert invalidate_dependents((), edges) == ()
    assert invalidate_dependents(("appearance:nobody",), edges) == ()


def test_evaluate_all_judges_every_entry() -> None:
    evaluations = evaluate_all(
        (
            _basis("ok"),
            _basis("old", dependency_revision="graph@6"),
            _basis("gone", exists=False, integrity_ok=False),
        ),
        {"graph": "7"},
    )
    assert [e.currency for e in evaluations] == [
        ArtifactCurrency.CURRENT,
        ArtifactCurrency.STALE,
        ArtifactCurrency.MISSING,
    ]


def test_stale_is_first_class_for_preview_export_inspect() -> None:
    evaluation = evaluate_currency(_basis(dependency_revision="graph@8"), {"graph": "7"})
    annotated = annotate_selections((evaluation,))
    assert annotated["vid-1"]["currency"] == "stale"
    assert "explicit reuse or regenerate" in (annotated["vid-1"]["reason"] or "")


def test_no_fuzzy_fifth_state_constructible() -> None:
    with pytest.raises(ValidationError):
        CurrencyEvaluation(
            artifact_id="x",
            role="y",
            currency="unknown_current",
            reason="r",  # type: ignore[arg-type]
        )
