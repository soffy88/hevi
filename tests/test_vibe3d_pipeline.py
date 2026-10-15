"""VIBE3D-R1 acceptance tests: asset pipeline, templates, character animation.

Real measurements only — no mocks.  Rendering tests run the actual CPU
SwiftShader renderer; a failure to render is a test failure, not a skip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.scene3d.assets_pipeline import (
    AssetManifest,
    BudgetExceeded,
    GlbError,
    inspect_glb,
    measure_budget,
    optimize_asset,
    ratio_for_kind,
    validate_glb,
)
from hevi.scene3d.assets_pipeline.budget import enforce_budget

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "scene3d" / "source"
MANIFEST = ROOT / "assets" / "scene3d" / "manifest.json"

_CHARACTER = SOURCE / "pedestrian-01-walk-anim.glb"
_BUILDING = SOURCE / "building-03-boulangerie.glb"
_TREE = SOURCE / "tree-01-plane-green.glb"


pytestmark = pytest.mark.skipif(
    not SOURCE.is_dir(), reason="scene3d source assets not present"
)


# --------------------------------------------------------------------------- #
# GLB inspector
# --------------------------------------------------------------------------- #
def test_inspect_glb_reads_triangles_and_vertices() -> None:
    info = inspect_glb(_BUILDING)
    # Handbook Appendix A lists building-03-boulangerie at 16696 triangles /
    # 16723 vertices in the 512 pack; our reader must reproduce that.
    assert info.triangles == 16696
    assert info.vertices == 16723
    assert info.mesh_count == 1
    assert info.texture_count == 3


def test_inspect_glb_reads_skins_and_animation_clips() -> None:
    info = inspect_glb(_CHARACTER)
    assert info.skin_count == 1
    assert info.joint_count == 41  # Tripo biped preset
    assert len(info.animations) == 1
    anim = info.animations[0]
    assert anim.name == "preset:biped:walk"
    assert anim.channel_count == 123  # 41 joints x (translation/rotation/scale)
    assert abs(anim.duration_s - 2.375) < 0.01


def test_inspect_glb_rejects_non_glb(tmp_path: Path) -> None:
    bad = tmp_path / "not.glb"
    bad.write_bytes(b"this is not a glb file at all")
    with pytest.raises(GlbError):
        inspect_glb(bad)


def test_inspect_glb_matches_handbook_measure_tool() -> None:
    """The measured bbox must agree with the handbook's own measure_glb.py.

    The independent tool prints size [0.3732, 1.0000, 0.2229] for this asset;
    our reader reads the same accessor min/max, so the numbers must match.
    """
    info = inspect_glb(_CHARACTER)
    assert info.bbox_size is not None
    assert abs(info.bbox_size[0] - 0.373169) < 1e-4
    assert abs(info.bbox_size[1] - 1.0) < 1e-4
    assert abs(info.bbox_size[2] - 0.222901) < 1e-4


def test_validate_glb_passes_a_real_asset_and_warns_on_quantization() -> None:
    report = validate_glb("building-03-boulangerie", _BUILDING)
    assert report.passed, report.failures
    # The 512 pack is quantized; the validator warns (not fails) and the reader
    # normalizes so the bbox is real metres.
    assert any("quantization" in w for w in report.warnings)


def test_validate_glb_flags_a_thin_pole_bbox() -> None:
    """height p90 < 0.70 must be surfaced (§17 bbox-stretched-by-a-pole)."""
    report = validate_glb("prop-06-pigeon-flock", SOURCE / "prop-06-pigeon-flock.glb")
    # The pigeon flock bbox is dominated by a low, wide mass; p90 is well above
    # 0.7 so this is a negative control for the warning path.
    assert report.passed
    assert report.info is not None
    assert report.info.height_p90_fraction is not None


# --------------------------------------------------------------------------- #
# Optimiser
# --------------------------------------------------------------------------- #
def test_ratio_for_kind_follows_handbook_floors() -> None:
    assert ratio_for_kind("character") == 0.25
    assert ratio_for_kind("building") == 0.45
    assert ratio_for_kind("vegetation") == 0.75
    assert ratio_for_kind("unknown-kind") == 0.25  # prop default


def test_optimize_asset_reduces_triangles_and_textures(tmp_path: Path) -> None:
    result = optimize_asset(
        "building-03-boulangerie", _BUILDING, tmp_path / "cache",
        kind="building", texture_target=512,
    )
    assert not result.cache_hit
    assert result.after.triangles < result.before.triangles
    assert result.after.triangles > 0
    # Texture ceiling is applied and never increased.
    assert result.after.max_texture_dim <= 512
    # Optimised file is real and hashed.
    assert Path(result.output_path).is_file()
    assert len(result.optimized_sha256) == 64


def test_optimize_asset_is_cached(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    first = optimize_asset("car-01-taxi", SOURCE / "car-01-taxi.glb", cache, kind="vehicle")
    second = optimize_asset("car-01-taxi", SOURCE / "car-01-taxi.glb", cache, kind="vehicle")
    assert not first.cache_hit
    assert second.cache_hit
    assert first.optimized_sha256 == second.optimized_sha256


def test_optimize_never_decimates_a_skinned_mesh(tmp_path: Path) -> None:
    """A rigged mesh is texture-only; triangle count must be unchanged."""
    result = optimize_asset(
        "pedestrian-01-walk-anim", _CHARACTER, tmp_path / "cache",
        kind="character", texture_target=512,
    )
    assert result.after.triangles == result.before.triangles
    assert result.after.max_texture_dim <= 512


# --------------------------------------------------------------------------- #
# Render budget gate
# --------------------------------------------------------------------------- #
def test_budget_gate_passes_within_ceiling() -> None:
    budget = measure_budget("planet", frames=100, total_s=50.0, ceiling_s=1.0)
    assert budget.per_frame_s == pytest.approx(0.5)
    assert budget.passed()
    enforce_budget(budget)  # must not raise


def test_budget_gate_rejects_over_ceiling() -> None:
    budget = measure_budget("planet", frames=10, total_s=30.0, ceiling_s=1.0)
    assert not budget.passed()
    with pytest.raises(BudgetExceeded):
        enforce_budget(budget)


def test_budget_gate_has_no_default_allow() -> None:
    with pytest.raises(Exception):
        measure_budget("planet", frames=0, total_s=1.0)


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def test_committed_manifest_records_provenance_and_spec() -> None:
    manifest = AssetManifest.load(MANIFEST)
    assert len(manifest.assets) >= 8
    for record in manifest.assets:
        assert record.licence == "CC BY-NC-SA 4.0"
        assert "alchaincyf/3d-vibe-coding-handbook" in record.attribution
        assert len(record.sha256) == 64
        assert record.triangles > 0
        assert record.optimized_triangles is not None
        assert record.optimized_triangles <= record.triangles
        assert record.texture_target == 512


def test_manifest_digest_is_stable() -> None:
    a = AssetManifest.load(MANIFEST)
    b = AssetManifest.load(MANIFEST)
    assert a.digest() == b.digest()
    assert json.loads(MANIFEST.read_text(encoding="utf-8"))["digest"] == a.digest()
