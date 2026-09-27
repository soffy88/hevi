"""HEVI P5.1 — editorial diagnosis and targeted repair mapping.

A ``VideoReview`` never modifies a video. It is converted into an
:class:`EditorialDiagnosis`, which deduplicates issues, maps each one onto the
canonical artifact that actually causes it, decides whether it is repairable,
and estimates the repair scope. Only then may a ``RepairIntent`` exist — and
with no ``RepairIntent`` there is no autonomous revision.

Root-cause discipline (§30): "the caption covers the subject" maps onto
``CAPTION_STYLE``; "the wrong product screenshot" maps onto ``EVIDENCE_ASSET``;
"the shot is too long" maps onto ``SHOT_PLAN``; "the visual misses the emotion"
maps onto ``VISUAL_BEAT`` / asset selection. It never maps onto "regenerate the
whole video".

Targeted repair (§32, §34): the plan reuses P3's DAG-scoped ``RepairPlan`` and
its ``rerun_nodes`` / ``preserve_artifact_ids`` split, so a three-second defect
re-runs the affected shot and re-assembles the master, and does not re-run
research, unaffected TTS, or unaffected shots. ``UNAFFECTED_SOURCE_RERUNS == 0``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from hevi.execution.plan import RepairPlan
from hevi.ops.p5_1_types import (
    AUTONOMOUS_REPAIR_SEVERITIES,
    GLOBAL_ISSUE_CATEGORIES,
    ROOT_CAUSE_MAP,
    CanonicalArtifact,
    DefectClass,
    DiagnosisFinding,
    EditableLayer,
    EditorialDiagnosis,
    EditorialIssue,
    EditorialIssueCategory,
    IssueSeverity,
    RepairIntent,
    RepairScope,
    VideoReview,
    classify_defect,
)

# ── Root cause narratives (§30) ──────────────────────────────────────────

ROOT_CAUSE_TEXT: dict[CanonicalArtifact, str] = {
    CanonicalArtifact.CAPTION_STYLE: (
        "caption placement/priority collides with the subject, so the caption layer "
        "and the shot layout must change rather than the footage"
    ),
    CanonicalArtifact.EVIDENCE_ASSET: (
        "the evidence bound to this claim is wrong, missing, or not provably real, so "
        "the EvidenceAsset selection must change rather than the shot"
    ),
    CanonicalArtifact.SHOT_PLAN: (
        "the shot boundary and length in the plan do not serve this beat, so the "
        "ShotPlan timeline must change rather than the sources"
    ),
    CanonicalArtifact.VISUAL_BEAT: (
        "the beat's visual specification is wrong for its narration, so the VisualBeat "
        "must change rather than the render"
    ),
    CanonicalArtifact.MOTION_PLAN: (
        "the motion specification does not serve a semantic purpose here, so the "
        "MotionPlan must change rather than adding more movement"
    ),
    CanonicalArtifact.ASSET_SELECTION: (
        "the chosen visual does not carry the intended meaning, so asset selection for "
        "this beat must change"
    ),
    CanonicalArtifact.AUDIO_MIX: (
        "the audio bed and the picture disagree, so the audio mix must change"
    ),
    CanonicalArtifact.PROFILE_DIRECTION: (
        "the cut contradicts the profile's creative direction, so the profile direction "
        "for this production must change"
    ),
    CanonicalArtifact.NONE: "no canonical artifact maps to this observation",
}

#: Canonical artifact -> default repair scope.
ARTIFACT_SCOPE: dict[CanonicalArtifact, RepairScope] = {
    CanonicalArtifact.EVIDENCE_ASSET: RepairScope.ASSET_ONLY,
    CanonicalArtifact.ASSET_SELECTION: RepairScope.ASSET_ONLY,
    CanonicalArtifact.CAPTION_STYLE: RepairScope.CAPTION_RANGE,
    CanonicalArtifact.SHOT_PLAN: RepairScope.TIMELINE_RANGE,
    CanonicalArtifact.VISUAL_BEAT: RepairScope.SHOT_ONLY,
    CanonicalArtifact.MOTION_PLAN: RepairScope.MOTION_RANGE,
    CanonicalArtifact.AUDIO_MIX: RepairScope.AUDIO_MIX_RANGE,
    CanonicalArtifact.PROFILE_DIRECTION: RepairScope.GLOBAL,
    CanonicalArtifact.NONE: RepairScope.GLOBAL,
}

#: How expensive each scope is expected to be, used for the intent's estimate.
SCOPE_COST: dict[RepairScope, float] = {
    RepairScope.ASSET_ONLY: 0.05,
    RepairScope.SHOT_ONLY: 0.35,
    RepairScope.CAPTION_RANGE: 0.08,
    RepairScope.MOTION_RANGE: 0.12,
    RepairScope.AUDIO_MIX_RANGE: 0.10,
    RepairScope.TIMELINE_RANGE: 0.40,
    RepairScope.MULTI_SHOT: 0.90,
    RepairScope.GLOBAL: 2.50,
}

SCOPE_RISK: dict[RepairScope, str] = {
    RepairScope.ASSET_ONLY: "LOW",
    RepairScope.CAPTION_RANGE: "LOW",
    RepairScope.MOTION_RANGE: "LOW",
    RepairScope.AUDIO_MIX_RANGE: "LOW",
    RepairScope.SHOT_ONLY: "MEDIUM",
    RepairScope.TIMELINE_RANGE: "MEDIUM",
    RepairScope.MULTI_SHOT: "MEDIUM",
    RepairScope.GLOBAL: "HIGH",
}


# ── Shot timeline (for timestamp validation, adversarial A3) ─────────────


@dataclass
class ShotSpan:
    """One shot on the real timeline, used to validate issue timestamps."""

    shot_id: str
    beat_id: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def contains(self, at_ms: int) -> bool:
        return self.start_ms <= at_ms < self.end_ms

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LocationCheck:
    """Whether an issue's timestamps can be trusted to target a repair."""

    ok: bool = False
    reason: str = ""
    shot: ShotSpan | None = None
    shots: list[ShotSpan] = field(default_factory=list)

    @property
    def multi_shot(self) -> bool:
        return len({s.shot_id for s in self.shots}) > 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["shot"] = self.shot.to_dict() if self.shot else None
        d["shots"] = [s.to_dict() for s in self.shots]
        return d


def validate_issue_location(
    issue: EditorialIssue,
    shots: list[ShotSpan],
    *,
    duration_ms: int,
) -> LocationCheck:
    """Validate that an issue's time range lands on a real shot.

    A reviewer that reports a plausible-looking timestamp outside the video, or
    inside a gap that no shot occupies, must not be allowed to drive a targeted
    repair. This is the ``A3`` guard: a wrong timestamp produces no unsafe
    repair, it produces a *rejected* repair.
    """
    if issue.category in GLOBAL_ISSUE_CATEGORIES or issue.global_scope:
        return LocationCheck(ok=True, reason="GLOBAL_SCOPE", shot=None)
    if duration_ms > 0 and issue.end_ms > duration_ms:
        return LocationCheck(ok=False, reason="TIMESTAMP_BEYOND_VIDEO_DURATION", shot=None)
    if not issue.has_temporal_range:
        return LocationCheck(ok=False, reason="NO_TEMPORAL_RANGE_FOR_LOCAL_ISSUE", shot=None)
    if not shots:
        return LocationCheck(ok=True, reason="NO_SHOT_TIMELINE_TO_VALIDATE", shot=None)

    start_shot = next((s for s in shots if s.contains(issue.start_ms)), None)
    end_shot = next((s for s in shots if s.contains(max(issue.start_ms, issue.end_ms - 1))), None)
    if start_shot is None or end_shot is None:
        # The range does not land on real footage at all: nothing safe to repair.
        return LocationCheck(
            ok=False,
            reason="TIMESTAMP_OUTSIDE_ANY_SHOT",
            shot=start_shot or end_shot,
        )
    if start_shot.shot_id != end_shot.shot_id:
        # Spanning several shots is a *legitimate* observation, not a broken
        # timestamp. It is locatable and simply widens the repair scope to
        # MULTI_SHOT; rejecting it would throw away real reviewer findings.
        return LocationCheck(
            ok=True, reason="SPANS_MULTIPLE_SHOTS", shot=start_shot, shots=[
                s for s in shots if s.start_ms < issue.end_ms and issue.start_ms < s.end_ms
            ]
        )
    return LocationCheck(ok=True, reason="LOCATED", shot=start_shot, shots=[start_shot])


# ── Diagnosis (§29) ──────────────────────────────────────────────────────


def _overlaps(a: EditorialIssue, b: EditorialIssue) -> bool:
    return a.start_ms < b.end_ms and b.start_ms < a.end_ms


def _dedup_key(issue: EditorialIssue) -> tuple[EditorialIssueCategory, str]:
    return (issue.category, issue.shot_id or "")


def _estimate_scope(
    artifact: CanonicalArtifact,
    issues: list[EditorialIssue],
    shot_ids: set[str],
) -> RepairScope:
    scope = ARTIFACT_SCOPE.get(artifact, RepairScope.GLOBAL)
    if artifact in (CanonicalArtifact.NONE, CanonicalArtifact.PROFILE_DIRECTION):
        return RepairScope.GLOBAL
    if len(shot_ids) > 1:
        return RepairScope.MULTI_SHOT
    if scope is RepairScope.TIMELINE_RANGE and not shot_ids:
        return RepairScope.GLOBAL
    return scope


def diagnose_review(
    review: VideoReview,
    *,
    shots: list[ShotSpan] | None = None,
    allow_preferences: bool = False,
) -> EditorialDiagnosis:
    """Convert a review into a deduplicated, root-caused diagnosis.

    Preferences are kept as findings but are not marked repairable unless
    ``allow_preferences`` is set: a preference goes through pairwise comparison,
    not straight into an autonomous repair.
    """
    shots = shots or []
    duration_ms = int(review.video_duration_s * 1000)
    diagnosis = EditorialDiagnosis(
        review_id=review.review_id,
        candidate_id=review.candidate_id,
        content_id=review.content_id,
        video_hash=review.video_hash,
    )

    grouped: dict[tuple[EditorialIssueCategory, str], list[EditorialIssue]] = {}
    for issue in review.issues:
        grouped.setdefault(_dedup_key(issue), []).append(issue)

    for (category, shot_hint), grouped_issues in grouped.items():
        issues = sorted(grouped_issues, key=lambda i: (i.start_ms, i.end_ms))
        defect_class = classify_defect(category)
        artifact = ROOT_CAUSE_MAP.get(category, CanonicalArtifact.NONE)

        # Partition first: one bad timestamp must not disable repair of the
        # valid observations sitting in the same category. Unlocatable
        # observations are still reported, but they can never drive a repair
        # (A3).
        locatable_issues: list[EditorialIssue] = []
        unlocatable_issues: list[EditorialIssue] = []
        rejections: list[str] = []
        shot_ids: set[str] = set()
        beat_ids: set[str] = set()

        for issue in issues:
            check = validate_issue_location(issue, shots, duration_ms=duration_ms)
            if not check.ok:
                unlocatable_issues.append(issue)
                rejections.append(f"{issue.issue_id}:{check.reason}")
                continue
            locatable_issues.append(issue)
            for hit in check.shots or ([check.shot] if check.shot else []):
                shot_ids.add(hit.shot_id)
                beat_ids.add(hit.beat_id)
        if shot_hint:
            beat_ids.add(shot_hint)

        if locatable_issues:
            representative = locatable_issues[0]
            start_ms = min(i.start_ms for i in locatable_issues)
            end_ms = max(i.end_ms for i in locatable_issues)
            merged_confidence = max(i.confidence for i in locatable_issues)
            severity = min(locatable_issues, key=lambda i: i.severity_rank).severity
            repairable = (
                artifact is not CanonicalArtifact.NONE
                and (defect_class is DefectClass.HARD_DEFECT or allow_preferences)
            )
            scope = (
                _estimate_scope(artifact, locatable_issues, shot_ids) if repairable
                else RepairScope.GLOBAL
            )
            diagnosis.findings.append(
                DiagnosisFinding(
                    categories=[category],
                    representative_issue_id=representative.issue_id,
                    defect_class=defect_class,
                    severity=severity,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    root_cause=ROOT_CAUSE_TEXT.get(
                        artifact, ROOT_CAUSE_TEXT[CanonicalArtifact.NONE]
                    ),
                    canonical_artifact=artifact,
                    repairable=repairable,
                    repair_scope=scope,
                    confidence=merged_confidence,
                    rationale=(
                        f"{len(locatable_issues)} locatable observation(s) of {category.value}; "
                        f"maps to {artifact.value}; severity {severity.value}"
                        + (f"; {len(unlocatable_issues)} rejected as unlocatable" if unlocatable_issues else "")
                    ),
                    duplicate_issue_ids=[i.issue_id for i in locatable_issues],
                    shot_ids=sorted(shot_ids),
                    beat_ids=sorted(b for b in beat_ids if b),
                )
            )

        if unlocatable_issues:
            diagnosis.findings.append(
                DiagnosisFinding(
                    categories=[category],
                    representative_issue_id=unlocatable_issues[0].issue_id,
                    defect_class=defect_class,
                    severity=min(
                        unlocatable_issues, key=lambda i: i.severity_rank
                    ).severity,
                    start_ms=min(i.start_ms for i in unlocatable_issues),
                    end_ms=max(i.end_ms for i in unlocatable_issues),
                    root_cause=(
                        "the reviewer's timestamps do not land on any real shot, so the "
                        "observation cannot be located and therefore cannot be repaired"
                    ),
                    canonical_artifact=CanonicalArtifact.NONE,
                    repairable=False,
                    repair_scope=RepairScope.GLOBAL,
                    confidence=max(i.confidence for i in unlocatable_issues),
                    rationale=(
                        "UNSAFE_LOCATION: "
                        + ";".join(sorted(rejections))
                        + " - no targeted repair attempted"
                    ),
                    duplicate_issue_ids=[i.issue_id for i in unlocatable_issues],
                )
            )

    diagnosis.findings.sort(
        key=lambda f: (f.severity.value, f.categories[0].value if f.categories else "")
    )
    diagnosis.summary = _summarise(review, diagnosis)
    diagnosis.confidence = _diagnostic_confidence(review)
    return diagnosis


def _summarise(review: VideoReview, diagnosis: EditorialDiagnosis) -> str:
    if not diagnosis.findings:
        return "No editorial issues were observed in this candidate."
    parts = [f"{len(diagnosis.findings)} distinct editorial finding(s) from {len(review.issues)} observation(s)."]
    hard = sum(1 for f in diagnosis.findings if f.defect_class is DefectClass.HARD_DEFECT)
    if hard:
        parts.append(f"{hard} hard defect(s).")
    auto = len(diagnosis.autonomous_findings())
    if auto:
        parts.append(f"{auto} repairable finding(s) with a canonical artifact target.")
    unlocatable = sum(1 for f in diagnosis.findings if "UNSAFE_LOCATION" in f.rationale)
    if unlocatable:
        parts.append(f"{unlocatable} finding(s) rejected as unlocatable.")
    return " ".join(parts)


def _diagnostic_confidence(review: VideoReview) -> float:
    if not review.issues:
        return review.confidence
    return max(i.confidence for i in review.issues)


# ── Repair intents (§31) ─────────────────────────────────────────────────

_EXPECTED_EFFECT: dict[CanonicalArtifact, str] = {
    CanonicalArtifact.CAPTION_STYLE: "the caption no longer covers the subject and the "
    "text stops competing with the visual",
    CanonicalArtifact.EVIDENCE_ASSET: "the claim is backed by real, provable evidence instead "
    "of a stand-in visual",
    CanonicalArtifact.SHOT_PLAN: "the beat's pacing reads correctly and the shot length serves "
    "the narration",
    CanonicalArtifact.VISUAL_BEAT: "each beat's visual actually matches what the narration says",
    CanonicalArtifact.MOTION_PLAN: "movement on screen carries meaning instead of adding noise",
    CanonicalArtifact.ASSET_SELECTION: "the visual carries the intended meaning and emotion",
    CanonicalArtifact.AUDIO_MIX: "the audio bed and the picture agree",
    CanonicalArtifact.PROFILE_DIRECTION: "the cut matches the profile's creative direction",
    CanonicalArtifact.NONE: "",
}

_EXPECTED_CHANGE: dict[CanonicalArtifact, str] = {
    CanonicalArtifact.CAPTION_STYLE: "reposition or de-prioritise the caption layer for the "
    "affected time range",
    CanonicalArtifact.EVIDENCE_ASSET: "bind the affected shot to a corrected EvidenceAsset",
    CanonicalArtifact.SHOT_PLAN: "re-cut the shot boundary/duration for the affected range",
    CanonicalArtifact.VISUAL_BEAT: "revise the affected beat's visual specification",
    CanonicalArtifact.MOTION_PLAN: "replace the decorative motion with a purposeful P1 motion",
    CanonicalArtifact.ASSET_SELECTION: "select a different asset for the affected beat",
    CanonicalArtifact.AUDIO_MIX: "rebalance the audio mix for the affected range",
    CanonicalArtifact.PROFILE_DIRECTION: "revise profile direction for this production",
    CanonicalArtifact.NONE: "",
}

_VERIFICATION: dict[CanonicalArtifact, str] = {
    CanonicalArtifact.CAPTION_STYLE: "re-review the repaired range and confirm the caption no "
    "longer occludes the subject",
    CanonicalArtifact.EVIDENCE_ASSET: "re-review the repaired range and confirm the claim is "
    "visually grounded in real evidence",
    CanonicalArtifact.SHOT_PLAN: "re-review the repaired range and confirm the beat's pacing reads "
    "correctly",
    CanonicalArtifact.VISUAL_BEAT: "re-review the repaired range and confirm the visual matches "
    "the narration",
    CanonicalArtifact.MOTION_PLAN: "re-review the repaired range and confirm no decorative motion "
    "remains",
    CanonicalArtifact.ASSET_SELECTION: "re-review the repaired range and confirm the intended "
    "meaning reads through",
    CanonicalArtifact.AUDIO_MIX: "re-review the repaired range and confirm audio/visual agreement",
    CanonicalArtifact.PROFILE_DIRECTION: "re-review the full cut for profile consistency",
    CanonicalArtifact.NONE: "",
}


def build_repair_intents(
    diagnosis: EditorialDiagnosis,
    *,
    shots: list[ShotSpan] | None = None,
    include_minor: bool = False,
) -> list[RepairIntent]:
    """Build one ``RepairIntent`` per repairable finding.

    Only ``BLOCKER`` and ``MAJOR`` findings produce autonomous intents by
    default. ``MINOR`` intents require ``include_minor`` *and* are marked
    low-value; ``COSMETIC`` never produces an intent at all, which is how
    ``UNBOUNDED_REVISION == 0`` is enforced in practice.
    """
    shots = shots or []
    intents: list[RepairIntent] = []

    for finding in diagnosis.findings:
        if not finding.repairable or finding.canonical_artifact is CanonicalArtifact.NONE:
            continue
        if finding.severity in AUTONOMOUS_REPAIR_SEVERITIES or (finding.severity is IssueSeverity.MINOR and include_minor):
            pass
        else:
            continue

        artifact = finding.canonical_artifact
        hit_shots = [
            span
            for span in shots
            if span.start_ms < finding.end_ms and finding.start_ms < span.end_ms
        ]
        beat_ids = sorted({s.beat_id for s in hit_shots if s.beat_id} | set(finding.beat_ids))
        shot_ids = sorted({s.shot_id for s in hit_shots} | set(finding.shot_ids))

        global_reason = ""
        if finding.repair_scope is RepairScope.GLOBAL:
            global_reason = (
                f"artifact {artifact.value} is cut-wide; no narrower scope can express the fix"
            )

        intents.append(
            RepairIntent(
                diagnosis_id=diagnosis.diagnosis_id,
                finding_id=finding.finding_id,
                target_artifacts=[artifact],
                expected_change=_EXPECTED_CHANGE[artifact],
                expected_visual_effect=_EXPECTED_EFFECT[artifact],
                scope=finding.repair_scope,
                start_ms=finding.start_ms,
                end_ms=finding.end_ms,
                beat_ids=beat_ids,
                shot_ids=shot_ids,
                cost_estimate_usd=SCOPE_COST[finding.repair_scope],
                risk=SCOPE_RISK[finding.repair_scope],
                verification=_VERIFICATION[artifact],
                global_reason=global_reason,
                meaningful=finding.severity in AUTONOMOUS_REPAIR_SEVERITIES,
            )
        )

    valid: list[RepairIntent] = []
    for intent in intents:
        ok, _errors = intent.is_valid()
        if ok:
            valid.append(intent)
    return valid


def merge_intents(intents: list[RepairIntent]) -> list[RepairIntent]:
    """Collapse intents that target the same artifact and the same range.

    Repairing a caption-occlusion and a caption-overload in the same 2 seconds
    is one edit, not two — otherwise a single defect would re-render twice.
    """
    merged: dict[tuple[tuple[str, ...], int, int], RepairIntent] = {}
    for intent in intents:
        key = (tuple(a.value for a in intent.target_artifacts), intent.start_ms, intent.end_ms)
        existing = merged.get(key)
        if existing is None:
            merged[key] = intent
            continue
        existing.expected_change = f"{existing.expected_change}; {intent.expected_change}"
        existing.expected_visual_effect = (
            f"{existing.expected_visual_effect}; {intent.expected_visual_effect}"
        )
        existing.verification = f"{existing.verification}; {intent.verification}"
        existing.beat_ids = sorted({*existing.beat_ids, *intent.beat_ids})
        existing.shot_ids = sorted({*existing.shot_ids, *intent.shot_ids})
        existing.cost_estimate_usd = max(
            existing.cost_estimate_usd, intent.cost_estimate_usd
        )
    return sorted(merged.values(), key=lambda i: (i.start_ms, i.end_ms))


# ── Targeted repair plan (§32, §34) ──────────────────────────────────────

#: Canonical artifact -> the P3 pipeline node kind that produces it. Only these
#: may be re-run for a targeted repair; research, script and unaffected TTS are
#: never in this set.
ARTIFACT_RERUN_NODES: dict[CanonicalArtifact, tuple[str, ...]] = {
    CanonicalArtifact.EVIDENCE_ASSET: ("ASSET", "SHOT", "RENDER", "EDIT"),
    CanonicalArtifact.ASSET_SELECTION: ("ASSET", "SHOT", "RENDER", "EDIT"),
    CanonicalArtifact.CAPTION_STYLE: ("SHOT", "RENDER", "EDIT"),
    CanonicalArtifact.MOTION_PLAN: ("MOTION", "SHOT", "RENDER", "EDIT"),
    CanonicalArtifact.SHOT_PLAN: ("SHOT", "RENDER", "EDIT"),
    CanonicalArtifact.VISUAL_BEAT: ("VISUAL_PLAN", "ASSET", "SHOT", "RENDER", "EDIT"),
    CanonicalArtifact.AUDIO_MIX: ("AUDIO", "EDIT"),
    CanonicalArtifact.PROFILE_DIRECTION: ("VISUAL_PLAN", "SHOT", "RENDER", "EDIT"),
    CanonicalArtifact.NONE: (),
}

#: Node kinds that must never be re-run to fix a local visual defect.
PROTECTED_NODE_KINDS = frozenset({"RESEARCH", "SCRIPT"})


@dataclass
class TargetedRepairPlan:
    """P3-scoped repair plan with an explicit preserve list.

    ``rerun_nodes`` and ``preserve_artifact_ids`` mirror P3's ``RepairPlan``
    contract; ``rerun_plan`` is the actual P3 object handed to the executor, so
    P3 lineage and idempotency keep working unchanged.
    """

    content_id: str = ""
    candidate_id: str = ""
    intents: list[RepairIntent] = field(default_factory=list)
    rerun_nodes: list[str] = field(default_factory=list)
    preserve_artifact_ids: list[str] = field(default_factory=list)
    changed_ranges_ms: list[tuple[int, int]] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    expected_gain: float = 0.0
    decision: str = "execute"
    reason: str = ""
    rerun_plan: RepairPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "candidate_id": self.candidate_id,
            "intent_ids": [i.intent_id for i in self.intents],
            "rerun_nodes": self.rerun_nodes,
            "preserve_artifact_ids": self.preserve_artifact_ids,
            "changed_ranges_ms": [list(r) for r in self.changed_ranges_ms],
            "estimated_cost_usd": self.estimated_cost_usd,
            "expected_gain": self.expected_gain,
            "decision": self.decision,
            "reason": self.reason,
            "rerun_plan_id": self.rerun_plan.id if self.rerun_plan else "",
        }


def plan_targeted_repair(
    diagnosis: EditorialDiagnosis,
    intents: list[RepairIntent],
    *,
    content_id: str,
    candidate_id: str,
    node_ids: dict[str, str] | None = None,
    artifact_ids: dict[str, str] | None = None,
    all_artifact_ids: list[str] | None = None,
) -> TargetedRepairPlan:
    """Plan a repair that re-runs the minimum and preserves everything else."""
    plan = TargetedRepairPlan(content_id=content_id, candidate_id=candidate_id, intents=intents)
    if not intents:
        plan.decision = "stop"
        plan.reason = "NO_REPAIR_INTENT: nothing to repair"
        return plan

    node_ids = node_ids or {}
    artifacts = artifact_ids or {}
    all_artifacts = all_artifact_ids or list(artifacts.keys())

    rerun_kinds: set[str] = set()
    changed: list[tuple[int, int]] = []
    for intent in intents:
        for artifact in intent.target_artifacts:
            rerun_kinds.update(ARTIFACT_RERUN_NODES.get(artifact, ()))
        if intent.end_ms > intent.start_ms:
            changed.append((intent.start_ms, intent.end_ms))

    # §34: a protected node kind may never be re-run to fix a local visual defect.
    illegal = sorted(rerun_kinds & PROTECTED_NODE_KINDS)
    if illegal:
        plan.decision = "human_review"
        plan.reason = f"PROTECTED_NODE_RERUN:{','.join(illegal)}"
        return plan

    rerun_nodes = [
        node_ids.get(kind, f"node:{kind}") for kind in sorted(rerun_kinds)
    ]
    rerun_set = set(rerun_nodes)
    preserve = [
        artifacts[key]
        for key in all_artifacts
        if key not in rerun_kinds and artifacts.get(key) not in rerun_set
    ]

    plan.rerun_nodes = rerun_nodes
    plan.preserve_artifact_ids = preserve
    plan.changed_ranges_ms = _merge_ranges(changed)
    plan.estimated_cost_usd = round(sum(i.cost_estimate_usd for i in intents), 4)
    plan.expected_gain = round(
        sum(
            0.5 if f.severity is IssueSeverity.BLOCKER else 0.3
            for f in diagnosis.findings
            if f.repairable
        ),
        3,
    )
    plan.decision = "execute"
    plan.reason = (
        f"targeted repair over {len(plan.changed_ranges_ms)} range(s); "
        f"preserving {len(preserve)} unaffected artifact(s)"
    )

    plan.rerun_plan = RepairPlan.create(
        production_id=content_id,
        source_attempt_id=candidate_id,
        source_verdict_id=diagnosis.diagnosis_id,
        violated_constraint_ids=[f.finding_id for f in diagnosis.findings if f.repairable],
        root_nodes=[i.finding_id for i in intents],
        rerun_nodes=rerun_nodes,
        preserve_artifact_ids=preserve,
        estimated_cost=plan.estimated_cost_usd,
        expected_gain=plan.expected_gain,
        decision="execute",
        reason=plan.reason,
        iteration=max(
            (f.severity_rank for f in diagnosis.findings if f.repairable), default=0
        ),
    )
    return plan


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping ranges so one shot is not re-rendered twice."""
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def unaffected_source_reruns(
    plan: TargetedRepairPlan, node_kinds_by_id: dict[str, str]
) -> list[str]:
    """Audit: did the plan re-run any node kind that must be preserved?

    Returns the offending node ids. An empty list is the
    ``UNAFFECTED_SOURCE_RERUNS == 0`` evidence.
    """
    return sorted(
        node_id
        for node_id in plan.rerun_nodes
        if node_kinds_by_id.get(node_id, "") in PROTECTED_NODE_KINDS
    )


def changed_layers(
    intents: list[RepairIntent],
) -> list[EditableLayer]:
    """Which delivery layers a repair set will touch."""
    layers: set[EditableLayer] = set()
    for intent in intents:
        for artifact in intent.target_artifacts:
            if artifact is CanonicalArtifact.CAPTION_STYLE:
                layers.add(EditableLayer.CAPTIONS)
            elif artifact in (CanonicalArtifact.EVIDENCE_ASSET, CanonicalArtifact.ASSET_SELECTION):
                layers.add(EditableLayer.EVIDENCE)
            elif artifact is CanonicalArtifact.MOTION_PLAN:
                layers.add(EditableLayer.OVERLAY)
            elif artifact is CanonicalArtifact.AUDIO_MIX:
                layers.update({EditableLayer.VOICE, EditableLayer.BGM, EditableLayer.SFX})
            else:
                layers.add(EditableLayer.BACKGROUND)
    return sorted(layers, key=lambda layer: layer.value)


__all__ = [
    "ARTIFACT_RERUN_NODES",
    "ARTIFACT_SCOPE",
    "PROTECTED_NODE_KINDS",
    "ROOT_CAUSE_TEXT",
    "SCOPE_COST",
    "SCOPE_RISK",
    "LocationCheck",
    "ShotSpan",
    "TargetedRepairPlan",
    "build_repair_intents",
    "changed_layers",
    "diagnose_review",
    "merge_intents",
    "plan_targeted_repair",
    "unaffected_source_reruns",
    "validate_issue_location",
]
