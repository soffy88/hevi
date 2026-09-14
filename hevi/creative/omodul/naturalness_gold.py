"""Gold evaluation for the synthetic-writing naturalness corpus.

The corpus at ``tests/fixtures/writing_naturalness`` is authored by HEVI.  Each
fixture is a real passage plus the defect classes a correct auditor must (or must
not) report.  The harness also applies the deterministic quality-only revision
and verifies the defect disappears from the repaired draft.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hevi.creative.omodul.style import StyleModule
from hevi.obase.creative import StyleProfile

DEFAULT_CORPUS_ROOT = (
    Path(__file__).resolve().parents[3] / "tests/fixtures/writing_naturalness"
)

_NS: UUID = UUID("00000000-0000-0000-0000-0000000000aa")

NATURALNESS_THRESHOLDS: dict[str, float] = {
    "detection_rate": 0.95,
    "false_positive_rate": 0.05,
    "location_accuracy": 0.90,
    "revision_improvement_rate": 0.95,
}


class NaturalnessGoldFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    defect_class: str
    case_type: Literal["POSITIVE", "NEGATIVE"]
    text: str
    style_profile: dict[str, Any] | None = None
    expected_codes: tuple[str, ...] = ()
    expected_location: str | None = None
    must_not_find: tuple[str, ...] = ()
    rationale: str

    def profile(self) -> StyleProfile | None:
        if self.style_profile is None:
            return None
        sentence_length = self.style_profile.get("sentence_length")
        return StyleProfile(
            project_id=_NS,
            name="gold-style",
            sentence_length=str(sentence_length) if sentence_length is not None else None,
            dialogue_ratio=self.style_profile.get("dialogue_ratio"),
        )


class NaturalnessGoldMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_fixtures: int = Field(ge=0)
    positive_fixtures: int = Field(ge=0)
    negative_fixtures: int = Field(ge=0)
    detected: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    location_total: int = Field(ge=0)
    location_hits: int = Field(ge=0)
    revision_total: int = Field(ge=0)
    revision_improved: int = Field(ge=0)
    detection_rate: float = Field(ge=0.0, le=1.0)
    false_positive_rate: float = Field(ge=0.0, le=1.0)
    location_accuracy: float = Field(ge=0.0, le=1.0)
    revision_improvement_rate: float = Field(ge=0.0, le=1.0)
    thresholds: dict[str, float] = Field(default_factory=lambda: dict(NATURALNESS_THRESHOLDS))
    passed: bool


def load_corpus(root: Path | None = None) -> tuple[NaturalnessGoldFixture, ...]:
    corpus_root = root or DEFAULT_CORPUS_ROOT
    fixtures: list[NaturalnessGoldFixture] = []
    for path in sorted(corpus_root.glob("*.json")):
        if path.name.startswith("_"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"corpus file must contain a list: {path}")
        fixtures.extend(NaturalnessGoldFixture(**item) for item in payload)
    return tuple(fixtures)


def evaluate(
    fixtures: tuple[NaturalnessGoldFixture, ...] | None = None,
    *,
    root: Path | None = None,
) -> NaturalnessGoldMetrics:
    corpus = fixtures if fixtures is not None else load_corpus(root)
    module = StyleModule()
    positive_total = 0
    negative_total = 0
    detected = 0
    false_positives = 0
    location_total = 0
    location_hits = 0
    revision_total = 0
    revision_improved = 0
    for fixture in corpus:
        profile = fixture.profile()
        audit = module.audit_naturalness(fixture.text, style_profile=profile)
        codes = {finding.code for finding in audit.findings}
        expected = set(fixture.expected_codes)
        if fixture.case_type == "POSITIVE":
            positive_total += 1
            if expected.issubset(codes) and not (set(fixture.must_not_find) & codes):
                detected += 1
            if fixture.expected_location is not None and fixture.expected_codes:
                location_total += 1
                primary = next(
                    (
                        finding
                        for finding in audit.findings
                        if finding.code == fixture.expected_codes[0]
                    ),
                    None,
                )
                if primary is not None and primary.location == fixture.expected_location:
                    location_hits += 1
            revision_total += 1
            revision = module.revise_naturalness(fixture.text, audit)
            repaired = module.audit_naturalness(revision.revised_text, style_profile=profile)
            repaired_codes = {finding.code for finding in repaired.findings}
            if not (expected & repaired_codes):
                revision_improved += 1
        else:
            negative_total += 1
            if fixture.defect_class in codes or (set(fixture.must_not_find) & codes):
                false_positives += 1
    detection_rate = detected / positive_total if positive_total else 1.0
    false_positive_rate = false_positives / negative_total if negative_total else 0.0
    location_accuracy = location_hits / location_total if location_total else 1.0
    revision_rate = revision_improved / revision_total if revision_total else 1.0
    passed = (
        detection_rate >= NATURALNESS_THRESHOLDS["detection_rate"]
        and false_positive_rate <= NATURALNESS_THRESHOLDS["false_positive_rate"]
        and location_accuracy >= NATURALNESS_THRESHOLDS["location_accuracy"]
        and revision_rate >= NATURALNESS_THRESHOLDS["revision_improvement_rate"]
    )
    return NaturalnessGoldMetrics(
        total_fixtures=len(corpus),
        positive_fixtures=positive_total,
        negative_fixtures=negative_total,
        detected=detected,
        false_positives=false_positives,
        location_total=location_total,
        location_hits=location_hits,
        revision_total=revision_total,
        revision_improved=revision_improved,
        detection_rate=round(detection_rate, 6),
        false_positive_rate=round(false_positive_rate, 6),
        location_accuracy=round(location_accuracy, 6),
        revision_improvement_rate=round(revision_rate, 6),
        passed=passed,
    )


__all__ = [
    "DEFAULT_CORPUS_ROOT",
    "NATURALNESS_THRESHOLDS",
    "NaturalnessGoldFixture",
    "NaturalnessGoldMetrics",
    "evaluate",
    "load_corpus",
]
