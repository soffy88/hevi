from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import hevi.director.graph_render as graph_render


@pytest.mark.asyncio
async def test_director_graph_adapter_uses_standard_presenter_transaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_artifact(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        video = tmp_path / "final.mp4"
        video.write_bytes(b"video")
        return {"video_path": str(video), "shot_count": 2}

    async def fake_presenter(*, output_dir: Path, renderer, presentation_kind: str):
        assert output_dir == Path("output/tasks") / str(task_id)
        assert presentation_kind == "director-canvas"
        rendered = await renderer({}, output_dir, {})
        return SimpleNamespace(
            video_path=Path(rendered["video_path"]),
            engine_result={"report": rendered["report"]},
        )

    monkeypatch.setattr(graph_render, "render_graph_episode_artifact", fake_artifact)
    monkeypatch.setattr("hevi.tongjian.production.render_presenter_video", fake_presenter)
    monkeypatch.setattr("hevi.canvas.graph_repository.GraphRepository", MagicMock())
    monkeypatch.setattr("hevi.canvas.graph_service.GraphService", MagicMock())
    monkeypatch.setattr("hevi.canvas.executor_service.ExecutorService", MagicMock())

    result = await graph_render.execute_task(
        {
            "id": task_id,
            "config_json": {
                "graph_id": "graph-1",
                "render_spec": {"width": 1280, "height": 720, "fps": 30, "bgm": "epic"},
            },
        },
        MagicMock(),
    )

    assert result["status"] == "completed"
    assert result["result_video_path"] == str(tmp_path / "final.mp4")
    assert result["total_shots"] == 2
    assert captured["graph_id"] == "graph-1"
    assert captured["width"] == 1280
    assert captured["height"] == 720
