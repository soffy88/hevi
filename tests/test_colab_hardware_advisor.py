"""Tests for model.colab_hardware_advisor (advice and gating only)."""

import re
from pathlib import Path

import pytest

from hevi.capabilities import colab_hardware_advisor as advisor
from hevi.capabilities.errors import CapabilityError


def _runtime(rate=0.0, vram=20.0, name="cpu-runtime", balance=None):
    snapshot = {
        "gpu_name": name,
        "vram_gb": vram,
        "rate_ccu_per_hour": rate,
        "snapshot_date": "2026-10-30",
    }
    if balance is not None:
        snapshot["balance_ccu"] = balance
    return snapshot


# --- classification: all six classes ---

def test_classify_download():
    result = advisor.classify_task({"purpose": "download", "is_first_download": True})
    assert result["task_type"] == "download"
    assert result["unknown"] is False


def test_classify_light_video():
    result = advisor.classify_task({"purpose": "video", "video_model_params_billion": 2.0})
    assert result["task_type"] == "light_video"


def test_classify_heavy_video():
    result = advisor.classify_task({"purpose": "video", "video_model_params_billion": 14.0})
    assert result["task_type"] == "heavy_video"


def test_classify_llm_small():
    result = advisor.classify_task({"purpose": "llm", "model_params_billion": 1.5})
    assert result["task_type"] == "llm_small"


def test_classify_llm_medium():
    result = advisor.classify_task({"purpose": "llm", "model_params_billion": 32.0})
    assert result["task_type"] == "llm_medium"


def test_classify_llm_large():
    result = advisor.classify_task({"purpose": "llm", "model_params_billion": 70.0})
    assert result["task_type"] == "llm_large"


def test_classify_declared_type_is_accepted():
    result = advisor.classify_task({"task_type": "heavy_video"})
    assert result["task_type"] == "heavy_video"
    assert result["unknown"] is False


def test_classify_unknown_when_no_signals():
    result = advisor.classify_task({})
    assert result["task_type"] == "unknown"
    assert result["unknown"] is True
    assert result["reasons"]


def test_classify_unknown_when_llm_size_missing():
    result = advisor.classify_task({"purpose": "llm"})
    assert result["task_type"] == "unknown"


def test_classify_unknown_when_type_unrecognised():
    result = advisor.classify_task({"task_type": "teleport"})
    assert result["task_type"] == "unknown"


def test_classify_unknown_when_not_an_object():
    result = advisor.classify_task("llm")
    assert result["task_type"] == "unknown"


# --- runtime snapshot validation ---

def test_runtime_missing_rate_is_an_error():
    snapshot = _runtime()
    del snapshot["rate_ccu_per_hour"]
    with pytest.raises(CapabilityError):
        advisor.validate_runtime(snapshot)


def test_runtime_missing_snapshot_date_is_an_error():
    snapshot = _runtime(rate=6.0)
    del snapshot["snapshot_date"]
    with pytest.raises(CapabilityError):
        advisor.validate_runtime(snapshot)


def test_runtime_missing_name_is_an_error():
    snapshot = _runtime(rate=6.0)
    snapshot["gpu_name"] = "  "
    with pytest.raises(CapabilityError):
        advisor.validate_runtime(snapshot)


def test_runtime_valid_snapshot_is_normalised():
    checked = advisor.validate_runtime(_runtime(rate=6.0, vram=50.0, balance=100.0))
    assert checked["rate_source"] == "caller_supplied_runtime_snapshot"
    assert checked["balance_ccu"] == 100.0


# --- download guard ---

def test_download_guard_blocks_expensive_first_download():
    guard = advisor.check_download_guard(
        "download", advisor.validate_runtime(_runtime(rate=6.0, vram=50.0))
    )
    assert guard["blocked"] is True
    assert guard["forced"] is False
    assert "CPU" in guard["reason"]


def test_download_guard_allows_cheap_runtime():
    guard = advisor.check_download_guard(
        "download", advisor.validate_runtime(_runtime(rate=0.0, vram=20.0))
    )
    assert guard["blocked"] is False


def test_download_guard_force_is_recorded_not_hidden():
    guard = advisor.check_download_guard(
        "download",
        advisor.validate_runtime(_runtime(rate=6.0, vram=50.0)),
        force=True,
    )
    assert guard["blocked"] is False
    assert guard["forced"] is True


def test_download_guard_string_true_is_not_force():
    guard = advisor.check_download_guard(
        "download",
        advisor.validate_runtime(_runtime(rate=6.0, vram=50.0)),
        force="true",
    )
    assert guard["blocked"] is True
    assert guard["forced"] is False


def test_download_guard_does_not_block_generation():
    guard = advisor.check_download_guard(
        "llm_small", advisor.validate_runtime(_runtime(rate=6.0, vram=50.0))
    )
    assert guard["blocked"] is False


# --- oversized warning ---

def test_oversized_warning_for_small_job_on_costly_runtime():
    warning = advisor.check_oversized_warning(
        "llm_small", advisor.validate_runtime(_runtime(rate=6.0, vram=50.0))
    )
    assert warning["warning"] is True
    assert warning["downgrade_suggestion"] == "small_gpu"


def test_oversized_warning_absent_for_large_job():
    warning = advisor.check_oversized_warning(
        "llm_large", advisor.validate_runtime(_runtime(rate=6.0, vram=50.0))
    )
    assert warning["warning"] is False


def test_oversized_warning_absent_on_cheap_runtime():
    warning = advisor.check_oversized_warning(
        "llm_small", advisor.validate_runtime(_runtime(rate=0.0, vram=20.0))
    )
    assert warning["warning"] is False


# --- tuning advice ---

def test_tuning_advice_large_memory_threshold():
    tuning = advisor.tuning_advice(
        advisor.validate_runtime(_runtime(rate=6.0, vram=50.0))
    )
    assert tuning["applies"] is True
    assert tuning["suggest_cpu_offload"] is False
    assert tuning["suggest_reduced_precision"] is True
    assert "fp8" in tuning["suggested_dtypes"]


def test_tuning_advice_below_threshold_makes_no_suggestion():
    tuning = advisor.tuning_advice(
        advisor.validate_runtime(_runtime(rate=0.0, vram=20.0))
    )
    assert tuning["applies"] is False
    assert tuning["suggest_reduced_precision"] is False


# --- memory estimate and cost estimate ---

def test_vram_estimate_default_factor_is_labelled_reference():
    estimate = advisor.estimate_vram_gb(32.0, dtype="bf16")
    assert estimate["estimated_vram_gb"] == pytest.approx(32.0 * 2.4)
    assert estimate["estimate_kind"] == "order_of_magnitude_reference_only"


def test_vram_estimate_caller_factor_overrides_default():
    estimate = advisor.estimate_vram_gb(
        32.0, dtype="bf16", dtype_factors={"bf16": 2.0}, kv_reserve_gb=4.0
    )
    assert estimate["estimated_vram_gb"] == pytest.approx(68.0)


def test_vram_estimate_unknown_dtype_is_an_error():
    with pytest.raises(CapabilityError):
        advisor.estimate_vram_gb(32.0, dtype="int4")


def test_cost_estimate_uses_snapshot_rate_and_duration():
    runtime = advisor.validate_runtime(_runtime(rate=6.0, vram=50.0))
    cost = advisor.estimate_cost(runtime, duration_hours=2.0)
    assert cost["estimated_ccu"] == pytest.approx(12.0)
    assert cost["snapshot_date"] == "2026-10-30"


def test_cost_estimate_without_duration_invents_nothing():
    runtime = advisor.validate_runtime(_runtime(rate=6.0, vram=50.0))
    cost = advisor.estimate_cost(runtime)
    assert cost["estimated_ccu"] is None


# --- full advice report and spend-brake shaping ---

def test_advise_blocked_download_has_no_spend_brake_input():
    report = advisor.advise(
        {"purpose": "download", "is_first_download": True},
        _runtime(rate=6.0, vram=50.0),
        duration_hours=1.0,
    )
    assert report["download_guard"]["blocked"] is True
    assert report["spend_brake_input"]["spend_brake_ready"] is False
    assert "switches no runtime" in report["no_switching_notice"]


def test_advise_large_model_shortfall_is_reported():
    report = advisor.advise(
        {"purpose": "llm", "model_params_billion": 70.0},
        _runtime(rate=6.0, vram=50.0),
        duration_hours=1.0,
    )
    assert report["task_type"] == "llm_large"
    assert report["memory_estimate"]["fits_runtime"] is False
    assert report["memory_estimate"]["shortfall_gb"] > 0
    assert report["recommendation"]["tier"] == "large_vram_gpu"
    assert report["spend_brake_input"]["estimated_ccu_high"] == pytest.approx(6.0)


def test_advise_balance_note_when_balance_below_estimate():
    report = advisor.advise(
        {"purpose": "llm", "model_params_billion": 1.5},
        _runtime(rate=6.0, vram=50.0, balance=1.0),
        duration_hours=2.0,
    )
    assert report["balance_note"] is not None


def test_advise_unknown_task_gets_no_recommendation():
    report = advisor.advise({}, _runtime(rate=0.0, vram=20.0))
    assert report["task_type"] == "unknown"
    assert report["recommendation"]["tier"] is None


# --- no baked-in price table; no switching code ---

def test_no_hardcoded_rate_table_in_module_source():
    source = Path(advisor.__file__).read_text(encoding="utf-8")
    # Literals are assembled here so a repo-wide grep for baked-in
    # rates does not false-positive on this very assertion.
    forbidden_rates = ["8" + ".71", "18" + ".05", "5" + ".40",
                       "7" + ".52", "1" + ".19", "1" + ".71"]
    for rate in forbidden_rates:
        assert rate not in source, f"baked-in rate {rate} found in module"
    assert "webbrowser" not in source
    assert "subprocess" not in source
    assert "requests." not in source


def test_register_is_idempotent():
    assert advisor.register_colab_hardware_advisor_capabilities_once() == []


def test_capability_is_registered():
    from hevi.capabilities.registry import get

    capability = get("model.colab_hardware_advisor")
    assert capability.name == "model.colab_hardware_advisor"
    assert capability.has_media_output is False
