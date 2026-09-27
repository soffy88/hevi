"""HEVI P5.1 — evidence truth, fake-UI rejection, screenshot privacy.

Covers §15-§20 and §58-§60: the evidence-first ladder, the closed truth rules,
freshness and the privacy gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hevi.ops.p5_1_evidence import (
    apply_privacy_policy,
    assert_evidence_truth,
    classify_evidence_need,
    evaluate_evidence_freshness,
    evidence_truth_check,
    rank_evidence,
    scan_privacy,
    select_best_evidence,
    strip_sensitive_query,
)
from hevi.ops.p5_1_types import (
    EVIDENCE_PRIORITY,
    REALITY_ASSERTING_TYPES,
    EvidenceAsset,
    EvidenceFreshness,
    EvidenceRequest,
    EvidenceSourceType,
)


def _asset(**kwargs: object) -> EvidenceAsset:
    base: dict[str, object] = {
        "source_type": EvidenceSourceType.OFFICIAL_SCREENSHOT,
        "claim_supported": "Acme Console supports bulk export",
        "entity": "Acme Console",
        "captured_at": "2026-09-01T00:00:00Z",
        "source_uri": "https://docs.acme.dev/console",
        "confidence": 0.9,
    }
    base.update(kwargs)
    return EvidenceAsset(**base)  # type: ignore[arg-type]


# ── test_evidence_truth ──────────────────────────────────────────────────


def test_evidence_truth_accepts_a_real_capture() -> None:
    verdict = assert_evidence_truth(_asset())
    assert verdict.ok, verdict.violations
    assert verdict.violations == []


def test_evidence_truth_rejects_real_claiming_without_capture_time() -> None:
    verdict = assert_evidence_truth(_asset(captured_at=""))
    assert not verdict.ok
    assert "REALITY_ASSERTING_WITHOUT_CAPTURE_TIME" in verdict.violations


def test_evidence_truth_rejects_real_claiming_without_a_source() -> None:
    verdict = assert_evidence_truth(_asset(source_uri=""))
    assert not verdict.ok
    assert "REALITY_ASSERTING_WITHOUT_SOURCE" in verdict.violations


def test_evidence_ladder_is_ordered_best_first() -> None:
    assert EVIDENCE_PRIORITY[0] is EvidenceSourceType.OFFICIAL_SCREENSHOT
    assert EVIDENCE_PRIORITY[-1] is EvidenceSourceType.SYMBOLIC
    assert EVIDENCE_PRIORITY.index(EvidenceSourceType.REAL_INTERFACE) < (
        EVIDENCE_PRIORITY.index(EvidenceSourceType.GENERATED_VISUALIZATION)
    )


def test_capability_claim_forbids_generated_evidence() -> None:
    plan = classify_evidence_need(claim="这个产品支持批量导出", entity="Acme")
    assert plan.requires_real is True
    assert EvidenceSourceType.GENERATED_VISUALIZATION in plan.forbidden_types
    assert EvidenceSourceType.REAL_INTERFACE in plan.acceptable_types


def test_non_capability_claim_is_not_forced_to_real_evidence() -> None:
    plan = classify_evidence_need(claim="a story about a train", entity="")
    assert plan.requires_real is False


def test_evidence_ranking_follows_the_ladder() -> None:
    symbolic = _asset(
        source_type=EvidenceSourceType.SYMBOLIC,
        claim_supported="",
        entity="",
        captured_at="",
        source_uri="",
        confidence=0.99,
    )
    real = _asset(confidence=0.7)
    ranked = rank_evidence([symbolic, real])
    assert ranked[0].source_type is EvidenceSourceType.OFFICIAL_SCREENSHOT


def test_select_best_evidence_excludes_failing_candidates() -> None:
    fake = _asset(
        source_type=EvidenceSourceType.REAL_INTERFACE,
        provenance={"generated": True},
    )
    good = _asset(source_type=EvidenceSourceType.REAL_INTERFACE, confidence=0.6)
    chosen, rejected = select_best_evidence(
        [fake, good], claim="这个产品支持导出", entity="Acme"
    )
    assert chosen is not None
    assert chosen.asset_id == good.asset_id
    assert any("FAKE_UI_AS_EVIDENCE" in reason for reason in rejected)


def test_evidence_freshness_marks_stale_captures() -> None:
    old = _asset(captured_at="2020-01-01T00:00:00Z")
    assert evaluate_evidence_freshness(old).freshness is EvidenceFreshness.STALE_EVIDENCE

    recent = _asset(captured_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    assert evaluate_evidence_freshness(recent).freshness is EvidenceFreshness.FRESH

    undated = _asset(captured_at="")
    assert evaluate_evidence_freshness(undated).freshness is EvidenceFreshness.UNDATED


def test_generated_visuals_are_never_freshness_asserted() -> None:
    generated = _asset(source_type=EvidenceSourceType.GENERATED_VISUALIZATION)
    assert evaluate_evidence_freshness(generated).freshness is EvidenceFreshness.UNDATED


def test_every_reality_asserting_type_is_covered() -> None:
    for source_type in REALITY_ASSERTING_TYPES:
        asset = _asset(source_type=source_type, source_uri="https://github.com/acme/x")
        assert asset.is_reality_asserting


# ── test_fake_ui_rejection ───────────────────────────────────────────────


def test_fake_ui_rejection_blocks_generated_material_as_real() -> None:
    asset = _asset(
        source_type=EvidenceSourceType.REAL_INTERFACE, provenance={"generated": True}
    )
    verdict = assert_evidence_truth(asset)
    assert not verdict.ok
    assert any("FAKE_UI_AS_EVIDENCE" in v for v in verdict.violations)
    assert verdict.blocked_asset_id == asset.asset_id


def test_fake_ui_rejection_blocks_mock_ui_as_official() -> None:
    asset = _asset(
        source_type=EvidenceSourceType.OFFICIAL_SCREENSHOT,
        source_uri="https://docs.acme.dev/mock-ui",
        provenance={"capture_method": "mock"},
    )
    verdict = assert_evidence_truth(asset)
    assert not verdict.ok
    assert any("MOCK_UI_AS_OFFICIAL" in v for v in verdict.violations)


def test_fake_ui_rejection_blocks_sdxl_output_as_official() -> None:
    asset = _asset(
        source_type=EvidenceSourceType.OFFICIAL_SCREENSHOT,
        source_uri="https://acme.dev/",
        provenance={"generator": "sdxl", "capture_method": "text2image"},
    )
    verdict = evidence_truth_check(asset)
    assert any("FAKE_UI_AS_EVIDENCE" in v for v in verdict.violations)


def test_generated_visual_cannot_back_a_claim_unlabelled() -> None:
    asset = EvidenceAsset(
        source_type=EvidenceSourceType.GENERATED_VISUALIZATION,
        claim_supported="Acme Console looks like this",
        entity="Acme",
        provenance={"generator": "sdxl"},
    )
    verdict = evidence_truth_check(asset)
    assert not verdict.ok
    assert any("UNLABELLED_GENERATED_EVIDENCE" in v for v in verdict.violations)


def test_labelled_generated_visual_is_allowed_for_non_factual_context() -> None:
    asset = EvidenceAsset(
        source_type=EvidenceSourceType.GENERATED_VISUALIZATION,
        claim_supported="an illustration of the concept",
        entity="",
        provenance={"generator": "sdxl", "labelled_as_generated": True},
    )
    verdict = evidence_truth_check(asset, allow_symbolic_for_claim=True)
    assert verdict.ok, verdict.violations


def test_unverified_official_source_is_rejected() -> None:
    asset = _asset(
        source_type=EvidenceSourceType.OFFICIAL_IMAGE, source_uri="https://random-blog.example/x.png"
    )
    verdict = evidence_truth_check(asset)
    assert any("UNVERIFIED_OFFICIAL_SOURCE" in v for v in verdict.violations)


def test_evidence_request_carries_the_required_fields() -> None:
    request = EvidenceRequest(
        claim="Acme Console supports bulk export",
        entity="Acme Console",
        desired_evidence_type=EvidenceSourceType.REAL_INTERFACE,
    )
    payload = request.to_dict()
    for field in (
        "request_id", "claim", "entity", "desired_evidence_type",
        "source_preference", "time_context", "required_confidence",
    ):
        assert field in payload


# ── test_screenshot_privacy ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("key sk-abcdefghijklmnopqrstuvwxyz012345", "OPENAI_STYLE_KEY"),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345", "BEARER_TOKEN"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghij", "JWT"),
        ("AKIAIOSFODNN7EXAMPLE", "AWS_ACCESS_KEY"),
        ("ghp_abcdefghijklmnopqrstuvwxyz0123", "GITHUB_TOKEN"),
        ("AIzaSyA1234567890abcdefghijklmnopqrstuv", "GOOGLE_API_KEY"),
        ("-----BEGIN RSA PRIVATE KEY-----", "PRIVATE_KEY_BLOCK"),
    ],
)
def test_screenshot_privacy_detects_secret_shapes(text: str, kind: str) -> None:
    scan = scan_privacy(text)
    assert scan.safe is False
    assert kind in scan.secret_kinds
    assert scan.action == "REJECT"


def test_screenshot_privacy_detects_emails() -> None:
    scan = scan_privacy("contact us at someone@example.com for access")
    assert scan.emails == ["someone@example.com"]
    assert scan.action == "REDACT"


def test_screenshot_privacy_is_clean_for_ordinary_page_text() -> None:
    scan = scan_privacy("Acme Console — Settings — Export as CSV — Done")
    assert scan.safe is True
    assert scan.action == "ACCEPT"
    assert scan.secret_kinds == []


def test_screenshot_privacy_rejects_and_demotes_the_asset() -> None:
    asset = _asset()
    scan = scan_privacy("leaked sk-abcdefghijklmnopqrstuvwxyz012345")
    asset, reasons = apply_privacy_policy(asset, scan)
    assert any(r.startswith("REJECT:") for r in reasons)
    # A rejected asset can no longer back a claim.
    assert asset.source_type is EvidenceSourceType.SYMBOLIC
    assert asset.claim_supported == ""


def test_screenshot_privacy_redacts_and_records_emails() -> None:
    asset = _asset()
    scan = scan_privacy("reach me at person@example.com")
    asset, reasons = apply_privacy_policy(asset, scan)
    assert any(r.startswith("REDACT:") for r in reasons)
    assert asset.redactions
    assert asset.privacy_scan["emails"] == ["person@example.com"]


def test_credentials_are_never_persisted_in_the_recorded_url() -> None:
    cleaned = strip_sensitive_query(
        "https://acme.dev/console?token=SECRETVALUE&api_key=ALSO&view=grid"
    )
    assert "SECRETVALUE" not in cleaned
    assert "ALSO" not in cleaned
    assert "view=grid" in cleaned


def test_privacy_scan_sanitises_text() -> None:
    scan = scan_privacy("token sk-abcdefghijklmnopqrstuvwxyz012345 end")
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in scan.sanitized_text


def test_capture_refuses_unreachable_url(tmp_path: Path) -> None:
    from hevi.ops.p5_1_evidence import capture_screenshot

    capture = capture_screenshot(
        "http://127.0.0.1:1/definitely-not-listening", tmp_path / "x.png", timeout_ms=1500
    )
    assert capture.ok is False
    assert capture.reason.startswith("CAPTURE_FAILED")
