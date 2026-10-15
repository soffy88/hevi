"""Independent R2 acceptance tests for kid-friendly 3D visuals."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hevi.layer4_legacy.scene3d.renderer import SceneRenderer
from hevi.layer4_legacy.scene3d.schema import parse_scene

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "hevi/layer4_legacy/scene3d/examples"


def _spec(filename: str, aspect: str, *, duration: float, fps: int = 10):
    data = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    data["resolution"] = 270
    data["fps"] = fps
    data["duration_s"] = duration
    data["camera"]["aspect"] = aspect
    path = (data.get("camera", {}).get("paths", {}) or {}).get(aspect)
    if path:
        data["camera"]["path"] = path
    return parse_scene(data)


@pytest.mark.parametrize("aspect", ["9:16", "16:9"])
def test_fox_faces_camera_and_both_eyes_are_visible(aspect: str, tmp_path: Path) -> None:
    duration = 12.0
    renderer = SceneRenderer(
        _spec("fox_in_wheat.json", aspect, duration=duration),
        tmp_path / f"fox_face_{aspect.replace(':', 'x')}",
    )
    rows = renderer.probe_fox_face_stats([1.2, 6.0, 10.8])
    assert len(rows) == 3
    for row in rows:
        assert row["dot"] > 0.3, f"fox face is turned away at t={row['time']}: {row}"
        box = row["headBBox"]
        assert box["x0"] >= 0 and box["y0"] >= 0 and box["x1"] <= 1 and box["y1"] <= 1, box
        assert len(row["eyes"]) == 2
        for eye in row["eyes"]:
            assert eye["inFrame"], f"eye outside screen at t={row['time']}: {eye}"
            assert eye["notOccluded"], f"eye hidden by geometry at t={row['time']}: {eye}"


def test_rendered_fox_head_is_saturated_orange(tmp_path: Path) -> None:
    from hevi.layer4_legacy.scene3d.kids_gate import evaluate_color_region

    duration = 12.0
    renderer = SceneRenderer(
        _spec("fox_in_wheat.json", "9:16", duration=duration),
        tmp_path / "fox_color",
    )
    row = renderer.probe_fox_face_stats([6.0])[0]
    frame = renderer.render_frame_at(6.0, tmp_path / "fox_mid.png")
    region = evaluate_color_region(frame, row["headBBox"], hue_range_deg=(15, 40), min_saturation=0.5)
    assert region["passes"], f"fox head lacks orange pixels: {region}"
    assert 15 <= region["target_median_hue_deg"] <= 40, region
    assert region["target_mean_saturation"] >= 0.5, region


def test_star_sea_has_nearby_stars_and_no_terrestrial_ground(tmp_path: Path) -> None:
    import numpy as np

    from hevi.layer4_legacy.scene3d.kids_gate import evaluate_frames

    duration = 13.0
    renderer = SceneRenderer(
        _spec("through_star_sea.json", "9:16", duration=duration),
        tmp_path / "star_sea_near_stars",
    )
    times = [0.0, 3.25, 6.5, 9.75, 13.0]
    stats = renderer.probe_star_proximity(times)
    assert stats["pathTravel"] > 20, stats
    assert stats["maxVisibleNear"] > 0, stats
    assert stats["groundAssets"] == 0 and stats["grassAssets"] == 0, stats

    frame_path = renderer.render_frame_at(6.5, tmp_path / "star_sea_mid.png")
    image = Image.open(frame_path).convert("RGB")
    hsv = np.asarray(image.convert("HSV"), dtype=np.float32)
    hue = hsv[..., 0] * (360.0 / 255.0)
    saturation = hsv[..., 1] / 255.0
    # Ground vegetation is green; blue-violet nebula and warm star glints are not.
    green_ground_proxy = ((hue >= 65) & (hue <= 165) & (saturation >= 0.20)).mean()
    gate = evaluate_frames([image], fps=1.0, duration_s=duration)
    assert green_ground_proxy <= 0.20, f"ground-like pixels {green_ground_proxy:.3f} > 0.20"
    assert gate.passed, gate.as_dict()
    assert gate.mean_saturation >= 0.35, gate.as_dict()


def test_kids_gate_rejects_desaturated_frames() -> None:
    import numpy as np

    from hevi.layer4_legacy.scene3d.kids_gate import evaluate_frames

    frame = Image.fromarray(np.full((24, 24, 3), 128, dtype=np.uint8))
    report = evaluate_frames([frame] * 40, fps=10.0, duration_s=4.0)
    assert not report.passed
    assert report.mean_saturation < 0.35
    assert any("below 0.35 floor" in item for item in report.failures)


def test_capability_rejects_shots_shorter_than_two_seconds(tmp_path: Path) -> None:
    from hevi.capabilities import CapabilityError
    from hevi.capabilities.scene3d import register_scene3d_capabilities

    cap = next(
        item for item in register_scene3d_capabilities()
        if item.name == "scene3d.fox_wheat"
    )
    with pytest.raises(CapabilityError, match="at least 2.0s"):
        cap.render({}, tmp_path / "too_short", duration=1.99, aspect="9:16", seed=7)
