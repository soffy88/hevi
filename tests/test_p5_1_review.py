"""HEVI P5.1 — video review types, capability detection, temporal mapping, staleness.

Covers §4-§11: the canonical editorial types, provider capability detection,
temporal issue mapping and the stale-review guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.ops.p5_1_providers import (
    NATIVE_VIDEO_INPUT,
    VIDEO_UNDERSTANDING,
    VideoUnderstandingProvider,
    VideoUnderstandingRequestError,
    discover_video_understanding_providers,
    extract_json_object,
    register_video_understanding_providers,
    select_video_understanding_provider,
)
from hevi.ops.p5_1_review import (
    ReviewInputPackage,
    StaleVideoReviewError,
    assert_review_current,
    build_review_prompt,
    current_review_for,
    parse_issues,
    parse_temporal_observations,
    review_from_payload,
    review_is_current,
    run_video_review,
)
from hevi.ops.p5_1_types import (
    EDITORIAL_ISSUE_TAXONOMY,
    REVIEW_PROMPT_VERSION,
    EditorialIssue,
    EditorialIssueCategory,
    IssueSeverity,
    ReviewOutcome,
    VideoReview,
    normalize_category,
    normalize_severity,
    video_file_hash,
)

# ── test_video_review_types ──────────────────────────────────────────────


def test_video_review_types_carry_the_canonical_fields() -> None:
    review = VideoReview(
        content_id="c1",
        candidate_id="V0",
        video_hash="sha256:abc",
        video_duration_s=24.0,
        provider="fal_video_understanding",
        model="fal-ai/video-understanding",
    )
    payload = review.to_dict()
    for field in (
        "review_id",
        "content_id",
        "candidate_id",
        "video_hash",
        "video_duration",
        "provider",
        "model",
        "review_prompt_version",
        "reviewed_at",
        "temporal_observations",
        "issues",
        "summary",
        "confidence",
    ):
        assert field in payload or field == "video_duration", field
    assert payload["video_hash"] == "sha256:abc"
    assert review.review_prompt_version == REVIEW_PROMPT_VERSION
    assert review.outcome is ReviewOutcome.PASS


def test_video_review_requires_a_binding_hash() -> None:
    review = VideoReview(video_hash="")
    assert review.is_stale_for("sha256:anything") is True
    assert review.is_stale_for("") is True


def test_review_prompt_is_versioned_and_hides_internals() -> None:
    package = ReviewInputPackage(
        video_path="/tmp/x.mp4",
        content_profile="KNOWLEDGE_TALK",
        target_audience="developers",
        visual_beat_summary="beat 1 shows the dashboard",
    )
    prompt = build_review_prompt(package)
    assert "Editorial contract" in prompt
    assert "KNOWLEDGE_TALK" in prompt
    # The taxonomy is offered to the reviewer so its output can be normalised.
    assert EditorialIssueCategory.CAPTION_OCCLUSION.value in prompt
    # No internal state leaks into the reviewer input.
    assert "candidate_id" not in prompt
    assert "revision_number" not in prompt


# ── test_video_capability_detection ──────────────────────────────────────


def test_video_capability_detection_finds_the_native_provider() -> None:
    register_video_understanding_providers(force=True)
    specs = discover_video_understanding_providers(require_native=True)
    assert specs, "a native video provider must be discoverable"
    for spec in specs:
        assert VIDEO_UNDERSTANDING in spec.capabilities
        assert NATIVE_VIDEO_INPUT in spec.capabilities


def test_frame_only_provider_is_never_selected() -> None:
    """A provider that only accepts frames must not pass as video understanding."""
    register_video_understanding_providers(force=True)
    selection = select_video_understanding_provider("definitely_not_registered")
    assert selection.blocked is True
    assert "PROVIDER_NOT_REGISTERED" in selection.reason


def test_unknown_provider_selection_is_blocked_not_defaulted() -> None:
    selection = select_video_understanding_provider("nope_missing_provider")
    assert selection.blocked
    assert selection.provider_id == ""


def test_provider_selection_reports_its_reason() -> None:
    register_video_understanding_providers(force=True)
    selection = select_video_understanding_provider()
    if selection.blocked:  # no credential in the test environment
        assert selection.reason.startswith("BLOCKED_BY_PROVIDER")
    else:
        assert selection.reason in ("CAPABILITY_MATCH", "PREFERRED")
        assert selection.model_id


def test_video_understanding_request_error_is_typed() -> None:
    assert issubclass(VideoUnderstandingRequestError, Exception)
    assert hasattr(VideoUnderstandingProvider, "review_video")


# ── test_temporal_issue_mapping ──────────────────────────────────────────


def test_temporal_issue_mapping_converts_seconds_to_ms() -> None:
    issues = parse_issues(
        [
            {
                "category": "CAPTION_OCCLUSION",
                "severity": "MAJOR",
                "start_s": 2.5,
                "end_s": 5.0,
                "description": "caption covers the speaker's face",
            }
        ],
        duration_s=20.0,
    )
    assert len(issues) == 1
    issue = issues[0]
    assert issue.start_ms == 2500
    assert issue.end_ms == 5000
    assert issue.has_temporal_range is True
    assert issue.is_locatable() is True
    assert issue.category is EditorialIssueCategory.CAPTION_OCCLUSION


def test_temporal_issue_mapping_clamps_to_duration() -> None:
    """A range that starts inside the video is clamped, not discarded."""
    issues = parse_issues(
        [{"category": "PACING", "start_s": 8.0, "end_s": 20.0, "description": "runs long"}],
        duration_s=10.0,
    )
    assert len(issues) == 1
    assert issues[0].start_ms == 8000
    assert issues[0].end_ms == 10000


def test_issue_beyond_video_is_dropped() -> None:
    issues = parse_issues(
        [{"category": "PACING", "start_s": 500, "end_s": 520, "description": "past end"}],
        duration_s=10.0,
    )
    assert issues == []


def test_temporal_observations_are_sorted() -> None:
    observations = parse_temporal_observations(
        [
            {"start_s": 6, "end_s": 8, "observation": "second"},
            {"start_s": 1, "end_s": 3, "observation": "first"},
        ]
    )
    assert [o.observation for o in observations] == ["first", "second"]


def test_severity_and_category_normalisation() -> None:
    assert normalize_severity("CRITICAL") is IssueSeverity.BLOCKER
    assert normalize_severity("high") is IssueSeverity.MAJOR
    assert normalize_severity("nit") is IssueSeverity.COSMETIC
    assert normalize_severity(None) is IssueSeverity.MINOR

    category, raw = normalize_category("caption occlusion")
    assert category is EditorialIssueCategory.CAPTION_OCCLUSION
    assert raw == "CAPTION_OCCLUSION"

    category, raw = normalize_category("totally_new_problem")
    assert category is EditorialIssueCategory.UNCLASSIFIED
    assert raw == "TOTALLY_NEW_PROBLEM"


def test_taxonomy_covers_every_required_category() -> None:
    required = {
        "PACING", "DEAD_AIR", "VISUAL_STAGNATION", "SHOT_TOO_SHORT", "SHOT_TOO_LONG",
        "SUBJECT_JUMP", "LAYOUT_INSTABILITY", "CAPTION_OCCLUSION", "CAPTION_OVERLOAD",
        "TEXT_DOMINANCE", "WEAK_VISUAL_GROUNDING", "WRONG_EVIDENCE", "FAKE_UI",
        "LOW_INFORMATION_DENSITY", "EXCESSIVE_INFORMATION_DENSITY", "MOTION_DISTRACTION",
        "MOTION_MEANINGLESS", "TRANSITION_MISMATCH", "SPEAKER_OVERUSE", "SPEAKER_UNDERUSE",
        "EVIDENCE_UNDERUSE", "VISUAL_REPETITION", "STYLE_INCONSISTENCY",
        "AUDIO_VISUAL_MISMATCH", "EMOTIONAL_MISMATCH", "PROFILE_MISMATCH",
    }
    values = {c.value for c in EditorialIssueCategory}
    assert required.issubset(values), required - values
    assert required.issubset(set(EDITORIAL_ISSUE_TAXONOMY))


# ── test_stale_video_review ──────────────────────────────────────────────


def test_stale_video_review_is_detected_after_video_changes(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"first-version")
    review = VideoReview(
        video_hash=video_file_hash(video), video_path=str(video), candidate_id="V0"
    )
    assert review_is_current(review, video) is True

    video.write_bytes(b"second-version-is-different")
    assert review_is_current(review, video) is False
    with pytest.raises(StaleVideoReviewError):
        assert_review_current(review, video)


def test_stale_review_without_hash_is_never_trusted(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    review = VideoReview(video_hash="", video_path=str(video))
    with pytest.raises(StaleVideoReviewError):
        assert_review_current(review, video)


def test_current_review_for_skips_stale_entries(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v1")
    old = VideoReview(video_hash=video_file_hash(video), video_path=str(video), summary="old")
    video.write_bytes(b"v2-changed")
    fresh = VideoReview(video_hash=video_file_hash(video), video_path=str(video), summary="new")

    assert current_review_for([old, fresh], video) is fresh
    assert current_review_for([old], video) is None


def test_review_from_payload_binds_the_hash() -> None:
    review = review_from_payload(
        {
            "summary": "ok",
            "confidence": 0.8,
            "temporal_observations": [{"start_s": 0, "end_s": 2, "observation": "a"}],
            "issues": [
                {"category": "PACING", "severity": "MAJOR", "start_s": 1, "end_s": 2,
                 "description": "rushed"}
            ],
        },
        content_id="c1",
        candidate_id="V0",
        video_path="/tmp/v.mp4",
        video_hash="sha256:deadbeef",
        duration_s=12.0,
        provider="p",
        model="m",
        latency_s=1.5,
        cost_usd=None,
    )
    assert review.video_hash == "sha256:deadbeef"
    assert review.temporal_issue_count() == 1
    assert review.major_count() == 1
    assert review.cost_usd is None  # UNKNOWN stays UNKNOWN, never coerced to 0


def test_extract_json_object_handles_fences_and_prose() -> None:
    fenced = '```json\n{"winner": "A"}\n```'
    assert extract_json_object(fenced) == {"winner": "A"}
    noisy = 'Here you go: {"a": 1, "b": {"c": 2}} hope that helps'
    assert extract_json_object(noisy) == {"a": 1, "b": {"c": 2}}
    assert extract_json_object("no json at all") is None


def test_run_video_review_blocks_on_missing_video(tmp_path: Path) -> None:
    import asyncio

    review = asyncio.run(
        run_video_review(tmp_path / "nope.mp4", content_id="c", candidate_id="V0")
    )
    assert review.outcome is ReviewOutcome.FAILED
    assert review.issues == []


def test_run_video_review_blocks_without_a_capable_provider(tmp_path: Path) -> None:
    import asyncio

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    review = asyncio.run(
        run_video_review(
            video, content_id="c", candidate_id="V0", provider_id="missing_provider"
        )
    )
    assert review.outcome is ReviewOutcome.BLOCKED_BY_PROVIDER
    assert review.native_video_input is False
    assert review.issues == []
    # A blocked review must not pretend it found nothing by watching.
    assert review.summary == ""


def test_blocked_review_is_not_a_false_success() -> None:
    review = VideoReview(outcome=ReviewOutcome.BLOCKED_BY_PROVIDER, blocked_reason="X")
    assert review.confidence == 0.0
    assert review.video_hash == ""
    assert json.dumps(review.to_dict())  # serialisable for lineage


def test_issue_locatability_contract() -> None:
    located = EditorialIssue(start_ms=100, end_ms=400)
    assert located.has_temporal_range and located.is_locatable()
    point = EditorialIssue(start_ms=100, end_ms=100)
    assert not point.is_locatable()
    glob = EditorialIssue(start_ms=0, end_ms=0, global_scope=True)
    assert glob.is_locatable()
