"""VIBE3D-R1 acceptance tests: scene templates, camera presets, character anim.

These run the real CPU (SwiftShader) renderer at a low resolution.  A render
failure is a test failure — nothing is mocked and nothing is skipped when the
asset pipeline is present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.layer4_legacy.scene3d.renderer import SceneRenderer
from hevi.layer4_legacy.scene3d.templates import (
    CAMERA_PRESETS,
    TEMPLATE_NAMES,
    build_template,
    list_templates,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "scene3d" / "source"

pytestmark = pytest.mark.skipif(
    not SOURCE.is_dir(), reason="scene3d source assets not present"
)


# --------------------------------------------------------------------------- #
# Template construction (no render)
# --------------------------------------------------------------------------- #
def test_three_templates_are_registered() -> None:
    names = [t["name"] for t in list_templates()]
    assert names == list(TEMPLATE_NAMES)
    assert len(names) >= 3
    for t in list_templates():
        assert set(t["camera_presets"]) == set(CAMERA_PRESETS)


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_build_template_validates(name: str, aspect: str) -> None:
    spec = build_template(name, aspect=aspect, duration=4.0, resolution=270)
    assert spec.width > 0 and spec.height > 0
    assert spec.assets
    # Every template carries a consistent warm main light (the task's 主光一致).
    assert spec.lights.sun_color[0] >= spec.lights.sun_color[2]


def test_unknown_template_and_preset_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown scene3d template"):
        build_template("does_not_exist")
    with pytest.raises(ValueError, match="unknown camera preset"):
        build_template("town_street", camera_preset="barrel_roll")


def test_templates_carry_a_character_and_a_camera_preset() -> None:
    for name in TEMPLATE_NAMES:
        spec = build_template(name, duration=4.0, resolution=270)
        assert any(a.kind == "character" for a in spec.assets), name
        assert spec.camera.preset in CAMERA_PRESETS, name


# --------------------------------------------------------------------------- #
# Character animation — real skeletal motion
# --------------------------------------------------------------------------- #
def test_character_really_walks(tmp_path: Path) -> None:
    spec = build_template("town_street", aspect="16:9", duration=6.0, resolution=270,
                          camera_preset="follow")
    renderer = SceneRenderer(spec, tmp_path / "walk")
    stats = renderer.probe_character_stats([0.0, 1.5, 3.0, 4.5, 6.0])
    assert stats and all(row["characters"] for row in stats)

    # Limb bones must move across time (not a static rig).
    foot_tracks: dict[str, list[tuple[float, float, float]]] = {}
    for row in stats:
        for char in row["characters"]:
            for bone, pos in char["bones"].items():
                foot_tracks.setdefault(bone, []).append(tuple(pos))
    assert "L_Foot" in foot_tracks and "R_Foot" in foot_tracks
    for bone in ("L_Foot", "R_Foot", "L_Hand"):
        pts = foot_tracks[bone]
        spread = max(
            max(abs(p[i] - q[i]) for i in range(3)) for p in pts for q in pts
        )
        assert spread > 0.05, f"{bone} barely moves: spread={spread}"


def test_character_walk_is_deterministic(tmp_path: Path) -> None:
    """Same seed + same times ⇒ identical bone positions."""
    def _probe(out: Path):
        spec = build_template("town_street", aspect="16:9", duration=4.0,
                              resolution=270, camera_preset="follow", seed=99)
        return SceneRenderer(spec, out).probe_character_stats([0.0, 2.0, 4.0])

    a = _probe(tmp_path / "det_a")
    b = _probe(tmp_path / "det_b")
    assert a == b


def test_character_walk_is_phase_shifted_by_position(tmp_path: Path) -> None:
    """Two walkers at different z must not be in lock-step (§06)."""
    spec = build_template("town_street", aspect="16:9", duration=4.0, resolution=270)
    walker = next(a for a in spec.assets if a.kind == "character")
    walker.params["from"] = [-3.0, 0.0, 1.0]
    walker.params["to"] = [3.0, 0.0, 1.0]
    from hevi.layer4_legacy.scene3d.schema import AssetSpec

    spec.assets.append(
        AssetSpec(kind="character", name="walker2", params=dict(walker.params))
    )
    spec.assets[-1].params["from"] = [-3.0, 0.0, 2.5]
    spec.assets[-1].params["to"] = [3.0, 0.0, 2.5]
    renderer = SceneRenderer(spec, tmp_path / "phase")
    stats = renderer.probe_character_stats([2.0])
    chars = stats[0]["characters"]
    assert len(chars) == 2
    lf0 = chars[0]["bones"]["L_Foot"]
    lf1 = chars[1]["bones"]["L_Foot"]
    assert abs(lf0[1] - lf1[1]) > 1e-4


def test_character_stands_on_the_ground(tmp_path: Path) -> None:
    """The measured glTF bbox keeps the feet near y=0 (SkinnedMesh fix)."""
    spec = build_template("town_street", aspect="16:9", duration=4.0, resolution=270)
    renderer = SceneRenderer(spec, tmp_path / "ground")
    stats = renderer.probe_character_stats([0.0, 2.0, 4.0])
    for row in stats:
        for char in row["characters"]:
            feet = [v[1] for k, v in char["bones"].items() if "Foot" in k]
            assert feet, char["bones"]
            for y in feet:
                assert -0.15 <= y <= 0.6, f"foot off the ground: {y}"


def test_character_render_produces_a_video(tmp_path: Path) -> None:
    spec = build_template("town_street", aspect="16:9", duration=2.0, resolution=270)
    metrics = SceneRenderer(spec, tmp_path / "vid").render()
    assert metrics["frame_count"] == 60
    assert Path(metrics["video"]).is_file()
    assert Path(metrics["video"]).stat().st_size > 0


# --------------------------------------------------------------------------- #
# Camera presets
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("preset", CAMERA_PRESETS)
def test_every_camera_preset_frames_the_subject(preset: str, tmp_path: Path) -> None:
    spec = build_template("town_street", aspect="16:9", duration=4.0, resolution=270,
                          camera_preset=preset)
    renderer = SceneRenderer(spec, tmp_path / f"preset_{preset}")
    boxes = renderer.probe_subject_bboxes([2.0, 4.0])
    assert all(b is not None for b in boxes), f"{preset}: subject left frame"
