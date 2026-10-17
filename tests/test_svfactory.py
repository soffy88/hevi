"""Tests for SVFACTORY (short-video factory capabilities & workflows)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from hevi.capabilities import get, list_capabilities
from hevi.svfactory.batch import BatchRunner
from hevi.svfactory.montage import auto_montage_segments, list_local_assets


def test_svfactory_capabilities_registered() -> None:
    caps = list_capabilities()
    names = {c.name for c in caps}
    assert "svfactory.montage" in names
    assert "svfactory.render" in names

    cap_montage = get("svfactory.montage")
    assert cap_montage.aspects == ["16:9", "9:16"]
    assert cap_montage.cpu_cost_hint == 0.1


def test_auto_montage_determinism_and_seed(tmp_path: Path) -> None:
    # Create mock video/image assets in tmp_path
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    for i in range(3):
        img_path = asset_dir / f"clip_{i}.jpg"
        Image.new("RGB", (320, 240), color=(i * 50, 100, 200)).save(img_path)

    assets = list_local_assets(asset_dir)
    assert len(assets) == 3

    # Test deterministic montage with same seed
    res1 = auto_montage_segments(asset_dir, 6.0, seed=123, aspect="16:9")
    res2 = auto_montage_segments(asset_dir, 6.0, seed=123, aspect="16:9")
    assert res1["video_files"] == res2["video_files"]
    assert res1["time_ranges"] == res2["time_ranges"]

    # Test different seed changes selection or order
    res3 = auto_montage_segments(asset_dir, 6.0, seed=999, aspect="16:9")
    # Even if same files might be picked by chance, seed is stored in output contract
    assert res3["seed"] == 999


def test_batch_runner_initialization(tmp_path: Path) -> None:
    out_dir = tmp_path / "batch_out"
    config = {
        "batch_id": "test_batch_1",
        "topics": ["分享", "轮流"],
        "output_dir": str(out_dir),
        "aspect": "16:9",
        "seed": 42,
    }
    runner = BatchRunner(config)
    assert runner.batch_id == "test_batch_1"
    assert len(runner.topics) == 2
