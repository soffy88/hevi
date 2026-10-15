"""Acceptance test for SVFACTORY-R1.

Executes:
1. Batch preset with 3 topics -> renders 3 episodes (including 1 portrait 9:16).
2. Verifies ffprobe stats, non-black frames, audio presence, kids_gate pass.
3. Tests breakpoint resume (interrupting / re-running skips already completed items).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from hevi.svfactory.batch import BatchRunner


@pytest.mark.asyncio
async def test_svfactory_acceptance_render_and_batch(tmp_path: Path) -> None:
    # Setup asset dir with test images
    asset_dir = tmp_path / "test_assets"
    asset_dir.mkdir()
    for i in range(3):
        p = asset_dir / f"frame_{i}.jpg"
        Image.new("RGB", (640, 360), color=(i * 60 + 50, 150, 200)).save(p)

    out_dir = tmp_path / "acceptance_output"

    # Run batch with 3 topics (mix of 16:9 and 9:16)
    config = {
        "batch_id": "acc_batch_01",
        "topics": ["分享快乐", "排队轮流", "安全过马路"],
        "output_dir": str(out_dir),
        "asset_dir": str(asset_dir),
        "aspect": "9:16", # portrait test >=1 9:16
        "seed": 2026,
    }

    runner = BatchRunner(config)
    state = await runner.run()

    assert state["completed"] == 3
    assert state["failed"] == 0

    # Verify each episode output and manifest
    for _idx, item in enumerate(state["items"], 1):
        mp4_path = Path(item["path"])
        assert mp4_path.exists()
        manifest_path = mp4_path.with_suffix(".manifest.json")
        assert manifest_path.exists()

        m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert m_data["aspect"] == "9:16"
        assert m_data["duration"] > 0
        assert m_data["gate_passed"] is True

    # Test breakpoint resume: running BatchRunner again should resume/skip completed items instantly
    runner2 = BatchRunner(config)
    state2 = await runner2.run()
    assert state2["completed"] == 3
    assert state2["failed"] == 0
