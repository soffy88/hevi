"""Contract tests for the Blender clay capability (CAPABILITY_CONTRACT.md).

Offline only: the real Blender render is an acceptance step, not a CI test.
The missing-binary path is exercised by monkeypatching ``find_blender`` on
the engine module; the capability resolves it through that module object at
call time, so the patch takes effect.
"""

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.video import blender_clay as clay


def test_blender_clay_registered_and_listable() -> None:
    assert "video.blender_clay_render" in caps.names()
    listed = [c.name for c in caps.list(kind="shot")]
    assert "video.blender_clay_render" in listed


def test_blender_clay_describe_has_schema_and_cost_warning() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    assert "video.blender_clay_render" in by_name
    item = by_name["video.blender_clay_render"]
    assert item.get("description")
    # The description must carry the quantified CPU warning, not just vibes.
    assert "75s" in item["description"]
    assert "480p" in item["description"]
    assert item["cpu_cost_hint"] >= 10  # it is a slow CPU render, honestly priced
    schema = item.get("params_schema") or {}
    props = schema.get("properties") or {}
    for expected in ("preset", "motion", "palette", "resolution", "fps", "samples", "seed"):
        assert expected in props, expected
    assert schema.get("additionalProperties") is False


def test_blender_clay_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("video.blender_clay_render")
    with pytest.raises(CapabilityError):  # unknown preset
        cap.render_safe({"preset": "dragon"}, tmp_path, duration=2.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):  # unknown resolution
        cap.render_safe({"resolution": "4k"}, tmp_path, duration=2.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):  # samples out of range
        cap.render_safe({"samples": 999}, tmp_path, duration=2.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):  # additional property
        cap.render_safe({"bogus": 1}, tmp_path, duration=2.0, aspect="9:16", seed=1)


def test_blender_clay_rejects_bad_duration_and_aspect(tmp_path: Path) -> None:
    cap = caps.get("video.blender_clay_render")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path, duration=30.0, aspect="9:16", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path, duration=2.0, aspect="4:3", seed=1)


def test_blender_clay_missing_binary_surfaces_as_capability_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(clay, "find_blender", lambda explicit=None: None)
    cap = caps.get("video.blender_clay_render")
    with pytest.raises(CapabilityError) as excinfo:
        cap.render_safe({}, tmp_path, duration=2.0, aspect="9:16", seed=1)
    assert "blender" in str(excinfo.value).lower()
    assert "HEVI_BLENDER_BIN" in str(excinfo.value)


def test_find_blender_rejects_nonexistent_explicit() -> None:
    # An explicit bogus path must never be returned as-is (the search may
    # legitimately fall through to a real install found later in the chain).
    result = clay.find_blender("/definitely/not/a/real/blender-binary")
    assert result != "/definitely/not/a/real/blender-binary"


def test_resolve_resolution_aspects() -> None:
    assert clay.resolve_resolution("480p", "16:9") == (854, 480)
    assert clay.resolve_resolution("480p", "9:16") == (480, 854)
    assert clay.resolve_resolution("540p", "9:16") == (540, 960)
    assert clay.resolve_resolution("540p", "1:1") == (540, 540)
    with pytest.raises(CapabilityError):
        clay.resolve_resolution("720p", "16:9")
    with pytest.raises(CapabilityError):
        clay.resolve_resolution("480p", "4:3")


def test_frame_count_for() -> None:
    assert clay.frame_count_for(2.5, 24) == 60
    assert clay.frame_count_for(3.0, 24) == 72
    assert clay.frame_count_for(2.0, 24) == 48
    with pytest.raises(CapabilityError):
        clay.frame_count_for(0, 24)


def test_compute_keyframes_bounce_endpoints_and_shape() -> None:
    keys = clay.compute_keyframes(60, 24, "bounce")
    assert keys[0]["frame"] == 1
    assert keys[-1]["frame"] == 60
    frames = [k["frame"] for k in keys]
    assert frames == sorted(frames) and len(set(frames)) == len(frames)
    # Bounce actually leaves the ground: some key is well above the base.
    assert max(k["location"][2] for k in keys) > 1.5
    assert all(k["location"][1] == 0.0 for k in keys)


def test_compute_keyframes_slide_turn_endpoints() -> None:
    keys = clay.compute_keyframes(48, 24, "slide_turn")
    assert keys[0]["location"][0] == pytest.approx(-1.6)
    assert keys[-1]["location"][0] == pytest.approx(1.6)
    assert keys[0]["rotation_z"] < keys[-1]["rotation_z"]
    with pytest.raises(CapabilityError):
        clay.compute_keyframes(48, 24, "spin_forever")


def test_build_config_and_script_are_deterministic_and_clay() -> None:
    cfg_a = clay.build_config(duration=2.0, fps=24, aspect="9:16", frames_dir="/tmp/f")
    cfg_b = clay.build_config(duration=2.0, fps=24, aspect="9:16", frames_dir="/tmp/f")
    assert cfg_a == cfg_b
    assert cfg_a["total_frames"] == 48
    assert (cfg_a["width"], cfg_a["height"]) == (480, 854)
    script_a = clay.build_bpy_script(cfg_a)
    script_b = clay.build_bpy_script(cfg_b)
    assert script_a == script_b
    # Clay material + render contract baked into the generated bpy script.
    assert '"Roughness"' in script_a or "Roughness" in script_a
    assert "0.9" in script_a
    assert "CYCLES" in script_a
    assert '"CPU"' in script_a or "'CPU'" in script_a or 'device = "CPU"' in script_a
    assert "keyframe_insert" in script_a
    assert "Principled BSDF" in script_a


def test_hex_to_rgb() -> None:
    assert clay.hex_to_rgb("#000000") == (0.0, 0.0, 0.0)
    assert clay.hex_to_rgb("#FFFFFF") == (1.0, 1.0, 1.0)
    with pytest.raises(CapabilityError):
        clay.hex_to_rgb("#12")
