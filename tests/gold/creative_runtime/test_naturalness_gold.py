"""Gold gate for the synthetic-writing naturalness corpus (11 defect classes)."""

from __future__ import annotations

import pytest

from hevi.creative.omodul.naturalness_gold import evaluate, load_corpus
from hevi.creative.omodul.style import (
    EMPTY_INTENSIFIERS,
    FORBIDDEN_EVASION_GOALS,
    StyleModule,
)

CORPUS = load_corpus()
EXPECTED_CLASSES = {
    "REPETITIVE_PHRASE",
    "TEMPLATE_CADENCE",
    "GENERIC_TRANSITION",
    "EMPTY_INTENSIFIER",
    "SEMANTIC_REPETITION",
    "UNNATURAL_DIALOGUE",
    "OVER_EXPLANATION",
    "CLICHE_DENSITY",
    "STYLE_DRIFT",
    "PARAGRAPH_MONOTONY",
    "SYNTACTIC_MONOTONY",
}


def test_corpus_covers_all_classes_with_controls() -> None:
    classes = {fixture.defect_class for fixture in CORPUS}
    assert classes == EXPECTED_CLASSES
    for defect_class in EXPECTED_CLASSES:
        positives = [
            fixture
            for fixture in CORPUS
            if fixture.defect_class == defect_class and fixture.case_type == "POSITIVE"
        ]
        negatives = [
            fixture
            for fixture in CORPUS
            if fixture.defect_class == defect_class and fixture.case_type == "NEGATIVE"
        ]
        assert len(positives) >= 2, defect_class
        assert len(negatives) >= 2, defect_class
        assert all(fixture.expected_codes for fixture in positives), defect_class


def test_naturalness_gold_metrics_pass() -> None:
    metrics = evaluate(CORPUS)
    assert metrics.passed
    assert metrics.detection_rate >= 0.95
    assert metrics.false_positive_rate <= 0.05
    assert metrics.location_accuracy >= 0.90
    assert metrics.revision_improvement_rate >= 0.95


def test_every_positive_is_detected_with_a_location() -> None:
    module = StyleModule()
    for fixture in CORPUS:
        if fixture.case_type != "POSITIVE":
            continue
        audit = module.audit_naturalness(fixture.text, style_profile=fixture.profile())
        codes = {finding.code for finding in audit.findings}
        assert set(fixture.expected_codes).issubset(codes), fixture.fixture_id
        primary = next(
            finding for finding in audit.findings if finding.code in fixture.expected_codes
        )
        assert primary.location == fixture.expected_location, fixture.fixture_id
        assert primary.explanation, fixture.fixture_id


def test_every_positive_improves_after_revision() -> None:
    module = StyleModule()
    for fixture in CORPUS:
        if fixture.case_type != "POSITIVE":
            continue
        audit = module.audit_naturalness(fixture.text, style_profile=fixture.profile())
        revision = module.revise_naturalness(fixture.text, audit)
        assert revision.operations, fixture.fixture_id
        after = module.audit_naturalness(revision.revised_text, style_profile=fixture.profile())
        codes = {finding.code for finding in after.findings}
        assert not (set(fixture.expected_codes) & codes), fixture.fixture_id


def test_clean_text_has_no_findings() -> None:
    audit = StyleModule().audit_naturalness("The bell rings once.")
    assert audit.status == "PASS"
    assert audit.findings == ()


def test_no_evasion_goal_is_implemented() -> None:
    assert "AI_DETECTOR_EVASION" not in dir(StyleModule)
    assert "humanize" not in dir(StyleModule)
    module = StyleModule()
    audit = module.audit_naturalness("It was very very very just.")
    assert not (set(FORBIDDEN_EVASION_GOALS) & {finding.code for finding in audit.findings})


@pytest.mark.parametrize("intensifier", EMPTY_INTENSIFIERS)
def test_each_intensifier_is_detected(intensifier: str) -> None:
    audit = StyleModule().audit_naturalness(f"It was {intensifier} cold.")
    assert any(finding.code == "EMPTY_INTENSIFIER" for finding in audit.findings)
