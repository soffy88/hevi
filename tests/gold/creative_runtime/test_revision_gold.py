"""Gold gate for the bounded revision workflow and canon safety."""

from __future__ import annotations

from uuid import uuid4

import pytest

from hevi.creative.omodul.revision import (
    RevisionEngine,
    RevisionLimitError,
    RevisionPolicy,
)
from hevi.creative.omodul.revision_gold import run_revision_gold

RESULT = run_revision_gold()


def test_all_revision_gold_checks_pass() -> None:
    assert RESULT.passed, RESULT.checks
    assert all(RESULT.checks.values()), {
        name: value for name, value in RESULT.checks.items() if not value
    }


def test_seven_scenarios_cover_four_change_types() -> None:
    assert len(RESULT.scenarios) == 7
    change_types = {scenario.change_type for scenario in RESULT.scenarios}
    assert {"POLISH", "SPOT_FIX", "REWRITE", "STRUCTURAL_REWORK"}.issubset(change_types)


def test_resolved_findings_have_operations_and_disappear() -> None:
    for scenario in RESULT.scenarios:
        if not scenario.resolved:
            continue
        assert scenario.diff_present, scenario.name
        assert scenario.trace_complete, scenario.name
        assert not (set(scenario.resolved) & set(scenario.re_audit_codes)), scenario.name


def test_unresolved_findings_are_preserved() -> None:
    multiple = next(item for item in RESULT.scenarios if item.name == "multiple_independent")
    assert "SAF_UNSAFE_CONTENT" in multiple.unresolved
    assert "SAF_UNSAFE_CONTENT" in multiple.re_audit_codes


def test_conflicting_issues_are_held_not_oscillated() -> None:
    conflicting = next(item for item in RESULT.scenarios if item.name == "conflicting")
    assert conflicting.conflict
    assert conflicting.passes == 1
    assert conflicting.resolved == ()


def test_canon_sensitive_issue_is_aligned_not_mutated() -> None:
    canon = next(item for item in RESULT.scenarios if item.name == "canon_sensitive")
    assert "CC_CONFLICT" in canon.resolved
    assert canon.re_audit_codes == ()
    assert RESULT.checks["REJECT_NO_CANON_MUTATION"]
    assert RESULT.checks["APPROVE_ATOMIC_COMMIT"]


def test_original_hash_is_preserved_before_commit() -> None:
    for scenario in RESULT.scenarios:
        assert scenario.original_hash_preserved, scenario.name


def test_iteration_bound_is_enforced() -> None:
    engine = RevisionEngine(RevisionPolicy(max_passes=1))
    with pytest.raises(RevisionLimitError):
        engine.candidate(project_id=uuid4(), asset_id=uuid4(), base_revision=0, pass_number=2)
