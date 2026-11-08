"""Tests for deferred 20-skills batch B: Jolt (B3), CosyVoice
authorization gate (B4), Tweakpane panel contract (B5).
Contract/gate layer only; nothing executes.
"""

import pytest

from hevi.capabilities import cosyvoice_authorization_gate as b4
from hevi.capabilities import jolt_rigid_body_contract as b3
from hevi.capabilities import tweakpane_panel_contract as b5
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains


def _jolt_plan(**overrides):
    plan = {
        "world": {"gravity": [0, -9.8, 0]},
        "bodies": [
            {
                "id": "crate",
                "shape": "box",
                "half_extents": [0.5, 0.5, 0.5],
                "position": [0, 1, 0],
                "mass": 2.0,
            },
            {
                "id": "ball",
                "shape": "sphere",
                "radius": 0.3,
                "position": [1, 1, 0],
                "velocity": [0, 0, 1],
                "mass": 0.5,
                "restitution": 0.4,
            },
        ],
    }
    plan.update(overrides)
    return plan


def test_jolt_contract_positive():
    contract = b3.compile_jolt_rigid_body_contract(_jolt_plan())
    assert contract["body_count"] == 2
    assert contract["simulated_here"] is False
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert "soft-body" in contract["scope"]
    assert "collision_check" in contract["division_of_labour"]


def test_jolt_contract_soft_body_narrowed_out():
    with pytest.raises(CapabilityError, match="narrowed out"):
        b3.compile_jolt_rigid_body_contract(
            _jolt_plan(bodies=[{
                "id": "cloth", "shape": "box", "half_extents": [1, 1, 0.1],
                "position": [0, 0, 0], "mass": 1.0, "soft_body": True,
            }])
        )
    with pytest.raises(CapabilityError, match="narrowed out"):
        b3.compile_jolt_rigid_body_contract({"world": {"gravity": [0, -9.8, 0]}, "bodies": [], "material": "cloth"})
    with pytest.raises(CapabilityError):
        b3.compile_jolt_rigid_body_contract(_jolt_plan(bodies=[{
            "id": "x", "shape": "capsule", "position": [0, 0, 0], "mass": 1.0,
        }]))
    with pytest.raises(CapabilityError):
        b3.compile_jolt_rigid_body_contract(_jolt_plan(bodies=[{
            "id": "x", "shape": "sphere", "radius": 0.3,
            "position": [0, 0, 0], "mass": 0,
        }]))


def _voice_plan(**overrides):
    plan = {
        "voice_authorization": {
            "voice_id": "own-voice-1",
            "authorization_kind": "own",
            "evidence_ref": "voice-ledger:own-voice-1",
        },
        "code_ref": "QwenAudio/CosyVoice",
        "model_ref": "FunAudioLLM/CosyVoice3-0.5B",
    }
    plan.update(overrides)
    return plan


def test_cosyvoice_gate_positive():
    report = b4.check_cosyvoice_authorization(_voice_plan())
    assert report["verdict"] == "pass"
    assert report["voice_id"] == "own-voice-1"
    assert report["clone_route"] == "never_connected"
    assert report["executed_here"] is False


def test_cosyvoice_gate_no_authorization_fails():
    assert b4.check_cosyvoice_authorization({})["verdict"] == "fail"
    assert b4.check_cosyvoice_authorization(
        {"voice_authorization": {"voice_id": "v1"}}
    )["verdict"] == "fail"
    assert b4.check_cosyvoice_authorization(
        _voice_plan(voice_authorization={
            "voice_id": "v1", "authorization_kind": "public",
            "evidence_ref": "somewhere",
        })
    )["verdict"] == "fail"


def test_cosyvoice_gate_clone_always_refused():
    for extra in (
        {"clone": True},
        {"clone_voice": True},
        {"request_kind": "zero_shot_clone"},
        {"mode": "clone"},
    ):
        report = b4.check_cosyvoice_authorization(_voice_plan(**extra))
        assert report["verdict"] == "fail"
        assert any(i["code"] == "clone_route_refused" for i in report["issues"])


def test_cosyvoice_gate_attribution_and_claims():
    report = b4.check_cosyvoice_authorization(
        _voice_plan(code_ref="FunAudioLLM/CosyVoice")
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "code_ref_misattributed" for i in report["issues"])
    report = b4.check_cosyvoice_authorization(
        _voice_plan(model_ref="QwenAudio/CosyVoice3-0.5B")
    )
    assert any(i["code"] == "model_ref_misattributed" for i in report["issues"])
    report = b4.check_cosyvoice_authorization(
        _voice_plan(claims={"installed": True, "actively_maintained": True})
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "installed_claim_refused" for i in report["issues"])
    assert any(i["code"] == "maintenance_claim_refused" for i in report["issues"])


def _panel_plan(**overrides):
    plan = {
        "panel": {"title": "Exposure tuning"},
        "parameters": [
            {"key": "exposure", "kind": "number", "min": 0, "max": 2,
             "step": 0.1, "default": 1.0},
            {"key": "grain", "kind": "boolean", "default": False},
            {"key": "look", "kind": "choice",
             "options": ["flat", "warm"], "default": "flat"},
        ],
        "bindings": [{"parameter_key": "exposure", "target": "grade.exposure"}],
    }
    plan.update(overrides)
    return plan


def test_tweakpane_contract_positive():
    contract = b5.compile_tweakpane_panel_contract(_panel_plan())
    assert contract["parameter_count"] == 3
    assert contract["executed_here"] is False
    assert contract["dom_created"] is False
    assert contract["output_file"] is None
    assert "debugging" in contract["purpose"]
    with pytest.raises(CapabilityError):
        b5.compile_tweakpane_panel_contract(_panel_plan(parameters=[
            {"key": "x", "kind": "number", "min": 0, "max": 1, "default": 2},
        ]))
    with pytest.raises(CapabilityError):
        b5.compile_tweakpane_panel_contract(_panel_plan(parameters=[
            {"key": "x", "kind": "choice", "options": [], "default": "a"},
        ]))
    with pytest.raises(CapabilityError):
        b5.compile_tweakpane_panel_contract(_panel_plan(bindings=[
            {"parameter_key": "missing", "target": "grade.x"},
        ]))


def test_batch3_registered():
    assert contains("video.jolt_rigid_body_contract")
    assert contains("qa.cosyvoice_authorization_gate")
    assert contains("video.tweakpane_panel_contract")
