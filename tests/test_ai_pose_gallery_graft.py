"""ai-pose-gallery-zh graft tests (A1-A9 gates, B1-B6 fake schemas).

The gate (A) tests assert pass/fail verdicts on good and bad
declarations. The schema (B) tests assert fail-closed
behaviour: ``compile_*`` returns a contract declaring
``executed_here`` false and ``output_file`` None on a
well-formed input, and raises ``CapabilityError`` on any
shape violation. The registration test asserts all 15 new
capability names are present exactly once. No test installs,
downloads, or generates an image, and no test contacts a
model or a ComfyUI instance. Depth disk checks run against
a fake gallery directory under tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.capabilities import list_capabilities, pose_library
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.pose_adult_safety_gate import check_pose_adult_safety
from hevi.capabilities.pose_character_recipe_gate import (
    check_pose_character_recipe,
    recipe_to_multi_ref,
)
from hevi.capabilities.pose_character_recipe_schema import (
    compile_pose_character_recipe,
)
from hevi.capabilities.pose_comfyui_gallery_node_schema import (
    compile_pose_comfyui_gallery_node,
)
from hevi.capabilities.pose_costume_library_gate import (
    GIAA_CATEGORY_SETS,
    GIAA_TOTAL_SETS,
    TOTAL_SETS,
    check_pose_costume,
)
from hevi.capabilities.pose_costume_reference_schema import (
    compile_pose_costume_reference,
)
from hevi.capabilities.pose_depth_switch_gate import (
    check_pose_depth_switch,
    depth_path_for,
    pose_index_depth_coverage,
)
from hevi.capabilities.pose_depth_switch_schema import compile_pose_depth_switch
from hevi.capabilities.pose_dynasty_costume_gate import check_pose_dynasty_costume
from hevi.capabilities.pose_model_select_gate import check_pose_model_selection
from hevi.capabilities.pose_portrait_library_gate import (
    FACE_COUNT,
    MOOD_COUNT,
    TOTAL_PORTRAITS,
    check_pose_portrait,
)
from hevi.capabilities.pose_portrait_reference_schema import (
    compile_pose_portrait_reference,
)
from hevi.capabilities.pose_rights_gate import check_pose_rights
from hevi.capabilities.pose_studio_workbench_schema import (
    compile_pose_studio_workbench,
)
from hevi.capabilities.pose_style_preset_gate import (
    FULL_PACK_SIZE,
    check_pose_style_preset,
    check_pose_style_preset_pack,
)

EXPECTED_POSE_GALLERY_NAMES = {
    "qa.pose_costume_library_gate",
    "qa.pose_portrait_library_gate",
    "qa.pose_depth_switch_gate",
    "qa.pose_character_recipe_gate",
    "qa.pose_style_preset_gate",
    "qa.pose_model_select_gate",
    "qa.pose_rights_gate",
    "qa.pose_adult_safety_gate",
    "qa.pose_dynasty_costume_gate",
    "video.pose_costume_reference_schema",
    "video.pose_portrait_reference_schema",
    "video.pose_depth_switch_schema",
    "video.pose_character_recipe_schema",
    "video.pose_comfyui_gallery_node_schema",
    "video.pose_studio_workbench_schema",
}

SEPARATION_RULE = "仅参考姿势，不参考服装/发型/画风"


def test_pose_gallery_names_registered_once() -> None:
    names = [cap.name for cap in list_capabilities()]
    for expected in EXPECTED_POSE_GALLERY_NAMES:
        assert names.count(expected) == 1, expected


def _good_costume() -> dict:
    return {
        "source": "giaa-realistic",
        "category": "春",
        "set_id": "giaa-spring-001",
        "tags": ["连衣裙", "碎花"],
        "category_sets": 215,
    }


def test_a1_costume_pass_and_category_counts() -> None:
    assert sum(GIAA_CATEGORY_SETS.values()) == GIAA_TOTAL_SETS == 1407
    assert TOTAL_SETS == 3224
    assert check_pose_costume(_good_costume())["verdict"] == "pass"


def test_a1_costume_commercial_and_bundled_refused() -> None:
    bad = _good_costume()
    bad["commercial_use"] = True
    assert check_pose_costume(bad)["verdict"] == "fail"
    bad = _good_costume()
    bad["images_bundled"] = True
    assert check_pose_costume(bad)["verdict"] == "fail"


def test_a1_costume_unknown_category_and_wrong_count() -> None:
    bad = _good_costume()
    bad["category"] = "秋装"
    assert check_pose_costume(bad)["verdict"] == "fail"
    bad = _good_costume()
    bad["category_sets"] = 999
    assert check_pose_costume(bad)["verdict"] == "fail"


def test_a1_costume_source_conditions() -> None:
    shisei = {"source": "shisei", "set_id": "shisei-ming-001", "dynasty": "明"}
    assert check_pose_costume(shisei)["verdict"] == "pass"
    assert check_pose_costume({"source": "shisei", "set_id": "x"})["verdict"] == "fail"
    anime = {"source": "anime-hotlink", "set_id": "anime-001", "hotlink": True}
    assert check_pose_costume(anime)["verdict"] == "pass"
    anime_offline = dict(anime, offline_available=True)
    assert check_pose_costume(anime_offline)["verdict"] == "fail"
    charadb = {
        "source": "charadb",
        "set_id": "chara-001",
        "no_redistribution": True,
        "no_real_person_or_minor": True,
    }
    assert check_pose_costume(charadb)["verdict"] == "pass"
    assert check_pose_costume({"source": "charadb", "set_id": "x"})["verdict"] == "fail"


def _good_portrait() -> dict:
    return {
        "portrait_id": "portrait-0001",
        "mode": "正脸",
        "hair_length": "长发",
        "hairstyle": "高马尾",
        "cc0_tension_acknowledged": True,
    }


def test_a2_portrait_pass_and_counts() -> None:
    assert TOTAL_PORTRAITS == 1499
    assert FACE_COUNT + MOOD_COUNT == TOTAL_PORTRAITS
    assert check_pose_portrait(_good_portrait())["verdict"] == "pass"


def test_a2_portrait_cc0_tension_must_be_acknowledged() -> None:
    bad = _good_portrait()
    del bad["cc0_tension_acknowledged"]
    assert check_pose_portrait(bad)["verdict"] == "fail"
    bad = _good_portrait()
    bad["commercial_use"] = True
    assert check_pose_portrait(bad)["verdict"] == "fail"


def test_a2_portrait_unknown_mode_and_real_person() -> None:
    bad = _good_portrait()
    bad["mode"] = "侧脸"
    assert check_pose_portrait(bad)["verdict"] == "fail"
    bad = _good_portrait()
    bad["real_person_use"] = True
    assert check_pose_portrait(bad)["verdict"] == "fail"
    bad = _good_portrait()
    bad["minor_use"] = True
    assert check_pose_portrait(bad)["verdict"] == "fail"


def test_a3_depth_path_derivation_and_coverage() -> None:
    assert depth_path_for("full_standard_P001", "正面") == ("img/depth/full_single_P001_front.webp")
    coverage = pose_index_depth_coverage()
    assert coverage["total_views"] == 1439
    assert coverage["depth_fields"] == 1439
    with pytest.raises(CapabilityError):
        depth_path_for("no_such_pose", "正面")


def test_a3_depth_switch_shape_only() -> None:
    decl = {
        "pose_key": "full_standard_P001",
        "view": "正面",
        "mode": "depth",
    }
    verdict = check_pose_depth_switch(decl, check_disk=False)
    assert verdict["verdict"] == "pass"
    assert verdict["depth_path"] == "img/depth/full_single_P001_front.webp"
    assert verdict["disk_checked"] is False
    bad = dict(decl, depth_path="img/depth/wrong.webp")
    assert check_pose_depth_switch(bad, check_disk=False)["verdict"] == "fail"
    bad = dict(decl, mode="side")
    assert check_pose_depth_switch(bad, check_disk=False)["verdict"] == "fail"


def _make_fake_gallery(tmp_path: Path) -> Path:
    (tmp_path / "img" / "depth").mkdir(parents=True)
    (tmp_path / "img" / "full_single_P001_front.png").write_bytes(b"fake")
    (tmp_path / "img" / "depth" / "full_single_P001_front.webp").write_bytes(b"fake")
    return tmp_path


def test_a3_depth_switch_disk_checks(tmp_path: Path) -> None:
    home = _make_fake_gallery(tmp_path)
    decl = {
        "pose_key": "full_standard_P001",
        "view": "正面",
        "mode": "depth",
        "home": str(home),
    }
    verdict = check_pose_depth_switch(decl)
    assert verdict["verdict"] == "pass"
    assert verdict["depth_exists"] is True
    missing_home = {
        "pose_key": "full_standard_P001",
        "view": "正面",
        "mode": "depth",
        "home": str(tmp_path / "no-such-gallery"),
    }
    assert check_pose_depth_switch(missing_home)["verdict"] == "fail"
    depth_only = tmp_path / "depth-only"
    (depth_only / "img" / "depth").mkdir(parents=True)
    (depth_only / "img" / "depth" / "full_single_P001_front.webp").write_bytes(b"fake")
    # The gate checks only the file the mode needs: depth mode passes
    # here (depth file present), white mode fails (white file absent).
    assert (
        check_pose_depth_switch(
            {
                "pose_key": "full_standard_P001",
                "view": "正面",
                "mode": "depth",
                "home": str(depth_only),
            }
        )["verdict"]
        == "pass"
    )
    assert (
        check_pose_depth_switch(
            {
                "pose_key": "full_standard_P001",
                "view": "正面",
                "mode": "white",
                "home": str(depth_only),
            }
        )["verdict"]
        == "fail"
    )
    white_only = tmp_path / "white-only"
    (white_only / "img").mkdir(parents=True)
    (white_only / "img" / "full_single_P001_front.png").write_bytes(b"fake")
    assert (
        check_pose_depth_switch(
            {
                "pose_key": "full_standard_P001",
                "view": "正面",
                "mode": "white",
                "home": str(white_only),
            }
        )["verdict"]
        == "pass"
    )
    assert (
        check_pose_depth_switch(
            {
                "pose_key": "full_standard_P001",
                "view": "正面",
                "mode": "depth",
                "home": str(white_only),
            }
        )["verdict"]
        == "fail"
    )


def _good_recipe() -> dict:
    return {
        "portrait_ref": {"portrait_id": "portrait-0001"},
        "costume_ref": {"source": "giaa-realistic", "set_id": "giaa-spring-001"},
        "pose_ref": {"pose_key": "full_standard_P001", "view": "正面"},
        "prompt_zh": "一位少女站在窗边，阳光洒落",
        "separation_rule": SEPARATION_RULE,
        "provider": "h3_local",
    }


def test_a4_recipe_pass_and_multi_ref_shape() -> None:
    assert check_pose_character_recipe(_good_recipe())["verdict"] == "pass"
    compiled = recipe_to_multi_ref(_good_recipe())
    assert compiled["shot_prompt"].startswith("一位少女")
    assert compiled["references"] == {
        "portrait": "portrait-0001",
        "costume": "giaa-spring-001",
        "pose": "full_standard_P001",
    }
    assert compiled["provider"] == "h3_local"
    assert compiled["max_refs"] == 4


def test_a4_recipe_separation_and_provider_limits() -> None:
    bad = _good_recipe()
    bad["separation_rule"] = "参考姿势和服装"
    assert check_pose_character_recipe(bad)["verdict"] == "fail"
    bad = _good_recipe()
    bad["prompt_zh"] = "a girl by the window"
    assert check_pose_character_recipe(bad)["verdict"] == "fail"
    bad = _good_recipe()
    bad["provider"] = "runway"
    bad["extra_refs"] = ["one"]
    assert check_pose_character_recipe(bad)["verdict"] == "fail"
    bad = _good_recipe()
    bad["pose_ref"] = {"pose_key": "no_such_pose", "view": "正面"}
    assert check_pose_character_recipe(bad)["verdict"] == "fail"
    with pytest.raises(CapabilityError):
        recipe_to_multi_ref(_good_recipe() | {"provider": "nope"})


def _good_preset(name: str = "水墨") -> dict:
    return {
        "name": name,
        "source": "hevi-local",
        "prompt_template_zh": "水墨画风，留白，淡彩",
    }


def test_a5_preset_pass_and_upstream_refused() -> None:
    assert check_pose_style_preset(_good_preset())["verdict"] == "pass"
    bad = _good_preset()
    bad["source"] = "upstream"
    assert check_pose_style_preset(bad)["verdict"] == "fail"


def test_a5_pack_requires_twelve_unique() -> None:
    assert FULL_PACK_SIZE == 12
    pack = {"presets": [_good_preset(f"风格{i}") for i in range(12)]}
    verdict = check_pose_style_preset_pack(pack)
    assert verdict["verdict"] == "pass"
    assert verdict["count"] == 12
    short = {"presets": [_good_preset(f"风格{i}") for i in range(11)]}
    assert check_pose_style_preset_pack(short)["verdict"] == "fail"
    dup = {"presets": [_good_preset("同名") for _ in range(12)]}
    assert check_pose_style_preset_pack(dup)["verdict"] == "fail"


def _good_selection() -> dict:
    return {
        "protocol": "qwen",
        "model": "qwen-image-3.0-pro",
        "model_source": "code",
        "task": "quality",
        "key_owner": "user",
    }


def test_a6_model_select_pass() -> None:
    assert check_pose_model_selection(_good_selection())["verdict"] == "pass"


def test_a6_model_select_stale_readme_and_key_owner() -> None:
    bad = _good_selection()
    bad["model_source"] = "readme"
    assert check_pose_model_selection(bad)["verdict"] == "fail"
    bad = _good_selection()
    bad["key_owner"] = "hevi"
    assert check_pose_model_selection(bad)["verdict"] == "fail"
    bad = _good_selection()
    bad["protocol"] = "comfyui"
    assert check_pose_model_selection(bad)["verdict"] == "fail"
    bad = _good_selection()
    bad["protocol"] = "comfyui"
    bad["local_comfyui"] = True
    assert check_pose_model_selection(bad)["verdict"] == "pass"


def _good_rights() -> dict:
    return {
        "source": "giaaibusi",
        "kind": "pose",
        "commercial_use": False,
        "redistribute": False,
        "attribution": True,
        "objection_removal": True,
    }


def test_a7_rights_pass() -> None:
    assert check_pose_rights(_good_rights())["verdict"] == "pass"


def test_a7_rights_commercial_and_attribution_refused() -> None:
    bad = _good_rights()
    bad["commercial_use"] = True
    assert check_pose_rights(bad)["verdict"] == "fail"
    bad = _good_rights()
    bad["attribution"] = False
    assert check_pose_rights(bad)["verdict"] == "fail"
    bad = _good_rights()
    bad["source"] = "charadb"
    assert check_pose_rights(bad)["verdict"] == "fail"
    bad = _good_rights()
    bad["source"] = "charadb"
    bad["no_real_person_or_minor"] = True
    assert check_pose_rights(bad)["verdict"] == "pass"
    bad = _good_rights()
    bad["kind"] = "portrait"
    assert check_pose_rights(bad)["verdict"] == "fail"
    bad = _good_rights()
    bad["kind"] = "portrait"
    bad["cc0_tension_acknowledged"] = True
    assert check_pose_rights(bad)["verdict"] == "pass"


def _good_safety() -> dict:
    return {
        "sfw_mode": True,
        "age_verified_adult": True,
        "explicit_unlock": True,
        "content_tier": "sexy",
        "target_audience": "adults",
    }


def test_a8_safety_adult_tier_needs_unlock() -> None:
    assert check_pose_adult_safety(_good_safety())["verdict"] == "pass"
    bad = _good_safety()
    bad["explicit_unlock"] = False
    assert check_pose_adult_safety(bad)["verdict"] == "fail"


def test_a8_safety_minor_hard_blocked_and_kids_line() -> None:
    bad = _good_safety()
    bad["age_verified_adult"] = False
    assert check_pose_adult_safety(bad)["verdict"] == "fail"
    bad = _good_safety()
    bad["target_audience"] = "kids"
    assert check_pose_adult_safety(bad)["verdict"] == "fail"
    bad = _good_safety()
    bad["sfw_mode"] = False
    assert check_pose_adult_safety(bad)["verdict"] == "fail"
    standard_kids = {
        "sfw_mode": True,
        "age_verified_adult": False,
        "content_tier": "standard",
        "target_audience": "kids",
    }
    assert check_pose_adult_safety(standard_kids)["verdict"] == "pass"


def _good_dynasty() -> dict:
    return {
        "dynasty": "明",
        "set_id": "shisei-ming-001",
        "source": "shisei",
        "views": ["正面", "侧面"],
        "counts": {"sets": 57, "views": 227},
    }


def test_a9_dynasty_pass_and_counts() -> None:
    assert check_pose_dynasty_costume(_good_dynasty())["verdict"] == "pass"


def test_a9_dynasty_wangyangming_requires_ming() -> None:
    bad = _good_dynasty()
    bad["dynasty"] = "唐"
    bad["history_line"] = "wangyangming"
    assert check_pose_dynasty_costume(bad)["verdict"] == "fail"
    good = _good_dynasty()
    good["history_line"] = "wangyangming"
    assert check_pose_dynasty_costume(good)["verdict"] == "pass"
    bad = _good_dynasty()
    bad["dynasty"] = "秦朝"
    assert check_pose_dynasty_costume(bad)["verdict"] == "fail"
    bad = _good_dynasty()
    bad["counts"] = {"sets": 58, "views": 227}
    assert check_pose_dynasty_costume(bad)["verdict"] == "fail"


def test_b1_costume_reference_contract() -> None:
    ref = dict(_good_costume(), reference_id="ref-c-001", gallery_path="img/costume-001.png")
    contract = compile_pose_costume_reference(ref)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["contract"] == "pose-costume-reference"
    with pytest.raises(CapabilityError):
        compile_pose_costume_reference(dict(ref, commercial_use=True))
    with pytest.raises(CapabilityError):
        compile_pose_costume_reference(dict(ref, gallery_path="/etc/passwd"))
    with pytest.raises(CapabilityError):
        compile_pose_costume_reference(dict(ref, gallery_path="../escape.png"))


def test_b2_portrait_reference_contract() -> None:
    ref = dict(
        _good_portrait(),
        reference_id="ref-p-001",
        gallery_path="img/portrait-0001.webp",
    )
    contract = compile_pose_portrait_reference(ref)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    with pytest.raises(CapabilityError):
        compile_pose_portrait_reference(dict(ref, cc0_tension_acknowledged=False))
    with pytest.raises(CapabilityError):
        compile_pose_portrait_reference({"reference_id": "x"})


def test_b3_depth_switch_contract() -> None:
    switch = {
        "switch_id": "sw-001",
        "pose_key": "full_standard_P001",
        "view": "正面",
        "mode": "depth",
    }
    contract = compile_pose_depth_switch(switch)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["depth_path"] == "img/depth/full_single_P001_front.webp"
    with pytest.raises(CapabilityError):
        compile_pose_depth_switch(dict(switch, mode="side"))
    with pytest.raises(CapabilityError):
        compile_pose_depth_switch(dict(switch, pose_key="no_such_pose"))


def test_b4_character_recipe_contract() -> None:
    recipe = dict(_good_recipe(), recipe_id="recipe-001")
    contract = compile_pose_character_recipe(recipe)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["multi_ref"]["provider"] == "h3_local"
    with pytest.raises(CapabilityError):
        compile_pose_character_recipe(dict(recipe, separation_rule="随便参考"))
    with pytest.raises(CapabilityError):
        compile_pose_character_recipe(dict(recipe, unknown_field=1))


def test_b5_comfyui_node_contract() -> None:
    call = {
        "node_id": "node-001",
        "node": "PoseGalleryNode",
        "use_depth": True,
        "depth_source": "img/depth",
        "inputs": {"pose_key": "full_standard_P001"},
    }
    contract = compile_pose_comfyui_gallery_node(call)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    with pytest.raises(CapabilityError):
        compile_pose_comfyui_gallery_node(dict(call, node="FakeNode"))
    with pytest.raises(CapabilityError):
        compile_pose_comfyui_gallery_node(dict(call, depth_source="img/other"))
    plain = {
        "node_id": "node-002",
        "node": "CharacterRecipeNode",
        "use_depth": False,
        "inputs": {},
    }
    assert compile_pose_comfyui_gallery_node(plain)["node"] == "CharacterRecipeNode"


def test_b6_workbench_contract() -> None:
    session = {
        "workbench_id": "wb-001",
        "protocols": ["qwen", "comfyui"],
        "slots": {"portrait": True, "costume": True, "pose": True},
        "background_generation": True,
        "history_store": "indexeddb",
        "canvas_size": [1800, 1200],
    }
    contract = compile_pose_studio_workbench(session)
    assert contract["executed_here"] is False
    assert contract["output_file"] is None
    assert contract["protocols"] == ["comfyui", "qwen"]
    with pytest.raises(CapabilityError):
        compile_pose_studio_workbench(dict(session, history_store="localstorage"))
    with pytest.raises(CapabilityError):
        compile_pose_studio_workbench(dict(session, protocols=["nope"]))
    with pytest.raises(CapabilityError):
        compile_pose_studio_workbench(dict(session, slots={"portrait": True, "hat": True}))


def test_pose_library_depth_helper_reports_coverage() -> None:
    coverage = pose_index_depth_coverage()
    assert coverage["total_views"] == 1439
    assert coverage["depth_fields"] == 1439
    group = pose_library.get_pose_by_key("full_standard_P001")
    entry = group["views"]["正面"]
    assert entry["depth"] == "img/depth/full_single_P001_front.webp"
    depth = pose_library.depth_for(group, "正面")
    assert depth["depth"] == "img/depth/full_single_P001_front.webp"
    assert depth["image"] == entry["image"]
