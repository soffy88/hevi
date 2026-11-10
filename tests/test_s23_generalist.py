"""S23：吸收 creator-generalist 的 2D/3D 方法与自检。"""

from __future__ import annotations

from hevi.studio import generalist_s23
from hevi.studio.formats import FORMAT_BY_ID, resolve_format


def test_history_scene_has_cutaway_world_and_editorial_substyles() -> None:
    fmt = FORMAT_BY_ID["history_scene"]
    ids = {style.id for style in fmt.styles}
    assert {"cutaway_3d", "world_3d", "editorial_2d"} <= ids
    plan = resolve_format(format_id="history_scene", style_id="cutaway_3d", line_id=None, slots={})
    assert plan["line_id"] == "scene3d"
    assert plan["slots"]["s23_style"] == "cutaway_3d"
    plan = resolve_format(format_id="history_scene", style_id="editorial_2d", line_id=None, slots={})
    assert plan["line_id"] == "explainer"


def test_explainer_has_editorial_substyle() -> None:
    assert "editorial_2d" in {style.id for style in FORMAT_BY_ID["explainer"].styles}


def test_plan_for_routes_new_styles() -> None:
    cutaway = generalist_s23.plan_for("history_scene", "cutaway_3d", topic="水磨")
    assert cutaway and cutaway["kind"] == "cutaway_3d"
    world = generalist_s23.plan_for("history_scene", "world_3d", topic="汴河", slots={"era": "北宋"})
    assert world and world["kind"] == "world_3d"
    editorial = generalist_s23.plan_for("explainer", "editorial_2d", topic="丝路")
    assert editorial and editorial["kind"] == "editorial_2d"
    reference = generalist_s23.plan_for("material_cut", "reference", topic="参考片")
    assert reference and reference["status"] == "needs_watch"
    shorts = generalist_s23.plan_for("material_cut", "shorts", topic="拆条")
    assert shorts and shorts["kind"] == "shorts_spec"
    assert generalist_s23.plan_for("explainer", "standard", topic="x") is None


def test_cutaway_has_5_to_7_rounds_and_render_policy() -> None:
    plan = generalist_s23.plan_cutaway(topic="14 世纪水磨", rounds=6)
    assert plan["ok"] is True
    assert plan["round_count"] == 6
    assert [item["index"] for item in plan["rounds"]] == [1, 2, 3, 4, 5, 6]
    assert plan["render"]["preview"]["width"] == 720
    assert plan["render"]["final"]["width"] == 1080
    assert plan["render"]["requires_approval"] is True
    assert plan["render"]["queue"] == "serial"
    assert generalist_s23.plan_cutaway(topic="水磨", rounds=99)["round_count"] == 7
    assert generalist_s23.plan_cutaway(topic="水磨", rounds=1)["round_count"] == 5
    assert generalist_s23.plan_cutaway(topic="")["ok"] is False


def test_asset_manifest_enforces_license_credit_and_size() -> None:
    good = generalist_s23.check_asset_manifest([
        {"name": "mill", "license": "CC0", "author": "", "url": "https://example.org/a", "bytes": 10},
        {"name": "wheel", "license": "CC BY", "author": "Ada", "url": "https://example.org/b", "bytes": 20},
    ])
    assert good["ok"] is True
    assert len(good["credits"]) == 2
    bad = generalist_s23.check_asset_manifest([
        {"name": "nc", "license": "CC BY-NC", "bytes": 1},
        {"name": "uncredited", "license": "CC BY", "bytes": 1},
        {"name": "huge", "license": "CC0", "bytes": 301 * 1024 * 1024},
    ])
    codes = {item["code"] for item in bad["issues"]}
    assert {"asset_license", "asset_author_missing", "asset_too_large"} <= codes
    assert bad["ok"] is False
    overflow = generalist_s23.check_asset_manifest(
        [{"name": "big", "license": "CC0", "bytes": 1}], cache_bytes=5 * 1024**3
    )
    assert any(item["code"] == "asset_cache_overflow" for item in overflow["issues"])


def test_credits_markdown_lists_assets() -> None:
    plan = generalist_s23.plan_cutaway(
        topic="水磨", assets=[{"name": "gear", "license": "CC BY", "author": "Bob", "url": "u"}]
    )
    text = generalist_s23.credits_markdown(plan)
    assert "gear" in text and "Bob" in text and "CC BY" in text
    empty = generalist_s23.credits_markdown(generalist_s23.plan_cutaway(topic="水磨"))
    assert "未使用外部 3D 资产" in empty


def test_world_plan_has_period_checks_and_shots() -> None:
    plan = generalist_s23.plan_world(topic="北宋汴河边的一个清晨", era="北宋", shots=5)
    assert plan["ok"] is True
    assert len(plan["shots"]) == 5
    assert {item["id"] for item in plan["checks"]} >= {"period", "geography", "camera"}
    assert plan["render"]["requires_approval"] is True


def test_editorial_timeline_is_true_scale() -> None:
    plan = generalist_s23.plan_editorial_2d(
        topic="丝路",
        route=[{"name": "长安", "lon": 108.9, "lat": 34.3}, {"name": "敦煌", "lon": 94.7, "lat": 40.1},
               {"name": "君士坦丁堡", "lon": 28.9, "lat": 41.0}],
        timeline=[{"label": "张骞", "year": -138}, {"label": "唐", "year": 618}, {"label": "元", "year": 1271}],
    )
    assert plan["ok"] is True
    positions = [event["position"] for event in plan["timeline"]["events"]]
    assert positions[0] == 0.0 and positions[-1] == 1.0
    assert positions[1] < positions[2]
    # 真实比例：唐(618) 在 -138..1271 之间应位于约 0.481
    assert abs(plan["timeline"]["events"][1]["position"] - (618 + 138) / (1271 + 138)) < 0.001
    assert len(plan["route"]["points"]) == 3
    assert plan["route"]["total_length"] > 0
    assert plan["implementation"]["engine"] == "remotion"
    assert len(plan["collage"]["layers"]) >= 3


def test_editorial_rejects_unsorted_timeline() -> None:
    plan = generalist_s23.plan_editorial_2d(
        topic="x", timeline=[{"label": "晚", "year": 2000}, {"label": "早", "year": 1000}]
    )
    assert any(item["code"] == "timeline_order" for item in plan["issues"])


def test_check_timeline_scale_detects_equal_spacing() -> None:
    good = generalist_s23.check_timeline_scale([
        {"label": "a", "year": 0, "position": 0.0},
        {"label": "b", "year": 50, "position": 0.5},
        {"label": "c", "year": 100, "position": 1.0},
    ])
    assert good["ok"] is True
    bad = generalist_s23.check_timeline_scale([
        {"label": "a", "year": 0, "position": 0.0},
        {"label": "b", "year": 50, "position": 0.5},
        {"label": "c", "year": 200, "position": 1.0},
    ])
    assert any(item["code"] == "timeline_not_true_scale" for item in bad["issues"])


def test_motion_rules_head_leads_and_stagger() -> None:
    good = [
        {"part": "head", "kind": "move", "start_frame": 10, "end_frame": 20, "group": "turn"},
        {"part": "torso", "kind": "move", "start_frame": 15, "end_frame": 24, "group": "turn"},
        {"part": "head", "kind": "anticipation", "start_frame": 6, "end_frame": 9},
        {"part": "torso", "kind": "reaction", "start_frame": 26, "end_frame": 30},
    ]
    result = generalist_s23.check_character_motion(good)
    assert result["ok"] is True, result["issues"]

    bad_lead = [
        {"part": "head", "kind": "move", "start_frame": 16, "end_frame": 20, "group": "turn"},
        {"part": "torso", "kind": "move", "start_frame": 15, "end_frame": 24, "group": "turn"},
    ]
    result = generalist_s23.check_character_motion(bad_lead)
    assert any(item["code"] == "head_lead" for item in result["issues"])

    same_stop = [
        {"part": "arm_left", "kind": "move", "start_frame": 1, "end_frame": 10, "group": "g"},
        {"part": "arm_right", "kind": "move", "start_frame": 1, "end_frame": 10, "group": "g"},
    ]
    result = generalist_s23.check_character_motion(same_stop)
    assert any(item["code"] == "joint_stop_stagger" for item in result["issues"])


def test_contact_and_slip_flags_floating_slip_and_crossing() -> None:
    ok = generalist_s23.check_contact_and_slip([
        {"frame": 0, "part": "foot_left", "x": 0.3, "y": 0.0, "planted": True, "solid": True},
        {"frame": 1, "part": "foot_left", "x": 0.3, "y": 0.0, "planted": True, "solid": True},
        {"frame": 1, "part": "foot_right", "x": 0.7, "y": 0.0, "planted": False, "solid": True},
    ])
    assert ok["ok"] is True
    floating = generalist_s23.check_contact_and_slip([
        {"frame": 0, "part": "foot_left", "x": 0.3, "y": 0.2, "planted": True},
    ])
    assert any(item["code"] == "foot_floating" for item in floating["issues"])
    slip = generalist_s23.check_contact_and_slip([
        {"frame": 0, "part": "foot_left", "x": 0.3, "y": 0.0, "planted": True},
        {"frame": 1, "part": "foot_left", "x": 0.4, "y": 0.0, "planted": True},
    ])
    assert any(item["code"] == "foot_slip" for item in slip["issues"])
    crossing = generalist_s23.check_contact_and_slip([
        {"frame": 0, "part": "hand_left", "x": 0.5, "y": 0.5, "solid": True},
        {"frame": 0, "part": "hand_right", "x": 0.505, "y": 0.5, "solid": True},
    ])
    assert any(item["code"] == "limb_crossing" for item in crossing["issues"])


def test_sound_checks() -> None:
    good = generalist_s23.check_phone_speaker({"low": -18, "mid": -6, "high": -14}, loudness_lufs=-14)
    assert good["ok"] is True
    bad = generalist_s23.check_phone_speaker({"low": -2, "mid": -20, "high": -10}, loudness_lufs=-25)
    codes = {item["code"] for item in bad["issues"]}
    assert {"phone_low_dominant", "phone_mid_buried", "phone_too_quiet"} <= codes

    masked = generalist_s23.check_masking([
        {"name": "dialogue", "db": -10},
        {"name": "music", "db": -14},
    ])
    assert any(item["code"] == "stem_masking" for item in masked["issues"])
    clear = generalist_s23.check_masking([
        {"name": "dialogue", "db": -10},
        {"name": "music", "db": -20},
        {"name": "sfx", "db": -16},
    ])
    assert clear["ok"] is True

    sync = generalist_s23.check_sync([
        {"name": "a", "audio_ms": 100, "video_ms": 105},
        {"name": "b", "audio_ms": 200, "video_ms": 300},
    ])
    assert len([item for item in sync["issues"] if item["code"] == "sync_offset"]) == 1


def test_remake_recipe_from_watch_data() -> None:
    recipe = generalist_s23.plan_remake_recipe(
        topic="参考片的开场怎么留人",
        duration_s=30,
        cuts=[{"in_s": 0, "out_s": 10}, {"in_s": 10, "out_s": 20}, {"in_s": 20, "out_s": 30}],
        frames=[{"t": 1, "path": "f1.jpg", "ocr": "标题"}, {"t": 22, "path": "f2.jpg"}],
        transcript=[
            {"start": 0, "end": 5, "text": "开场先给结论"},
            {"start": 20, "end": 25, "text": "最后回到问题"},
        ],
        spectrogram_peaks=[{"t": 0.5, "hz": 120, "db": -10}, {"t": 20.2, "hz": 2000, "db": -8}],
    )
    assert recipe["ok"] is True
    assert len(recipe["shots"]) == 3
    assert recipe["cut_rhythm"]["shot_count"] == 3
    assert recipe["recipe"]["do_not_copy"]
    assert recipe["reference_adapt_slots"]["duration_s"] == 30
    assert recipe["shots"][0]["on_screen_text"] == "标题"
    overlap = generalist_s23.plan_remake_recipe(
        topic="x", duration_s=10, cuts=[{"in_s": 0, "out_s": 5}, {"in_s": 4, "out_s": 8}]
    )
    assert any(item["code"] == "cut_overlap" for item in overlap["issues"])


def test_shorts_audit_catches_gaps_and_passes_clean_spec() -> None:
    clean = generalist_s23.audit_shorts_edit({
        "hook": {"start_s": 0.0, "end_s": 1.5},
        "shots": [{"duration_s": 2.0, "cut_s": 2.0}, {"duration_s": 2.0, "cut_s": 4.0}],
        "beats_s": [2.0, 4.0],
        "captions": [{"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.1}],
        "loudness_lufs": -14,
        "exports": ["tiktok", "reels", "shorts"],
        "duration_s": 30,
    })
    assert clean["pass"] is True and clean["ok"] is True
    dirty = generalist_s23.audit_shorts_edit({
        "hook": {"start_s": 1.0, "end_s": 3.0},
        "shots": [{"duration_s": 5.0, "cut_s": 3.0}],
        "beats_s": [2.0],
        "captions": [{"x": 0.0, "y": 0.02, "w": 1.0, "h": 0.2}],
        "loudness_lufs": -22,
        "exports": ["tiktok"],
        "duration_s": 90,
    })
    codes = {item["code"] for item in dirty["issues"]}
    assert {"shorts_hook_late", "shorts_shot_length", "shorts_caption_safe", "shorts_loudness"} <= codes
    assert dirty["pass"] is False and dirty["score"] < 1.0


def test_catalog_lists_all_kinds() -> None:
    catalog = generalist_s23.catalog()
    assert catalog["version"] == "s23"
    assert "cutaway_3d" in catalog["kinds"]
    assert "shorts_audit" in catalog["kinds"]
    assert catalog["constraints"]["paid_services"] is False


def test_new_styles_route_to_blender_or_code() -> None:
    from hevi.studio.craft_s22 import classify_route

    assert classify_route(format_id="history_scene", style_id="cutaway_3d", line="水磨") == "blender"
    assert classify_route(format_id="history_scene", style_id="world_3d", line="汴河") == "blender"
    assert classify_route(format_id="explainer", style_id="editorial_2d", line="丝路") == "code"
