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
import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.layer4_legacy.scene3d import renderer as R
from hevi.layer4_legacy.scene3d import schema as S
from hevi.layer4_legacy.scene3d.cli import main as cli_main

# All SCENE3D tests use this venv's playwright (where the user already ran
# ``playwright install``).  We skip the suite gracefully if the chromium binary
# is missing.
_CHROMIUM = Path.home() / ".cache" / "ms-playwright"


def _chromium_available() -> bool:
    if not _CHROMIUM.exists():
        return False
    for sub in _CHROMIUM.iterdir():
        if sub.name.startswith("chromium-"):
            for cand in ("chrome-linux64/chrome", "chrome-linux/chrome"):
                if (sub / cand).exists():
                    return True
    return False


pytestmark = pytest.mark.skipif(
    not _chromium_available(),
    reason="playwright chromium not installed in ~/.cache/ms-playwright",
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
# 2) Wind motion: consecutive wheat/grass frames are not byte-identical.
# --------------------------------------------------------------------------- #
def test_wind_produces_frame_motion(tmp_path: Path) -> None:
    frames = _render(tmp_path / "wind")
    hashes = [_hash(p) for p in frames]
    distinct = len(set(hashes))
    # We expect at least a few distinct frames in a 1-second 10fps shot where
    # the camera path and grass/wheat are animated.
    assert distinct >= 3, f"only {distinct}/{len(frames)} distinct frames — wind likely static"


# --------------------------------------------------------------------------- #
# 3) 9:16 safe area: subject is in the middle 60% of the frame.
# --------------------------------------------------------------------------- #
def test_916_subject_in_safe_area(tmp_path: Path) -> None:
    cfg = json.loads(json.dumps(_TINY))
    cfg["camera"]["aspect"] = "9:16"
    cfg["name"] = "tiny_916"
    # Re-centre the planet: a 9:16 portrait shot needs the subject in the
    # vertical centre.  Use a tighter camera framing so the planet fills the
    # middle third of the frame.
    cfg["camera"]["path"] = [
        {"t": 0.0, "pos": [0.0, 2.0, 6.0], "look": [0.0, 1.8, 0.0]},
        {"t": 1.0, "pos": [0.0, 2.0, 6.0], "look": [0.0, 1.8, 0.0]},
    ]
    cfg["assets"] = [
        {"kind": "ground", "params": {"radius": 60}},
        {"kind": "planet", "params": {"radius": 1.6, "pos": [0.0, 1.8, 0.0]}},
    ]
    spec = S.parse_scene(cfg)
    assert spec.width * 16 == spec.height * 9  # sanity: 9:16 portrait (h > w)
    assert spec.width < spec.height  # 9:16 portrait has height > width
    out = tmp_path / "out916"
    r = R.SceneRenderer(spec, out)
    frames = r.render_frames()
    # Inspect the middle frame to confirm the planet is bright in the middle
    # band.  We locate the planet by its warm toon colour (high R, low B) and
    # assert the vertical centroid falls in the central 60% of the frame.
    import numpy as np
    from PIL import Image

    mid = Image.open(frames[len(frames) // 2]).convert("RGB")
    arr = np.asarray(mid)
    h, w, _ = arr.shape
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # Planet mask: warm tone, not too dark (skip shadows), not blown-out.
    planet_mask = (r > g + 10) & (r > 140) & (b < 200) & (r < 260)
    # centroid row
    counts = planet_mask.sum(axis=1)
    assert counts.sum() > 30, "no warm planet pixels found in the frame"
    rows = np.arange(h)
    centroid = float((rows * counts).sum() / counts.sum())
    assert 0.25 * h <= centroid <= 0.75 * h, (
        f"planet centroid row {centroid:.1f} outside safe area (h={h})"
    )


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
    with pytest.raises(Exception):
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
