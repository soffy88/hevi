import uuid
from pathlib import Path

import pytest

from hevi.cost.calibration import p90_relative_error, relative_error, summarize_calibration
from hevi.execution.resumable_render import execute_checkpoint_render


@pytest.mark.asyncio
async def test_resumable_render_skips_completed_shots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    task_id = uuid.uuid4()
    first = {
        "id": task_id,
        "user_id": "tester",
        "config_json": {"total_shots": 4, "crash_after_shot": 2, "production_id": str(uuid.uuid4())},
    }
    with pytest.raises(RuntimeError, match="injected crash"):
        await execute_checkpoint_render(first, pool=None)

    resume = {
        "id": task_id,
        "user_id": "tester",
        "_resume_checkpoint": {
            "completed_shots": 2,
            "state_json": {
                "shots": [
                    {"index": 0, "path": str(tmp_path / "output/tasks" / str(task_id) / "shot_000.bin")},
                    {"index": 1, "path": str(tmp_path / "output/tasks" / str(task_id) / "shot_001.bin")},
                ]
            },
        },
        "config_json": {
            "total_shots": 4,
            "crash_after_shot": 2,
            "production_id": first["config_json"]["production_id"],
        },
    }
    result = await execute_checkpoint_render(resume, pool=None)
    assert result["status"] == "completed"
    assert result["completed_shots"] == 4
    assert result["config_json"]["resumed_from_shot"] == 2
    assert Path(result["result_video_path"]).is_file()


def test_cost_p90_relative_error_under_slo() -> None:
    pairs = [
        (10.0, 10.5),
        (8.0, 7.6),
        (12.0, 13.0),
        (5.0, 5.4),
        (20.0, 18.5),
        (15.0, 16.2),
        (9.0, 9.1),
        (11.0, 12.5),
        (7.0, 7.2),
        (14.0, 14.8),
    ]
    assert relative_error(10.0, 10.0) == 0.0
    assert p90_relative_error(pairs) < 0.20
    summary = summarize_calibration(pairs)
    assert summary["passed"]
    assert summary["samples"] == 10
