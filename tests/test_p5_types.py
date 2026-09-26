"""P5 types unit tests."""

from __future__ import annotations

import pytest

from hevi.ops.p5_types import (
    BookSourceBundle,
    ContentRequest,
    ContentScript,
    ContentFingerprint,
    VoiceProfile,
    VoicePerformance,
    ApprovalRequest,
    ApprovalPolicySet,
    ApprovalType,
    ApprovalStatus,
    ApprovalPolicy,
    ContentStatus,
    SourceKind,
    VisualProvenance,
    Platform,
    ProductionAsset,
    ProductionAssetPack,
    MusicPolicy,
    AudioMixManifest,
    CaptionStyleProfile,
    ContentQualityReport,
    CostReport,
    BatchCostSummary,
    EditableProjectManifest,
    ContentFactoryRequest,
    TopicCandidate,
    validate_content_request,
    validate_book_source,
    validate_voice_pacing,
)


def test_content_request_validation() -> None:
    req = ContentRequest(
        topic="Test Book Review",
        profile_id="EMOTIONAL_BOOK_REVIEW",
        book_source=BookSourceBundle(
            book_title="Test Book",
            author="Test Author",
            verified_facts=["fact 1"],
        )
    )
    errors = validate_content_request(req)
    assert errors == []


def test_content_request_validation_fails_without_book() -> None:
    req = ContentRequest(
        topic="Test Book Review",
        profile_id="EMOTIONAL_BOOK_REVIEW",
    )
    errors = validate_content_request(req)
    assert any("book_source" in e for e in errors)


def test_book_source_validation() -> None:
    bundle = BookSourceBundle(
        book_title="Test Book",
        author="Test Author",
        verified_facts=["fact 1"],
        verified_quotes=[("quote 1", "p. 1")],
    )
    errors = validate_book_source(bundle)
    assert errors == []


def test_book_source_validation_fails() -> None:
    bundle = BookSourceBundle(
        book_title="Test Book",
        author="Test Author",
    )
    errors = validate_book_source(bundle)
    assert any("verified_facts" in e for e in errors)


def test_voice_pacing_validation() -> None:
    perf = VoicePerformance(
        performance_id="vp-1",
        content_id="c1",
        voice_profile_id="vp-1",
        script_revision=1,
        audio_path="/tmp/test.wav",
        audio_hash="abc",
        duration_s=10.0,
        actual_chars_per_second=4.56,
    )
    assert validate_voice_pacing(perf, 4.56, 0.15) is True
    assert validate_voice_pacing(perf, 10.0, 0.15) is False


def test_content_request_to_production_job() -> None:
    req = ContentRequest(
        topic="Test",
        profile_id="EMOTIONAL_BOOK_REVIEW",
        book_source=BookSourceBundle(
            book_title="Book",
            author="Author",
            verified_facts=["fact"],
        )
    )
    job = req.to_production_job()
    assert job.job_id == req.content_id
    assert job.profile_id == "EMOTIONAL_BOOK_REVIEW"
    assert job.book_meta["title"] == "Book"


def test_approval_request_states() -> None:
    appr = ApprovalRequest(
        approval_id="appr-1",
        content_id="c1",
        type="SCRIPT",
        revision=1,
    )
    assert not appr.is_terminal()
    appr.status = ApprovalStatus.APPROVED
    assert appr.is_terminal()


def test_approval_policy_check() -> None:
    from hevi.ops.p5_approval import check_approval_policy
    skip, reason = check_approval_policy(ApprovalPolicy.SKIP)
    assert skip and reason == "SKIP"

    skip, reason = check_approval_policy(ApprovalPolicy.AUTO_IF_CONFIDENT, 0.95)
    assert skip and reason == "AUTO_IF_CONFIDENT"

    skip, reason = check_approval_policy(ApprovalPolicy.AUTO_IF_CONFIDENT, 0.5)
    assert not skip and reason == "REQUIRED"

    skip, reason = check_approval_policy(ApprovalPolicy.REQUIRED)
    assert not skip and reason == "REQUIRED"


def test_content_fingerprint() -> None:
    fp = ContentFingerprint(
        content_id="c1",
        book_topic="Test Book",
        situation="loneliness",
        emotion="loneliness",
        argument="solitude is strength",
        script_hash="abc",
        voice_hash="def",
        visual_plan_hash="ghi",
    )
    assert fp.content_id == "c1"


def test_content_quality_report() -> None:
    report = ContentQualityReport(content_id="c1")
    assert report.overall_pass() is False

    report.source_truth = True
    report.script_quality = True
    report.voice_alignment = True
    report.voice_pacing = True
    report.visual_grounding = True
    report.visual_progression = True
    report.caption_sync = True
    report.music_mix = True
    report.profile_quality = True
    report.final_qa = True
    assert report.overall_pass() is True


def test_cost_report() -> None:
    cost = CostReport(content_id="c1", tts_usd=1.0, visual_usd=2.0)
    assert cost.total_usd == 0.0  # not auto-calculated


def test_batch_cost_summary() -> None:
    batch = BatchCostSummary(
        batch_id="b1",
        items=[CostReport(content_id="c1", total_usd=5.0), CostReport(content_id="c2", total_usd=3.0)]
    )
    assert batch.total_usd == 0.0  # not auto-calculated


def test_editable_project_manifest() -> None:
    manifest = EditableProjectManifest(
        project_type="jianying",
        project_path="/tmp/project",
        duration_s=120.0,
    )
    assert manifest.project_type == "jianying"


def test_content_factory_request() -> None:
    factory = ContentFactoryRequest(
        items=[
            ContentRequest(topic="Test 1", profile_id="EMOTIONAL_BOOK_REVIEW",
                          book_source=BookSourceBundle(book_title="B1", author="A1", verified_facts=["f"])),
            ContentRequest(topic="Test 2", profile_id="EMOTIONAL_BOOK_REVIEW",
                          book_source=BookSourceBundle(book_title="B2", author="A2", verified_facts=["f"])),
        ],
        concurrency_limit=2,
    )
    assert len(factory.items) == 2


def test_topic_candidate() -> None:
    tc = TopicCandidate(
        book_title="Test Book",
        author="Author",
        situation="loneliness",
        emotion="loneliness",
        hook="Opening hook",
        reason="Good fit",
        source_confidence=0.9,
    )
    assert tc.source_confidence == 0.9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])