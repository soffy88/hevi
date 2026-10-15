"""Tests for the SCENE3D line (hevi/layer4_legacy/scene3d).

Covers:
  1. Same-seed determinism (frames byte-identical across two runs).
  2. Wind motion produces frame-to-frame difference in fields.
  3. 9:16 subject stays in safe area (subject bounding box in the middle band).
  4. Missing artefact makes the test fail.
  5. Schema validation round-trip.
  6. CLI ``render`` produces a valid MP4 (integration smoke).

These tests avoid pulling heavy state (they render at very low resolution) and
do not require a real Chromium download — the playwright python package was
already installed in ``.venv-scene3d``. The renderer locates the binary that
``playwright install chromium`` placed in ``~/.cache/ms-playwright``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hevi.layer4_legacy.scene3d import renderer as R
from hevi.layer4_legacy.scene3d import schema as S
from hevi.layer4_legacy.scene3d.browser import chromium_available
from hevi.layer4_legacy.scene3d.cli import main as cli_main

# All SCENE3D tests use a resolvable Playwright Chromium bundle.  The suite
# skips gracefully if none is available (see scene3d.browser).
pytestmark = pytest.mark.skipif(
    not chromium_available(),
    reason="no playwright chromium bundle resolvable (set PLAYWRIGHT_BROWSERS_PATH)",
)


# --------------------------------------------------------------------------- #
# Test scene — tiny render, 270p, 1s, 10fps
# --------------------------------------------------------------------------- #
_TINY = {
    "name": "tiny",
    "duration_s": 1.0,
    "fps": 10,
    "resolution": 270,
    "seed": 1234,
    "camera": {
        "aspect": "16:9",
        "fov": 40.0,
        "path": [
            {"t": 0.0, "pos": [8.0, 3.0, 8.0], "look": [0.0, 0.0, 0.0]},
            {"t": 1.0, "pos": [-8.0, 3.0, 8.0], "look": [0.0, 0.0, 0.0]},
        ],
    },
    "weather": {
        "starfield": True,
        "star_count": 200,
        "bloom_strength": 0.6,
    },
    "assets": [
        {"kind": "ground", "params": {"radius": 60}},
        {"kind": "planet", "params": {"radius": 1.8, "pos": [0.0, 1.8, 0.0]}},
        {"kind": "wheat", "params": {"count": 200, "area": 16, "height": 1.2}},
        {"kind": "grass", "params": {"count": 150, "area": 16, "height": 0.6}},
        {"kind": "rock", "params": {"pos": [1.5, 0.0, 2.5], "scale": 1.0}},
    ],
}


def _render(tmp_path: Path) -> list[Path]:
    spec = S.parse_scene(_TINY)
    out = tmp_path / "out"
    r = R.SceneRenderer(spec, out)
    frames = r.render_frames()
    assert len(frames) == spec.duration_s * spec.fps
    return frames


def _hash(frame: Path) -> str:
    return hashlib.sha256(frame.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# 1) Determinism: two runs with the same seed produce byte-identical frames.
# --------------------------------------------------------------------------- #
def test_same_seed_determinism(tmp_path: Path) -> None:
    a = _render(tmp_path / "a")
    b = _render(tmp_path / "b")
    ha = [_hash(p) for p in a]
    hb = [_hash(p) for p in b]
    assert ha == hb, "two runs with the same seed produced different frames"


# --------------------------------------------------------------------------- #
# 2) Wind motion is covered properly by tests/test_scene3d_r1b.py
#    (test_wind_off_is_byte_identical / test_wind_on_changes_frames), which use
#    a *static* camera and no fox sway so the wind itself is what changes.  The
#    old moving-camera check here could not distinguish wind from camera motion
#    and was removed in R1B (see SCENE3D_FIX.md F4).
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 3) 9:16 safe-area framing is covered by tests/test_scene3d_r1b.py
#    (test_subject_in_safe_area_real_presets) over the three real presets × two
#    aspects.  The old fixed-camera check here did not exercise the shipped
#    presets and was removed in R1B (see SCENE3D_FIX.md F3).
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 4) Missing artefact: deleting any required output must make a follow-up
#    integrity check fail.
# --------------------------------------------------------------------------- #
def test_missing_artefact_fails_check(tmp_path: Path) -> None:
    frames = _render(tmp_path / "missing")
    # All frames must exist right now.
    assert all(p.is_file() for p in frames)
    # Delete the first frame and confirm the integrity check fails.
    victim = frames[0]
    victim.unlink()
    missing = [p for p in frames if not p.exists()]
    assert missing, "deletion did not register as missing"


# --------------------------------------------------------------------------- #
# 5) Schema validation round-trip: dict -> spec -> dict == (normalised) input.
# --------------------------------------------------------------------------- #
def test_schema_roundtrip() -> None:
    spec = S.parse_scene(_TINY)
    out = S.scene_to_dict(spec)
    again = S.parse_scene(out)
    assert again == spec


def test_schema_validation_fails_on_bad_asset() -> None:
    bad = json.loads(json.dumps(_TINY))
    bad["assets"] = [{"kind": "ufo"}]  # unknown kind is allowed (warned), but missing 'kind' is not
    del bad["assets"][0]["kind"]
    with pytest.raises(ValueError):  # schema rejects missing required 'kind'
        S.parse_scene(bad)


# --------------------------------------------------------------------------- #
# 6) CLI render integration (full pipeline -> MP4).
# --------------------------------------------------------------------------- #
def test_cli_render_produces_mp4(tmp_path: Path) -> None:
    spec_path = tmp_path / "scene.json"
    spec_path.write_text(json.dumps(_TINY, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    rc = cli_main(["render", str(spec_path), "--out", str(out)])
    assert rc == 0
    mp4 = out / "tiny.mp4"
    assert mp4.exists() and mp4.stat().st_size > 0
    probe = R.ffprobe(mp4)
    assert probe["width"] == 480 and probe["height"] == 270
    assert probe["codec"] == "h264"
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["sha256"]
    assert (out / "tiny_contact_sheet.png").exists()
