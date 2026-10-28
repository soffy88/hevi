"""Tests for qa.multimodal_review: supplement only, never invented."""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities import multimodal_review
from hevi.capabilities.multimodal_review import review
from hevi.capabilities.registry import get


def _gate() -> dict:
    return {"verdict": "pass", "failed_checks": [],
            "checks": {"change_rate": {"pass": True}}}


def test_capability_registered() -> None:
    assert get("qa.multimodal_review").name == "qa.multimodal_review"


def test_deterministic_gate_result_is_required(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="cannot replace it"):
        review(deterministic_result=None)
    with pytest.raises(CapabilityError, match="cannot replace it"):
        review(deterministic_result={})


def test_no_model_means_deterministic_only_no_invented_opinion(tmp_path: Path) -> None:
    report = review(deterministic_result=_gate())
    assert report["columns"]["deterministic_gate_result"] == _gate()
    assert report["columns"]["model_reference_opinion"] is None
    assert report["model_status"] == "unavailable"
    assert "model_unavailable_reason" in report
    assert report["does_not_replace"] == "qa.final_qc_gate"


def test_model_opinion_is_labelled_reference_with_warnings(tmp_path: Path) -> None:
    def _model() -> dict:
        return {"suspected_cut_points": [12.5],
                "subtitle_notes": "possible homophone at 00:03"}

    report = review(deterministic_result=_gate(), model_fn=_model)
    assert report["model_status"] == "provided"
    opinion = report["columns"]["model_reference_opinion"]
    assert opinion["may_miss_cut_points"] is True
    assert opinion["may_miswrite_homophones"] is True
    assert opinion["requires_human_check"] is True
    assert "仍需人工核对" in opinion["disclaimer"]
    assert opinion["model_raw"]["suspected_cut_points"] == [12.5]
    # The opinion never overwrites the gate column.
    assert report["columns"]["deterministic_gate_result"] == _gate()
    assert report["human_check_required"] is True


def test_model_opinion_does_not_change_gate_verdict(tmp_path: Path) -> None:
    gate = {"verdict": "fail", "failed_checks": ["change_rate"]}

    def _model() -> dict:
        return {"notes": "looks fine to me"}

    report = review(deterministic_result=gate, model_fn=_model)
    assert report["columns"]["deterministic_gate_result"]["verdict"] == "fail"
    assert report["columns"]["deterministic_gate_result"]["failed_checks"] == [
        "change_rate"]


def test_failing_model_falls_back_to_deterministic_only(tmp_path: Path) -> None:
    def _boom() -> dict:
        raise RuntimeError("model endpoint down")

    report = review(deterministic_result=_gate(), model_fn=_boom)
    assert report["columns"]["model_reference_opinion"] is None
    assert report["model_status"] == "unavailable"
    assert "model endpoint down" in report["model_unavailable_reason"]
    assert report["columns"]["deterministic_gate_result"] == _gate()


def test_model_returning_nothing_is_not_rewritten(tmp_path: Path) -> None:
    report = review(deterministic_result=_gate(),
                    model_fn=lambda: None)
    assert report["columns"]["model_reference_opinion"] is None
    assert report["model_status"] == "unavailable"


def test_module_builds_in_no_model_call_or_credentials() -> None:
    source = Path(multimodal_review.__file__).read_text(encoding="utf-8")
    for banned in ("api_key", "API_KEY", "environ", "requests.",
                   "urllib", "http.client"):
        assert banned not in source, banned
    assert "model_fn" in source  # injection point only, caller supplies it


def test_registry_render_is_deterministic_only(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = caps.get("qa.multimodal_review").render(
        {"deterministic_result": _gate()},
        out, duration=0.0, aspect="16:9", seed=1)
    report = result.qa["result"]
    assert report["columns"]["deterministic_gate_result"] == _gate()
    assert report["columns"]["model_reference_opinion"] is None
    assert report["model_status"] == "unavailable"
