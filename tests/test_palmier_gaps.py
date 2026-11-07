"""Palmier-gap tests: timeline register, tool readback, model catalogue,
edit recipes. All fixtures are invented for these tests only (a fictional
fog-harbour tea stall); no external text, plot, or person is reused.
Fully offline: no network, no keys, no generation API calls.
"""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.edit_recipes as recipes
import hevi.capabilities.model_catalog as catalog
import hevi.capabilities.timeline_register as timeline
import hevi.capabilities.tool_contract as tools
from hevi.capabilities.tool_contract import ToolSpec, ToolVerificationError


# ---------------------------------------------------------------- item 1
def _clip(clip_id, duration, **extra):
    clip = {"clip_id": clip_id, "file": f"{clip_id}.mp4", "duration_sec": duration}
    clip.update(extra)
    return clip


def test_timeline_register_and_continue_same_track(tmp_path):
    state = timeline.create_timeline("fog-harbour-tea")
    state, first = timeline.register_generation(
        state, _clip("c01", 12.0, source_model="gemini-nano-banana-2.1",
                      source_capability="image.nano_banana_generate",
                      estimated_cost_usd=0.0336))
    assert (first["timeline_start_sec"], first["timeline_end_sec"]) == (0.0, 12.0)
    assert first["track"] == "video"
    assert first["source_model"] == "gemini-nano-banana-2.1"
    assert first["estimated_cost_usd"] == 0.0336
    # Reload from disk, then generate again: same track, continued, old kept.
    path = timeline.save_timeline(state, tmp_path / "timeline.json")
    reloaded = timeline.load_timeline(path)
    assert len(reloaded["clips"]) == 1
    reloaded, second = timeline.register_generation(reloaded, _clip("c02", 8.0))
    assert second["track"] == "video"
    assert (second["timeline_start_sec"], second["timeline_end_sec"]) == (12.0, 20.0)
    snap = timeline.read_timeline(reloaded)
    assert snap["clip_count"] == 2
    assert [c["clip_id"] for c in snap["clips"]] == ["c01", "c02"]
    assert snap["tracks"]["video"]["total_duration_sec"] == 20.0
    # Input state is not mutated by a registration that is discarded.
    before = timeline.create_timeline("untouched")
    timeline.register_generation(before, _clip("x01", 5.0))
    assert before["clips"] == []


def test_timeline_rejects_duplicate_and_bad_clips():
    state = timeline.create_timeline("p")
    state, _ = timeline.register_generation(state, _clip("c01", 5.0))
    with pytest.raises(CapabilityError):
        timeline.register_generation(state, _clip("c01", 5.0))
    with pytest.raises(CapabilityError):
        timeline.register_generation(state, {"clip_id": "c02", "file": "c02.mp4", "duration_sec": 0})
    with pytest.raises(CapabilityError):
        timeline.register_generation(state, {"clip_id": "c03", "duration_sec": 5.0})


def test_timeline_capability_register_and_read(tmp_path):
    cap = registry.get("edit.timeline_register")
    result = cap.render_safe(
        {"action": "register", "project_id": "fog-harbour-tea",
         "timeline_path": str(tmp_path / "t.json"),
         "clip_id": "c01", "file": "c01.mp4", "duration_sec": 10.0,
         "source_model": "gemini-nano-banana-2.1", "estimated_cost_usd": 0.0336},
        tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert result.qa["entry"]["timeline_end_sec"] == 10.0
    again = cap.render_safe(
        {"action": "register", "timeline_path": str(tmp_path / "t.json"),
         "clip_id": "c02", "file": "c02.mp4", "duration_sec": 4.0},
        tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert again.qa["entry"]["timeline_start_sec"] == 10.0
    read = cap.render_safe(
        {"action": "read", "timeline_path": str(tmp_path / "t.json")},
        tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert read.qa["timeline"]["clip_count"] == 2


# ---------------------------------------------------------------- item 2
def test_tool_categories_are_split_and_schema_ui_separate():
    specs = tools.builtin_tools()
    assert sorted(s.category for s in specs) == [
        "edit_timeline", "export", "generate", "read_state", "undo"]
    assert len({s.name for s in specs}) == 5
    for spec in specs:
        desc = tools.tool_descriptor(spec)
        assert desc["ui"]["label"]
        # UI copy must not leak into the machine schema.
        assert desc["ui"]["label"] not in json.dumps(desc["params_schema"], ensure_ascii=False)


def test_tool_write_verified_by_readback_and_undo(tmp_path):
    state = timeline.create_timeline("p")
    by_name = tools.builtin_tool_map()
    out = tools.execute_tool(by_name["timeline.append"],
                             {"clip_id": "c01", "file": "c01.mp4", "duration_sec": 6.0}, state)
    assert out["verified_state"]["clip_count"] == 1
    assert out["verified_state"]["last_end_sec"] == 6.0
    # Success response alone is not completion: the verified state is.
    assert state["clips"][0]["clip_id"] == "c01"
    out = tools.execute_tool(by_name["timeline.undo"], {}, state)
    assert out["verified_state"]["clip_count"] == 0
    exported = tools.execute_tool(by_name["timeline.export"],
                                  {"path": str(tmp_path / "out.json")}, state)
    assert exported["verified_state"]["exported_clip_count"] == 0
    assert json.loads((tmp_path / "out.json").read_text())["clip_count"] == 0
    read = tools.execute_tool(by_name["timeline.read"], {}, state)
    assert read["timeline"]["clip_count"] == 0


def test_tool_generate_category_registers_fake_generation():
    tools.register_generator("fake-harbour", lambda params: {
        "clip_id": "g01", "file": "g01.mp4", "duration_sec": 7.0,
        "source_model": "fake-model", "source_capability": "test.fake"})
    state = timeline.create_timeline("p")
    out = tools.execute_tool(tools.builtin_tool_map()["timeline.generate"],
                             {"generator": "fake-harbour", "prompt": "fog over the harbour"}, state)
    assert out["entry"]["clip_id"] == "g01"
    assert out["verified_state"]["clip_count"] == 1


def test_tool_readback_mismatch_is_error_not_success():
    # Handler claims a clip landed; the readback store says otherwise.
    def lying_handler(params, store):
        return {"expected_after": {"clip_ids": ["ghost"], "clip_count": 1}}
    spec = ToolSpec(
        name="test.lying-write", category="edit_timeline",
        params_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ui={"label": "lying write"},
        handler=lying_handler,
        readback=lambda p, s, r: {"clip_ids": [], "clip_count": 0})
    with pytest.raises(ToolVerificationError):
        tools.execute_tool(spec, {}, {"clips": []})


def test_tool_write_without_readback_refused_before_execution():
    ran = []
    spec = ToolSpec(
        name="test.no-readback", category="edit_timeline",
        params_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ui={"label": "no readback"},
        handler=lambda p, s: ran.append(True) or {"expected_after": {"x": 1}})
    with pytest.raises(ToolVerificationError):
        tools.execute_tool(spec, {}, {})
    assert ran == []


def test_tool_bad_params_refused():
    by_name = tools.builtin_tool_map()
    with pytest.raises(CapabilityError):
        tools.execute_tool(by_name["timeline.append"],
                           {"clip_id": "c01", "file": "c01.mp4", "duration_sec": -3},
                           timeline.create_timeline("p"))


# ---------------------------------------------------------------- item 3
def test_model_catalogue_ids_and_prices():
    models = {m["key"]: m for m in catalog.list_models()}
    assert set(models) == {
        "nano_banana_2.1", "nano_banana_2_lite", "nano_banana_2",
        "nano_banana_pro", "nano_banana"}
    assert models["nano_banana_2.1"]["model_id"] == "gemini-nano-banana-2.1"
    assert models["nano_banana_2_lite"]["model_id"] == "gemini-3.1-flash-lite-image"
    assert models["nano_banana_2"]["model_id"] == "gemini-3.1-flash-image"
    assert models["nano_banana_pro"]["model_id"] == "gemini-3-pro-image"
    assert models["nano_banana"]["model_id"] == "gemini-2.5-flash-image"
    assert catalog.get_model("gemini-nano-banana-2.1")["key"] == "nano_banana_2.1"
    assert catalog.default_model_id() == "gemini-nano-banana-2.1"
    est = catalog.estimate_cost("nano_banana_2.1", "1K", 2)
    assert est["per_image_usd"] == 0.0336 and est["estimated_cost_usd"] == 0.0672
    assert catalog.estimate_cost("nano_banana_2.1", "2K", 1)["estimated_cost_usd"] == 0.0504
    assert catalog.estimate_cost("nano_banana_2.1", "4K", 1)["estimated_cost_usd"] == 0.113
    assert catalog.estimate_cost("nano_banana_2", "1K", 1)["estimated_cost_usd"] == 0.067
    assert catalog.estimate_cost("nano_banana_2", "2K", 1)["estimated_cost_usd"] == 0.101
    assert catalog.estimate_cost("nano_banana_2", "4K", 1)["estimated_cost_usd"] == 0.151
    assert catalog.estimate_cost("nano_banana_2_lite", "1K", 1)["estimated_cost_usd"] == 0.0336
    # Unverified prices are None, never invented.
    assert catalog.estimate_cost("nano_banana_2_lite", "2K", 1)["estimated_cost_usd"] is None
    assert catalog.estimate_cost("nano_banana_pro", "1K", 1)["estimated_cost_usd"] is None
    assert catalog.estimate_cost("nano_banana", "1K", 1)["estimated_cost_usd"] is None
    with pytest.raises(CapabilityError):
        catalog.estimate_cost("no-such-model", "1K", 1)


def test_cost_gate_blocks_by_default_and_allows_explicitly():
    est = catalog.estimate_cost("nano_banana_2.1", "1K", 1)
    with pytest.raises(CapabilityError):
        catalog.check_cost_gate(est, False)
    with pytest.raises(CapabilityError):
        catalog.estimate_and_gate("nano_banana_2.1", "1K", 1, allow_paid=False)
    allowed = catalog.estimate_and_gate("nano_banana_2.1", "1K", 1, allow_paid=True)
    assert allowed["cost_gate"] == "allowed" and allowed["estimated_cost_usd"] == 0.0336
    # Unknown price + explicit allow_paid: allowed but flagged, estimate stays None.
    unknown = catalog.estimate_and_gate("nano_banana_pro", "1K", 1, allow_paid=True)
    assert unknown["estimated_cost_usd"] is None and unknown["unknown_price_accepted"] is True


def test_model_catalog_capability_and_nano_banana_agree():
    cap = registry.get("model.model_catalog")
    result = cap.render_safe({"action": "estimate", "model": "nano_banana_2.1",
                              "image_size": "1K", "n": 2, "allow_paid": True},
                             Path(result_dir := __import__("tempfile").mkdtemp()),
                             duration=0.0, aspect="16:9", seed=1)
    assert result.qa["estimate"]["estimated_cost_usd"] == 0.0672
    with pytest.raises(CapabilityError):
        cap.render_safe({"action": "estimate", "model": "nano_banana_2.1",
                         "image_size": "1K", "n": 1},
                        Path(__import__("tempfile").mkdtemp()),
                        duration=0.0, aspect="16:9", seed=1)
    # nano_banana now reads its prices from the same catalogue data.
    import hevi.capabilities.nano_banana as nb
    assert nb.PER_IMAGE_USD == catalog.per_image_prices()


# ---------------------------------------------------------------- item 4
def _recipe(**over):
    base = {
        "name": "harbour-morning",
        "description": "Slow push-in, golden light, whoosh on the cut, rain bed under.",
        "movement_id": "dolly_in",
        "layer_ids": ["vv_golden_hour", "vv_rule_thirds"],
        "transition": "dissolve",
        "sfx_ids": ["whoosh_transition", "rain_bed"],
        "rhythm": {"tempo_bpm": 72, "cut_on_beat": True, "max_shot_sec": 12},
    }
    base.update(over)
    return base


def test_recipe_save_load_list_apply(tmp_path):
    store = tmp_path / "recipes"
    path = recipes.save_recipe(store, _recipe())
    assert Path(path).exists()
    loaded = recipes.load_recipe(store, "harbour-morning")
    assert loaded["movement_id"] == "dolly_in"
    assert loaded["transition"] == "dissolve"
    assert recipes.list_recipes(store) == ["harbour-morning"]
    plan = recipes.apply_recipe(loaded, [{"shot_id": "S01"}, {"shot_id": "S02"}])
    assert plan["recipe_name"] == "harbour-morning"
    assert [s["shot_id"] for s in plan["shots"]] == ["S01", "S02"]
    assert all(s["movement_id"] == "dolly_in" and s["transition"] == "dissolve" for s in plan["shots"])
    assert all(s["sfx_ids"] == ["whoosh_transition", "rain_bed"] for s in plan["shots"])
    assert all(s["rhythm"]["tempo_bpm"] == 72 for s in plan["shots"])
    # The stored file is plain data: no executable step in it.
    raw = json.loads(Path(path).read_text())
    assert "code" not in raw and "exec" not in raw


def test_recipe_rejects_unknown_movement_sfx_and_code_keys(tmp_path):
    store = tmp_path / "recipes"
    with pytest.raises(CapabilityError):
        recipes.save_recipe(store, _recipe(movement_id="no_such_move"))
    with pytest.raises(CapabilityError):
        recipes.save_recipe(store, _recipe(sfx_ids=["no_such_sfx"]))
    with pytest.raises(CapabilityError):
        recipes.save_recipe(store, _recipe(layer_ids=["vv_dolly"]))
    with pytest.raises(CapabilityError):
        recipes.save_recipe(store, _recipe(transition="wipe"))
    bad = _recipe()
    bad["code"] = "print(1)"
    with pytest.raises(CapabilityError):
        recipes.save_recipe(store, bad)
    # A hand-edited file is re-validated on load, not trusted.
    good = recipes.save_recipe(store, _recipe())
    data = json.loads(Path(good).read_text())
    data["sfx_ids"] = ["no_such_sfx"]
    Path(good).write_text(json.dumps(data))
    with pytest.raises(CapabilityError):
        recipes.load_recipe(store, "harbour-morning")


def test_recipe_capability_and_registration(tmp_path):
    cap = registry.get("edit.edit_recipe")
    result = cap.render_safe(
        {"action": "save", "store_dir": str(tmp_path / "r"), "recipe": _recipe()},
        tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert result.qa["recipe"]["name"] == "harbour-morning"
    applied = cap.render_safe(
        {"action": "apply", "store_dir": str(tmp_path / "r"),
         "name": "harbour-morning", "shots": [{"shot_id": "S01"}]},
        tmp_path, duration=0.0, aspect="16:9", seed=1)
    assert applied.qa["plan"]["shots"][0]["movement_id"] == "dolly_in"
    names = set(registry.names())
    assert {"edit.timeline_register", "model.model_catalog", "edit.edit_recipe"} <= names
