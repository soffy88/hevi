"""3O §5 Task 5.1/5.2:装配 workflow + oservi 编排 Manifest + PII 脱敏单测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.assembly.video_assemble_workflow import (
    AssembleConfig,
    AssembleInput,
    video_assemble_workflow,
)
from hevi.core.anon import anon_user_ref, sanitize_input_data


@pytest.mark.asyncio
async def test_workflow_fails_without_raising_no_shots(tmp_path: Path) -> None:
    result = await video_assemble_workflow(
        AssembleConfig(shots=[], output_path=tmp_path / "final.mp4"),
        AssembleInput(),
        tmp_path,
    )
    assert result["status"] == "failed"
    assert "no shots" in result["error"]


@pytest.mark.asyncio
async def test_workflow_runs_and_writes_report(tmp_path: Path) -> None:
    import subprocess

    from hevi.assembly.assembler import ShotSegment

    c0 = tmp_path / "s0.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2",
            "-pix_fmt", "yuv420p", str(c0),
        ],
        check=True, capture_output=True,
    )
    steps: list[dict] = []
    result = await video_assemble_workflow(
        AssembleConfig(
            shots=[ShotSegment(c0), ShotSegment(c0)],
            output_path=tmp_path / "final.mp4",
            width=320, height=240, fps=12, transition="cut",
        ),
        AssembleInput(),
        tmp_path,
        on_step=lambda s: steps.append(s),
    )
    assert result["status"] == "completed"
    report = Path(result["report_path"])
    assert report.exists()
    import json

    data = json.loads(report.read_text())
    assert data["pillars"] == ["cost", "decision_trail", "report"]
    assert data["shots"] == 2
    assert data["duration_s"] > 1.0
    assert data["decision_trail"][0]["transition"] == "cut"
    assert steps[-1]["stage"] == "completed"


def test_anon_user_ref_is_stable_and_distinct():
    a = anon_user_ref("u-1")
    b = anon_user_ref("u-1")
    c = anon_user_ref("u-2")
    assert a == b
    assert a != c
    assert len(a) == 24


def test_sanitize_input_data_strips_identity_keys():
    cleaned = sanitize_input_data(
        {
            "user_id": "u1",
            "student_id": "s1",
            "email": "x@y.z",
            "phone": "13800000000",
            "topic": "三国",
        },
        user_id="u1",
    )
    for key in ("user_id", "student_id", "email", "phone"):
        assert key not in cleaned
    assert cleaned["anon_user_ref"] == anon_user_ref("u1")
    assert cleaned["topic"] == "三国"


def test_manifest_shape():
    from hevi.pipeline.longvideo_manifest import longvideo_production_manifest

    m = longvideo_production_manifest(user_id="u-1")
    assert m.name == "longvideo_production"
    assert m.skeleton == "sequential_composer"
    assert m.trigger == {"mode": "on_demand"}
    assert m.inject["steps"]  # 非空步骤列表
    assert m.config["anon_user_ref"] == anon_user_ref("u-1")
    assert "user_id" not in m.config  # 不携带真实身份
