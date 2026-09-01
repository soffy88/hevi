from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.openshorts.omodul import execute_ai_short


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_ai_short_requires_real_talking_head_artifact(tmp_path: Path) -> None:
    job = asyncio.run(
        execute_ai_short(description="一个真实产品的快速介绍", output_dir=tmp_path / "missing")
    )
    assert job.status == "failed"
    assert not job.composite_path
    report = json.loads((tmp_path / "missing" / "ai_shorts_report.json").read_text())
    assert report["artifacts"] == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_ai_short_composes_verified_local_assets(tmp_path: Path) -> None:
    source = tmp_path / "talking.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-shortest", "-c:v", "libx264", "-c:a", "aac", str(source),
        ],
        check=True,
    )
    job = asyncio.run(
        execute_ai_short(
            description="快速演示一个产品。解决日常问题。现在开始行动。",
            input_data={"talking_head_path": str(source)},
            output_dir=tmp_path / "run",
        )
    )
    assert job.status == "succeeded"
    assert Path(job.voiceover_path).is_file()
    assert Path(job.composite_path).is_file()
    assert Path(job.composite_path).stat().st_size > 0
