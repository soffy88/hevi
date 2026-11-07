"""Pixelle-Video gap fill (2026-10-25): supplier directory, user-asset
script draft, named edit templates. Clean-room implementations of
borrowed ideas only; offline, zero real cost, fictional fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
import hevi.capabilities.asset_script as asset_script
import hevi.capabilities.edit_templates as templates
import hevi.capabilities.model_catalog as catalog
import hevi.capabilities.provider_catalog as providers
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities import registry


# ---------------------------------------------------------------- item 1
def test_provider_directory_shape_and_routes():
    rows = {p["key"]: p for p in providers.list_providers()}
    assert set(rows) == {"gemini_api", "pixstag", "monid"}
    for key, row in rows.items():
        routes = providers.list_routes(key)
        assert set(routes) == {"direct_api", "comfyui", "runninghub"}
        assert routes["direct_api"]["supported"] is True
    gemini = providers.get_provider("gemini_api")
    assert gemini["routes"]["direct_api"]["endpoint"] == "https://generativelanguage.googleapis.com"
    assert gemini["routes"]["direct_api"]["endpoint_verified"] is True
    assert gemini["routes"]["comfyui"]["supported"] is False
    assert gemini["routes"]["runninghub"]["supported"] is False
    assert set(gemini["models"]) == {
        "nano_banana_2.1", "nano_banana_2_lite", "nano_banana_2",
        "nano_banana_pro", "nano_banana"}
    assert providers.get_provider("pixstag")["routes"]["direct_api"]["endpoint"] == "https://pixstag.com"
    # Monid base URL is not recorded in hevi: null, never invented.
    monid_route = providers.get_route("monid", "direct_api")
    assert monid_route["endpoint"] is None and monid_route["endpoint_verified"] is False
    # DashScope is deliberately absent (account in arrears, no verified mapping).
    assert "dashscope" not in rows
    with pytest.raises(CapabilityError):
        providers.get_provider("no-such-supplier")
    with pytest.raises(CapabilityError):
        providers.get_route("gemini_api", "no-such-route")


def test_provider_central_config_names_only():
    config = providers.central_config()
    assert set(config) == {"gemini_api", "pixstag", "monid"}
    assert config["gemini_api"]["auth_env"] == ["GEMINI_API_KEY", "GOOGLE_API_KEY"]
    assert config["pixstag"]["auth_env"] == ["PIXSTAG_API_KEY"]
    assert config["monid"]["auth_env"] == ["MONID_API_KEY"]
    for entry in config.values():
        assert all(isinstance(v, bool) for v in entry["auth_configured"].values())
        assert all(isinstance(v, bool) for v in entry["endpoint_configured"].values())


def test_provider_estimate_matches_model_catalog_and_gate():
    est = providers.estimate_provider_cost("gemini_api", "nano_banana_2.1", "1K", 2)
    assert est["estimated_cost_usd"] == 0.0672
    assert est["provider"] == "gemini_api" and est["model_key"] == "nano_banana_2.1"
    assert est["estimated_cost_usd"] == catalog.estimate_cost("nano_banana_2.1", "1K", 2)["estimated_cost_usd"]
    assert est["per_image_usd"] == catalog.per_image_prices()["gemini-nano-banana-2.1"]["1K"]
    # Every Gemini model/size agrees with model_catalog (no price copy drift).
    for key in ("nano_banana_2.1", "nano_banana_2_lite", "nano_banana_2", "nano_banana_pro", "nano_banana"):
        for size in ("1K", "2K", "4K"):
            got = providers.estimate_provider_cost("gemini_api", key, size, 1)
            want = catalog.estimate_cost(key, size, 1)
            assert got["estimated_cost_usd"] == want["estimated_cost_usd"]
            assert got["price_known"] == want["price_known"]
    # Unknown price stays None, never invented (Pro; PixStag per-second credits).
    assert providers.estimate_provider_cost("gemini_api", "nano_banana_pro", "1K", 1)["estimated_cost_usd"] is None
    pix = providers.estimate_provider_cost("pixstag", "minimax_h3", "1K", 1)
    assert pix["estimated_cost_usd"] is None and pix["price_known"] is False
    assert providers.estimate_provider_cost("monid", "gpt_image", "1K", 1)["estimated_cost_usd"] is None
    with pytest.raises(CapabilityError):
        providers.estimate_provider_cost("gemini_api", "no-such-model", "1K", 1)
    with pytest.raises(CapabilityError):
        providers.estimate_and_gate("gemini_api", "nano_banana_2.1", "1K", 1, allow_paid=False)
    allowed = providers.estimate_and_gate("gemini_api", "nano_banana_2.1", "1K", 1, allow_paid=True)
    assert allowed["cost_gate"] == "allowed" and allowed["estimated_cost_usd"] == 0.0336
    unknown = providers.estimate_and_gate("gemini_api", "nano_banana_pro", "1K", 1, allow_paid=True)
    assert unknown["estimated_cost_usd"] is None and unknown["unknown_price_accepted"] is True


def test_provider_capability_registered_and_renders(tmp_path):
    assert "model.provider_catalog" in set(registry.names())
    cap = registry.get("model.provider_catalog")
    listed = cap.render_safe({"action": "list"}, tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert {p["key"] for p in listed.qa["providers"]} == {"gemini_api", "pixstag", "monid"}
    cfg = cap.render_safe({"action": "central_config"}, tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert set(cfg.qa["config"]) == {"gemini_api", "pixstag", "monid"}
    with pytest.raises(CapabilityError):
        cap.render_safe({"action": "estimate", "provider": "gemini_api", "model": "nano_banana_2.1",
                         "image_size": "1K", "n": 1},
                        tmp_path, duration=0.0, aspect="16:9", seed=1)
    ok = cap.render_safe({"action": "estimate", "provider": "gemini_api", "model": "nano_banana_2.1",
                          "image_size": "1K", "n": 1, "allow_paid": True},
                         tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert ok.qa["estimate"]["estimated_cost_usd"] == 0.0336


# ---------------------------------------------------------------- item 2
def _assets():
    return [
        {"asset_id": "morning-market", "kind": "photo", "path": "fixture/market.jpg",
         "note": "fictional morning market"},
        {"asset_id": "river-walk", "kind": "video", "path": "fixture/river.mp4",
         "note": "fictional riverside walk"},
    ]


def _fake_vlm(asset):
    fixture = {
        "morning-market": {"people": ["卖菜阿婆"], "scene": ["清晨菜市场"],
                           "objects": ["竹篮"], "mood": "烟火气"},
        "river-walk": {"people": ["晨跑青年"], "scene": ["河边步道"],
                       "objects": ["石桥"], "mood": "清爽"},
    }
    return fixture[asset["asset_id"]]


def test_asset_registration_validation():
    assert [a["asset_id"] for a in asset_script.register_assets(_assets())] == ["morning-market", "river-walk"]
    with pytest.raises(CapabilityError):
        asset_script.register_assets([])
    with pytest.raises(CapabilityError):
        asset_script.register_assets([{"asset_id": "x", "kind": "audio"}])
    with pytest.raises(CapabilityError):
        asset_script.register_assets([{"asset_id": "Bad ID", "kind": "photo"}])
    with pytest.raises(CapabilityError):
        asset_script.register_assets([{"asset_id": "dup", "kind": "photo"}, {"asset_id": "dup", "kind": "video"}])


def test_asset_script_with_fake_vlm_is_ready_and_quotes_analysis():
    result = asset_script.asset_script(_assets(), vlm_fn=_fake_vlm, title="Fictional Morning")
    assert result["status"] == "ready"
    assert result["draft"] is not None
    assert result["draft"]["title"] == "Fictional Morning"
    points = [p for s in result["draft"]["scenes"] for p in s["shot_points"]]
    for expected in ("清晨菜市场", "卖菜阿婆", "竹篮", "河边步道", "晨跑青年", "石桥", "烟火气"):
        assert any(expected in p for p in points), f"draft must quote analysis field {expected!r}"
    assert result["draft"]["scenes"][0]["asset_id"] == "morning-market"
    assert result["draft"]["scenes"][1]["asset_id"] == "river-walk"


def test_asset_script_without_vlm_is_pending_not_fabricated():
    asset_script.set_vlm_fn(None)
    result = asset_script.asset_script(_assets())
    assert result["status"] == "pending"
    assert result["analysis"] is None and result["draft"] is None
    assert "DashScope" in result["note"] and "not" in result["note"].lower() or "NOT" in result["note"]
    assert "pending" in result["note"].lower() or result["status"] == "pending"


def test_asset_script_vlm_failure_and_empty_analysis_are_pending():
    def _boom(asset):
        raise RuntimeError("vlm exploded")
    failed = asset_script.asset_script(_assets(), vlm_fn=_boom)
    assert failed["status"] == "pending" and failed["draft"] is None and failed["failures"]
    empty = asset_script.asset_script(_assets(), vlm_fn=lambda a: {"people": [], "scene": [], "objects": [], "mood": ""})
    assert empty["status"] == "pending" and empty["draft"] is None
    # A non-dict VLM return is a VLM failure, so it degrades to pending
    # (same contract as reference_decompose LLM failure), never a crash.
    bad_shape = asset_script.asset_script(_assets(), vlm_fn=lambda a: "not a dict")
    assert bad_shape["status"] == "pending" and bad_shape["draft"] is None and bad_shape["failures"]


def test_asset_script_capability_registered_and_renders(tmp_path):
    assert "story.asset_script" in set(registry.names())
    cap = registry.get("story.asset_script")
    try:
        asset_script.set_vlm_fn(_fake_vlm)
        ok = cap.render_safe({"assets": _assets(), "title": "Fictional Morning"},
                             tmp_path, duration=0.0, aspect="16:9", seed=1)
        assert ok.qa["status"] == "ready"
        assert ok.qa["draft"]["shot_point_count"] >= 6
    finally:
        asset_script.set_vlm_fn(None)
    pending = cap.render_safe({"assets": _assets()}, tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert pending.qa["status"] == "pending" and pending.qa["draft"] is None


# ---------------------------------------------------------------- item 3
def _vertical_static(**over):
    base = {
        "name": "street-still",
        "description": "Vertical locked-off street portrait.",
        "orientation": "9:16",
        "shot_kind": "static",
        "movement_id": None,
        "layer_ids": ["vv_golden_hour", "vv_rule_thirds"],
        "transition": "cut",
        "sfx_ids": ["room_tone_bed"],
        "rhythm": {"tempo_bpm": 72, "cut_on_beat": False, "max_shot_sec": 8},
    }
    base.update(over)
    return base


def _horizontal_moving(**over):
    base = {
        "name": "street-push",
        "description": "Horizontal push-in street scene.",
        "orientation": "16:9",
        "shot_kind": "moving",
        "movement_id": "dolly_in",
        "layer_ids": ["vv_golden_hour"],
        "transition": "dissolve",
        "sfx_ids": ["whoosh_transition"],
        "rhythm": {"tempo_bpm": 90, "cut_on_beat": True, "max_shot_sec": 10},
    }
    base.update(over)
    return base


def test_template_save_load_list(tmp_path):
    store = tmp_path / "templates"
    path = templates.save_template(store, _vertical_static())
    assert Path(path).exists()
    loaded = templates.load_template(store, "street-still")
    assert loaded["orientation"] == "9:16" and loaded["shot_kind"] == "static"
    assert loaded["movement_id"] is None
    assert templates.list_templates(store) == ["street-still"]
    raw = json.loads(Path(path).read_text())
    assert "code" not in raw and "exec" not in raw


def test_template_rejects_static_movement_moving_gaps_and_code(tmp_path):
    store = tmp_path / "templates"
    with pytest.raises(CapabilityError):
        templates.save_template(store, _vertical_static(movement_id="dolly_in"))
    with pytest.raises(CapabilityError):
        templates.save_template(store, _vertical_static(layer_ids=["vv_dolly"]))
    with pytest.raises(CapabilityError):
        templates.save_template(store, _horizontal_moving(movement_id=None))
    with pytest.raises(CapabilityError):
        templates.save_template(store, _horizontal_moving(movement_id="no_such_move"))
    with pytest.raises(CapabilityError):
        templates.save_template(store, _horizontal_moving(layer_ids=["vv_crane"]))
    with pytest.raises(CapabilityError):
        templates.save_template(store, _horizontal_moving(sfx_ids=["no_such_sfx"]))
    with pytest.raises(CapabilityError):
        templates.save_template(store, _horizontal_moving(transition="wipe"))
    with pytest.raises(CapabilityError):
        templates.save_template(store, _horizontal_moving(orientation="1:1"))
    with pytest.raises(CapabilityError):
        templates.save_template(store, _horizontal_moving(unknown_key=1))
    bad = _horizontal_moving()
    bad["rhythm"] = {"tempo_bpm": 90, "command": "rm -rf /"}
    with pytest.raises(CapabilityError):
        templates.save_template(store, bad)
    # Hand-edited file is re-validated on load, not trusted.
    good = templates.save_template(store, _horizontal_moving())
    data = json.loads(Path(good).read_text())
    data["movement_id"] = "no_such_move"
    Path(good).write_text(json.dumps(data))
    with pytest.raises(CapabilityError):
        templates.load_template(store, "street-push")


def test_template_select_orientation_match_and_mismatch():
    vertical = templates.validate_template(_vertical_static())
    selected = templates.select_template(vertical, "9:16")
    assert selected["matched"] is True and selected["orientation_label"] == "vertical"
    with pytest.raises(CapabilityError):
        templates.select_template(vertical, "16:9")
    moving = templates.validate_template(_horizontal_moving())
    assert templates.select_template(moving, "16:9")["orientation_label"] == "horizontal"
    with pytest.raises(CapabilityError):
        templates.select_template(moving, "9:16")


def test_template_preview_is_readable_plan_not_video():
    static_plan = templates.preview_template(
        _vertical_static(), [{"shot_id": "S01"}, {"shot_id": "S02"}], "9:16")
    assert static_plan["shot_count"] == 2
    assert static_plan["orientation_label"] == "vertical"
    assert all(s["movement"] == "固定画面" and s["movement_id"] is None for s in static_plan["shots"])
    assert static_plan["shots"][0]["layers"] and static_plan["shots"][0]["sfx_ids"] == ["room_tone_bed"]
    assert "mp4" not in json.dumps(static_plan)
    moving_plan = templates.preview_template(
        _horizontal_moving(), [{"shot_id": "S01"}], "16:9")
    assert moving_plan["shots"][0]["movement_id"] == "dolly_in"
    assert moving_plan["shots"][0]["movement"]
    assert moving_plan["shots"][0]["movement"] != "固定画面"
    with pytest.raises(CapabilityError):
        templates.preview_template(_horizontal_moving(), [], "16:9")
    with pytest.raises(CapabilityError):
        templates.preview_template(_horizontal_moving(), [{"no_id": 1}], "16:9")


def test_template_capability_registered_and_renders(tmp_path):
    assert "edit.edit_template" in set(registry.names())
    cap = registry.get("edit.edit_template")
    saved = cap.render_safe({"action": "save", "store_dir": str(tmp_path / "t"),
                             "template": _vertical_static()},
                            tmp_path, duration=0.0, aspect="9:16", seed=1)
    assert saved.qa["template"]["name"] == "street-still"
    with pytest.raises(CapabilityError):
        cap.render_safe({"action": "select", "store_dir": str(tmp_path / "t"),
                         "name": "street-still", "aspect": "16:9"},
                        tmp_path, duration=0.0, aspect="16:9", seed=1)
    selected = cap.render_safe({"action": "select", "store_dir": str(tmp_path / "t"),
                                "name": "street-still", "aspect": "9:16"},
                               tmp_path, duration=0.0, aspect="9:16", seed=1)
    assert selected.qa["selection"]["matched"] is True
    preview = cap.render_safe({"action": "preview", "store_dir": str(tmp_path / "t"),
                               "name": "street-still", "aspect": "9:16",
                               "shots": [{"shot_id": "S01"}]},
                              tmp_path, duration=0.0, aspect="9:16", seed=1)
    assert preview.qa["plan"]["shots"][0]["movement"] == "固定画面"


# ---------------------------------------------------------------- item 4
def test_new_capabilities_mount_via_package_import():
    # Item 4对照: talking_head has no plugin/extension registry (its
    # pipeline stages are direct imports, verified by grep at build
    # time), so the single mount point for a new module is the unified
    # registry plus the __init__ import -- the same mount talking_head
    # itself uses. These three names must therefore be present after
    # `import hevi.capabilities` alone, which the G13 completeness
    # guard also checks in a fresh subprocess.
    names = set(caps.names())
    assert {"model.provider_catalog", "story.asset_script", "edit.edit_template"} <= names
    assert "talking_head.render" in names
