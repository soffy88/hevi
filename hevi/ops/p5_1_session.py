"""HEVI P5.1 — revision convergence policy.

:class:`RevisionSession` is the **single promotion authority**. It combines hard
gates, blind bidirectional pairwise results, repair verification, budget and
human override. A reviewer can produce evidence but can never promote; and the
session never re-introduces a fixed ``max_rounds`` termination into the P3
mission runtime — the editorial budget is separate and additive.

Convergence rules enforced here:

* ``MAX_REVISION_ROUNDS = 3`` is an *editorial* budget (§36). It bounds how many
  times HEVI re-cuts its own video, not how many times a mission may run.
* Every revision must be **meaningful** (§37): at least one ``BLOCKER``/``MAJOR``
  repair, or a declared, perceptible editorial hypothesis. A round that exists
  only to "polish a bit" is refused, which is what keeps
  ``UNBOUNDED_REVISION == 0`` real rather than aspirational.
* ``NO_PROGRESS_DETECTED`` (§47): if the same issue category keeps coming back
  across consecutive revisions, the loop stops instead of reshuffling assets
  forever.
* Only ``MINOR``/``COSMETIC`` issues left -> stop (§46, ``A14``).
* A human decision outranks autonomous promotion (§67), and P5 approval is never
  bypassed (§68).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.ops.p5_1_diagnosis import (
    ShotSpan,
    build_repair_intents,
    diagnose_review,
    merge_intents,
    plan_targeted_repair,
)
from hevi.ops.p5_1_pairwise import (
    PairwiseOutcome,
    PairwiseUnavailable,
    check_regression_guard,
    decide_promotion,
    run_bidirectional_pairwise,
    verify_expected_repair,
)
from hevi.ops.p5_1_types import (
    MAX_REVISION_ROUNDS,
    CanonicalArtifact,
    EditorialDiagnosis,
    EditorialIssueCategory,
    HumanDecision,
    IssueSeverity,
    PromotionDecision,
    PromotionDecisionKind,
    RepairIntent,
    RevisionCandidate,
    RevisionSession,
    SessionCost,
    SessionStopReason,
    VideoReview,
    video_file_hash,
)

#: A category seen in this many consecutive revisions is treated as no progress.
NO_PROGRESS_CATEGORY_STREAK = 2


# ── Meaningful revision (§37) ────────────────────────────────────────────


@dataclass
class MeaningfulnessVerdict:
    ok: bool = False
    reason: str = ""
    driving_intents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_meaningful_revision(
    intents: list[RepairIntent], diagnosis: EditorialDiagnosis, *, hypothesis: str = ""
) -> MeaningfulnessVerdict:
    """Refuse a revision that would exist only to look busier.

    A revision qualifies when it carries at least one ``MAJOR``/``BLOCKER``
    repair, or when a specific, perceptible editorial hypothesis is declared
    and aimed at a real canonical artifact.
    """
    if not intents:
        return MeaningfulnessVerdict(
            ok=False, reason="NO_REPAIR_INTENT: a revision without an intent is not a revision"
        )

    drivers = [i.intent_id for i in intents if i.meaningful]
    if drivers:
        return MeaningfulnessVerdict(
            ok=True,
            reason=f"{len(drivers)} BLOCKER/MAJOR repair intent(s) drive this revision",
            driving_intents=drivers,
        )

    targeted = [i for i in intents if i.target_artifacts and i.expected_visual_effect]
    if hypothesis.strip() and targeted:
        return MeaningfulnessVerdict(
            ok=True,
            reason=f"declared editorial hypothesis: {hypothesis.strip()[:200]}",
            driving_intents=[i.intent_id for i in targeted],
        )
    return MeaningfulnessVerdict(
        ok=False,
        reason=(
            "MEANINGFUL_REVISION_REFUSED: only minor/cosmetic findings and no "
            "declared editorial hypothesis; refusing to cut a new version for that"
        ),
    )


# ── No-progress detection (§47) ──────────────────────────────────────────


def detect_no_progress(
    session: RevisionSession, *, streak_limit: int = NO_PROGRESS_CATEGORY_STREAK
) -> tuple[bool, str]:
    """Detect the same editorial problem recurring across revisions.

    ``A15``: if the same category keeps coming back, stop. Reshuffling assets
    forever is not convergence.

    The streak is derived from the session's own history rather than from a
    counter that only grows when this function is called again, so one pass
    over three already-identical revisions is enough to see the pattern.
    """
    history: list[set[EditorialIssueCategory]] = []
    for candidate in session.candidates:
        diagnosis = session.diagnoses.get(candidate.candidate_id)
        if diagnosis is not None:
            history.append(diagnosis.categories_present())
    if len(history) < 2:
        session.no_progress_streak = 0
        return False, ""

    # Longest run of consecutive revisions that share at least one category.
    recurring: EditorialIssueCategory | None = None
    streak = 0
    best = 0
    previous: set[EditorialIssueCategory] = set()
    for index, current in enumerate(history):
        shared = previous & current if index else set()
        if shared:
            if recurring is not None and recurring in shared and streak:
                streak += 1
            else:
                recurring = sorted(shared, key=lambda c: c.value)[0]
                streak = 1
            best = max(best, streak)
        else:
            recurring, streak = None, 0
        previous = current

    session.no_progress_streak = best
    if best < streak_limit or recurring is None:
        return False, ""
    return True, (
        f"NO_PROGRESS_DETECTED: {recurring.value} persisted across {best + 1} "
        "consecutive revisions without being resolved"
    )


# ── Stop conditions (§46) ────────────────────────────────────────────────


def evaluate_stop_conditions(
    session: RevisionSession,
    diagnosis: EditorialDiagnosis,
    promotion: PromotionDecision | None,
) -> SessionStopReason | None:
    """Return the stop reason for the session, or ``None`` to continue."""
    if not session.provider_available:
        return SessionStopReason.PROVIDER_UNAVAILABLE

    auto_work = diagnosis.autonomous_findings()
    has_blocker_or_major = bool(diagnosis.blocker_findings() or diagnosis.major_findings())
    if not has_blocker_or_major and not auto_work:
        if diagnosis.findings:
            return SessionStopReason.ONLY_MINOR_COSMETIC_REMAINS
        return SessionStopReason.NO_BLOCKER_OR_MAJOR_ISSUES

    if promotion is not None and promotion.decision is PromotionDecisionKind.KEEP_OLD:
        return SessionStopReason.NEW_NOT_PROMOTED
    if promotion is not None and promotion.decision is PromotionDecisionKind.HUMAN_REVIEW:
        return SessionStopReason.HUMAN_REVIEW_REQUIRED

    no_progress, _detail = detect_no_progress(session)
    if no_progress:
        session.stop_reason = SessionStopReason.NO_PROGRESS_DETECTED
        return SessionStopReason.NO_PROGRESS_DETECTED

    if session.rounds_remaining() <= 0:
        return SessionStopReason.MAX_REVISION_ROUNDS_REACHED
    if session.budget_usd > 0 and session.budget_remaining_usd() <= 0:
        return SessionStopReason.BUDGET_EXHAUSTED
    return None


# ── Cost accounting (§48, §80, §81) ──────────────────────────────────────


def add_review_cost(session: RevisionSession, review: VideoReview) -> None:
    """Record review cost. UNKNOWN stays UNKNOWN; it is never written as 0."""
    if review.cost_usd is None:
        session.cost.unknown_cost_items += 1
    else:
        session.cost.review_cost_usd += review.cost_usd


def add_pairwise_cost(session: RevisionSession, outcome: PairwiseOutcome) -> None:
    for comparison in (outcome.forward, outcome.reversed):
        if comparison.cost_usd is None:
            session.cost.unknown_cost_items += 1
        else:
            session.cost.pairwise_cost_usd += comparison.cost_usd


# ── Session orchestration ───────────────────────────────────────────────


@dataclass
class RepairOutcome:
    """Result of applying one round of targeted repair."""

    candidate: RevisionCandidate | None = None
    plan: Any = None
    intents: list[RepairIntent] = field(default_factory=list)
    stopped: bool = False
    stop_reason: SessionStopReason | None = None
    reason: str = ""
    render_duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate.candidate_id if self.candidate else "",
            "intent_ids": [i.intent_id for i in self.intents],
            "stopped": self.stopped,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "reason": self.reason,
            "render_duration_s": self.render_duration_s,
        }


class RevisionSessionRunner:
    """Drives the SEE -> DIAGNOSE -> REPAIR -> COMPARE -> PROMOTE loop.

    The caller supplies the *real* production steps (render, evidence
    acquisition) through callbacks. This class owns only the editorial policy:
    what to repair, whether the repair was meaningful, whether the new candidate
    may replace the old one, and when to stop.
    """

    def __init__(
        self,
        session: RevisionSession,
        *,
        workdir: Path,
        repair_renderer: Any = None,
        pairwise_runner: Any = None,
        max_revision_rounds: int | None = None,
    ) -> None:
        self.session = session
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.repair_renderer = repair_renderer
        self.pairwise_runner = pairwise_runner or run_bidirectional_pairwise
        if max_revision_rounds is not None:
            session.max_revision_rounds = max_revision_rounds

    # ── Intake ──
    def register_candidate(
        self,
        candidate: RevisionCandidate,
        review: VideoReview,
        *,
        shots: list[ShotSpan] | None = None,
    ) -> EditorialDiagnosis:
        """Register a rendered candidate and its fresh review, then diagnose it."""
        candidate.video_hash = candidate.video_hash or video_file_hash(candidate.video_path)
        review.video_hash = review.video_hash or candidate.video_hash
        self.session.add_candidate(candidate)
        self.session.reviews[candidate.candidate_id] = review
        add_review_cost(self.session, review)
        diagnosis = diagnose_review(review, shots=shots or [])
        self.session.diagnoses[candidate.candidate_id] = diagnosis
        return diagnosis

    def set_provider_available(self, available: bool) -> None:
        self.session.provider_available = available

    # ── One revision round ──
    async def propose_revision(
        self,
        *,
        hypothesis: str = "",
        include_minor: bool = False,
        shots: list[ShotSpan] | None = None,
    ) -> RepairOutcome:
        """Plan, render and adjudicate one revision. Never runs more than the budget."""
        current = self.session.authoritative() or self.session.current
        if current is None:
            return RepairOutcome(reason="NO_CANDIDATE")

        stop = evaluate_stop_conditions(
            self.session, self.session.diagnoses.get(current.candidate_id) or
            EditorialDiagnosis(), None,
        )
        if stop is not None and stop not in (
            SessionStopReason.MAX_REVISION_ROUNDS_REACHED,
            SessionStopReason.BUDGET_EXHAUSTED,
        ):
            self.session.stop(stop)
            return RepairOutcome(stopped=True, stop_reason=stop, reason=stop.value)

        if self.session.rounds_remaining() <= 0:
            self.session.stop(SessionStopReason.MAX_REVISION_ROUNDS_REACHED)
            return RepairOutcome(
                stopped=True,
                stop_reason=SessionStopReason.MAX_REVISION_ROUNDS_REACHED,
                reason=f"editorial revision budget of {self.session.max_revision_rounds} exhausted",
            )
        if self.session.budget_usd > 0 and self.session.budget_remaining_usd() <= 0:
            self.session.stop(SessionStopReason.BUDGET_EXHAUSTED)
            return RepairOutcome(
                stopped=True, stop_reason=SessionStopReason.BUDGET_EXHAUSTED,
                reason="revision budget exhausted",
            )

        diagnosis = self.session.diagnoses.get(current.candidate_id)
        if diagnosis is None:
            return RepairOutcome(reason="NO_DIAGNOSIS")

        intents = merge_intents(build_repair_intents(diagnosis, shots=shots or [], include_minor=include_minor))
        meaningful = check_meaningful_revision(intents, diagnosis, hypothesis=hypothesis)
        if not meaningful.ok:
            self.session.stop(SessionStopReason.MEANINGFUL_REVISION_REFUSED)
            return RepairOutcome(
                stopped=True,
                stop_reason=SessionStopReason.MEANINGFUL_REVISION_REFUSED,
                reason=meaningful.reason,
            )

        plan = plan_targeted_repair(
            diagnosis,
            intents,
            content_id=self.session.content_id,
            candidate_id=current.candidate_id,
        )
        if plan.decision != "execute":
            self.session.stop(SessionStopReason.HUMAN_REVIEW_REQUIRED)
            return RepairOutcome(
                stopped=True, stop_reason=SessionStopReason.HUMAN_REVIEW_REQUIRED,
                reason=plan.reason,
            )

        if self.repair_renderer is None:
            return RepairOutcome(plan=plan, intents=intents, reason="NO_RENDERER_BOUND")

        started = time.monotonic()
        rendered = self.repair_renderer(plan=plan, intents=intents, parent=current)
        render_duration = time.monotonic() - started
        if not rendered or not getattr(rendered, "video_path", ""):
            return RepairOutcome(
                plan=plan, intents=intents, reason="REPAIR_RENDER_FAILED"
            )

        self.session.cost.repair_cost_usd += plan.estimated_cost_usd
        self.session.cost.render_cost_usd += plan.estimated_cost_usd

        candidate = RevisionCandidate(
            content_id=self.session.content_id,
            parent_candidate_id=current.candidate_id,
            revision_number=current.revision_number + 1,
            repair_intents=intents,
            video_path=rendered.video_path,
            video_duration_s=float(getattr(rendered, "video_duration_s", 0.0) or 0.0),
            changed_artifacts=list(getattr(rendered, "changed_artifacts", []) or []),
            unchanged_artifacts=list(getattr(rendered, "unchanged_artifacts", []) or []),
            changed_ranges=list(plan.changed_ranges_ms),
            cost=plan.estimated_cost_usd,
            render_duration_s=render_duration,
        )
        candidate.video_hash = video_file_hash(candidate.video_path)
        self.session.add_candidate(candidate)
        return RepairOutcome(
            candidate=candidate, plan=plan, intents=intents, render_duration_s=render_duration
        )

    # ── Adjudication ──
    async def adjudicate(
        self,
        new_review: VideoReview,
        new_candidate: RevisionCandidate,
        *,
        shots: list[ShotSpan] | None = None,
    ) -> PromotionDecision:
        """Review the new candidate, compare blind both ways, and decide."""
        old = self.session.candidate(new_candidate.parent_candidate_id)
        if old is None:
            raise ValueError("new candidate has no parent in this session")

        self.session.reviews[new_candidate.candidate_id] = new_review
        new_candidate.review_id = new_review.review_id
        add_review_cost(self.session, new_review)

        intents = new_candidate.repair_intents
        targets = sorted(
            {
                category.value
                for intent in intents
                for category in self._target_categories(intent)
            }
        )
        verified, verify_notes = verify_expected_repair(
            new_review, targets=targets, protected_categories=set(targets)
        )

        regression = check_regression_guard(old, new_candidate, new_review)

        outcome: PairwiseOutcome | None = None
        try:
            outcome = await self.pairwise_runner(
                old, new_candidate, workdir=self.workdir, content_id=self.session.content_id
            )
            self.session.pairwise.extend([outcome.forward, outcome.reversed])
            add_pairwise_cost(self.session, outcome)
        except PairwiseUnavailable as exc:
            self.session.provider_available = False
            outcome = None
            verify_notes = [*verify_notes, f"PAIRWISE_UNAVAILABLE:{exc}"]

        promotion = decide_promotion(
            content_id=self.session.content_id,
            session_id=self.session.session_id,
            old=old,
            new=new_candidate,
            new_review=new_review,
            old_review=self.session.reviews.get(old.candidate_id),
            pairwise=outcome,
            expected_repair_verified=verified,
            regression=regression,
        )
        if verify_notes:
            promotion.rationale = f"{promotion.rationale} | {';'.join(verify_notes)}"
        self.session.record_promotion(promotion)

        diagnosis = diagnose_review(new_review, shots=shots or [])
        self.session.diagnoses[new_candidate.candidate_id] = diagnosis

        stop = evaluate_stop_conditions(self.session, diagnosis, promotion)
        if stop is not None:
            self.session.stop(stop)
        return promotion

    @staticmethod
    def _target_categories(intent: RepairIntent) -> set[EditorialIssueCategory]:
        """Which issue categories a repair intent was trying to eliminate."""
        mapping = {
            CanonicalArtifact.CAPTION_STYLE: {
                EditorialIssueCategory.CAPTION_OCCLUSION,
                EditorialIssueCategory.CAPTION_OVERLOAD,
                EditorialIssueCategory.TEXT_DOMINANCE,
            },
            CanonicalArtifact.EVIDENCE_ASSET: {
                EditorialIssueCategory.WRONG_EVIDENCE,
                EditorialIssueCategory.FAKE_UI,
                EditorialIssueCategory.WEAK_VISUAL_GROUNDING,
                EditorialIssueCategory.EVIDENCE_UNDERUSE,
            },
            CanonicalArtifact.SHOT_PLAN: {
                EditorialIssueCategory.SHOT_TOO_LONG,
                EditorialIssueCategory.SHOT_TOO_SHORT,
                EditorialIssueCategory.PACING,
                EditorialIssueCategory.SUBJECT_JUMP,
                EditorialIssueCategory.DEAD_AIR,
                EditorialIssueCategory.TRANSITION_MISMATCH,
                EditorialIssueCategory.LAYOUT_INSTABILITY,
            },
            CanonicalArtifact.VISUAL_BEAT: {
                EditorialIssueCategory.VISUAL_STAGNATION,
                EditorialIssueCategory.VISUAL_REPETITION,
                EditorialIssueCategory.LOW_INFORMATION_DENSITY,
                EditorialIssueCategory.EXCESSIVE_INFORMATION_DENSITY,
                EditorialIssueCategory.SPEAKER_OVERUSE,
                EditorialIssueCategory.SPEAKER_UNDERUSE,
            },
            CanonicalArtifact.MOTION_PLAN: {
                EditorialIssueCategory.MOTION_DISTRACTION,
                EditorialIssueCategory.MOTION_MEANINGLESS,
            },
            CanonicalArtifact.ASSET_SELECTION: {EditorialIssueCategory.EMOTIONAL_MISMATCH},
            CanonicalArtifact.AUDIO_MIX: {EditorialIssueCategory.AUDIO_VISUAL_MISMATCH},
            CanonicalArtifact.PROFILE_DIRECTION: {
                EditorialIssueCategory.STYLE_INCONSISTENCY,
                EditorialIssueCategory.PROFILE_MISMATCH,
            },
            CanonicalArtifact.NONE: set(),
        }
        out: set[EditorialIssueCategory] = set()
        for artifact in intent.target_artifacts:
            out |= mapping.get(artifact, set())
        return out


# ── Human override (§67) ─────────────────────────────────────────────────


def apply_human_decision(
    session: RevisionSession, decision: HumanDecision
) -> PromotionDecision:
    """Apply a human decision, which outranks autonomous promotion."""
    candidates = session.candidates
    old = candidates[0] if candidates else None
    new = candidates[-1] if len(candidates) > 1 else (candidates[0] if candidates else None)
    if old is None or new is None:
        raise ValueError("no candidates to decide between")

    session.human_decision = decision
    promotion = decide_promotion(
        content_id=session.content_id,
        session_id=session.session_id,
        old=old,
        new=new,
        new_review=session.reviews.get(new.candidate_id) or VideoReview(),
        old_review=session.reviews.get(old.candidate_id),
        pairwise=None,
        expected_repair_verified=False,
        regression=check_regression_guard(old, new, session.reviews.get(new.candidate_id) or VideoReview()),
        human_override=decision,
    )
    if decision is HumanDecision.REQUEST_CHANGE:
        promotion.decision = PromotionDecisionKind.HUMAN_REVIEW
        promotion.rationale = "HUMAN_OVERRIDE:REQUEST_CHANGE - human asked for another pass"
    session.record_promotion(promotion)
    if decision is HumanDecision.REJECT_ALL:
        session.stop(SessionStopReason.HUMAN_REVIEW_REQUIRED)
    return promotion


def authoritative_candidate(session: RevisionSession) -> RevisionCandidate | None:
    """The candidate the rest of the pipeline must treat as current."""
    return session.authoritative()


def new_session(
    content_id: str,
    profile_id: str = "",
    *,
    budget_usd: float = 0.0,
    max_revision_rounds: int = MAX_REVISION_ROUNDS,
) -> RevisionSession:
    return RevisionSession(
        content_id=content_id,
        profile_id=profile_id,
        budget_usd=budget_usd,
        max_revision_rounds=max_revision_rounds,
        cost=SessionCost(),
    )


__all__ = [
    "MAX_REVISION_ROUNDS",
    "NO_PROGRESS_CATEGORY_STREAK",
    "IssueSeverity",
    "MeaningfulnessVerdict",
    "RepairOutcome",
    "RevisionSessionRunner",
    "add_pairwise_cost",
    "add_review_cost",
    "apply_human_decision",
    "authoritative_candidate",
    "check_meaningful_revision",
    "detect_no_progress",
    "evaluate_stop_conditions",
    "new_session",
]
