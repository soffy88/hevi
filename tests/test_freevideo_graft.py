"""FreeVideo graft tests (A1-A10 gates, B1-B6 fake schemas).

The gate (A) tests assert pass/fail verdicts on good and bad
inputs. The schema (B) tests assert fail-closed behaviour:
``compile_*`` returns a contract declaring ``executed_here``
false and ``output_file`` None on a well-formed input, and
raises ``CapabilityError`` on any shape violation. The
registration test asserts all 16 new capability names are
present exactly once. No test runs FreeVideo, loads weights,
or touches a GPU.
"""

from __future__ import annotations

import pytest

from hevi.capabilities import list_capabilities
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.freevideo_agent_mcp_schema import (
    compile_freevideo_agent_mcp,
)
from hevi.capabilities.freevideo_dubbing_task_schema import (
    compile_freevideo_dubbing_task,
)
from hevi.capabilities.freevideo_execution_plan_schema import (
    compile_freevideo_execution_plan,
)
from hevi.capabilities.freevideo_execution_planner_gate import (
    check_freevideo_execution_plan,
)
from hevi.capabilities.freevideo_h3_community_license_gate import (
    check_freevideo_h3_license,
)
from hevi.capabilities.freevideo_h3_image_task_schema import (
    compile_freevideo_h3_image_task,
)
from hevi.capabilities.freevideo_lora_honesty_gate import check_freevideo_lora
from hevi.capabilities.freevideo_low_vram_honesty_gate import (
    check_freevideo_low_vram_claim,
)
from hevi.capabilities.freevideo_post_chain_license_gate import (
    check_freevideo_post_chain,
)
from hevi.capabilities.freevideo_post_chain_task_schema import (
    compile_freevideo_post_chain_task,
)
from hevi.capabilities.freevideo_preview_first_gate import (
    check_freevideo_preview_first,
)
from hevi.capabilities.freevideo_prompt_drama_execution_gate import (
    check_freevideo_prompt_drama_execution,
)
from hevi.capabilities.freevideo_vdn_h3_distinction_gate import (
    check_freevideo_vdn_h3_identity,
)
from hevi.capabilities.freevideo_vdn_h3_task_schema import (
    compile_freevideo_vdn_h3_task,
)
from hevi.capabilities.freevideo_voice_reference_authorization_gate import (
    check_freevideo_voice_reference,
)
from hevi.capabilities.freevideo_workflow_bundle_gate import (
    check_freevideo_workflow_bundle,
)
from hevi.capabilities.scene_reference import H3_SECTIONS

EXPECTED_FREEVIDEO_NAMES = {
    "qa.freevideo_execution_planner_gate",
    "qa.freevideo_low_vram_honesty_gate",
    "qa.freevideo_vdn_h3_distinction_gate",
    "qa.freevideo_h3_community_license_gate",
    "qa.freevideo_prompt_drama_execution_gate",
    "qa.freevideo_preview_first_gate",
    "qa.freevideo_lora_honesty_gate",
    "qa.freevideo_voice_reference_authorization_gate",
    "qa.freevideo_workflow_bundle_gate",
    "qa.freevideo_post_chain_license_gate",
    "video.freevideo_execution_plan_schema",
    "video.freevideo_vdn_h3_task_schema",
    "video.freevideo_h3_image_task_schema",
    "video.freevideo_dubbing_task_schema",
    "video.freevideo_agent_mcp_schema",
    "video.freevideo_post_chain_task_schema",
}


def test_freevideo_names_registered_once() -> None:
    names = [cap.name for cap in list_capabilities()]
    for expected in EXPECTED_FREEVIDEO_NAMES:
        assert names.count(expected) == 1, expected


def _good_plan() -> dict:
    # 8 GiB VRAM, no activation working set stated: resident range check only.
    return {
        "vram_gib": 8,
        "ram_gib": 32,
        "resident_blocks": 8,
        "prefetch_slots": 1,
        "oom_retries": 2,
        "plan_dry_run": True,
        "quality": "Max",
        "seconds": 15,
        "width": 768,
        "height": 1344,
        "pinned_host_gib": 22,
        "disk_streaming": True,
    }


def test_a1_planner_pass() -> None:
    assert check_freevideo_execution_plan(_good_plan())["verdict"] == "pass"


def test_a1_planner_formula() -> None:
    # (10 - 1.0) * 1024 / 432.5 = 21.3 -> 21 blocks.
    plan = _good_plan()
    plan.update(
        {
            "vram_gib": 10,
            "activation_working_set_gib": 1.0,
            "resident_blocks": 21,
        }
    )
    assert check_freevideo_execution_plan(plan)["verdict"] == "pass"
    plan["resident_blocks"] = 22
    assert check_freevideo_execution_plan(plan)["verdict"] == "fail"


def test_a1_planner_slots_and_retries() -> None:
    plan = _good_plan()
    plan["prefetch_slots"] = 2
    assert check_freevideo_execution_plan(plan)["verdict"] == "fail"
    plan["prefetch_slots"] = 1
    plan["oom_retries"] = 3
    assert check_freevideo_execution_plan(plan)["verdict"] == "fail"
    plan["oom_retries"] = 2
    plan["plan_dry_run"] = False
    assert check_freevideo_execution_plan(plan)["verdict"] == "fail"


def test_a1_planner_disk_streaming_required() -> None:
    plan = _good_plan()
    plan.update(
        {
            "ram_gib": 16,
            "non_resident_gib": 12,
            "host_working_gib": 6,
            "disk_streaming": False,
        }
    )
    assert check_freevideo_execution_plan(plan)["verdict"] == "fail"
    plan["disk_streaming"] = True
    assert check_freevideo_execution_plan(plan)["verdict"] == "pass"


def test_a1_planner_pinned_cap() -> None:
    plan = _good_plan()
    plan["pinned_host_gib"] = 23
    assert check_freevideo_execution_plan(plan)["verdict"] == "fail"


def _good_claim() -> dict:
    return {
        "vram_gib": 10,
        "host_ram_gib": 32,
        "quality": "Max",
        "seconds": 15,
        "estimated_minutes": 33,
        "disk_read_mbps": 500,
    }


def test_a2_low_vram_pass() -> None:
    assert check_freevideo_low_vram_claim(_good_claim())["verdict"] == "pass"


def test_a2_low_vram_minimums() -> None:
    claim = _good_claim()
    claim["vram_gib"] = 6
    assert check_freevideo_low_vram_claim(claim)["verdict"] == "fail"
    claim = _good_claim()
    claim["host_ram_gib"] = 8
    assert check_freevideo_low_vram_claim(claim)["verdict"] == "fail"


def test_a2_low_vram_zero_cost_refused() -> None:
    claim = _good_claim()
    claim["zero_cost_claim"] = True
    assert check_freevideo_low_vram_claim(claim)["verdict"] == "fail"


def test_a2_low_vram_time_understated() -> None:
    claim = _good_claim()
    claim["estimated_minutes"] = 5
    assert check_freevideo_low_vram_claim(claim)["verdict"] == "fail"


def test_a2_low_vram_slow_disk() -> None:
    claim = _good_claim()
    claim["disk_read_mbps"] = 60
    assert check_freevideo_low_vram_claim(claim)["verdict"] == "fail"
    claim["disk_streaming_acknowledged"] = True
    assert check_freevideo_low_vram_claim(claim)["verdict"] == "pass"


def _good_identity() -> dict:
    return {
        "model_name": "VDN-H3",
        "model_kind": "vdn-h3-distilled",
        "revision": "751739ee5b9e3ac802dca5d5111075fdaeb47885",
        "steps": 8,
    }


def test_a3_distinction_pass() -> None:
    assert check_freevideo_vdn_h3_identity(_good_identity())["verdict"] == "pass"


def test_a3_distinction_wrong_kind_and_revision() -> None:
    identity = _good_identity()
    identity["model_kind"] = "minimax-h3-original"
    assert check_freevideo_vdn_h3_identity(identity)["verdict"] == "fail"
    identity = _good_identity()
    identity["revision"] = "deadbeef"
    assert check_freevideo_vdn_h3_identity(identity)["verdict"] == "fail"
    identity = _good_identity()
    identity["steps"] = 50
    assert check_freevideo_vdn_h3_identity(identity)["verdict"] == "fail"


def test_a3_distinction_name_and_transfer() -> None:
    identity = _good_identity()
    identity["model_name"] = "MiniMax H3"
    assert check_freevideo_vdn_h3_identity(identity)["verdict"] == "fail"
    identity = _good_identity()
    identity["claims_equivalent_to_h3"] = True
    assert check_freevideo_vdn_h3_identity(identity)["verdict"] == "fail"
    identity = _good_identity()
    identity["fasth3_conclusions_applied"] = True
    assert check_freevideo_vdn_h3_identity(identity)["verdict"] == "fail"


def _good_use() -> dict:
    return {
        "regions": ["CN"],
        "commercial": False,
        "ui_displays_minimax_h3": False,
        "license_copy_attached": False,
        "improves_other_models_with_output": False,
        "impersonation_without_consent": False,
        "minors_harmed": False,
    }


def test_a4_license_pass_noncommercial() -> None:
    assert check_freevideo_h3_license(_good_use())["verdict"] == "pass"


def test_a4_license_barred_region() -> None:
    use = _good_use()
    use["regions"] = ["CN", "US"]
    assert check_freevideo_h3_license(use)["verdict"] == "fail"


def test_a4_license_commercial_rules() -> None:
    use = _good_use()
    use.update(
        {
            "commercial": True,
            "annual_revenue_usd": 25_000_000,
            "ui_displays_minimax_h3": True,
            "license_copy_attached": True,
        }
    )
    assert check_freevideo_h3_license(use)["verdict"] == "fail"
    use["written_authorization"] = True
    assert check_freevideo_h3_license(use)["verdict"] == "pass"
    use = _good_use()
    use.update({"commercial": True, "annual_revenue_usd": 1_000_000})
    assert check_freevideo_h3_license(use)["verdict"] == "fail"
    use["ui_displays_minimax_h3"] = True
    use["license_copy_attached"] = True
    assert check_freevideo_h3_license(use)["verdict"] == "pass"


def test_a4_license_bans() -> None:
    use = _good_use()
    use["improves_other_models_with_output"] = True
    assert check_freevideo_h3_license(use)["verdict"] == "fail"
    use = _good_use()
    use["impersonation_without_consent"] = True
    assert check_freevideo_h3_license(use)["verdict"] == "fail"
    use = _good_use()
    use["minors_harmed"] = True
    assert check_freevideo_h3_license(use)["verdict"] == "fail"
    use = _good_use()
    use.update({"public_release": True, "public_release_discloses_ai_generated": False})
    assert check_freevideo_h3_license(use)["verdict"] == "fail"
    use["public_release_discloses_ai_generated"] = True
    assert check_freevideo_h3_license(use)["verdict"] == "pass"


def _good_drama_plan() -> dict:
    return {
        "six_sections": list(H3_SECTIONS),
        "shot_seconds": 18,
        "has_cast_card": False,
        "shot_cuts": [
            {"at": 0, "duration_s": 3, "framing": "wide", "action": "enter", "camera": "static"},
            {"at": 3, "duration_s": 4, "framing": "medium", "action": "speak", "camera": "pan"},
        ],
        "pre_generation_checks": {
            "stray_lettering": True,
            "small_faces_wide_shot": True,
            "text_under_14px": True,
            "third_party_marks": True,
            "voice_references": True,
        },
        "speakers_numbered_by_first_line": True,
        "dialogue_word_for_word": True,
        "agent": {"agent_name": "director", "plan_before_run": True},
    }


def test_a5_drama_pass() -> None:
    assert check_freevideo_prompt_drama_execution(_good_drama_plan())["verdict"] == "pass"


def test_a5_drama_sections_and_shots() -> None:
    plan = _good_drama_plan()
    plan["six_sections"] = list(reversed(list(H3_SECTIONS)))
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"
    plan = _good_drama_plan()
    plan["shot_seconds"] = 5
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"
    plan = _good_drama_plan()
    plan["shot_seconds"] = 25
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"
    plan = _good_drama_plan()
    plan.update({"has_cast_card": True, "cast_wardrobe_fixed": True, "shot_seconds": 15})
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "pass"
    plan["shot_seconds"] = 18
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"
    plan = _good_drama_plan()
    plan.update({"has_cast_card": True, "shot_seconds": 15})
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"


def test_a5_drama_cuts_checks_agent() -> None:
    plan = _good_drama_plan()
    plan["shot_cuts"] = [{"at": 0, "duration_s": 8, "framing": "wide"}]
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"
    plan = _good_drama_plan()
    plan["pre_generation_checks"]["third_party_marks"] = False
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"
    plan = _good_drama_plan()
    plan["speakers_numbered_by_first_line"] = False
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"
    plan = _good_drama_plan()
    plan["agent"] = {"agent_name": "director", "plan_before_run": False}
    assert check_freevideo_prompt_drama_execution(plan)["verdict"] == "fail"


def _good_run() -> dict:
    return {
        "first_pass": {"resolution_fraction": 0.5, "completed": True},
        "second_pass": {"reuses_first_pass": True, "completed": True},
        "preview_reviewed_full_size": True,
        "two_seeds_first_shot": True,
        "only_liked_completed": True,
    }


def test_a6_preview_pass() -> None:
    assert check_freevideo_preview_first(_good_run())["verdict"] == "pass"


def test_a6_preview_failures() -> None:
    run = _good_run()
    run["first_pass"] = {"resolution_fraction": 1.0, "completed": True}
    assert check_freevideo_preview_first(run)["verdict"] == "fail"
    run = _good_run()
    run["second_pass"] = {"reuses_first_pass": False, "completed": True}
    assert check_freevideo_preview_first(run)["verdict"] == "fail"
    run = _good_run()
    run["two_seeds_first_shot"] = False
    assert check_freevideo_preview_first(run)["verdict"] == "fail"
    run = _good_run()
    run["only_liked_completed"] = False
    assert check_freevideo_preview_first(run)["verdict"] == "fail"


def test_a7_lora_pass_and_fail() -> None:
    loras = [{"lora_id": "vhs", "source": "community", "license": "CC BY 4.0"}]
    assert check_freevideo_lora(loras)["verdict"] == "pass"
    loras = [{"lora_id": "vhs", "source": "community", "license": "unknown"}]
    assert check_freevideo_lora(loras)["verdict"] == "fail"
    loras = [{"lora_id": "adult-x", "source": "community", "license": "CC BY 4.0", "adult": True}]
    assert check_freevideo_lora(loras)["verdict"] == "fail"
    loras[0]["subject_age_years"] = 24
    assert check_freevideo_lora(loras)["verdict"] == "pass"
    loras[0]["subject_age_years"] = 17
    assert check_freevideo_lora(loras)["verdict"] == "fail"
    assert check_freevideo_lora([])["verdict"] == "fail"


def _good_voice_plan() -> dict:
    return {
        "voice_reference": {
            "voice_id": "soffy",
            "authorization": {"kind": "own", "proof": "owner-declared"},
        },
        "text": "hello",
    }


def test_a8_voice_pass_and_fail() -> None:
    assert check_freevideo_voice_reference(_good_voice_plan())["verdict"] == "pass"
    plan = _good_voice_plan()
    plan["clone"] = True
    assert check_freevideo_voice_reference(plan)["verdict"] == "fail"
    plan = {"text": "hello"}
    assert check_freevideo_voice_reference(plan)["verdict"] == "fail"
    plan = _good_voice_plan()
    plan["voice_reference"]["authorization"]["proof"] = ""
    assert check_freevideo_voice_reference(plan)["verdict"] == "fail"
    plan = _good_voice_plan()
    plan["voice_reference"]["authorization"]["kind"] = "third-party"
    assert check_freevideo_voice_reference(plan)["verdict"] == "fail"


def _good_bundle() -> dict:
    return {
        "video_id": "shot-001",
        "prompt": "a courtyard at dusk",
        "seed": 42,
        "settings": {"quality": "High"},
        "workflow_file": "shot-001.json",
        "source_traceable": True,
    }


def test_a9_workflow_pass_and_fail() -> None:
    assert check_freevideo_workflow_bundle(_good_bundle())["verdict"] == "pass"
    bundle = _good_bundle()
    bundle["workflow_file"] = ""
    assert check_freevideo_workflow_bundle(bundle)["verdict"] == "fail"
    bundle = _good_bundle()
    bundle["source_traceable"] = False
    assert check_freevideo_workflow_bundle(bundle)["verdict"] == "fail"


def _good_chain() -> list:
    return [
        {"tool": "rife", "license": "MIT", "commercial": True},
        {"tool": "ace_step", "license": "MIT", "commercial": False},
    ]


def test_a10_post_chain_pass_and_fail() -> None:
    assert check_freevideo_post_chain(_good_chain())["verdict"] == "pass"
    chain = [{"tool": "bandit_stems", "license": "CC BY-NC 4.0", "commercial": True}]
    assert check_freevideo_post_chain(chain)["verdict"] == "fail"
    chain = [{"tool": "bandit_stems", "license": "CC BY-NC 4.0", "commercial": False}]
    assert check_freevideo_post_chain(chain)["verdict"] == "pass"
    chain = [{"tool": "qwen_image", "license": "Qwen RESEARCH LICENSE", "commercial": False}]
    assert check_freevideo_post_chain(chain)["verdict"] == "fail"
    chain[0]["research_only"] = True
    assert check_freevideo_post_chain(chain)["verdict"] == "pass"
    chain = [{"tool": "mystery", "license": "MIT", "commercial": False}]
    assert check_freevideo_post_chain(chain)["verdict"] == "fail"
    chain = [
        {"tool": "rife", "license": "MIT", "commercial": False, "ships_gpl_code_into_hevi": True}
    ]
    assert check_freevideo_post_chain(chain)["verdict"] == "fail"


def test_b1_execution_plan_schema() -> None:
    plan = _good_plan()
    plan["plan_id"] = "plan-001"
    contract = compile_freevideo_execution_plan(plan)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["resident_blocks"] == 8
    bad = dict(plan)
    bad["plan_dry_run"] = False
    with pytest.raises(CapabilityError):
        compile_freevideo_execution_plan(bad)


def test_b2_vdn_h3_task_schema() -> None:
    task = {
        "task_id": "task-001",
        **_good_identity(),
        "quality": "High",
        "seconds": 15,
        "width": 768,
        "height": 1344,
        "two_pass": True,
    }
    contract = compile_freevideo_vdn_h3_task(task)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    bad = dict(task)
    bad["model_name"] = "MiniMax H3"
    with pytest.raises(CapabilityError):
        compile_freevideo_vdn_h3_task(bad)


def test_b3_h3_image_task_schema() -> None:
    task = {
        "task_id": "img-001",
        "model": "minimax-h3-image",
        "megapixels": 16,
        "width": 4096,
        "height": 4096,
        "license_acknowledged": True,
    }
    contract = compile_freevideo_h3_image_task(task)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    bad = dict(task)
    bad["megapixels"] = 20
    with pytest.raises(CapabilityError):
        compile_freevideo_h3_image_task(bad)
    task = {
        "task_id": "img-002",
        "model": "qwen-image-2.1",
        "megapixels": 4,
        "width": 2048,
        "height": 2048,
        "license_acknowledged": True,
        "research_only": True,
    }
    assert compile_freevideo_h3_image_task(task)["executed_here"] is False
    task["commercial"] = True
    with pytest.raises(CapabilityError):
        compile_freevideo_h3_image_task(task)


def test_b4_dubbing_task_schema() -> None:
    task = {
        "task_id": "dub-001",
        **_good_voice_plan(),
        "language": "zh",
    }
    contract = compile_freevideo_dubbing_task(task)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["voice_id"] == "soffy"
    bad = dict(task)
    bad["voice_reference"] = {
        "voice_id": "someone-else",
        "authorization": {"kind": "own", "proof": ""},
    }
    with pytest.raises(CapabilityError):
        compile_freevideo_dubbing_task(bad)


def test_b5_agent_mcp_schema() -> None:
    contract_in = {
        "agent_name": "director",
        "mcp_server": "freevideo-mcp",
        "plan_before_run": True,
        "six_sections": list(H3_SECTIONS),
        "cost": {"model": "claude-code", "max_tokens": 16000, "estimated_cost_usd": 0.5},
    }
    contract = compile_freevideo_agent_mcp(contract_in)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    bad = dict(contract_in)
    bad["plan_before_run"] = False
    with pytest.raises(CapabilityError):
        compile_freevideo_agent_mcp(bad)
    bad = dict(contract_in)
    bad["cost"] = {"model": "claude-code", "max_tokens": 16000}
    with pytest.raises(CapabilityError):
        compile_freevideo_agent_mcp(bad)


def test_b6_post_chain_task_schema() -> None:
    task = {"task_id": "post-001", "steps": _good_chain(), "output": "shot-001-graded.mp4"}
    contract = compile_freevideo_post_chain_task(task)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["step_count"] == 2
    bad = dict(task)
    bad["steps"] = [{"tool": "bandit_stems", "license": "CC BY-NC 4.0", "commercial": True}]
    with pytest.raises(CapabilityError):
        compile_freevideo_post_chain_task(bad)
