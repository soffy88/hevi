"""S17: Blender sub-line brief gate, quota, queue approval, sozai CC0 rules."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.scene3d.assets_pipeline.sozai import (
    CC0_LICENCES,
    MAX_CACHE_BYTES,
    AssetRejected,
    cache_size,
    fetch_cc0,
)
from hevi.scene3d.blender import NeedsApproval, build_brief, quota_units, render_shot
from hevi.scene3d.blender.check_brief import check_brief


def _measured(**over: object) -> dict:
    base = {
        "resolution": [720, 1280],
        "fps": 24,
        "duration_s": 2.0,
        "triangles": 1000,
        "bbox_size_m": [10, 10, 5],
        "mesh_objects": 3,
        "origin": [0, 0, 0],
        "angles": ["a.png"],
        "non_manifold": {},
        "duplicate_suffix_objects": [],
        "zero_area_objects": [],
        "no_material_objects": [],
        "residual_objects": [],
    }
    base.update(over)
    return base


def test_brief_passes_on_matching_measurement():
    brief = build_brief(seconds=2.0, fps=24)
    report = check_brief(brief, _measured())
    assert report["ok"], report


def test_brief_rejects_scale_and_residual_objects():
    brief = build_brief(seconds=2.0, fps=24)
    report = check_brief(brief, _measured(bbox_size_m=[999, 10, 5],
                                         duplicate_suffix_objects=["Cube.001"]))
    assert not report["ok"]
    assert any("bbox" in e for e in report["errors"])
    assert any("duplicate" in e for e in report["errors"])


def test_blender_quota_is_two_units():
    assert quota_units("scene3d_blender") == 2
    assert quota_units("two_d") == 1


def test_final_requires_approval(tmp_path: Path):
    with pytest.raises(NeedsApproval):
        render_shot(tmp_path, quality="final", approved=False, seconds=1.0)


def test_sozai_accepts_cc0_and_writes_credits(tmp_path: Path):
    payload = tmp_path / "asset.glb"
    payload.write_bytes(b"glb")

    def runner(cmd):
        target = Path(cmd[-1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "asset.glb").write_bytes(b"glb")
        line = json.dumps({"path": str(payload), "licence": "CC0-1.0", "source": "Poly Haven",
                           "redistributable": True})
        return subprocess.CompletedProcess(cmd, 0, stdout=line, stderr="")

    record = fetch_cc0("polyhaven:crate", root=tmp_path, runner=runner)
    assert record["licence"] == "CC0-1.0"
    assert Path(record["credits"]).is_file()
    assert "crate" in Path(record["credits"]).read_text(encoding="utf-8")
    assert cache_size(tmp_path) > 0


def test_sozai_rejects_non_cc0(tmp_path: Path):
    def runner(cmd):
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout=json.dumps({"path": str(tmp_path / "x"), "licence": "Fab Standard"}),
            stderr="",
        )

    with pytest.raises(AssetRejected):
        fetch_cc0("megascans:rock", root=tmp_path, runner=runner)


def test_cc0_licence_set_is_narrow():
    assert "cc0-1.0" in CC0_LICENCES
    assert "cc-by-4.0" not in CC0_LICENCES
    assert MAX_CACHE_BYTES == 5 * 1024**3
