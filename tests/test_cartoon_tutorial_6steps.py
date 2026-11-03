"""Tests for the 3D cartoon 6-step tutorial graft (A1-A4 gates, B1-B2 renders).

Clean-room: only the disciplines restated in the graft modules are
judged here -- the hook-reversal script shape, the pre-release
self-check, reference-picture anchors, the word-pop subtitle
contract, the Remotion bridge smoke, and the word-pop renderer.
No tutorial text or prompt is copied, no anecdote is treated as
measured evidence, no account or key is used, and the Three.js
geometry half is never claimed.
"""

import json
import subprocess

import pytest

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.hook_reversal_script_gate import check_hook_reversal_script
from hevi.capabilities.prerelease_self_check_gate import check_prerelease_self_check
from hevi.capabilities.reference_anchor_gate import check_reference_anchors
from hevi.capabilities.registry import get as registry_get
from hevi.capabilities.remotion_bridge_smoke import run_remotion_bridge_smoke
from hevi.capabilities.word_pop_renderer import render_word_pop
from hevi.capabilities.word_pop_subtitle_contract import (
    check_word_pop_subtitle_contract,
)

_SHA = "a" * 64
_SHA2 = "b" * 64
_SHA3 = "c" * 64


def _script(**overrides):
    script = {
        "topic_kind": "factual",
        "sources": ["county archive record"],
        "total_duration_s": 40.0,
        "acts": {
            "hook": {"text": "Two mapmakers invented a town that did not exist.", "duration_s": 5.0},
            "chain": {"text": "A rival map copied it, and a lawsuit followed.", "duration_s": 25.0},
            "reversal": {"text": "Years later a real store stood at that crossroads.", "duration_s": 10.0},
        },
    }
    script.update(overrides)
    return script


def test_a1_hook_reversal_pass():
    report = check_hook_reversal_script(_script())
    assert report["verdict"] == "pass", report


def test_a1_missing_reversal_fails():
    script = _script()
    del script["acts"]["reversal"]
    script["total_duration_s"] = 30.0
    assert check_hook_reversal_script(script)["verdict"] == "fail"


def test_a1_reversal_same_as_hook_fails():
    script = _script()
    script["acts"]["reversal"]["text"] = script["acts"]["hook"]["text"]
    assert check_hook_reversal_script(script)["verdict"] == "fail"


def test_a1_durations_must_tile_total():
    script = _script(total_duration_s=41.0)
    report = check_hook_reversal_script(script)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "acts_do_not_tile_total" for i in report["issues"])


def test_a1_factual_topic_requires_sources():
    script = _script(sources=[])
    report = check_hook_reversal_script(script)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "factual_sources_missing" for i in report["issues"])


def _self_check(**overrides):
    report = {
        "items": {
            "hook_first_3s": {"checked": True, "passed": True, "evidence": "frame 0-90 shows the hook line"},
            "subtitle_no_face_block": {"checked": True, "passed": True, "evidence": "zone/face geometry checked, no overlap"},
            "ending_one_sentence": {"checked": True, "passed": True, "evidence": "last beat is one sentence, 4.0s"},
        }
    }
    report.update(overrides)
    return report


def test_a2_self_check_pass():
    assert check_prerelease_self_check(_self_check())["verdict"] == "pass"


def test_a2_unchecked_item_fails():
    report = _self_check()
    report["items"]["hook_first_3s"]["checked"] = False
    assert check_prerelease_self_check(report)["verdict"] == "fail"


def test_a2_evidence_free_pass_fails():
    report = _self_check()
    report["items"]["ending_one_sentence"]["evidence"] = "  "
    assert check_prerelease_self_check(report)["verdict"] == "fail"


def test_a2_geometry_overlap_fails_despite_claim():
    report = _self_check(
        face_boxes=[{"x": 0.3, "y": 0.05, "w": 0.4, "h": 0.3}],
        subtitle_rects=[{"x": 0.1, "y": 0.2, "w": 0.8, "h": 0.2}],
    )
    result = check_prerelease_self_check(report)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "subtitle_covers_face" for i in result["issues"])


def _anchor_plan(count=3, **overrides):
    refs = [
        {"sha256": _SHA, "source": "self-shot", "anchor_dimensions": ["proportion", "palette"], "rights": "self_owned"},
        {"sha256": _SHA2, "source": "self-shot", "anchor_dimensions": ["stroke"], "rights": "self_owned"},
        {"sha256": _SHA3, "source": "self-shot", "anchor_dimensions": ["lighting", "material"], "rights": "self_owned"},
    ]
    plan = {"references": refs[:count]}
    plan.update(overrides)
    return plan


def test_a3_anchor_pass():
    assert check_reference_anchors(_anchor_plan())["verdict"] == "pass"


def test_a3_two_references_fail():
    assert check_reference_anchors(_anchor_plan(count=2))["verdict"] == "fail"


def test_a3_bad_sha_and_duplicate_fail():
    plan = _anchor_plan()
    plan["references"][1]["sha256"] = "xyz"
    assert check_reference_anchors(plan)["verdict"] == "fail"
    plan = _anchor_plan()
    plan["references"][1]["sha256"] = _SHA
    assert check_reference_anchors(plan)["verdict"] == "fail"


def test_a3_rights_and_dimensions_required():
    plan = _anchor_plan()
    del plan["references"][0]["rights"]
    assert check_reference_anchors(plan)["verdict"] == "fail"
    plan = _anchor_plan()
    plan["references"][0]["anchor_dimensions"] = ["mood"]
    assert check_reference_anchors(plan)["verdict"] == "fail"


def _pop_contract(**overrides):
    contract = {
        "timestamp_source": "whisper word-level timestamps, verified run 2026-11-03",
        "words": [
            {"word": "HELLO", "start_s": 0.0, "end_s": 0.5},
            {"word": "WORLD", "start_s": 0.5, "end_s": 1.0},
            {"word": "POP", "start_s": 1.0, "end_s": 1.5},
        ],
        "pop": {"position": "bottom", "scale_from": 0.6, "scale_to": 1.0, "window_s": 0.15},
        "subtitle_zone": {"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.15},
        "face_boxes": [{"x": 0.3, "y": 0.05, "w": 0.4, "h": 0.3}],
    }
    contract.update(overrides)
    return contract


def test_a4_pop_contract_pass():
    assert check_word_pop_subtitle_contract(_pop_contract())["verdict"] == "pass"


def test_a4_timestamp_source_required():
    contract = _pop_contract(timestamp_source="  ")
    assert check_word_pop_subtitle_contract(contract)["verdict"] == "fail"


def test_a4_overlapping_words_fail():
    contract = _pop_contract()
    contract["words"][1]["start_s"] = 0.4
    assert check_word_pop_subtitle_contract(contract)["verdict"] == "fail"


def test_a4_scale_must_grow_and_zone_must_clear_face():
    contract = _pop_contract()
    contract["pop"]["scale_to"] = 0.5
    assert check_word_pop_subtitle_contract(contract)["verdict"] == "fail"
    contract = _pop_contract()
    contract["face_boxes"] = [{"x": 0.2, "y": 0.75, "w": 0.6, "h": 0.2}]
    result = check_word_pop_subtitle_contract(contract)
    assert result["verdict"] == "fail"
    assert any(i["code"] == "subtitle_zone_covers_face" for i in result["issues"])


def test_b1_remotion_bridge_smoke(tmp_path):
    evidence = run_remotion_bridge_smoke(tmp_path / "b1")
    assert evidence["ok"] is True
    assert evidence["ffprobe"]["width"] == 540
    assert evidence["ffprobe"]["height"] == 960
    assert evidence["ffprobe"]["nb_frames"] == 90
    assert abs(evidence["ffprobe"]["duration_s"] - 3.0) <= 0.2
    assert evidence["threejs_present_in_hevi_remotion"] is False
    assert evidence["threejs_geometry"] == "not_rendered"
    assert (tmp_path / "b1" / "evidence.json").is_file()


def test_b2_word_pop_renders_three_words(tmp_path):
    evidence = render_word_pop(_pop_contract(), tmp_path / "pop.mp4")
    assert evidence["ok"] is True
    assert evidence["words_rendered"] == ["HELLO", "WORLD", "POP"]
    assert evidence["face_overlap"] is False
    assert evidence["frames"] == 45
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(tmp_path / "pop.mp4")],
        capture_output=True, text=True, timeout=60, check=True,
    )
    assert abs(float(probe.stdout.strip()) - 1.5) <= 0.2


def test_b2_face_overlap_refuses_to_render(tmp_path):
    plan = _pop_contract()
    plan["face_boxes"] = [{"x": 0.2, "y": 0.75, "w": 0.6, "h": 0.2}]
    with pytest.raises(CapabilityError):
        render_word_pop(plan, tmp_path / "blocked.mp4")


def test_b2_bad_contract_refuses_to_render(tmp_path):
    plan = _pop_contract()
    plan["words"][1]["start_s"] = 0.4
    with pytest.raises(CapabilityError):
        render_word_pop(plan, tmp_path / "blocked.mp4")


def test_registry_resolves_all_new_capabilities():
    for name in (
        "qa.hook_reversal_script_gate",
        "qa.prerelease_self_check_gate",
        "qa.reference_anchor_gate",
        "qa.word_pop_subtitle_contract",
        "video.remotion_bridge_smoke",
        "video.word_pop_renderer",
    ):
        assert registry_get(name) is not None, name
