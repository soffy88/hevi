"""HEVI P5.1 — native video review execution.

Turns a real candidate video into a formal :class:`VideoReview` artifact.

Rules enforced here:

* The reviewer receives a *review input package* (§10): the video, the script /
  transcript, the content profile, the target audience, a VisualBeat summary and
  a ShotPlan summary. It does **not** receive HEVI's internal implementation
  dump, nor which candidate is newer.
* A review is bound to the exact ``video_hash`` of the bytes that were reviewed.
  :func:`assert_review_current` refuses to let a stale review stand in for a
  changed video, which is what keeps ``STALE_VIDEO_REVIEW_REUSE == 0``.
* Provider selection is capability-aware. A blocked provider yields
  ``BLOCKED_BY_PROVIDER`` — never a frame-only substitute.
* Severity and category vocabularies are normalised onto the canonical taxonomy
  so downstream diagnosis never branches on provider wording.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.ops.p5_1_providers import (
    VideoReviewRequest,
    VideoUnderstandingCallError,
    VideoUnderstandingUnavailable,
    extract_json_object,
    probe_duration_s,
    probe_native_video_input,
    select_video_understanding_provider,
)
from hevi.ops.p5_1_providers import get_provider as _get_provider
from hevi.ops.p5_1_types import (
    REVIEW_PROMPT_VERSION,
    EditorialIssue,
    EditorialIssueCategory,
    ReviewOutcome,
    TemporalObservation,
    VideoReview,
    normalize_category,
    normalize_severity,
    video_file_hash,
)


class StaleVideoReviewError(RuntimeError):
    """A review was reused after the reviewed video changed."""


# ── Review input package (§10) ───────────────────────────────────────────


@dataclass
class ReviewInputPackage:
    """Exactly what the reviewer is allowed to see.

    Deliberately excludes internal implementation state, the candidate's
    revision number, its cost, and whether it is newer than another candidate.
    """

    video_path: str
    script_text: str = ""
    transcript: str = ""
    content_profile: str = ""
    target_audience: str = ""
    visual_beat_summary: str = ""
    shot_plan_summary: str = ""
    reference_video_path: str = ""
    source_manifest: str = ""
    previous_candidate_summary: str = ""
    contract_version: str = REVIEW_PROMPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "has_reference_video": bool(self.reference_video_path),
            "has_transcript": bool(self.transcript),
            "has_beat_summary": bool(self.visual_beat_summary),
            "has_shot_summary": bool(self.shot_plan_summary),
        }


def build_review_prompt(package: ReviewInputPackage) -> str:
    """Build the versioned reviewer prompt for one candidate.

    The prompt states the *editorial contract* to judge against, not HEVI's
    internals, and requires a single JSON object with temporal ranges.
    """
    parts: list[str] = [
        "You are the editorial reviewer for a finished video. Watch the entire "
        "clip as a video and judge it against the editorial contract below.",
        "",
        "## Editorial contract",
        "Report ONLY problems you can actually observe in the video. Do not invent "
        "problems. Every issue must carry a time range in seconds.",
        "Severity vocabulary: BLOCKER (unusable: black/blank frames, frozen or "
        "broken video, captions covering the subject, evidence that does not match "
        "the claim, a fabricated interface presented as real, obvious audio/visual "
        "mismatch), MAJOR (clearly degrades the video), MINOR (small but real), "
        "COSMETIC (polish only).",
        f"Category vocabulary (choose from this list only): "
        f"{', '.join(c.value for c in EditorialIssueCategory if c is not EditorialIssueCategory.UNCLASSIFIED)}.",
        "Set \"is_global\": true only for a defect that is a property of the whole "
        "cut rather than one moment.",
        "",
        "## Production intent",
        f"Content profile: {package.content_profile or 'unspecified'}",
        f"Target audience: {package.target_audience or 'unspecified'}",
    ]
    if package.visual_beat_summary:
        parts += ["", "## Intended visual beats (the plan this render should follow)",
                  package.visual_beat_summary]
    if package.shot_plan_summary:
        parts += ["", "## Intended shot plan", package.shot_plan_summary]
    if package.script_text or package.transcript:
        text = package.transcript or package.script_text
        parts += ["", "## Narration", text[:4000]]
    parts += [
        "",
        "## Required output",
        "Return ONLY a JSON object, no prose and no markdown fence:",
        "{",
        '  "summary": "one paragraph on what the video actually shows and how well '
        'it works editorially",',
        '  "confidence": 0.0,',
        '  "temporal_observations": [{"start_s": 0.0, "end_s": 0.0, '
        '"observation": "what is on screen in this window"}],',
        '  "issues": [{"category": "PACE", "severity": "MAJOR", "start_s": 0.0, '
        '"end_s": 0.0, "is_global": false, "description": "what is wrong and why it '
        'hurts", "evidence": "what in the video proves it", "confidence": 0.0, '
        '"repair_hint": "the single most useful change"}]',
        "}",
    ]
    return "\n".join(parts)


# ── Parsing / normalisation ──────────────────────────────────────────────

_MAX_DURATION_S = 24 * 60 * 60


def _to_ms(value: Any, *, default: int = 0) -> int:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return default
    if seconds < 0:
        return 0
    return int(min(seconds, _MAX_DURATION_S) * 1000)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, result))


def parse_temporal_observations(raw: Any) -> list[TemporalObservation]:
    out: list[TemporalObservation] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("observation") or item.get("text") or "").strip()
        if not text:
            continue
        out.append(
            TemporalObservation(
                start_ms=_to_ms(item.get("start_s") or item.get("start_ms")),
                end_ms=_to_ms(item.get("end_s") or item.get("end_ms")),
                observation=text[:600],
            )
        )
    out.sort(key=lambda o: (o.start_ms, o.end_ms))
    return out


def parse_issues(
    raw: Any, *, duration_s: float
) -> list[EditorialIssue]:
    """Normalise provider issues onto the canonical taxonomy.

    Timestamps are clamped into the video's real duration. An issue whose range
    is entirely outside the video is dropped rather than repaired against a
    location that does not exist.
    """
    out: list[EditorialIssue] = []
    if not isinstance(raw, list):
        return out
    limit_ms = int(duration_s * 1000) if duration_s > 0 else 0

    for item in raw:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue

        category, raw_label = normalize_category(item.get("category"))
        severity = normalize_severity(item.get("severity"))
        is_global = bool(item.get("is_global") or item.get("global"))

        start_ms = _to_ms(item.get("start_s") if item.get("start_s") is not None else item.get("start_ms"))
        end_ms = _to_ms(item.get("end_s") if item.get("end_s") is not None else item.get("end_ms"))
        if limit_ms:
            start_ms = min(start_ms, limit_ms)
            end_ms = min(end_ms, limit_ms)
        if end_ms < start_ms:
            start_ms, end_ms = end_ms, start_ms
        if not is_global and start_ms == end_ms:
            # A zero-width non-global issue cannot drive a targeted repair.
            end_ms = min(start_ms + 1, limit_ms) if limit_ms else start_ms + 1
        if limit_ms and start_ms >= limit_ms and not is_global:
            continue

        out.append(
            EditorialIssue(
                category=category,
                raw_category=raw_label,
                severity=severity,
                start_ms=start_ms,
                end_ms=end_ms,
                description=description[:1200],
                evidence=str(item.get("evidence") or "").strip()[:600],
                confidence=_to_float(item.get("confidence"), 0.5),
                repair_hint=str(item.get("repair_hint") or "").strip()[:400],
                global_scope=is_global,
            )
        )

    out.sort(key=lambda i: (i.severity.value, i.start_ms))
    return out


def review_from_payload(
    payload: dict[str, Any],
    *,
    content_id: str,
    candidate_id: str,
    video_path: str,
    video_hash: str,
    duration_s: float,
    provider: str,
    model: str,
    latency_s: float,
    cost_usd: float | None,
    raw_payload: dict[str, Any] | None = None,
) -> VideoReview:
    """Build a formal :class:`VideoReview` from a reviewer JSON payload."""
    return VideoReview(
        content_id=content_id,
        candidate_id=candidate_id,
        video_hash=video_hash,
        video_path=str(video_path),
        video_duration_s=round(duration_s, 3),
        provider=provider,
        model=model,
        review_prompt_version=REVIEW_PROMPT_VERSION,
        temporal_observations=parse_temporal_observations(payload.get("temporal_observations")),
        issues=parse_issues(payload.get("issues"), duration_s=duration_s),
        summary=str(payload.get("summary") or "").strip()[:4000],
        confidence=_to_float(payload.get("confidence"), 0.5),
        native_video_input=True,
        latency_s=latency_s,
        cost_usd=cost_usd,
        outcome=ReviewOutcome.PASS,
        raw_provider_payload=raw_payload or {},
    )


# ── Staleness guard (§5, adversarial A2) ─────────────────────────────────


def assert_review_current(review: VideoReview, video_path: str | Path) -> None:
    """Raise if the review no longer describes the bytes on disk."""
    if not review.video_hash:
        raise StaleVideoReviewError(
            f"review {review.review_id} carries no video_hash and cannot be trusted"
        )
    current = video_file_hash(video_path)
    if review.is_stale_for(current):
        raise StaleVideoReviewError(
            f"review {review.review_id} was made against {review.video_hash[:19]}... "
            f"but the video is now {current[:19]}...; re-review required"
        )


def review_is_current(review: VideoReview, video_path: str | Path) -> bool:
    try:
        assert_review_current(review, video_path)
    except StaleVideoReviewError:
        return False
    return True


def current_review_for(
    reviews: list[VideoReview], video_path: str | Path
) -> VideoReview | None:
    """Return the newest review that is still bound to the current video bytes."""
    for review in reversed(reviews):
        if review_is_current(review, video_path):
            return review
    return None


# ── Review execution ─────────────────────────────────────────────────────


def blocked_review(
    content_id: str, candidate_id: str, video_path: str, *, reason: str, outcome: ReviewOutcome
) -> VideoReview:
    """A review artifact that honestly records a block.

    It carries no issues, because nothing was actually watched. Pretending a
    blocked review found nothing would be a false success.
    """
    return VideoReview(
        content_id=content_id,
        candidate_id=candidate_id,
        video_path=str(video_path),
        video_hash="",
        provider="",
        model="",
        native_video_input=False,
        outcome=outcome,
        blocked_reason=reason,
        summary="",
        confidence=0.0,
    )


async def run_video_review(
    video_path: str | Path,
    *,
    content_id: str,
    candidate_id: str,
    package: ReviewInputPackage | None = None,
    provider_id: str | None = None,
    require_native_probe: bool = False,
    timeout_s: float = 300.0,
    retries: int = 2,
    retry_backoff_s: float = 8.0,
) -> VideoReview:
    """Run one native video review and return a formal ``VideoReview``.

    Failure modes are reported, never hidden:

    * no native-video provider -> ``BLOCKED_BY_PROVIDER``
    * provider rejected the call -> ``BLOCKED_BY_PROVIDER``
    * provider answered but not with reviewable content -> ``FAILED``
    * a required native probe failed -> ``BLOCKED_BY_NATIVE_INPUT``
    """
    video = Path(video_path)
    if not video.is_file():
        return blocked_review(
            content_id, candidate_id, str(video),
            reason=f"VIDEO_MISSING:{video}", outcome=ReviewOutcome.FAILED,
        )

    selection = select_video_understanding_provider(provider_id)
    if selection.blocked:
        return blocked_review(
            content_id, candidate_id, str(video),
            reason=selection.reason, outcome=ReviewOutcome.BLOCKED_BY_PROVIDER,
        )

    if require_native_probe:
        probe = await probe_native_video_input(
            selection.provider_id, workdir=Path("/tmp/hevi_p5_1_probe")
        )
        if not probe.native_video_input:
            return blocked_review(
                content_id, candidate_id, str(video),
                reason=f"NATIVE_PROBE_FAILED:{probe.reason}",
                outcome=ReviewOutcome.BLOCKED_BY_NATIVE_INPUT,
            )

    pkg = package or ReviewInputPackage(video_path=str(video))
    prompt = build_review_prompt(pkg)

    try:
        provider = _get_provider(selection.provider_id)
    except VideoUnderstandingUnavailable as exc:
        return blocked_review(
            content_id, candidate_id, str(video),
            reason=exc.reason, outcome=ReviewOutcome.BLOCKED_BY_PROVIDER,
        )

    request = VideoReviewRequest(
        video_path=str(video),
        prompt=prompt,
        transcript=pkg.transcript or pkg.script_text,
        content_profile=pkg.content_profile,
        target_audience=pkg.target_audience,
        visual_beat_summary=pkg.visual_beat_summary,
        shot_plan_summary=pkg.shot_plan_summary,
        timeout_s=timeout_s,
    )

    started = time.monotonic()
    response = None
    last_error: VideoUnderstandingCallError | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            response = await provider.review_video(request)
            break
        except VideoUnderstandingUnavailable as exc:
            return blocked_review(
                content_id, candidate_id, str(video),
                reason=exc.reason, outcome=ReviewOutcome.BLOCKED_BY_PROVIDER,
            )
        except VideoUnderstandingCallError as exc:
            last_error = exc
            if attempt >= retries or not exc.is_retryable:
                break
            # A quota hold can clear; back off rather than hammering it.
            await asyncio.sleep(retry_backoff_s * (attempt + 1))
    if response is None:
        return blocked_review(
            content_id, candidate_id, str(video),
            reason=f"PROVIDER_CALL_FAILED:{last_error.reason if last_error else 'NO_RESPONSE'}",
            outcome=ReviewOutcome.BLOCKED_BY_PROVIDER,
        )
    latency = time.monotonic() - started

    payload = extract_json_object(response.text)
    if payload is None:
        return blocked_review(
            content_id, candidate_id, str(video),
            reason="REVIEWER_RETURNED_NO_STRUCTURED_OUTPUT",
            outcome=ReviewOutcome.FAILED,
        )
    if "issues" not in payload and "temporal_observations" not in payload:
        return blocked_review(
            content_id, candidate_id, str(video),
            reason="REVIEWER_RETURNED_NO_REVIEW_FIELDS",
            outcome=ReviewOutcome.FAILED,
        )

    return review_from_payload(
        payload,
        content_id=content_id,
        candidate_id=candidate_id,
        video_path=str(video),
        video_hash=video_file_hash(video),
        duration_s=probe_duration_s(video),
        provider=response.provider,
        model=response.model or selection.model_id,
        latency_s=latency,
        cost_usd=response.cost_usd,
        raw_payload=response.raw,
    )


__all__ = [
    "ReviewInputPackage",
    "StaleVideoReviewError",
    "assert_review_current",
    "blocked_review",
    "build_review_prompt",
    "current_review_for",
    "parse_issues",
    "parse_temporal_observations",
    "review_from_payload",
    "review_is_current",
    "run_video_review",
]
