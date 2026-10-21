"""Offline tests for the hand-drawn character expression rig.

Covers the technique module
(:mod:`hevi.layer4_legacy.handdraw.expression_rig`) and the registered
``image.expression_rig`` / ``image.expression_contact_sheet``
capabilities: catalogue sizes, preset/override resolution, strict
failure on unknown names, render determinism, per-emotion
distinguishability, and on-model identity (body colour present in every
render).  No network, no paid calls, CPU only.
"""
from __future__ import annotations

import hashlib
import io
import json
import random
from pathlib import Path

import pytest
from PIL import Image

import hevi.capabilities as caps
from hevi.capabilities.registry import CapabilityError
from hevi.layer4_legacy.handdraw.expression_rig import (
    BROW_STYLES,
    DEMO_CHARACTER,
    EMOTIONS,
    EXTRA_STYLES,
    EYE_STYLES,
    MOUTH_STYLES,
    VIEWS,
    build_contact_sheet,
    render_face,
    resolve_face,
)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _sha(img: Image.Image) -> str:
    return hashlib.sha256(_png_bytes(img)).hexdigest()


def _body_color_count(img: Image.Image) -> int:
    """Pixels close to the model-sheet body colour (#FFE3A3)."""
    rgba = img.convert("RGBA")
    count = 0
    for r, g, b, a in rgba.getdata():
        if a > 200 and abs(r - 0xFF) < 12 and abs(g - 0xE3) < 12 and abs(b - 0xA3) < 14:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Catalogues and model sheet
# ---------------------------------------------------------------------------


def test_catalogue_sizes() -> None:
    assert len(EMOTIONS) >= 12
    assert len(VIEWS) >= 2
    assert len(EYE_STYLES) >= 8
    assert len(MOUTH_STYLES) >= 10
    assert len(BROW_STYLES) >= 3


def test_model_sheet_is_json_serialisable() -> None:
    sheet = DEMO_CHARACTER.model_sheet()
    text = json.dumps(sheet, ensure_ascii=False)
    assert sheet["character_id"] == "tuantuan"
    assert set(sheet["emotions"]) == set(EMOTIONS)
    assert json.loads(text)["views"] == list(VIEWS)


def test_every_preset_references_catalogued_parts() -> None:
    for name, preset in EMOTIONS.items():
        assert preset.eyes in EYE_STYLES, name
        assert preset.mouth in MOUTH_STYLES, name
        assert preset.brows in BROW_STYLES, name
        assert all(extra in EXTRA_STYLES for extra in preset.extras), name


# ---------------------------------------------------------------------------
# Resolution: presets, overrides, strict failures
# ---------------------------------------------------------------------------


def test_resolve_uses_preset_then_overrides() -> None:
    preset = resolve_face(emotion="angry")
    assert preset.eyes == EMOTIONS["angry"].eyes
    assert preset.mouth == EMOTIONS["angry"].mouth
    custom = resolve_face(emotion="angry", eyes="dot", mouth="cat")
    assert custom.eyes == "dot"
    assert custom.mouth == "cat"
    # Untouched parts still come from the preset.
    assert custom.brows == EMOTIONS["angry"].brows
    swapped = resolve_face(emotion="happy", extras=[])
    assert swapped.extras == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"view": "back"},
        {"emotion": "meh"},
        {"eyes": "laser"},
        {"mouth": "zipper"},
        {"brows": "bushy"},
        {"extras": ["halo"]},
        {"extras": ["tear", "tear"]},
        {"character": "clawd"},
    ],
)
def test_resolve_rejects_unknown_names(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        resolve_face(**kwargs)


def test_render_rejects_bad_seed_and_size() -> None:
    with pytest.raises(ValueError):
        render_face(seed=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        render_face(size=10)


# ---------------------------------------------------------------------------
# Rendering: all combos succeed, deterministic, distinguishable, on-model
# ---------------------------------------------------------------------------


def test_all_view_emotion_combos_render_on_model() -> None:
    for view in VIEWS:
        for emotion in EMOTIONS:
            img = render_face(view=view, emotion=emotion, seed=3, size=240)
            assert img.size == (240, 240)
            assert img.getbbox() is not None  # something was drawn
            # Identity: the body colour shows up in every single render.
            assert _body_color_count(img) > 1500, (view, emotion)


def test_render_is_deterministic_and_seed_sensitive() -> None:
    a = render_face(view="front", emotion="happy", seed=42, size=240)
    b = render_face(view="front", emotion="happy", seed=42, size=240)
    assert _sha(a) == _sha(b)
    other_seed = render_face(view="front", emotion="happy", seed=43, size=240)
    assert _sha(other_seed) != _sha(a)


def test_module_does_not_touch_global_rng() -> None:
    random.seed(20261021)
    expected_next = random.random()
    random.seed(20261021)
    render_face(view="front", emotion="joy", seed=7, size=160)
    assert random.random() == expected_next


def test_emotions_are_pairwise_distinguishable_front_view() -> None:
    hashes = {
        emotion: _sha(render_face(view="front", emotion=emotion, seed=1, size=240))
        for emotion in EMOTIONS
    }
    assert len(set(hashes.values())) == len(EMOTIONS)


def test_part_overrides_change_the_picture() -> None:
    base = _sha(render_face(emotion="neutral", seed=5, size=240))
    eyes = _sha(render_face(emotion="neutral", eyes="star", seed=5, size=240))
    mouth = _sha(render_face(emotion="neutral", mouth="laugh_open", seed=5, size=240))
    assert eyes != base
    assert mouth != base
    assert eyes != mouth


def test_every_part_style_renders() -> None:
    for eyes in EYE_STYLES:
        assert render_face(eyes=eyes, seed=2, size=160).getbbox() is not None
    for mouth in MOUTH_STYLES:
        assert render_face(mouth=mouth, seed=2, size=160).getbbox() is not None
    for brows in BROW_STYLES:
        assert render_face(brows=brows, seed=2, size=160).getbbox() is not None
    for extra in EXTRA_STYLES:
        img = render_face(extras=[extra], seed=2, size=160)
        assert img.getbbox() is not None


def test_contact_sheet_geometry() -> None:
    sheet = build_contact_sheet(views=["front", "profile"], emotions=["happy", "sad"], cell=120)
    # width = view-label strip + cols*cell ; height = rows*(cell + label bar)
    assert sheet.size == (92 + 2 * 120, 2 * (120 + 30))
    full = build_contact_sheet(cell=96)
    assert full.size == (92 + len(EMOTIONS) * 96, len(VIEWS) * (96 + 30))
    with pytest.raises(ValueError):
        build_contact_sheet(emotions=["nope"])


# ---------------------------------------------------------------------------
# Capability registration
# ---------------------------------------------------------------------------


def test_capabilities_are_registered() -> None:
    assert "image.expression_rig" in caps.names()
    assert "image.expression_contact_sheet" in caps.names()
    for name in ("image.expression_rig", "image.expression_contact_sheet"):
        assert caps.get(name).params_schema["additionalProperties"] is False


def test_capability_rejects_invalid_params() -> None:
    cap = caps.get("image.expression_rig")
    with pytest.raises(CapabilityError):
        cap.validate_params({"emotion": "meh"})
    with pytest.raises(CapabilityError):
        cap.validate_params({"view": "back"})
    with pytest.raises(CapabilityError):
        cap.validate_params({"unknown": 1})
    sheet_cap = caps.get("image.expression_contact_sheet")
    with pytest.raises(CapabilityError):
        sheet_cap.validate_params({"emotions": ["happy", "nope"]})


def test_capability_render_is_deterministic(tmp_path: Path) -> None:
    cap = caps.get("image.expression_rig")
    params = {"view": "three_quarter", "emotion": "shy"}
    first = cap.render(params, tmp_path / "a", duration=0, aspect="1:1", seed=42)
    second = cap.render(params, tmp_path / "b", duration=0, aspect="1:1", seed=42)
    assert first.png and Path(first.png).is_file()
    assert first.sha256 == second.sha256
    assert hashlib.sha256(Path(first.png).read_bytes()).hexdigest() == first.sha256
    sidecar = json.loads(Path(first.qa["sidecar"]).read_text(encoding="utf-8"))
    assert sidecar["resolved"]["emotion"] == "shy"
    assert sidecar["resolved"]["extras"] == ["blush_strong"]
    assert sidecar["model_sheet"]["character_id"] == "tuantuan"
    with pytest.raises(CapabilityError):
        cap.render({"emotion": "meh"}, tmp_path / "bad", duration=0, aspect="1:1", seed=1)


def test_contact_sheet_capability_render(tmp_path: Path) -> None:
    cap = caps.get("image.expression_contact_sheet")
    result = cap.render(
        {"views": ["front"], "emotions": ["happy", "angry"], "cell": 120},
        tmp_path / "sheet",
        duration=0,
        aspect="16:9",
        seed=9,
    )
    assert result.png and Path(result.png).is_file()
    assert result.qa["sheet_size"] == [92 + 2 * 120, 120 + 30]
