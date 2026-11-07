"""Tests for model.qwen_image_license_gate: research-only licence gate."""

from __future__ import annotations

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.qwen_image_license_gate import (
    LICENSE_NOTICE,
    check_deployment,
    check_license_use,
    check_qwen_image_license,
    check_redistribution,
    component_sizes_gb,
    three_piece_total_gb,
)
from hevi.capabilities.registry import get


def _research_plan(**overrides):
    plan = {
        "model": "qwen-image-2.1",
        "purpose": "research",
        "quantization": "int8",
        "vram_gb": 24,
    }
    plan.update(overrides)
    return plan


def test_capability_registered() -> None:
    assert get("model.qwen_image_license_gate").name == "model.qwen_image_license_gate"


def test_research_use_passes() -> None:
    report = check_qwen_image_license(_research_plan())
    assert report["verdict"] == "pass"
    assert report["license"]["attribution_required"] is False
    assert report["deployment"]["speed_status"] == "unmeasured"


def test_evaluation_use_passes() -> None:
    report = check_qwen_image_license(_research_plan(purpose="evaluation"))
    assert report["verdict"] == "pass"


def test_commercial_use_without_license_fails_section_2b() -> None:
    report = check_license_use(_research_plan(purpose="commercial"))
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "commercial_use_without_license" and f["clause"] == "2(b)"
        for f in report["failures"]
    )


def test_paid_generation_without_license_fails() -> None:
    report = check_license_use(_research_plan(purpose="paid_generation"))
    assert report["verdict"] == "fail"


def test_commercial_licensed_with_record_passes() -> None:
    plan = _research_plan(
        purpose="commercial_licensed",
        commercial_license={
            "licensor": "Hangzhou Tongyi Laboratory Technology Co., Ltd.",
            "date": "2026-10-31",
            "scope": "image generation for client delivery",
        },
    )
    report = check_license_use(plan)
    assert report["verdict"] == "pass"


def test_commercial_licensed_without_record_fails() -> None:
    report = check_license_use(_research_plan(purpose="commercial_licensed"))
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "commercial_license_record_missing"
        for f in report["failures"]
    )


def test_redistribution_missing_items_fail() -> None:
    plan = _research_plan(redistribution={"modified": True})
    report = check_redistribution(plan)
    assert report["verdict"] == "fail"
    codes = {f["code"] for f in report["failures"]}
    assert "redistribution_missing_license_copy" in codes
    assert "redistribution_missing_modification_notice" in codes
    assert "redistribution_notice_not_retained" in codes


def test_redistribution_complete_passes() -> None:
    plan = _research_plan(
        redistribution={
            "modified": True,
            "includes_license_copy": True,
            "modification_notice": True,
            "notice_retained": True,
            "notice_text": LICENSE_NOTICE,
        }
    )
    report = check_redistribution(plan)
    assert report["verdict"] == "pass"


def test_attribution_triggered_for_distributed_derivative_model() -> None:
    plan = _research_plan(derivative_model=True, derivative_distributed=True)
    report = check_license_use(plan)
    assert report["attribution_required"] is True
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "attribution_required_not_shown"
        for f in report["failures"]
    )
    shown = _research_plan(
        derivative_model=True,
        derivative_distributed=True,
        attribution_shown=True,
    )
    assert check_license_use(shown)["verdict"] == "pass"


def test_ordinary_generation_does_not_trigger_attribution() -> None:
    report = check_license_use(_research_plan())
    assert report["attribution_required"] is False
    assert report["verdict"] == "pass"


def test_qwen_primary_name_forbidden() -> None:
    report = check_license_use(_research_plan(derivative_name="Qwen Studio"))
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "qwen_primary_name_forbidden" for f in report["failures"]
    )


def test_turbo_license_status_unverified() -> None:
    report = check_license_use(_research_plan(model="qwen-image-2.1-turbo"))
    assert report["license_status"] == "unverified"
    assert any(
        w["code"] == "turbo_license_unverified" for w in report["warnings"]
    )


def test_floyo_claim_does_not_cover_self_hosted_commercial() -> None:
    plan = _research_plan(
        purpose="commercial",
        hosting="floyo_hosted",
        floyo_commercial_license_claimed=True,
    )
    report = check_license_use(plan)
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "floyo_license_does_not_cover_self_hosted"
        for f in report["failures"]
    )


def test_24gb_bf16_without_offload_fails() -> None:
    report = check_deployment(_research_plan(quantization="bf16", vram_gb=24))
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "bf16_resident_not_permitted_without_offload"
        for f in report["failures"]
    )


def test_24gb_bf16_with_offload_passes_with_warning() -> None:
    report = check_deployment(
        _research_plan(quantization="bf16", vram_gb=24, offload_declared=True)
    )
    assert report["verdict"] == "pass"
    assert any(
        w["code"] == "bf16_offload_speed_cost" for w in report["warnings"]
    )


def test_24gb_int8_passes() -> None:
    report = check_deployment(_research_plan(quantization="int8", vram_gb=24))
    assert report["verdict"] == "pass"


def test_turbo_steps_only_changed_fails() -> None:
    plan = _research_plan(
        model="qwen-image-2.1-turbo", turbo_steps=40, turbo_schedule="manual_sigmas"
    )
    report = check_deployment(plan)
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "turbo_steps_only_changed" for f in report["failures"]
    )


def test_turbo_fixed_schedule_passes() -> None:
    plan = _research_plan(
        model="qwen-image-2.1-turbo", turbo_steps=8, turbo_schedule="manual_sigmas"
    )
    report = check_deployment(plan)
    assert report["verdict"] == "pass"


def test_speed_claim_fails() -> None:
    report = check_deployment(_research_plan(seconds_per_image=5))
    assert report["verdict"] == "fail"
    assert any(f["code"] == "speed_unmeasured" for f in report["failures"])


def test_component_sizes_and_totals() -> None:
    sizes = component_sizes_gb()
    assert sizes["dit_bf16"] == 14.23
    assert sizes["encoder_bf16"] == 17.53
    assert sizes["vae_bf16"] == 0.68
    assert three_piece_total_gb("bf16") == 32.44
    assert three_piece_total_gb("int8") == 17.28


def test_non_dict_plan_raises() -> None:
    with pytest.raises(CapabilityError):
        check_qwen_image_license(None)  # type: ignore[arg-type]
