"""Tests for the 15 open-tools graft (A1-A5 gates + B1/B2 fake contracts).

Every gate/contract gets a positive case and at least one
negative case. Nothing here renders, installs, executes, or
reads any desktop application, model, or upstream item.
"""

from __future__ import annotations

import pytest

from hevi.capabilities.audacity_version_gate import check_audacity_version
from hevi.capabilities.cosyvoice_attribution_note import (
    CODE_REPO,
    check_cosyvoice_citation,
    cosyvoice_notes,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.krita_asset_index import compile_krita_asset_index
from hevi.capabilities.krita_file_contract_gate import check_krita_file_contract
from hevi.capabilities.one_shot_film_honesty_gate import (
    STAGES,
    check_one_shot_film_status,
)
from hevi.capabilities.r3f_scene_contract import compile_r3f_scene_contract
from hevi.capabilities.r3f_variant_gate import check_r3f_variant


def _krita_plan(**overrides):
    plan = {
        "source_ref": "assets/scene01.kra",
        "source_preserved": True,
        "container": "zip",
        "mode": "read_only_index",
        "mergedimage_png": True,
    }
    plan.update(overrides)
    return plan


def _r3f_renderer(**overrides):
    renderer = {
        "renderer": "r3f",
        "react_version": "19.1.0",
        "three_version": "0.169.0",
        "r3f_version": "9.8.2",
    }
    renderer.update(overrides)
    return renderer


# --- A1: Krita file contract gate ----------------------------------------


def test_a1_read_only_index_pass():
    report = check_krita_file_contract(_krita_plan())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False
    assert report["source_never_modified"] is True


def test_a1_cli_export_pass_and_source_separation():
    report = check_krita_file_contract(
        _krita_plan(
            mode="cli_export",
            export_parameters={
                "output_path": "exports/scene01.png",
                "format": "png",
            },
        )
    )
    assert report["verdict"] == "pass"


def test_a1_plugin_pass():
    report = check_krita_file_contract(
        _krita_plan(mode="plugin", runs_inside_krita=True, uses_libkis=True)
    )
    assert report["verdict"] == "pass"


def test_a1_source_overwrite_fails():
    report = check_krita_file_contract(_krita_plan(source_preserved=False))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "source_not_preserved" for i in report["issues"])


def test_a1_wrong_container_fails():
    report = check_krita_file_contract(_krita_plan(container="tar"))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "container_not_zip" for i in report["issues"])


def test_a1_missing_mergedimage_fails():
    report = check_krita_file_contract(_krita_plan(mergedimage_png=False))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "mergedimage_missing" for i in report["issues"])


def test_a1_export_overwriting_source_fails():
    report = check_krita_file_contract(
        _krita_plan(
            mode="cli_export",
            export_parameters={
                "output_path": "assets/scene01.kra",
                "format": "png",
            },
        )
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "export_overwrites_source" for i in report["issues"])


def test_a1_export_parameter_not_whitelisted_fails():
    report = check_krita_file_contract(
        _krita_plan(
            mode="cli_export",
            export_parameters={
                "output_path": "exports/scene01.png",
                "batch_script": "rm -rf /",
            },
        )
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "export_parameter_not_whitelisted" for i in report["issues"]
    )


def test_a1_sdk_claim_fails():
    report = check_krita_file_contract(_krita_plan(sdk_installed=True))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "no_sdk_to_install" for i in report["issues"])


def test_a1_plugin_without_gui_session_fails():
    report = check_krita_file_contract(
        _krita_plan(mode="plugin", uses_libkis=True)
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "plugin_requires_gui_session" for i in report["issues"]
    )


def test_a1_unknown_mode_fails():
    report = check_krita_file_contract(_krita_plan(mode="paint_live"))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "mode_unknown" for i in report["issues"])


# --- A2: R3F variant gate -------------------------------------------------


def test_a2_r3f_combination_pass():
    report = check_r3f_variant(_r3f_renderer())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a2_plain_three_pass():
    report = check_r3f_variant({"renderer": "plain_three"})
    assert report["verdict"] == "pass"


def test_a2_react_18_fails():
    report = check_r3f_variant(_r3f_renderer(react_version="18.3.1"))
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "react_version_out_of_range" for i in report["issues"]
    )


def test_a2_react_19_4_fails():
    report = check_r3f_variant(_r3f_renderer(react_version="19.4.0"))
    assert report["verdict"] == "fail"


def test_a2_three_too_old_fails():
    report = check_r3f_variant(_r3f_renderer(three_version="0.150.0"))
    assert report["verdict"] == "fail"
    assert any(i["code"] == "three_version_too_old" for i in report["issues"])


def test_a2_r3f_alpha_fails():
    report = check_r3f_variant(_r3f_renderer(r3f_version="10.0.0-alpha.6"))
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "r3f_prerelease_not_stable" for i in report["issues"]
    )


def test_a2_plain_three_with_r3f_version_fails():
    report = check_r3f_variant(
        {"renderer": "plain_three", "r3f_version": "9.8.2"}
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "plain_three_mislabelled_r3f" for i in report["issues"]
    )


# --- A3: Audacity version gate --------------------------------------------


def test_a3_audacity4_no_scripting_pass():
    report = check_audacity_version(
        {"audacity_version": "4.0.2", "project_format": "aup4"}
    )
    assert report["verdict"] == "pass"
    assert report["scripting_available"] is False


def test_a3_audacity4_scripting_fails():
    report = check_audacity_version(
        {"audacity_version": "4.0.2", "scripting": True}
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "audacity4_no_scripting" for i in report["issues"])


def test_a3_audacity4_effect_chain_fails():
    report = check_audacity_version(
        {"audacity_version": "4.0.2", "effect_chain": ["noise_reduction"]}
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "audacity4_effect_chain_unavailable"
        for i in report["issues"]
    )


def test_a3_audacity4_wrong_format_fails():
    report = check_audacity_version(
        {"audacity_version": "4.0.2", "project_format": "aup3"}
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "audacity4_format_mismatch" for i in report["issues"]
    )


def test_a3_audacity3_scripting_pass():
    report = check_audacity_version(
        {
            "audacity_version": "3.7.9",
            "scripting": True,
            "scripting_interface": "macro",
            "project_format": "aup3",
        }
    )
    assert report["verdict"] == "pass"
    assert report["scripting_available"] is True


def test_a3_audacity3_scripting_without_interface_fails():
    report = check_audacity_version(
        {"audacity_version": "3.7.9", "scripting": True}
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "legacy_scripting_interface_undeclared"
        for i in report["issues"]
    )


def test_a3_companion_fork_claim_fails():
    report = check_audacity_version(
        {"audacity_version": "4.0.2", "companion_fork_built": True}
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "companion_fork_not_built" for i in report["issues"]
    )


# --- A4: CosyVoice attribution note ---------------------------------------


def test_a4_notes_cover_both_kinds():
    notes = cosyvoice_notes()
    assert [n["ref_kind"] for n in notes] == ["code_repo", "model_release"]
    assert notes[0]["name"] == CODE_REPO
    assert notes[1]["name"].startswith("FunAudioLLM/")


def test_a4_code_repo_pass():
    report = check_cosyvoice_citation(
        {"ref_kind": "code_repo", "name": CODE_REPO}
    )
    assert report["verdict"] == "pass"


def test_a4_old_address_as_code_repo_fails():
    report = check_cosyvoice_citation(
        {"ref_kind": "code_repo", "name": "FunAudioLLM/CosyVoice"}
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "code_repo_must_be_qwenaudio" for i in report["issues"]
    )


def test_a4_model_release_pass():
    report = check_cosyvoice_citation(
        {"ref_kind": "model_release", "name": "FunAudioLLM/CosyVoice3-0.5B"}
    )
    assert report["verdict"] == "pass"


def test_a4_model_release_under_code_org_fails():
    report = check_cosyvoice_citation(
        {"ref_kind": "model_release", "name": "QwenAudio/CosyVoice3-0.5B"}
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "model_release_must_be_funaudiollm"
        for i in report["issues"]
    )


def test_a4_clone_claim_fails():
    report = check_cosyvoice_citation(
        {
            "ref_kind": "code_repo",
            "name": CODE_REPO,
            "clone_claim": True,
        }
    )
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "clone_route_never_connected" for i in report["issues"]
    )


def test_a4_active_maintenance_claim_fails():
    report = check_cosyvoice_citation(
        {
            "ref_kind": "code_repo",
            "name": CODE_REPO,
            "actively_maintained": True,
        }
    )
    assert report["verdict"] == "fail"
    assert any(i["code"] == "maintenance_slowed" for i in report["issues"])


# --- A5: one-shot film honesty gate ---------------------------------------


def _honest_status(**overrides):
    stages = {
        "picture": {"state": "blocked_key_gpu"},
        "three_d": {"state": "design_only"},
        "narration": {"state": "blocked_key_gpu"},
        "subtitles": {
            "state": "open",
            "evidence": "faster-whisper ASR run, job id recorded",
        },
        "music": {"state": "contract_only"},
        "final_cut": {"state": "contract_only"},
        "platform_versions": {"state": "design_only"},
    }
    stages.update(overrides)
    return {"stages": stages}


def test_a5_honest_status_pass_and_never_connected():
    report = check_one_shot_film_status(_honest_status())
    assert report["verdict"] == "pass"
    assert report["one_shot_film_connected"] is False
    assert report["verified_end_to_end"] is False
    assert report["overall"] == "not_connected"
    assert set(report["stages"]) == set(STAGES)


def test_a5_ready_claim_fails():
    status = _honest_status()
    status["claims_one_shot_ready"] = True
    report = check_one_shot_film_status(status)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "one_shot_not_connected" for i in report["issues"]
    )


def test_a5_overall_connected_claim_fails():
    status = _honest_status()
    status["overall"] = "connected"
    report = check_one_shot_film_status(status)
    assert report["verdict"] == "fail"


def test_a5_end_to_end_verified_claim_fails():
    status = _honest_status()
    status["end_to_end_verified"] = True
    report = check_one_shot_film_status(status)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "end_to_end_not_verified_here" for i in report["issues"]
    )


def test_a5_missing_stage_fails():
    status = _honest_status()
    del status["stages"]["music"]
    report = check_one_shot_film_status(status)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "stage_missing" for i in report["issues"])


def test_a5_open_stage_without_evidence_fails():
    status = _honest_status()
    status["stages"]["subtitles"] = {"state": "open"}
    report = check_one_shot_film_status(status)
    assert report["verdict"] == "fail"
    assert any(
        i["code"] == "open_stage_needs_evidence" for i in report["issues"]
    )


# --- B1: Krita asset index -------------------------------------------------


def _asset_plan(**overrides):
    plan = {
        "source_ref": "assets/scene01.kra",
        "source_preserved": True,
        "mergedimage_png": True,
        "layers": [
            {"id": "bg", "name": "background", "kind": "paint"},
            {
                "id": "walk",
                "name": "walk cycle",
                "kind": "animation",
                "frame_count": 24,
            },
        ],
    }
    plan.update(overrides)
    return plan


def test_b1_index_contract_pass():
    contract = compile_krita_asset_index(_asset_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["index_only"] is True
    assert contract["source_never_modified"] is True
    assert len(contract["layers"]) == 2


def test_b1_animation_layer_without_frames_fails():
    with pytest.raises(CapabilityError, match="frame_count"):
        compile_krita_asset_index(
            _asset_plan(
                layers=[
                    {"id": "walk", "name": "walk", "kind": "animation"},
                ]
            )
        )


def test_b1_read_actual_kra_claim_fails():
    with pytest.raises(CapabilityError, match="no .kra file is read"):
        compile_krita_asset_index(_asset_plan(read_actual_kra=True))


def test_b1_export_overwriting_source_fails():
    with pytest.raises(CapabilityError, match="separate from"):
        compile_krita_asset_index(
            _asset_plan(
                exports=[
                    {
                        "id": "e1",
                        "format": "png",
                        "output_path": "assets/scene01.kra",
                    }
                ]
            )
        )


# --- B2: R3F scene contract ------------------------------------------------


def _scene_plan(**overrides):
    plan = {
        "renderer": _r3f_renderer(),
        "canvas": {"width": 1920, "height": 1080},
        "camera": {"position": [0, 1.6, 5], "fov": 45},
        "primitives": [
            {"id": "floor", "type": "plane", "position": [0, 0, 0]},
            {
                "id": "hero",
                "type": "box",
                "position": [0, 1, 0],
                "scale": [1, 2, 1],
                "color": "red",
            },
        ],
    }
    plan.update(overrides)
    return plan


def test_b2_scene_contract_pass():
    contract = compile_r3f_scene_contract(_scene_plan())
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["render_bridge"] == "real_machine_case"
    assert len(contract["primitives"]) == 2


def test_b2_bad_renderer_fails():
    with pytest.raises(CapabilityError, match="variant gate"):
        compile_r3f_scene_contract(
            _scene_plan(renderer=_r3f_renderer(react_version="18.3.1"))
        )


def test_b2_unknown_primitive_fails():
    with pytest.raises(CapabilityError, match="type must be one of"):
        compile_r3f_scene_contract(
            _scene_plan(
                primitives=[
                    {"id": "x", "type": "torus_knot", "position": [0, 0, 0]},
                ]
            )
        )


def test_b2_bad_position_fails():
    with pytest.raises(CapabilityError, match="position"):
        compile_r3f_scene_contract(
            _scene_plan(
                primitives=[
                    {"id": "x", "type": "box", "position": [0, 0]},
                ]
            )
        )


# --- Registry: the seven new capabilities are registered ------------------


def test_registry_contains_seven_new_capabilities():
    from hevi.capabilities import list_capabilities

    names = {cap.name for cap in list_capabilities()}
    assert {
        "qa.krita_file_contract_gate",
        "qa.r3f_variant_gate",
        "qa.audacity_version_gate",
        "qa.cosyvoice_attribution_note",
        "qa.one_shot_film_honesty_gate",
        "video.krita_asset_index",
        "video.r3f_scene_contract",
    } <= names
