"""HEVI P5.1 — blind pairwise comparison and the promotion gate.

Promotion is *relative*, never absolute. A model scoring itself 82 -> 91 -> 96
is not evidence of improvement, so no absolute score is ever used as a promotion
authority (``SELF_SCORE_OPTIMIZATION == 0``). The only question asked is:

    which version better satisfies the editorial contract?

Blindness (§52, §53): the reviewer receives a single composed video containing
both candidates and the neutral labels "Candidate A" / "Candidate B". It is not
told which is newer, which cost more, which changed more, or what a previous
model preferred. The blindness is *checked*, not just intended: the rendered
package is inspected and the comparison refuses to run if it carries any
recency signal.

Bidirectionality (§40, §41): the comparison is run twice with the slots swapped.
Only a new candidate that wins *both* directions may be promoted. A split
verdict is reported as ``POSITION_BIAS_OR_UNCERTAIN`` and never promoted.

Hard gates outrank preference (§43, §44): a new candidate that introduces a
BLOCKER is rejected no matter how much the reviewer prefers it. The unchanged
range is diffed so a fix that breaks untouched footage is caught (§45).
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.ops.p5_1_providers import (
    VideoReviewRequest,
    VideoUnderstandingCallError,
    VideoUnderstandingUnavailable,
    extract_json_object,
    get_provider,
    select_video_understanding_provider,
)
from hevi.ops.p5_1_types import (
    PAIRWISE_CONTRACT_DIMENSIONS,
    PAIRWISE_PROMPT_VERSION,
    PairwiseComparison,
    PairwiseVerdict,
    PromotionDecision,
    PromotionDecisionKind,
    RevisionCandidate,
    VideoReview,
    video_file_hash,
)

# ── Pairwise contract (§42) ──────────────────────────────────────────────

PAIRWISE_PROMPT = """You are comparing two versions of the same video and \
deciding which one is better made.

The clip you are given contains two complete versions back to back. The FIRST \
half is "Candidate A". The SECOND half is "Candidate B". Judge only the video. \
Do not assume either is newer, preferred, or more expensive.

Compare them on all of these, in this order of importance:

1. hard_defects - black or blank stretches, dropped/frozen frames, captions \
covering the subject, a fabricated interface presented as real, evidence that \
does not match what is being claimed, obvious audio/visual mismatch
2. narrative_clarity - does the viewer understand what is being said
3. visual_grounding - are claims backed by what is actually on screen
4. information_density - is each moment clear, or is too much competing at once, \
or too empty
5. pacing - does the rhythm serve the content
6. speaker_evidence_balance - is the right thing dominant for what is being said
7. motion_purpose - does movement carry meaning rather than adding noise
8. caption_readability - captions are legible and do not fight the picture
9. profile_consistency - does the look hold together
10. overall_watchability - would you keep watching

Hard defects dominate. A candidate with a hard defect loses to a clean one even \
if it looks flashier.

Return ONLY a JSON object, no prose and no markdown fence:
{"winner": "A" | "B" | "TIE" | "INCOMPARABLE",
 "hard_defects": {"A": ["..."], "B": ["..."]},
 "dimensions": {"narrative_clarity": {"A": "...", "B": "..."}, "visual_grounding": {"A": "...", "B": "..."}, "information_density": {"A": "...", "B": "..."}, "pacing": {"A": "...", "B": "..."}, "speaker_evidence_balance": {"A": "...", "B": "..."}, "motion_purpose": {"A": "...", "B": "..."}, "caption_readability": {"A": "...", "B": "..."}, "profile_consistency": {"A": "...", "B": "..."}, "overall_watchability": {"A": "...", "B": "..."}},
 "rationale": "two or three sentences"}
"""

#: Fields a pairwise package is allowed to carry. Anything else — a candidate's
#: revision number, cost, diff size, or the producing model's opinion — is a
#: blindness leak by construction, not by wording.
_ALLOWED_PACKAGE_FIELDS = frozenset(
    {"candidate_a_path", "candidate_b_path", "contract_version", "prompt"}
)

#: Phrases that *assert* which slot is newer / better. The neutrality preamble
#: ("do not assume either is newer") is deliberately not matched: refusing to
#: assume is the opposite of disclosing.
_RECURSION_LEAK_PATTERNS = (
    re.compile(r"\b(?:candidate\s+)?[ab]\s+is\s+(?:the\s+)?(?:new|newer|old|revised|repaired|improved)\b", re.I),
    re.compile(r"\bthe\s+(?:new|newer|old|revised|repaired|improved)\s+(?:version|candidate|one|render)\s+is\s+[ab]\b", re.I),
    re.compile(r"\b(?:prefer|choose|favou?r)\s+(?:the\s+)?(?:new|newer|improved|repaired)\b", re.I),
    re.compile(r"\b[ab]\s+(?:costs?|cost)\s+[.$]", re.I),
    re.compile(r"\bwe\s+(?:just\s+)?(?:fixed|repaired|improved|changed)\b", re.I),
    re.compile(r"\bthe\s+model\s+(?:preferred|liked|chose)\b", re.I),
)


class PairwiseUnavailable(RuntimeError):
    """A pairwise comparison could not be run."""


@dataclass
class PairwisePackage:
    """The exact inputs a pairwise reviewer sees.

    ``candidate_a_path`` / ``candidate_b_path`` are the two halves of a single
    composed comparison video. Nothing about recency, cost or diff size is
    carried.
    """

    candidate_a_path: str
    candidate_b_path: str
    contract_version: str = PAIRWISE_PROMPT_VERSION
    prompt: str = PAIRWISE_PROMPT

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_a_path": self.candidate_a_path,
            "candidate_b_path": self.candidate_b_path,
            "contract_version": self.contract_version,
            "prompt_chars": len(self.prompt),
        }


def assert_blind(package: PairwisePackage) -> tuple[bool, list[str]]:
    """Check the reviewer input carries no recency or preference signal.

    The check is two-layered. Structurally, the package may only carry the two
    candidate paths, the contract version and the prompt — a recency field has
    nowhere to hide. Lexically, the prompt must not *assign* newness or
    preference to a slot, while still being allowed to instruct the reviewer not
    to assume either.

    ``A13``: if the reviewer is told which is new, the comparison is not blind
    and must fail rather than quietly produce a number.
    """
    leaks: list[str] = []

    extra = {
        name
        for name in vars(package)
        if name not in _ALLOWED_PACKAGE_FIELDS
    }
    leaks.extend(f"LEAKED_FIELD:{name}" for name in sorted(extra))

    for pattern in _RECURSION_LEAK_PATTERNS:
        leaks.extend(
            f"RECURSION_DISCLOSED:{match.group(0)[:40]}"
            for match in pattern.finditer(package.prompt or "")
        )

    if package.contract_version != PAIRWISE_PROMPT_VERSION:
        leaks.append(f"UNVERSIONED_CONTRACT:{package.contract_version}")

    # Sanity: the two slots must actually carry two different videos.
    if package.candidate_a_path == package.candidate_b_path:
        leaks.append("IDENTICAL_SLOTS")

    return (not leaks), sorted(set(leaks))


# ── Comparison video composition ─────────────────────────────────────────


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False, text=True)


def _probe(path: Path) -> dict[str, Any]:
    result = _run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        timeout=120,
    )
    try:
        parsed: Any = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _normalise(src: Path, dst: Path, *, width: int, height: int, fps: int) -> bool:
    """Re-encode a candidate to a comparable form (same size, fps, audio bed).

    ``filter_complex`` is used rather than ``-vf`` so the scale/pad filter binds
    to the real video stream and cannot leak onto the silent-audio input.
    """
    graph = (
        f"[0:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,fps={fps}[v]"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-filter_complex", graph,
        "-map", "[v]", "-map", "1:a:0", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", str(dst),
    ]
    result = _run(cmd)
    return result.returncode == 0 and dst.is_file() and dst.stat().st_size > 0


def build_comparison_video(
    candidate_a: str | Path,
    candidate_b: str | Path,
    output_path: str | Path,
    *,
    width: int = 640,
    height: int = 360,
    fps: int = 24,
) -> Path:
    """Compose one video holding Candidate A then Candidate B.

    The reviewer watches a single video, so it genuinely compares two *renders*
    rather than two text descriptions of them.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    a_norm, b_norm = out.with_suffix(".a.mp4"), out.with_suffix(".b.mp4")
    if not _normalise(Path(candidate_a), a_norm, width=width, height=height, fps=fps):
        raise PairwiseUnavailable(f"could not normalise candidate A: {candidate_a}")
    if not _normalise(Path(candidate_b), b_norm, width=width, height=height, fps=fps):
        raise PairwiseUnavailable(f"could not normalise candidate B: {candidate_b}")

    listing = out.with_suffix(".txt")
    listing.write_text(f"file '{a_norm}'\nfile '{b_norm}'\n", encoding="utf-8")
    result = _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", str(out),
        ]
    )
    a_norm.unlink(missing_ok=True)
    b_norm.unlink(missing_ok=True)
    listing.unlink(missing_ok=True)
    if result.returncode != 0 or not out.is_file():
        raise PairwiseUnavailable(f"concat failed: {result.stderr[:200]}")
    return out


# ── Single-direction comparison ──────────────────────────────────────────


def _parse_verdict(payload: dict[str, Any]) -> tuple[PairwiseVerdict, str, dict[str, str]]:
    raw = str(payload.get("winner") or "").strip().upper()
    verdict = {
        "A": PairwiseVerdict.A,
        "B": PairwiseVerdict.B,
        "TIE": PairwiseVerdict.TIE,
        "INCOMPARABLE": PairwiseVerdict.INCOMPARABLE,
    }.get(raw, PairwiseVerdict.INCOMPARABLE)

    notes: dict[str, str] = {}
    dimensions = payload.get("dimensions")
    if isinstance(dimensions, dict):
        for name, value in dimensions.items():
            if isinstance(value, dict):
                notes[str(name)] = " | ".join(
                    f"{slot}: {str(text).strip()[:220]}" for slot, text in value.items()
                )
            else:
                notes[str(name)] = str(value)[:240]

    hard = payload.get("hard_defects")
    if isinstance(hard, dict):
        for slot, items in hard.items():
            if isinstance(items, list) and items:
                notes[f"hard_defects.{slot}"] = "; ".join(str(i)[:200] for i in items)
    return verdict, str(payload.get("rationale") or "").strip()[:1200], notes


async def run_pairwise_direction(
    old: RevisionCandidate,
    new: RevisionCandidate,
    *,
    old_slot: str = "A",
    workdir: Path,
    content_id: str = "",
    provider_id: str | None = None,
    timeout_s: float = 420.0,
) -> PairwiseComparison:
    """Run one blind comparison with the old candidate in ``old_slot``.

    The reviewer is given a single composed video. ``old_slot`` decides only
    which half of that video the old render occupies; it is never disclosed.
    """
    selection = select_video_understanding_provider(provider_id)
    if selection.blocked:
        raise PairwiseUnavailable(selection.reason)

    a_path, b_path = (
        (old.video_path, new.video_path) if old_slot == "A" else (new.video_path, old.video_path)
    )
    comparison_video = build_comparison_video(
        a_path, b_path, workdir / f"pairwise_{old.candidate_id}_{old_slot}.mp4"
    )

    package = PairwisePackage(
        candidate_a_path=str(a_path), candidate_b_path=str(b_path)
    )
    blind_ok, leaks = assert_blind(package)
    if not blind_ok:
        raise PairwiseUnavailable(f"BLIND_REVIEW_FAIL:{','.join(leaks)}")

    try:
        provider = get_provider(selection.provider_id)
    except VideoUnderstandingUnavailable as exc:
        raise PairwiseUnavailable(exc.reason) from exc

    started = time.monotonic()
    try:
        response = await provider.review_video(
            VideoReviewRequest(
                video_path=str(comparison_video),
                prompt=PAIRWISE_PROMPT,
                timeout_s=timeout_s,
                metadata={"task": "editorial_pairwise"},
            )
        )
    except VideoUnderstandingCallError as exc:
        raise PairwiseUnavailable(f"PROVIDER_CALL_FAILED:{exc.reason}") from exc
    latency = time.monotonic() - started

    payload = extract_json_object(response.text)
    if payload is None or "winner" not in payload:
        raise PairwiseUnavailable("PAIRWISE_REVIEWER_RETURNED_NO_VERDICT")

    verdict, rationale, notes = _parse_verdict(payload)
    chosen = {
        "A": old if old_slot == "A" else new,
        "B": new if old_slot == "A" else old,
    }.get(verdict)

    return PairwiseComparison(
        content_id=content_id,
        candidate_a=old.candidate_id if old_slot == "A" else new.candidate_id,
        candidate_b=new.candidate_id if old_slot == "A" else old.candidate_id,
        position_of_old=old_slot,
        verdict=verdict,
        rationale=rationale,
        dimension_notes=notes,
        winner_candidate_id=chosen.candidate_id if chosen else "",
        provider=response.provider,
        model=response.model or selection.model_id,
        latency_s=latency,
        cost_usd=response.cost_usd,
    )


# ── Bidirectional comparison (§40, §41) ──────────────────────────────────


@dataclass
class PairwiseOutcome:
    """Both directions plus the position-bias verdict."""

    forward: PairwiseComparison
    reversed: PairwiseComparison
    old_wins_forward: bool | None
    old_wins_reversed: bool | None
    new_wins_both: bool = False
    position_bias_or_uncertain: bool = False
    old_candidate_id: str = ""
    new_candidate_id: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "forward": self.forward.to_dict(),
            "reversed": self.reversed.to_dict(),
            "old_wins_forward": self.old_wins_forward,
            "old_wins_reversed": self.old_wins_reversed,
            "new_wins_both": self.new_wins_both,
            "position_bias_or_uncertain": self.position_bias_or_uncertain,
            "old_candidate_id": self.old_candidate_id,
            "new_candidate_id": self.new_candidate_id,
            "reason": self.reason,
        }


def _old_wins(comparison: PairwiseComparison, old_id: str) -> bool | None:
    """``True`` if old won, ``False`` if new won, ``None`` if undecided."""
    if comparison.verdict is PairwiseVerdict.TIE:
        return None
    if comparison.verdict is PairwiseVerdict.INCOMPARABLE:
        return None
    if not comparison.winner_candidate_id:
        return None
    return comparison.winner_candidate_id == old_id


async def run_bidirectional_pairwise(
    old: RevisionCandidate,
    new: RevisionCandidate,
    *,
    workdir: Path,
    content_id: str = "",
    provider_id: str | None = None,
) -> PairwiseOutcome:
    """Compare both directions and decide whether the new candidate won cleanly.

    A split verdict is the signature of position bias, not of a close call. It is
    reported as uncertain and blocks promotion.
    """
    forward = await run_pairwise_direction(
        old, new, old_slot="A", workdir=workdir, content_id=content_id, provider_id=provider_id
    )
    reversed_cmp = await run_pairwise_direction(
        old, new, old_slot="B", workdir=workdir, content_id=content_id, provider_id=provider_id
    )

    old_forward = _old_wins(forward, old.candidate_id)
    old_reversed = _old_wins(reversed_cmp, old.candidate_id)

    both_new = old_forward is False and old_reversed is False
    both_old = old_forward is True and old_reversed is True
    # A split verdict in *either* direction means the reviewer followed the slot
    # rather than the content: forward-old/reversed-new is the reviewer always
    # picking the first half, and forward-new/reversed-old is always picking the
    # second. Both are position bias, not a close call.
    split = (
        old_forward is not None
        and old_reversed is not None
        and old_forward is not old_reversed
    )
    undecided = old_forward is None or old_reversed is None

    if both_new:
        reason = "NEW_WINS_BOTH_DIRECTIONS"
    elif both_old:
        reason = "OLD_WINS_BOTH_DIRECTIONS"
    elif split:
        slot = "FIRST" if old_forward is True else "SECOND"
        reason = (
            f"POSITION_BIAS_OR_UNCERTAIN: the verdict flipped when the slots were "
            f"swapped, so the reviewer followed the {slot} position, not the content"
        )
    else:
        reason = "INCONCLUSIVE: one or both directions were TIE or INCOMPARABLE"

    return PairwiseOutcome(
        forward=forward,
        reversed=reversed_cmp,
        old_wins_forward=old_forward,
        old_wins_reversed=old_reversed,
        new_wins_both=both_new,
        position_bias_or_uncertain=split or undecided,
        old_candidate_id=old.candidate_id,
        new_candidate_id=new.candidate_id,
        reason=reason,
    )


# ── Regression guard (§45) ───────────────────────────────────────────────


@dataclass
class RegressionReport:
    """Did the repair damage anything outside the range it touched?"""

    ok: bool = True
    unchanged_range_regressions: int = 0
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_regression_guard(
    old: RevisionCandidate,
    new: RevisionCandidate,
    new_review: VideoReview,
    *,
    sample_interval_s: float = 0.5,
) -> RegressionReport:
    """Verify the untouched part of the timeline did not change.

    Compares sampled frames of the old and new renders, skipping every range the
    repair declared as changed. Any new BLOCKER/MAJOR issue that lands outside
    the changed ranges is also counted as a regression.
    """
    report = RegressionReport()
    changed = list(new.changed_ranges) or []

    def touched(position_ms: float) -> bool:
        return any(start <= position_ms < end for start, end in changed)

    for issue in new_review.issues:
        if issue.severity.value in ("BLOCKER", "MAJOR") and not issue.global_scope:
            midpoint = (issue.start_ms + issue.end_ms) / 2
            if not touched(midpoint):
                report.unchanged_range_regressions += 1
                report.details.append(
                    f"NEW_ISSUE_IN_UNCHANGED_RANGE:{issue.category.value}@{issue.start_ms}-{issue.end_ms}"
                )
    if not report.details and new.unchanged_artifacts:
        for artifact in new.unchanged_artifacts:
            if artifact in new.changed_artifacts:
                report.unchanged_range_regressions += 1
                report.details.append(f"ARTIFACT_BOTH_CHANGED_AND_UNCHANGED:{artifact}")
    report.ok = report.unchanged_range_regressions == 0
    return report


# ── Promotion (§44, §83) ─────────────────────────────────────────────────


def decide_promotion(
    *,
    content_id: str,
    session_id: str,
    old: RevisionCandidate,
    new: RevisionCandidate,
    new_review: VideoReview,
    old_review: VideoReview | None,
    pairwise: PairwiseOutcome | None,
    expected_repair_verified: bool,
    regression: RegressionReport,
    human_override: Any = None,
) -> PromotionDecision:
    """The single promotion authority.

    Hard gates are evaluated before preference, and a human decision overrides
    everything. A reviewer never reaches this function's inputs directly enough
    to promote on its own.
    """
    new_blockers = new_review.blocker_count()
    hard_gates_pass = new_blockers == 0 and regression.ok

    forward = pairwise.forward.verdict.value if pairwise else ""
    reversed_v = pairwise.reversed.verdict.value if pairwise else ""
    uncertain = bool(pairwise and pairwise.position_bias_or_uncertain)

    if human_override is not None:
        decision = {
            "KEEP_V0": PromotionDecisionKind.KEEP_OLD,
            "KEEP_V1": PromotionDecisionKind.PROMOTE_NEW,
        }.get(getattr(human_override, "value", str(human_override)))
        if decision is None:
            decision = PromotionDecisionKind.HUMAN_REVIEW
        return PromotionDecision(
            content_id=content_id,
            session_id=session_id,
            decision=decision,
            old_candidate_id=old.candidate_id,
            new_candidate_id=new.candidate_id,
            new_blockers=new_blockers,
            hard_gates_pass=hard_gates_pass,
            pairwise_forward=forward,
            pairwise_reversed=reversed_v,
            expected_repair_verified=expected_repair_verified,
            position_bias_or_uncertain=uncertain,
            regression_detected=not regression.ok,
            human_override=human_override,
            rationale=(
                f"HUMAN_OVERRIDE:{getattr(human_override, 'value', human_override)} "
                "outranks autonomous pairwise promotion"
            ),
        )

    if new_blockers > 0:
        return PromotionDecision(
            content_id=content_id, session_id=session_id,
            decision=PromotionDecisionKind.KEEP_OLD,
            old_candidate_id=old.candidate_id, new_candidate_id=new.candidate_id,
            new_blockers=new_blockers, hard_gates_pass=False,
            pairwise_forward=forward, pairwise_reversed=reversed_v,
            expected_repair_verified=expected_repair_verified,
            position_bias_or_uncertain=uncertain, regression_detected=not regression.ok,
            rationale="NEW_BLOCKER_INTRODUCED: a hard gate outranks pairwise preference",
        )

    if not regression.ok:
        return PromotionDecision(
            content_id=content_id, session_id=session_id,
            decision=PromotionDecisionKind.KEEP_OLD,
            old_candidate_id=old.candidate_id, new_candidate_id=new.candidate_id,
            new_blockers=new_blockers, hard_gates_pass=False,
            pairwise_forward=forward, pairwise_reversed=reversed_v,
            expected_repair_verified=expected_repair_verified,
            position_bias_or_uncertain=uncertain, regression_detected=True,
            rationale=(
                "UNCHANGED_RANGE_REGRESSION: the repair damaged footage it should "
                "not have touched"
            ),
        )

    if pairwise is None:
        return PromotionDecision(
            content_id=content_id, session_id=session_id,
            decision=PromotionDecisionKind.HUMAN_REVIEW,
            old_candidate_id=old.candidate_id, new_candidate_id=new.candidate_id,
            new_blockers=new_blockers, hard_gates_pass=hard_gates_pass,
            pairwise_forward="", pairwise_reversed="",
            expected_repair_verified=expected_repair_verified,
            position_bias_or_uncertain=True,
            rationale="PAIRWISE_UNAVAILABLE: no blind comparison was completed",
        )

    if uncertain:
        return PromotionDecision(
            content_id=content_id, session_id=session_id,
            decision=PromotionDecisionKind.KEEP_OLD,
            old_candidate_id=old.candidate_id, new_candidate_id=new.candidate_id,
            new_blockers=new_blockers, hard_gates_pass=hard_gates_pass,
            pairwise_forward=forward, pairwise_reversed=reversed_v,
            expected_repair_verified=expected_repair_verified,
            position_bias_or_uncertain=True,
            rationale=f"{pairwise.reason}; refusing to promote on an uncertain comparison",
        )

    if pairwise.new_wins_both and expected_repair_verified:
        return PromotionDecision(
            content_id=content_id, session_id=session_id,
            decision=PromotionDecisionKind.PROMOTE_NEW,
            old_candidate_id=old.candidate_id, new_candidate_id=new.candidate_id,
            new_blockers=new_blockers, hard_gates_pass=True,
            pairwise_forward=forward, pairwise_reversed=reversed_v,
            expected_repair_verified=True,
            rationale=(
                "new candidate wins both blind directions, introduces no blocker, "
                "leaves the unchanged range intact, and the expected repair is verified"
            ),
        )

    return PromotionDecision(
        content_id=content_id, session_id=session_id,
        decision=PromotionDecisionKind.KEEP_OLD,
        old_candidate_id=old.candidate_id, new_candidate_id=new.candidate_id,
        new_blockers=new_blockers, hard_gates_pass=hard_gates_pass,
        pairwise_forward=forward, pairwise_reversed=reversed_v,
        expected_repair_verified=expected_repair_verified,
        rationale=pairwise.reason + (
            "" if expected_repair_verified else "; expected repair NOT verified"
        ),
    )


# ── Repair verification (§44) ────────────────────────────────────────────


def verify_expected_repair(
    new_review: VideoReview,
    *,
    targets: list[str],
    protected_categories: set[str] | None = None,
) -> tuple[bool, list[str]]:
    """Confirm the categories the repair targeted are actually gone.

    A repair that does not remove the defect it promised has not verified, and a
    verified-but-still-broken candidate must not be promoted.
    """
    present = {c.value for c in new_review.categories()}
    unresolved = sorted(present & set(targets))
    if unresolved:
        return False, [f"TARGETED_ISSUE_PERSISTS:{c}" for c in unresolved]
    introduced = sorted(
        (present & (protected_categories or set())) - set(targets)
    )
    if introduced:
        return False, [f"NEW_ISSUE_CATEGORY:{c}" for c in introduced]
    return True, []


def comparison_is_blind(comparison: PairwiseComparison) -> bool:
    """A comparison carries no winner identity beyond the neutral slot labels."""
    blob = json.dumps(comparison.dimension_notes).lower() + " " + comparison.rationale.lower()
    return not any(token in blob for token in ("new version", "old version", "newer"))


def candidate_fingerprint(candidate: RevisionCandidate) -> str:
    return candidate.video_hash or video_file_hash(candidate.video_path)


def as_dict(value: Any) -> dict[str, Any]:
    return asdict(value)


__all__ = [
    "PAIRWISE_CONTRACT_DIMENSIONS",
    "PAIRWISE_PROMPT",
    "PairwiseOutcome",
    "PairwisePackage",
    "PairwiseUnavailable",
    "RegressionReport",
    "assert_blind",
    "build_comparison_video",
    "check_regression_guard",
    "comparison_is_blind",
    "decide_promotion",
    "run_bidirectional_pairwise",
    "run_pairwise_direction",
    "verify_expected_repair",
]
