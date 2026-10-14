"""SCENE3D R1B regression tests.

These are the tests demanded by ``SCENE3D_FIX.md`` (Hark independent review of
R1).  They exercise the *real* presets and the *real* API, not synthetic
stand-ins:

* F1 — ``POST /api/capabilities/{name}/preview`` returns a real MP4 (200) via
  the FastAPI TestClient (the sync-Playwright-inside-asyncio bug).
* F2 — no穿模: ring annulus vs tree canopies, field instances vs props.
* F3 — 3 capabilities × 2 aspects: the subject stays inside the safe area for
  the middle and last frame, using the shipped per-aspect camera presets.
* F4 — wind lives in the vertex shader: static camera + wind off ⇒
  byte-identical frames; wind on ⇒ different frames.
* F5 — unsupported aspect fails, a truncated (frame-dropped) mp4 fails, and a
  missing mp4 raises ``CapabilityError`` (not ``CalledProcessError``).

Run with the main hevi venv (has fastapi/httpx), *without* ``--noconftest`` and
with ``TMPDIR`` on a disk with quota headroom::

    TMPDIR=/data/tmp/scene3d_r1b JWT_SECRET=test-only PYTHONPATH=$PWD \
      /data/soffy/projects/hevi/.venv/bin/python -m pytest \
      tests/test_scene3d_r1b.py -q
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from hevi.capabilities import CapabilityError, get
from hevi.layer4_legacy.scene3d import renderer as R
from hevi.layer4_legacy.scene3d.browser import chromium_available
from hevi.layer4_legacy.scene3d.schema import parse_scene

_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _ROOT / "hevi" / "layer4_legacy" / "scene3d" / "examples"


pytestmark = pytest.mark.skipif(
    not chromium_available(),
    reason="no playwright chromium bundle resolvable (set PLAYWRIGHT_BROWSERS_PATH)",
)

# 3 capabilities × 2 aspects, as required by F3.
_CAPS = ["scene3d.planet_orbit", "scene3d.fox_wheat", "scene3d.star_sea"]
_ASPECTS = ["16:9", "9:16"]

_PRESET_FILE = {
    "scene3d.planet_orbit": "little_planet_orbit.json",
    "scene3d.fox_wheat": "fox_in_wheat.json",
    "scene3d.star_sea": "through_star_sea.json",
}


def _preset_spec(name: str, aspect: str, *, resolution: int, duration: float, fps: int):
    """Load a shipped preset, apply the requested aspect, return a SceneSpec."""
    data = json.loads((_EXAMPLES / _PRESET_FILE[name]).read_text(encoding="utf-8"))
    data["resolution"] = resolution
    data["duration_s"] = duration
    data["fps"] = fps
    data["camera"]["aspect"] = aspect
    paths = data["camera"].get("paths", {}) or {}
    if aspect in paths and paths[aspect]:
        data["camera"]["path"] = paths[aspect]
    return parse_scene(data)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# F1 — API preview must actually render (sync Playwright inside asyncio loop).
# --------------------------------------------------------------------------- #
def test_api_preview_returns_real_mp4(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from hevi.api.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/capabilities/scene3d.fox_wheat/preview?aspect=9:16&seed=5",
        json={"resolution": 270},
    )
    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers["content-type"].startswith("video/mp4")
    assert len(resp.content) > 1000
    video = tmp_path / "preview.mp4"
    video.write_bytes(resp.content)
    probe = R.ffprobe(video)
    assert probe["codec"] == "h264"
    assert abs(probe["duration"] - 3.0) <= 0.2, probe
    counted = R.ffprobe_frames(video)
    assert counted["nb_read_frames"] == 90  # 3.0s @ 30fps


def test_api_preview_rejects_unsupported_aspect() -> None:
    from fastapi.testclient import TestClient

    from hevi.api.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/capabilities/scene3d.fox_wheat/preview?aspect=4:3",
        json={"resolution": 270},
    )
    assert resp.status_code == 422, resp.text[:300]


def test_api_preview_unknown_capability_is_404() -> None:
    from fastapi.testclient import TestClient

    from hevi.api.main import app

    client = TestClient(app)
    resp = client.post("/api/capabilities/scene3d.does_not_exist/preview", json={})
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# F2 — no穿模: rings must not slice through trees, fields must not grow through
#      the character/rocks/trees.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", _CAPS)
def test_no_intersection_in_presets(tmp_path: Path, name: str) -> None:
    aspect = json.loads((_EXAMPLES / _PRESET_FILE[name]).read_text(encoding="utf-8"))[
        "camera"
    ]["aspect"]
    spec = _preset_spec(name, aspect, resolution=270, duration=1.0, fps=10)
    r = R.SceneRenderer(spec, tmp_path / name.replace(".", "_"))
    report = r.probe_collisions()
    assert report["violations"] == [], (
        f"{name}: geometry intersections (穿模): {report['violations'][:5]}"
    )
    # The report must actually have inspected something (guard against a no-op).
    assert report["counts"]["obstacles"] > 0


# --------------------------------------------------------------------------- #
# F3 — subject stays in the safe area for 3 caps × 2 aspects (real presets).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("aspect", _ASPECTS)
@pytest.mark.parametrize("name", _CAPS)
def test_subject_in_safe_area_real_presets(
    tmp_path: Path, name: str, aspect: str
) -> None:
    duration = 4.0
    spec = _preset_spec(name, aspect, resolution=270, duration=duration, fps=10)
    r = R.SceneRenderer(spec, tmp_path / f"{name.replace('.', '_')}_{aspect.replace(':', 'x')}")
    boxes = r.probe_subject_bboxes([duration / 2, duration])
    for label, b in zip(("mid", "last"), boxes):
        assert b is not None, f"{name} {aspect}: no subject in frame"
        # Safe area: 10% top/bottom, 5% left/right.
        assert b["x0"] >= 0.05 - 1e-6, f"{name} {aspect} {label}: left crop {b}"
        assert b["x1"] <= 0.95 + 1e-6, f"{name} {aspect} {label}: right crop {b}"
        assert b["y0"] >= 0.10 - 1e-6, f"{name} {aspect} {label}: top crop {b}"
        assert b["y1"] <= 0.90 + 1e-6, f"{name} {aspect} {label}: bottom crop {b}"


# --------------------------------------------------------------------------- #
# F4 — wind is a vertex-shader effect: off ⇒ frozen, on ⇒ moving.
# --------------------------------------------------------------------------- #
_WIND_SCENE = {
    "name": "wind_probe",
    "duration_s": 2.0,
    "fps": 10,
    "resolution": 270,
    "seed": 42,
    "camera": {
        "aspect": "16:9",
        "fov": 40.0,
        "path": [
            {"t": 0.0, "pos": [0.0, 2.0, 8.0], "look": [0.0, 0.6, 0.0]},
            {"t": 2.0, "pos": [0.0, 2.0, 8.0], "look": [0.0, 0.6, 0.0]},
        ],
    },
    "weather": {
        "starfield": False,
        "star_count": 0,
        "shadows": False,
        "fox_sway": False,
        "bloom_strength": 0.0,
    },
    "assets": [
        {"kind": "ground", "params": {"color": [0.4, 0.5, 0.3], "radius": 40}},
        {"kind": "wheat", "params": {"count": 400, "area": 14, "height": 1.0}},
        {"kind": "grass", "params": {"count": 200, "area": 14, "height": 0.6}},
    ],
}


def _wind_scene(tmp_path: Path, *, wind: float):
    cfg = json.loads(json.dumps(_WIND_SCENE))
    cfg["weather"]["wind_strength"] = wind
    return parse_scene(cfg)


def test_wind_off_is_byte_identical(tmp_path: Path) -> None:
    spec = _wind_scene(tmp_path, wind=0.0)
    r = R.SceneRenderer(spec, tmp_path / "wind_off")
    a = r.render_frame_at(0.5, tmp_path / "wind_off" / "a.png")
    b = r.render_frame_at(1.5, tmp_path / "wind_off" / "b.png")
    assert _sha(a) == _sha(b), "wind_strength=0 must freeze the field exactly"


def test_wind_on_changes_frames(tmp_path: Path) -> None:
    spec = _wind_scene(tmp_path, wind=1.6)
    r = R.SceneRenderer(spec, tmp_path / "wind_on")
    a = r.render_frame_at(0.5, tmp_path / "wind_on" / "a.png")
    b = r.render_frame_at(1.5, tmp_path / "wind_on" / "b.png")
    assert _sha(a) != _sha(b), "wind_strength>0 must bend the blades"


# --------------------------------------------------------------------------- #
# F5 — capability completeness gates.
# --------------------------------------------------------------------------- #
def test_unsupported_aspect_raises(tmp_path: Path) -> None:
    cap = get("scene3d.planet_orbit")
    with pytest.raises(CapabilityError):
        cap.render({}, tmp_path / "bad_aspect", duration=2.0, aspect="1:1", seed=1)


def test_missing_video_raises_capability_error(tmp_path: Path) -> None:
    from hevi.capabilities.scene3d import _verify_video

    with pytest.raises(CapabilityError):
        _verify_video(tmp_path / "does_not_exist.mp4", duration=2.0, fps=30, name="x")


def test_truncated_video_frame_count_fails(tmp_path: Path) -> None:
    """A dropped final frame must fail the exact frame-count gate."""
    from hevi.capabilities.scene3d import _verify_video

    # Render a short clip, then drop the last frame and re-encode (a truncation
    # mutation).  The container duration stays ~2.0s but one frame is gone.
    cap = get("scene3d.fox_wheat")
    res = cap.render({}, tmp_path / "full", duration=2.0, aspect="9:16", seed=3)
    full = Path(res.mp4)
    assert R.ffprobe_frames(full)["nb_read_frames"] == 60

    frames = sorted((tmp_path / "full" / "frames").glob("frame_*.png"))
    frames[-1].unlink()  # drop the last frame
    truncated = tmp_path / "truncated.mp4"
    import subprocess

    subprocess.run(
        [
            R.FFMPEG, "-y", "-framerate", "30", "-start_number", "1",
            "-i", (tmp_path / "full" / "frames" / "frame_%05d.png").as_posix(),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-crf", "20", str(truncated),
        ],
        check=True,
        capture_output=True,
    )
    assert R.ffprobe_frames(truncated)["nb_read_frames"] == 59
    with pytest.raises(CapabilityError):
        _verify_video(truncated, duration=2.0, fps=30, name="scene3d.fox_wheat")


def test_params_seed_overrides_seed_argument(tmp_path: Path) -> None:
    """``params['seed']`` is authoritative when both are supplied."""
    from hevi.capabilities.scene3d import _build_spec

    spec = _build_spec(
        "scene3d.fox_wheat",
        {"seed": 111},
        duration=1.0,
        aspect="9:16",
        seed=999,
    )
    assert spec.seed == 111
    # …and the keyword seed is used when params has none.
    spec2 = _build_spec(
        "scene3d.fox_wheat", {}, duration=1.0, aspect="9:16", seed=999
    )
    assert spec2.seed == 999


# --------------------------------------------------------------------------- #
# F6 — kids gate: pacing, flicker cap, saturation cap.
# --------------------------------------------------------------------------- #
def test_kids_gate_flags_short_shot() -> None:
    from hevi.layer4_legacy.scene3d.kids_gate import evaluate_frames

    frames = [_solid((40, 120, 60)) for _ in range(15)]  # 1.5s @ 10fps
    report = evaluate_frames(frames, fps=10.0)
    assert not report.passed
    assert any("too short" in f for f in report.failures)


def test_kids_gate_flags_fast_flicker() -> None:
    import numpy as np
    from PIL import Image

    from hevi.layer4_legacy.scene3d.kids_gate import evaluate_frames

    # 6 Hz square-wave brightness flicker @ 60 fps → must trip the 3 Hz cap.
    frames = []
    for i in range(120):
        v = 235 if i % 10 < 5 else 20
        frames.append(Image.fromarray(np.full((8, 8, 3), v, dtype=np.uint8)))
    report = evaluate_frames(frames, fps=60.0, duration_s=3.0)
    assert not report.passed
    assert report.flicker_hz > 3.0


def test_kids_gate_passes_calm_shot() -> None:
    from hevi.layer4_legacy.scene3d.kids_gate import evaluate_frames

    frames = [_solid((120, 170, 90)) for _ in range(40)]  # 4s @ 10fps, steady
    report = evaluate_frames(frames, fps=10.0)
    assert report.passed, report.failures


def _solid(rgb: tuple[int, int, int]):
    import numpy as np
    from PIL import Image

    return Image.fromarray(np.full((16, 16, 3), rgb, dtype=np.uint8))


# --------------------------------------------------------------------------- #
# Sanity: the sample frames directory is cleaned up by pytest, not leaked.
# --------------------------------------------------------------------------- #
def test_examples_dir_intact() -> None:
    for f in _PRESET_FILE.values():
        assert (_EXAMPLES / f).is_file()
