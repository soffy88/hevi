from __future__ import annotations

import json
from pathlib import Path
import uuid
import pytest
from fastapi.testclient import TestClient

from hevi.capabilities import get, list_capabilities, CapabilityError
from hevi.api.main import app

client = TestClient(app)


def test_golive3_capabilities_registered():
    caps = {c.name for c in list_capabilities()}
    expected = {
        "assets.library",
        "assets.extract",
        "image.multi_ref_compose",
        "style.project_snapshot",
        "storyboard.shot_groups",
    }
    assert expected.issubset(caps)
    for name in expected:
        c = get(name)
        assert c.name == name


def test_api_capabilities_endpoint():
    resp = client.get("/api/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    names = {item["name"] for item in data.get("capabilities", [])}
    for expected in [
        "assets.library",
        "assets.extract",
        "image.multi_ref_compose",
        "style.project_snapshot",
        "storyboard.shot_groups",
    ]:
        assert expected in names


# ─────────────────────────────────────────────────────────────────────────────
# Block 1: assets.library (with persistence & TestClient CRUD)
# ─────────────────────────────────────────────────────────────────────────────
def test_assets_library_list_empty(tmp_path: Path):
    cap = get("assets.library")
    res = cap.render({"action": "list"}, tmp_path, duration=0, aspect="16:9", seed=1)
    assert res.png is not None


def test_assets_library_create_character(tmp_path: Path):
    cap = get("assets.library")
    res = cap.render(
        {
            "action": "create",
            "kind": "character",
            "name": "小熊",
            "description": "勇敢的小熊",
            "reference_images": ["ref1.png"],
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=1,
    )
    assert res.qa["name"] == "小熊"
    assert res.qa["kind"] == "character"


def test_assets_library_create_scene(tmp_path: Path):
    cap = get("assets.library")
    res = cap.render(
        {
            "action": "create",
            "kind": "scene",
            "name": "魔法森林",
            "description": "充满发光植物的森林",
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=2,
    )
    assert res.qa["kind"] == "scene"


def test_assets_library_create_prop(tmp_path: Path):
    cap = get("assets.library")
    res = cap.render(
        {
            "action": "create",
            "kind": "prop",
            "name": "星星魔杖",
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=3,
    )
    assert res.qa["kind"] == "prop"


def test_assets_library_empty_name_fails(tmp_path: Path):
    cap = get("assets.library")
    with pytest.raises(CapabilityError):
        cap.render(
            {
                "action": "create",
                "kind": "character",
                "name": "",
            },
            tmp_path,
            duration=0,
            aspect="16:9",
            seed=4,
        )


def test_assets_library_invalid_kind_fails(tmp_path: Path):
    cap = get("assets.library")
    with pytest.raises(CapabilityError):
        cap.render(
            {
                "action": "create",
                "kind": "spaceship",
                "name": "飞船",
            },
            tmp_path,
            duration=0,
            aspect="16:9",
            seed=5,
        )


def test_assets_library_get_nonexistent_fails(tmp_path: Path):
    cap = get("assets.library")
    with pytest.raises(CapabilityError):
        cap.render(
            {
                "action": "get",
                "id": "nonexistent-id",
            },
            tmp_path,
            duration=0,
            aspect="16:9",
            seed=6,
        )


def test_assets_library_get_existing(tmp_path: Path):
    cap = get("assets.library")
    created = cap.render(
        {
            "action": "create",
            "kind": "character",
            "name": "兔兔",
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=7,
    )
    asset_id = created.qa["id"]
    fetched = cap.render(
        {
            "action": "get",
            "id": asset_id,
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=8,
    )
    assert fetched.qa["id"] == asset_id
    assert fetched.qa["name"] == "兔兔"


def test_api_assets_crud_and_persistence():
    # Test POST asset via API
    resp = client.post(
        "/api/golive3/assets",
        json={
            "project_id": "test_proj",
            "kind": "character",
            "name": "API小熊",
            "description": "Test asset",
            "reference_images": ["api_ref.png"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    asset_id = data["id"]
    assert data["name"] == "API小熊"

    # Test GET asset list
    resp_list = client.get("/api/golive3/assets?project_id=test_proj")
    assert resp_list.status_code == 200
    items = resp_list.json()
    assert any(item["id"] == asset_id for item in items)

    # Test GET single asset
    resp_get = client.get(f"/api/golive3/assets/{asset_id}")
    assert resp_get.status_code == 200
    assert resp_get.json()["name"] == "API小熊"

    # Test DELETE asset
    resp_del = client.delete(f"/api/golive3/assets/{asset_id}")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "deleted"


# ─────────────────────────────────────────────────────────────────────────────
# Block 2: assets.extract (Layer4 ImportModule reuse)
# ─────────────────────────────────────────────────────────────────────────────
def test_assets_extract_basic(tmp_path: Path):
    cap = get("assets.extract")
    res = cap.render(
        {"script_text": "场景：魔法森林。\n\n@小熊 拿著 @魔法棒 走进森林。"},
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=1,
    )
    assert "小熊" in res.qa["characters"]
    assert "魔法森林" in res.qa["scenes"]
    assert res.qa["chapters_count"] >= 1


def test_assets_extract_empty_script_fails(tmp_path: Path):
    cap = get("assets.extract")
    with pytest.raises(CapabilityError):
        cap.render({"script_text": ""}, tmp_path, duration=0, aspect="16:9", seed=2)


def test_assets_extract_determinism(tmp_path: Path):
    cap = get("assets.extract")
    script = "【场景：海边】\n\n@波波 拿着 @贝壳。"
    res1 = cap.render({"script_text": script}, tmp_path / "1", duration=0, aspect="16:9", seed=10)
    res2 = cap.render({"script_text": script}, tmp_path / "2", duration=0, aspect="16:9", seed=10)
    assert res1.qa["deterministic_hash"] == res2.qa["deterministic_hash"]
    assert res1.qa["characters"] == res2.qa["characters"]


def test_assets_extract_multiple_characters(tmp_path: Path):
    cap = get("assets.extract")
    res = cap.render(
        {"script_text": "@小熊 和 @兔兔 一起玩耍。"},
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=3,
    )
    assert "小熊" in res.qa["characters"]
    assert "兔兔" in res.qa["characters"]


def test_assets_extract_fallback_heuristics(tmp_path: Path):
    cap = get("assets.extract")
    res = cap.render(
        {"script_text": "小熊在森林里跑来跑去。"},
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=4,
    )
    assert len(res.qa["characters"]) > 0


def test_assets_extract_scene_brackets(tmp_path: Path):
    cap = get("assets.extract")
    res = cap.render(
        {"script_text": "场景：星空城堡。@公主 在唱歌。"},
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=5,
    )
    assert "星空城堡" in res.qa["scenes"]


def test_assets_extract_prop_mention(tmp_path: Path):
    cap = get("assets.extract")
    res = cap.render(
        {"script_text": "@小熊 使用魔法棒变出苹果。"},
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=6,
    )
    assert isinstance(res.qa["props"], list)


def test_assets_extract_result_contract(tmp_path: Path):
    cap = get("assets.extract")
    res = cap.render(
        {"script_text": "@猫咪 在@花园。"},
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=7,
    )
    assert res.png is not None
    assert res.sha256 != ""


# ─────────────────────────────────────────────────────────────────────────────
# Block 3: image.multi_ref_compose (capability_guard limit check)
# ─────────────────────────────────────────────────────────────────────────────
def test_multi_ref_compose_basic(tmp_path: Path):
    cap = get("image.multi_ref_compose")
    res = cap.render(
        {
            "shot_prompt": "@小熊 在 @森林 里散步",
            "references": {"@小熊": "char_bear.png", "@森林": "scene_forest.png"},
            "provider": "h3_local",
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=1,
    )
    assert res.png is not None
    assert res.qa["references_count"] == 2


def test_multi_ref_compose_exceeds_limit_fails(tmp_path: Path):
    cap = get("image.multi_ref_compose")
    with pytest.raises(CapabilityError, match="exceeds provider"):
        cap.render(
            {
                "shot_prompt": "@A @B @C @D @E",
                "references": {"@A": "1.png", "@B": "2.png", "@C": "3.png", "@D": "4.png", "@E": "5.png"},
                "provider": "runway",  # runway max refs is 3
            },
            tmp_path,
            duration=0,
            aspect="16:9",
            seed=2,
        )


def test_multi_ref_compose_zero_refs(tmp_path: Path):
    cap = get("image.multi_ref_compose")
    res = cap.render(
        {
            "shot_prompt": "单纯的日落风景",
            "references": {},
            "provider": "h3_local",
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=3,
    )
    assert res.qa["references_count"] == 0


def test_multi_ref_compose_placeholder_resolution(tmp_path: Path):
    cap = get("image.multi_ref_compose")
    res = cap.render(
        {
            "shot_prompt": "@主角 挥舞 @武器",
            "references": {"@主角": "hero.png", "@武器": "sword.png"},
            "provider": "vidu",
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=4,
    )
    assert res.png is not None


def test_multi_ref_compose_aspect_support(tmp_path: Path):
    cap = get("image.multi_ref_compose")
    assert cap.supports_aspect("9:16")
    assert cap.supports_aspect("16:9")


def test_multi_ref_compose_provider_routing(tmp_path: Path):
    cap = get("image.multi_ref_compose")
    res = cap.render(
        {
            "shot_prompt": "@熊",
            "references": {"@熊": "bear.png"},
            "provider": "h3_local",
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=5,
    )
    assert res.qa["provider"] == "h3_local"


def test_multi_ref_compose_exact_max_limit(tmp_path: Path):
    cap = get("image.multi_ref_compose")
    res = cap.render(
        {
            "shot_prompt": "@1 @2 @3",
            "references": {"@1": "1.png", "@2": "2.png", "@3": "3.png"},
            "provider": "runway",  # max 3
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=6,
    )
    assert res.qa["references_count"] == 3


def test_multi_ref_compose_missing_placeholder_warns(tmp_path: Path):
    cap = get("image.multi_ref_compose")
    res = cap.render(
        {
            "shot_prompt": "晴空万里",
            "references": {"@unused": "img.png"},
            "provider": "h3_local",
        },
        tmp_path,
        duration=0,
        aspect="16:9",
        seed=7,
    )
    assert res.png is not None


# ─────────────────────────────────────────────────────────────────────────────
# Block 4: style.project_snapshot (Persistent & queryable API)
# ─────────────────────────────────────────────────────────────────────────────
def test_project_snapshot_create(tmp_path: Path):
    cap = get("style.project_snapshot")
    res = cap.render(
        {
            "project_id": "proj_1",
            "base_preset": "pixar_3d",
            "overrides": {"lighting": "sunset"},
        },
        tmp_path,
        duration=0,
        aspect="universal",
        seed=1,
    )
    snapshot_id = res.qa["snapshot_id"]
    assert snapshot_id.startswith("snap_")
    assert res.qa["base_preset"] == "pixar_3d"

    # Test API query for snapshot
    resp = client.get(f"/api/golive3/snapshots/{snapshot_id}")
    assert resp.status_code == 200
    assert resp.json()["snapshot_id"] == snapshot_id


def test_project_snapshot_immutability(tmp_path: Path):
    cap = get("style.project_snapshot")
    res1 = cap.render(
        {
            "project_id": "proj_2",
            "base_preset": "anime_v2",
            "overrides": {"color_grade": "warm"},
        },
        tmp_path / "1",
        duration=0,
        aspect="universal",
        seed=1,
    )
    snap1_id = res1.qa["snapshot_id"]

    res2 = cap.render(
        {
            "project_id": "proj_2",
            "base_preset": "anime_v2",
            "overrides": {"color_grade": "cold"},
        },
        tmp_path / "2",
        duration=0,
        aspect="universal",
        seed=1,
    )
    snap2_id = res2.qa["snapshot_id"]
    assert snap1_id != snap2_id


def test_project_snapshot_unchanged_same_params(tmp_path: Path):
    cap = get("style.project_snapshot")
    params = {
        "project_id": "proj_3",
        "base_preset": "claymation",
        "overrides": {"camera": "close_up"},
    }
    res1 = cap.render(params, tmp_path / "1", duration=0, aspect="universal", seed=1)
    res2 = cap.render(params, tmp_path / "2", duration=0, aspect="universal", seed=1)
    assert res1.qa["snapshot_id"] == res2.qa["snapshot_id"]


def test_project_snapshot_default_values(tmp_path: Path):
    cap = get("style.project_snapshot")
    res = cap.render({}, tmp_path, duration=0, aspect="universal", seed=1)
    assert res.qa["snapshot_id"].startswith("snap_")


def test_project_snapshot_multiple_projects(tmp_path: Path):
    cap = get("style.project_snapshot")
    r1 = cap.render({"project_id": "alpha"}, tmp_path / "a", duration=0, aspect="universal", seed=1)
    r2 = cap.render({"project_id": "beta"}, tmp_path / "b", duration=0, aspect="universal", seed=1)
    assert r1.qa["snapshot_id"] != r2.qa["snapshot_id"]


def test_project_snapshot_version_increment(tmp_path: Path):
    cap = get("style.project_snapshot")
    pid = f"v_test_{uuid.uuid4()}"
    r1 = cap.render({"project_id": pid, "overrides": {"v": 1}}, tmp_path / "1", duration=0, aspect="universal", seed=1)
    r2 = cap.render({"project_id": pid, "overrides": {"v": 2}}, tmp_path / "2", duration=0, aspect="universal", seed=1)
    assert r2.qa["version"] > r1.qa["version"]


def test_project_snapshot_preview_artifact(tmp_path: Path):
    cap = get("style.project_snapshot")
    res = cap.render({"project_id": "art"}, tmp_path, duration=0, aspect="universal", seed=1)
    assert res.png is not None
    assert res.sha256 != ""


def test_project_snapshot_schema_valid(tmp_path: Path):
    cap = get("style.project_snapshot")
    valid_params = {"project_id": "p", "base_preset": "pixar_3d", "overrides": {}}
    validated = cap.validate_params(valid_params)
    assert validated["project_id"] == "p"


# ─────────────────────────────────────────────────────────────────────────────
# Block 5: storyboard.shot_groups (StoryPlan model reuse)
# ─────────────────────────────────────────────────────────────────────────────
def test_storyboard_shot_groups_default(tmp_path: Path):
    cap = get("storyboard.shot_groups")
    res = cap.render({}, tmp_path, duration=0, aspect="16:9", seed=1)
    assert res.qa["total_groups"] > 0
    assert res.duration_s > 0


def test_storyboard_shot_groups_custom_shots(tmp_path: Path):
    cap = get("storyboard.shot_groups")
    shots = [
        {"id": "s1", "scene": "A", "duration_s": 5.0, "prompt": "Shot 1"},
        {"id": "s2", "scene": "B", "duration_s": 5.0, "prompt": "Shot 2"},
    ]
    res = cap.render({"shots": shots, "group_duration_s": 10.0}, tmp_path, duration=0, aspect="16:9", seed=1)
    assert res.qa["total_shots"] == 2
    assert len(res.qa["groups"]) == 1


def test_storyboard_shot_groups_split_by_duration(tmp_path: Path):
    cap = get("storyboard.shot_groups")
    shots = [
        {"id": "s1", "scene": "A", "duration_s": 6.0, "prompt": "Prompt 1"},
        {"id": "s2", "scene": "A", "duration_s": 6.0, "prompt": "Prompt 2"},
    ]
    res = cap.render({"shots": shots, "group_duration_s": 5.0}, tmp_path, duration=0, aspect="16:9", seed=1)
    assert len(res.qa["groups"]) == 2


def test_storyboard_shot_groups_constraints(tmp_path: Path):
    cap = get("storyboard.shot_groups")
    shots = [
        {"id": "s1", "scene": "X", "duration_s": 4.0, "prompt": "Start frame"},
        {"id": "s2", "scene": "X", "duration_s": 4.0, "prompt": "End frame"},
    ]
    res = cap.render({"shots": shots, "group_duration_s": 10.0}, tmp_path, duration=0, aspect="16:9", seed=1)
    group = res.qa["groups"][0]
    assert group["first_frame_constraint"] == "Start frame"
    assert group["last_frame_constraint"] == "End frame"


def test_storyboard_shot_groups_empty_shots_uses_defaults(tmp_path: Path):
    cap = get("storyboard.shot_groups")
    res = cap.render({"shots": []}, tmp_path, duration=0, aspect="16:9", seed=1)
    assert res.qa["total_shots"] == 3


def test_storyboard_shot_groups_preview_png(tmp_path: Path):
    cap = get("storyboard.shot_groups")
    res = cap.render({}, tmp_path, duration=0, aspect="16:9", seed=1)
    assert res.png is not None


def test_storyboard_shot_groups_aspect_support(tmp_path: Path):
    cap = get("storyboard.shot_groups")
    assert cap.supports_aspect("16:9")
    assert cap.supports_aspect("9:16")


def test_storyboard_shot_groups_sha256(tmp_path: Path):
    cap = get("storyboard.shot_groups")
    res = cap.render({}, tmp_path, duration=0, aspect="16:9", seed=1)
    assert res.sha256 != ""
