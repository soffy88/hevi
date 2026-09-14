"""Evaluation harness for the deterministic 33-dimension audit gold corpus.

The corpus lives in ``tests/fixtures/creative_audit_gold`` and is authored by
HEVI.  Each fixture carries a structured artifact, reconstructed canon state,
and the findings a correct audit must (or must not) produce.  This module turns
fixtures into :class:`~hevi.creative.layer4.audit_dimensions.AuditContext`
objects, runs the real audit engine, and reconciles the observed findings with
the gold truth.

The harness is deliberately independent of the verifier implementation: it only
knows the fixture schema and the public audit envelope, so a regression in a
verifier changes the *result*, not the expectation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from hevi.creative.layer4.audit import NarrativeAuditEngine
from hevi.creative.layer4.audit_dimensions import (
    HARD_CONTINUITY_DIMENSIONS,
    AuditClaim,
    AuditContext,
    AuditState,
    AuthorIntentSpec,
    GenreSpec,
    LengthTarget,
    SceneSpec,
    StyleSpec,
    canonical_ref,
)

DEFAULT_CORPUS_ROOT = Path(__file__).resolve().parents[3] / "tests/fixtures/creative_audit_gold"

#: Acceptance thresholds for the audit gold gate.  Hard continuity dimensions
#: must be found at 100%; the softer craft dimensions are allowed a small margin.
AUDIT_THRESHOLDS: dict[str, float] = {
    "true_positive_rate": 0.95,
    "hard_continuity_true_positive_rate": 1.0,
    "false_positive_rate": 0.05,
    "location_accuracy": 0.95,
    "canon_ref_accuracy": 0.95,
    "must_not_find_violations": 0.0,
}


class AuditGoldFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    dimension: str
    case_type: Literal["POSITIVE", "NEGATIVE"]
    input_artifact: dict[str, Any]
    canon_state: dict[str, Any]
    expected_findings: tuple[dict[str, str], ...] = ()
    expected_severity: tuple[str, ...] = ()
    expected_location: tuple[str | None, ...] = ()
    expected_canonical_refs: tuple[tuple[str, ...], ...] = ()
    must_not_find: tuple[str, ...] = ()
    rationale: str

    def context(self) -> AuditContext:
        artifact = self.input_artifact
        canon = self.canon_state
        return AuditContext(
            project_id=uuid5(NAMESPACE_URL, f"hevi:gold:{self.fixture_id}"),
            artifact_id=uuid5(NAMESPACE_URL, f"hevi:gold:artifact:{self.fixture_id}"),
            text=str(artifact.get("text", "")),
            claims=_claims(artifact.get("claims", [])),
            scenes=_scenes(artifact.get("scenes", [])),
            style=StyleSpec(**artifact["style"]) if artifact.get("style") else None,
            genre=GenreSpec(**artifact["genre"]) if artifact.get("genre") else None,
            author_intent=(
                AuthorIntentSpec(**artifact["author_intent"])
                if artifact.get("author_intent")
                else None
            ),
            length_target=(
                LengthTarget(**artifact["length_target"]) if artifact.get("length_target") else None
            ),
            shot_constraints=tuple(artifact.get("shot_constraints", ())),
            state=AuditState(
                canon_facts=_claims(canon.get("canon_facts", [])),
                known_entities=tuple(canon.get("known_entities", ())),
                hook_deadlines=tuple(
                    (str(item[0]), int(item[1])) for item in canon.get("hook_deadlines", ())
                ),
                payoff_setup_refs=tuple(
                    (str(item[0]), str(item[1])) for item in canon.get("payoff_setup_refs", ())
                ),
            ),
            current_chapter=int(canon.get("current_chapter", 1)),
        )


def _claims(items: Any) -> tuple[AuditClaim, ...]:
    return tuple(
        AuditClaim(
            dimension=str(item["dimension"]),
            subject=str(item["subject"]),
            predicate=str(item["predicate"]),
            value=str(item["value"]),
            location=item.get("location"),
            entity_ref=item.get("entity_ref"),
        )
        for item in items
    )


def _scenes(items: Any) -> tuple[SceneSpec, ...]:
    return tuple(SceneSpec(**item) for item in items)


class DimensionMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    positive_fixtures: int
    negative_fixtures: int
    expected_findings: int
    matched_findings: int
    false_positive_findings: int
    true_positive_rate: float
    hard_continuity: bool


class AuditGoldMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_fixtures: int = Field(ge=0)
    positive_fixtures: int = Field(ge=0)
    negative_fixtures: int = Field(ge=0)
    expected_findings: int = Field(ge=0)
    matched_findings: int = Field(ge=0)
    false_positive_findings: int = Field(ge=0)
    must_not_find_violations: int = Field(ge=0)
    location_total: int = Field(ge=0)
    location_hits: int = Field(ge=0)
    canon_ref_total: int = Field(ge=0)
    canon_ref_hits: int = Field(ge=0)
    true_positive_rate: float = Field(ge=0.0, le=1.0)
    hard_continuity_true_positive_rate: float = Field(ge=0.0, le=1.0)
    false_positive_rate: float = Field(ge=0.0, le=1.0)
    location_accuracy: float = Field(ge=0.0, le=1.0)
    canon_ref_accuracy: float = Field(ge=0.0, le=1.0)
    per_dimension: tuple[DimensionMetric, ...] = ()
    thresholds: dict[str, float] = Field(default_factory=lambda: dict(AUDIT_THRESHOLDS))
    passed: bool

    @property
    def dimension_count(self) -> int:
        return len(self.per_dimension)


def load_corpus(root: Path | None = None) -> tuple[AuditGoldFixture, ...]:
    corpus_root = root or DEFAULT_CORPUS_ROOT
    fixtures: list[AuditGoldFixture] = []
    for path in sorted(corpus_root.glob("*.json")):
        if path.name.startswith("_"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"gold corpus file must contain a list: {path}")
        fixtures.extend(AuditGoldFixture(**item) for item in payload)
    return tuple(fixtures)


def _fixture_evidence(
    fixture: AuditGoldFixture, engine: NarrativeAuditEngine
) -> tuple[tuple[str, str, str | None, tuple[UUID, ...]], ...]:
    audit = engine.audit_context(fixture.context())
    return tuple(
        (finding.dimension, finding.code or "", finding.artifact_location, finding.canonical_refs)
        for finding in audit.findings
    )


def evaluate(
    fixtures: tuple[AuditGoldFixture, ...] | None = None,
    *,
    root: Path | None = None,
) -> AuditGoldMetrics:
    corpus = fixtures if fixtures is not None else load_corpus(root)
    engine = NarrativeAuditEngine()
    expected_total = 0
    matched_total = 0
    false_positive_total = 0
    must_not_find_violations = 0
    location_total = 0
    location_hits = 0
    canon_ref_total = 0
    canon_ref_hits = 0
    hard_expected = 0
    hard_matched = 0
    per_dimension: list[DimensionMetric] = []

    by_dimension: dict[str, list[AuditGoldFixture]] = {}
    for fixture in corpus:
        by_dimension.setdefault(fixture.dimension, []).append(fixture)

    for dimension, items in by_dimension.items():
        dim_expected = 0
        dim_matched = 0
        dim_false_positive = 0
        for fixture in items:
            observed = _fixture_evidence(fixture, engine)
            expected_keys = {
                (item["dimension"], item["code"]) for item in fixture.expected_findings
            }
            observed_keys = {(dim, code) for dim, code, _, _ in observed}
            dim_expected += len(expected_keys)
            for index, item in enumerate(fixture.expected_findings):
                key = (item["dimension"], item["code"])
                match = next(
                    (record for record in observed if (record[0], record[1]) == key),
                    None,
                )
                if match is None:
                    continue
                dim_matched += 1
                expected_location = (
                    fixture.expected_location[index]
                    if index < len(fixture.expected_location)
                    else None
                )
                if expected_location is not None:
                    location_total += 1
                    if match[2] == expected_location:
                        location_hits += 1
                if index < len(fixture.expected_canonical_refs):
                    refs = fixture.expected_canonical_refs[index]
                    if refs:
                        canon_ref_total += 1
                        expected_uuids = {canonical_ref(ref) for ref in refs}
                        if expected_uuids.issubset(set(match[3])):
                            canon_ref_hits += 1
            dim_false_positive += len(observed_keys - expected_keys)
            for token in fixture.must_not_find:
                if any(
                    token in {record[1], record[0]} or record[1].startswith(token)
                    for record in observed
                ):
                    must_not_find_violations += 1
        expected_total += dim_expected
        matched_total += dim_matched
        false_positive_total += dim_false_positive
        if dimension in HARD_CONTINUITY_DIMENSIONS:
            hard_expected += dim_expected
            hard_matched += dim_matched
        positives = sum(1 for item in items if item.case_type == "POSITIVE")
        negatives = sum(1 for item in items if item.case_type == "NEGATIVE")
        per_dimension.append(
            DimensionMetric(
                dimension=dimension,
                positive_fixtures=positives,
                negative_fixtures=negatives,
                expected_findings=dim_expected,
                matched_findings=dim_matched,
                false_positive_findings=dim_false_positive,
                true_positive_rate=dim_matched / dim_expected if dim_expected else 1.0,
                hard_continuity=dimension in HARD_CONTINUITY_DIMENSIONS,
            )
        )

    true_positive_rate = matched_total / expected_total if expected_total else 1.0
    hard_rate = hard_matched / hard_expected if hard_expected else 1.0
    denominator = expected_total + false_positive_total
    false_positive_rate = false_positive_total / denominator if denominator else 0.0
    location_accuracy = location_hits / location_total if location_total else 1.0
    canon_ref_accuracy = canon_ref_hits / canon_ref_total if canon_ref_total else 1.0
    passed = (
        true_positive_rate >= AUDIT_THRESHOLDS["true_positive_rate"]
        and hard_rate >= AUDIT_THRESHOLDS["hard_continuity_true_positive_rate"]
        and false_positive_rate <= AUDIT_THRESHOLDS["false_positive_rate"]
        and location_accuracy >= AUDIT_THRESHOLDS["location_accuracy"]
        and canon_ref_accuracy >= AUDIT_THRESHOLDS["canon_ref_accuracy"]
        and must_not_find_violations <= int(AUDIT_THRESHOLDS["must_not_find_violations"])
    )
    return AuditGoldMetrics(
        total_fixtures=len(corpus),
        positive_fixtures=sum(1 for item in corpus if item.case_type == "POSITIVE"),
        negative_fixtures=sum(1 for item in corpus if item.case_type == "NEGATIVE"),
        expected_findings=expected_total,
        matched_findings=matched_total,
        false_positive_findings=false_positive_total,
        must_not_find_violations=must_not_find_violations,
        location_total=location_total,
        location_hits=location_hits,
        canon_ref_total=canon_ref_total,
        canon_ref_hits=canon_ref_hits,
        true_positive_rate=round(true_positive_rate, 6),
        hard_continuity_true_positive_rate=round(hard_rate, 6),
        false_positive_rate=round(false_positive_rate, 6),
        location_accuracy=round(location_accuracy, 6),
        canon_ref_accuracy=round(canon_ref_accuracy, 6),
        per_dimension=tuple(per_dimension),
        passed=passed,
    )


__all__ = [
    "AUDIT_THRESHOLDS",
    "DEFAULT_CORPUS_ROOT",
    "AuditGoldFixture",
    "AuditGoldMetrics",
    "DimensionMetric",
    "evaluate",
    "load_corpus",
]
