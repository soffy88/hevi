"""Tests for the procedural brush painting engine + image.brush_scene.

Offline and CPU-only: determinism of the stroke build, scene-spec
parsing/validation, primitive coverage, capability registration and
real (tiny) renders, plus the storyfilm brush preset wiring.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hevi.image.brushpaint import (
    SpecError,
    build_strokes,
    get_template,
    list_templates,
    parse_scene,
    pick_template_for_text,
    render_paint_video,
    render_still,
)

SMALL = (288, 384)  # fast test canvas
MEDIUM = (480, 640)  # ~1600 grid points: enough for stroke-count asserts


def _keys(strokes):
    return [s.key() for s in strokes]


def test_determinism_same_seed_same_strokes() -> None:
    scene = parse_scene(get_template("pond_night"))
    a = _keys(build_strokes(scene, *MEDIUM))
    b = _keys(build_strokes(scene, *MEDIUM))
    assert a == b
    assert len(a) > 1000  # a real painting, not a token gesture


def test_different_seed_different_strokes() -> None:
    spec = get_template("pond_night")
    a = _keys(build_strokes(parse_scene(spec), *MEDIUM))
    spec2 = {**spec, "seed": spec["seed"] + 1}
    b = _keys(build_strokes(parse_scene(spec2), *MEDIUM))
    assert a != b


def test_still_render_is_byte_deterministic() -> None:
    scene = parse_scene(get_template("river_dusk"))
    h1 = hashlib.sha256(render_still(scene, *SMALL).tobytes()).hexdigest()
    h2 = hashlib.sha256(render_still(scene, *SMALL).tobytes()).hexdigest()
    assert h1 == h2


def test_progress_reveals_partially() -> None:
    scene = parse_scene(get_template("pond_night"))
    early = render_still(scene, *SMALL, progress=0.15, grain=False)
    full = render_still(scene, *SMALL, progress=1.0, grain=False)
    bg = scene.background

    def painted(img) -> int:
        return sum(1 for px in img.getdata() if px != bg)

    assert 0 < painted(early) < painted(full)


def test_all_templates_parse_and_paint() -> None:
    assert list_templates() == [
        "meadow_dawn",
        "pond_night",
        "river_dusk",
        "village_night",
    ]
    for name in list_templates():
        scene = parse_scene(get_template(name))
        strokes = build_strokes(scene, *MEDIUM)
        assert len(strokes) > 1000, name
        img = render_still(scene, *SMALL, grain=False)
        # Not a flat canvas: real colour variance.
        assert len(set(img.getdata())) > 200, name


def test_kitchen_sink_spec_uses_every_primitive() -> None:
    spec = {
        "name": "kitchen",
        "seed": 5,
        "step": 16,
        "background": "#101c3a",
        "layers": [
            {"type": "swirl_sky", "palette": ["#16264f", "#3f6e8f"], "horizon": 0.7},
            {"type": "stars", "count": 5, "seed": 3},
            {"type": "moon", "x": 0.8, "y": 0.15, "r": 0.06},
            {"type": "clouds", "palette": ["#9cc0e6", "#cfe0f0"]},
            {"type": "hills", "base": 0.55, "palette": ["#1b3a6b", "#2a4a5e"]},
            {"type": "water", "from": 0.62, "palette": ["#1d3d5c", "#101f38"],
             "reflect_x": 0.8},
            {"type": "cypress", "x": 0.12, "base": 0.66, "height": 0.4,
             "palette": ["#16261a", "#2c4a2b"]},
            {"type": "tree", "x": 0.3, "base": 0.9, "palette": ["#2c4a2b", "#3d5a2a"]},
            {"type": "house", "x": 0.62, "base": 0.86,
             "wall_palette": ["#3a4a6b"], "roof_palette": ["#131f38"]},
            {"type": "meadow", "from": 0.88, "palette": ["#1d3a26", "#2c4a2b"]},
        ],
    }
    scene = parse_scene(spec)
    strokes = build_strokes(scene, *MEDIUM)
    assert len(strokes) > 1000
    img = render_still(scene, *SMALL, grain=False)
    assert len(set(img.getdata())) > 200


def test_spec_errors_are_loud() -> None:
    with pytest.raises(SpecError):
        parse_scene({"layers": []})
    with pytest.raises(SpecError):
        parse_scene({"layers": [{"type": "nope"}]})
    with pytest.raises(SpecError):
        parse_scene({"layers": [{"type": "hills"}]})  # missing palette
    with pytest.raises(SpecError):
        get_template("no_such_template")
    with pytest.raises(SpecError):
        parse_scene({"layers": [{"type": "moon", "order": [0.9, 0.1]}]})


def test_pick_template_for_text() -> None:
    assert pick_template_for_text("a quiet pond under the moon at night") == "pond_night"
    assert pick_template_for_text("清晨的田野上有一座小屋") == "meadow_dawn"
    assert pick_template_for_text("黄昏时分，小河在晚霞里发光") == "river_dusk"
    assert pick_template_for_text("山村的夜里，窗户亮着灯") == "village_night"
    # Fallback is deterministic.
    assert pick_template_for_text("zzzz") == pick_template_for_text("zzzz")


def test_capability_registered_and_still(tmp_path: Path) -> None:
    import hevi.capabilities as caps
    import hevi.capabilities.brushpaint  # noqa: F401  (import-time registration)

    assert "image.brush_scene" in caps.names()
    cap = caps.get("image.brush_scene")
    result = cap.render_safe(
        {"template": "pond_night", "mode": "still"},
        tmp_path,
        duration=0.0,
        aspect="1:1",
        seed=7,
    )
    assert result.png and Path(result.png).is_file()
    assert result.qa["stroke_count"] > 1000
    assert result.qa["cost"] == 0.0
    assert (tmp_path / "brush_scene.json").is_file()


def test_capability_paint_video_tiny(tmp_path: Path) -> None:
    import hevi.capabilities as caps
    import hevi.capabilities.brushpaint  # noqa: F401

    cap = caps.get("image.brush_scene")
    result = cap.render_safe(
        {"template": "river_dusk", "mode": "paint", "paint_seconds": 2},
        tmp_path,
        duration=0.0,
        aspect="1:1",
        seed=3,
    )
    assert result.mp4 and Path(result.mp4).is_file()
    assert Path(result.mp4).stat().st_size > 10_000
    assert result.duration_s == pytest.approx(2.0, abs=0.2)


def test_paint_video_direct(tmp_path: Path) -> None:
    scene = parse_scene(get_template("meadow_dawn"))
    out = tmp_path / "paint.mp4"
    stats = render_paint_video(scene, out, 240, 320, seconds=2, fps=6)
    assert out.is_file() and out.stat().st_size > 5_000
    assert stats["frames"] == 12
    assert stats["strokes"] > 300


def test_storyfilm_brush_provider_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """run_story_film(image_provider='brush') paints real PNGs and
    never calls the GPT image functions (they raise if touched)."""
    import asyncio
    import json as _json

    from hevi.audio import (
        forced_alignment,
        lux_tts_service,
        tts_alignment,
        whisper_alignment,
    )
    from hevi.image import gpt_image_service
    from hevi.storyfilm import pipeline

    draft = {
        "title": "月夜池塘",
        "hook": "月亮落在池塘里了。",
        "characters": [
            {"name": "小鸭", "role": "主角",
             "appearance_en": "a small yellow duckling"}
        ],
        "beats": [
            {"narration": "夜里，月亮挂在池塘上空，星星一闪一闪。",
             "visual_en": "a quiet pond under the moon at night",
             "motion_prompt": "slow push-in"},
            {"narration": "清晨，田野上有一座小屋，太阳升起来了。",
             "visual_en": "a small house in a meadow at dawn",
             "motion_prompt": "gentle pan"},
        ],
    }

    async def fake_story(premise, *, style, max_shots):
        return _json.loads(_json.dumps(draft)), 0.0

    monkeypatch.setattr(pipeline, "generate_story", fake_story)

    def _boom(*args, **kwargs):
        raise AssertionError("GPT image service must not be called in brush mode")

    monkeypatch.setattr(gpt_image_service, "gpt_image_generate", _boom)
    monkeypatch.setattr(gpt_image_service, "gpt_image_edit", _boom)
    monkeypatch.setattr(lux_tts_service, "lux_tts_available", lambda: True)

    async def fake_synth(*, text, output_path, voice=None, **_):
        Path(output_path).write_bytes(b"RIFFfake")
        return Path(output_path)

    monkeypatch.setattr(lux_tts_service, "synth_with_luxtts", fake_synth)
    monkeypatch.setattr(
        pipeline,
        "apply_gain_control",
        lambda path, **_: {"peak_before_dbtp": 0.0, "peak_after_dbtp": -1.5,
                            "gain_db": -1.5, "method": "volume"},
    )

    async def fake_align(*, audio_path, text, **_):
        full = "".join(b["narration"] for b in draft["beats"])
        chars = list(pipeline.normalize_text(full))
        words = tuple(
            tts_alignment.WordTiming(c, i * 100, i * 100 + 90)
            for i, c in enumerate(chars)
        )
        return words, None

    monkeypatch.setattr(forced_alignment, "forced_align_words", fake_align)
    monkeypatch.setattr(whisper_alignment, "whisper_align_words", fake_align)
    monkeypatch.setattr(tts_alignment, "probe_duration_ms", lambda p: 3200)

    def fake_render(*, shots, title, narration_path, output_path, **_):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"mp4bytes")
        return sum(float(s["duration_s"]) for s in shots)

    monkeypatch.setattr(pipeline, "render_motion_film", fake_render)
    monkeypatch.setattr(
        pipeline, "_run_gates",
        lambda film, out, *, aspect: {"film_gate": {"verdict": "pass"}},
    )

    out_dir = tmp_path / "brushjob"
    delivery = asyncio.run(
        pipeline.run_story_film(
            premise="小鸭子在月夜池塘边看月亮",
            max_shots=2,
            out_dir=out_dir,
            music=False,
            image_provider="brush",
        )
    )
    assert delivery["stages"]["images"]["status"] == "ok"
    assert delivery["stages"]["images"]["cost"] == 0.0
    shots = sorted((out_dir / "images").glob("shot_*.png"))
    assert len(shots) == 2
    from PIL import Image

    for shot in shots:
        with Image.open(shot) as img:
            assert img.size == (1024, 1536)  # 9:16 GPT-parity size
            assert len(set(img.convert("RGB").getdata())) > 200


def test_oneclick_brush_preset_wiring() -> None:
    from hevi.storyfilm.oneclick import PRESETS, resolve_preset

    assert resolve_preset("brush")["visual"] == "brush"
    # The four original presets keep their exact behaviour.
    assert PRESETS["storybook"]["visual"] == "gpt"
    assert PRESETS["tuantuan"]["visual"] == "rig"
    assert PRESETS["cinema"]["visual"] == "gpt"
    assert PRESETS["watercolor"]["visual"] == "gpt"
