"""Gold gate for the deterministic 33-dimension creative audit.

The fixtures under ``tests/fixtures/creative_audit_gold`` are authored by HEVI
(see ``scripts/qualification/build_audit_gold.py``).  This test asserts that the
real audit engine reproduces the gold truth and that the accuracy metrics meet
their thresholds.
"""

from __future__ import annotations

from collections import Counter
from uuid import uuid4

import pytest

from hevi.creative.omodul.audit import ALL_AUDIT_DIMENSIONS, NarrativeAuditEngine
from hevi.creative.omodul.audit_dimensions import (
    HARD_CONTINUITY_DIMENSIONS,
    MODEL_ASSISTED_DIMENSIONS,
    AuditContext,
    DimensionFinding,
    ModelAssistedVerifier,
)
from hevi.creative.omodul.audit_gold import evaluate, load_corpus

CORPUS = load_corpus()


def test_corpus_shape_meets_minimum() -> None:
    assert len(CORPUS) >= 99
    dimensions = {fixture.dimension for fixture in CORPUS}
    assert dimensions == set(ALL_AUDIT_DIMENSIONS)
    counts: dict[str, Counter[str]] = {}
    for fixture in CORPUS:
        counts.setdefault(fixture.dimension, Counter())[fixture.case_type] += 1
    for dimension, counter in counts.items():
        assert counter["POSITIVE"] >= 1, dimension
        assert counter["NEGATIVE"] >= 2, dimension


def test_every_fixture_carries_required_evidence_fields() -> None:
    for fixture in CORPUS:
        assert fixture.fixture_id
        assert fixture.input_artifact is not None
        assert fixture.canon_state is not None
        assert fixture.rationale
        assert len(fixture.expected_severity) == len(fixture.expected_findings)
        assert len(fixture.expected_location) == len(fixture.expected_findings)
        if fixture.expected_findings:
            assert len(fixture.expected_canonical_refs) == len(fixture.expected_findings)


def test_audit_gold_metrics_pass() -> None:
    metrics = evaluate(CORPUS)
    assert metrics.passed, metrics
    assert metrics.true_positive_rate >= 0.95
    assert metrics.hard_continuity_true_positive_rate == 1.0
    assert metrics.false_positive_rate <= 0.05
    assert metrics.location_accuracy >= 0.95
    assert metrics.canon_ref_accuracy >= 0.95
    assert metrics.must_not_find_violations == 0


def test_hard_continuity_dimensions_are_deterministic_and_complete() -> None:
    metrics = evaluate(CORPUS)
    for metric in metrics.per_dimension:
        if metric.dimension in HARD_CONTINUITY_DIMENSIONS:
            assert metric.true_positive_rate == 1.0, metric
            assert metric.false_positive_findings == 0, metric


def test_negative_fixtures_never_trigger_their_own_dimension() -> None:
    engine = NarrativeAuditEngine()
    for fixture in CORPUS:
        if fixture.case_type != "NEGATIVE":
            continue
        audit = engine.audit_context(fixture.context())
        assert not [
            finding for finding in audit.findings if finding.dimension == fixture.dimension
        ], fixture.fixture_id


def test_engine_envelope_status_is_fail_closed() -> None:
    engine = NarrativeAuditEngine()
    defect = next(fixture for fixture in CORPUS if fixture.case_type == "POSITIVE")
    clean = next(
        fixture for fixture in CORPUS if fixture.case_type == "NEGATIVE" and fixture.must_not_find
    )
    assert engine.audit_context(defect.context()).status in {"FAIL", "WARN"}
    assert engine.audit_context(clean.context()).status == "PASS"
    assert defect.context().project_id is not None


def test_model_assisted_verifier_rejects_unstructured_judgements() -> None:
    def invoke(dimension: str, text: str) -> DimensionFinding | None:
        return DimensionFinding(
            dimension=dimension,
            code="DQ_EXPOSITION",
            severity="WARN",
            message="ok",
            recommendation="ok",
            location="sentence:1",
            confidence=0.5,
        )

    verifier = ModelAssistedVerifier(invoke)
    assert verifier.verify("DIALOGUE_QUALITY", "x", evidence_span="span", location="sentence:1")
    with pytest.raises(ValueError):
        verifier.verify("DIALOGUE_QUALITY", "x", evidence_span="", location="sentence:1")
    with pytest.raises(ValueError):
        verifier.verify("DIALOGUE_QUALITY", "x", evidence_span="span", location="")
    with pytest.raises(ValueError):
        verifier.verify("SAFETY", "x", evidence_span="span", location="sentence:1")


def test_model_assisted_verifier_requires_repeatability() -> None:
    calls = {"count": 0}

    def flaky(dimension: str, text: str) -> DimensionFinding | None:
        calls["count"] += 1
        location = "sentence:1" if calls["count"] <= 1 else "sentence:2"
        return DimensionFinding(
            dimension=dimension,
            code="PC_OVERLONG_SENTENCE",
            severity="WARN",
            message="x",
            recommendation="x",
            location=location,
            confidence=0.5,
        )

    verifier = ModelAssistedVerifier(flaky)
    assert (
        verifier.verify("PROSE_CLARITY", "x", evidence_span="span", location="sentence:1") is None
    )


def test_model_assisted_verifier_rejects_evasion_goals() -> None:
    def evasion(dimension: str, text: str) -> DimensionFinding | None:
        return DimensionFinding(
            dimension=dimension,
            code="AI_DETECTOR_EVASION",
            severity="WARN",
            message="x",
            recommendation="x",
            location="sentence:1",
            confidence=0.5,
        )

    with pytest.raises(ValueError):
        ModelAssistedVerifier(evasion).verify(
            "DIALOGUE_QUALITY", "x", evidence_span="span", location="sentence:1"
        )


def test_model_assisted_dimensions_are_declared() -> None:
    assert set(MODEL_ASSISTED_DIMENSIONS).issubset(set(ALL_AUDIT_DIMENSIONS))
    assert len(MODEL_ASSISTED_DIMENSIONS) >= 4


def test_audit_context_uses_the_real_project_identity() -> None:
    project_id = uuid4()
    context = AuditContext(project_id=project_id, artifact_id=uuid4(), text="One clear line.")
    audit = NarrativeAuditEngine().audit_context(context)
    assert audit.project_id == project_id
    assert audit.dimensions_checked == ALL_AUDIT_DIMENSIONS
