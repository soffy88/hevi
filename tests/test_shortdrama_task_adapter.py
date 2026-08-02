from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import hevi.season_planner.production as production
from hevi.season_planner.schemas import EpisodePlan
from hevi.storygraph.schemas import StoryCharacter, StoryGraph, StoryMeta
from hevi.tongjian.production import PresenterProductionError


@pytest.mark.asyncio
async def test_shortdrama_task_adapter_runs_episode_through_presenter_transaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task_id = uuid4()
    story = StoryGraph(
        meta=StoryMeta(source="测试短剧"),
        characters=[StoryCharacter(char_id="C001", name="主角")],
    )
    episode = EpisodePlan(ep_number=1, title="第一集", characters_present=["C001"])

    async def fake_episode(_episode, _story, *, run_dir: Path, **_kwargs: object) -> dict:
        video = run_dir / "final.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        return {
            "final_video": SimpleNamespace(video_path=str(video)),
            "shots": [{"index": 0, "path": "clip.mp4", "passed": True, "provider": "avatar"}],
        }

    async def fake_presenter(*, output_dir: Path, renderer, presentation_kind: str):
        assert presentation_kind == "shortdrama-episode"
        rendered = await renderer({}, tmp_path, {})
        return SimpleNamespace(video_path=Path(rendered["video_path"]))

    monkeypatch.setattr(production, "render_episode", fake_episode)
    monkeypatch.setattr(production, "render_presenter_video", fake_presenter)
    monkeypatch.setattr(production, "_subject3d_views", AsyncMock(return_value={}))

    result = await production.execute_shortdrama_task(
        {
            "id": task_id,
            "duration_archetype": "1-5min",
            "config_json": {
                "episode_plan": episode.model_dump(mode="json"),
                "shortdrama_story": story.model_dump(mode="json"),
                "estimated_usd": 2.5,
            },
        },
        object(),
    )

    assert result["status"] == "completed"
    assert result["result_video_path"] == str(tmp_path / "final.mp4")
    assert result["total_shots"] == 1
    assert result["config_json"]["actual_usd"] == 2.5


@pytest.mark.asyncio
async def test_shortdrama_task_adapter_surfaces_missing_final_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    task_id = uuid4()
    story = StoryGraph(meta=StoryMeta(source="测试短剧"))
    episode = EpisodePlan(ep_number=1)

    async def fake_episode(*_args: object, **_kwargs: object) -> dict:
        return {"final_video": SimpleNamespace(video_path=tmp_path / "missing.mp4"), "shots": []}

    monkeypatch.setattr(production, "render_episode", fake_episode)

    with pytest.raises(PresenterProductionError, match="ARTIFACT_MISSING"):
        await production.execute_shortdrama_task(
            {
                "id": task_id,
                "duration_archetype": "1-5min",
                "config_json": {
                    "episode_plan": episode.model_dump(mode="json"),
                    "shortdrama_story": story.model_dump(mode="json"),
                },
            },
            object(),
        )
