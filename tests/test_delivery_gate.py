"""路径 0 compose 门 + 路径 1 导演残片合同。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from hevi.production.delivery_gate import (
    ComposeGateError,
    VideoProbe,
    assert_explainer_compose,
    evaluate_director_delivery,
    evaluate_preview_delivery,
    write_preview_report,
)


def test_evaluate_empty_shots_is_failed() -> None:
    verdict = evaluate_director_delivery([])
    assert verdict.ok is False
    assert verdict.status == "failed"
    assert "无镜头" in verdict.reason


def test_evaluate_failed_shots_cannot_complete() -> None:
    verdict = evaluate_director_delivery(
        [
            {"passed": True, "degraded": False, "quality_checks": {}},
            {"passed": False, "degraded": True, "quality_checks": {"keyframe_degraded": True}},
        ]
    )
    assert verdict.status == "failed"
    assert verdict.failed_shots == 1
    assert verdict.canon_copy_ratio == 0.5


def test_evaluate_motion_fallback_blocks_motion_promise() -> None:
    shots = [
        {
            "passed": True,
            "degraded": False,
            "quality_checks": {"has_action_beats": True, "kf2v_action_arc": False},
        }
    ]
    blocked = evaluate_director_delivery(shots, delivery_promise="motion")
    assert blocked.ok is False
    assert blocked.motion_fallback == 1
    allowed = evaluate_director_delivery(shots, delivery_promise="any")
    assert allowed.ok is True


def test_evaluate_all_pass_is_completed() -> None:
    verdict = evaluate_director_delivery(
        [
            {
                "passed": True,
                "degraded": False,
                "quality_checks": {"has_action_beats": True, "kf2v_action_arc": True},
            }
        ]
    )
    assert verdict.ok is True
    assert verdict.status == "completed"


def test_assert_explainer_compose_rejects_missing_audio(tmp_path: Path) -> None:
    video = tmp_path / "out.mp4"
    video.write_bytes(b"not-a-real-mp4")
    with patch(
        "hevi.production.delivery_gate.probe_video",
        return_value=VideoProbe(video, 10.0, True, False, 12),
    ):
        with pytest.raises(ComposeGateError, match="音频轨"):
            assert_explainer_compose(video, expected_duration_s=10.0)


def test_assert_explainer_compose_rejects_duration_drift(tmp_path: Path) -> None:
    video = tmp_path / "out.mp4"
    video.write_bytes(b"mp4")
    with patch(
        "hevi.production.delivery_gate.probe_video",
        return_value=VideoProbe(video, 4.0, True, True, 12),
    ):
        with pytest.raises(ComposeGateError, match="时长"):
            assert_explainer_compose(video, expected_duration_s=10.0)


def test_evaluate_preview_delivery_marks_short_source(tmp_path: Path) -> None:
    video = tmp_path / "preview.mp4"
    video.write_bytes(b"mp4")
    report = evaluate_preview_delivery(
        VideoProbe(video, 32.0, True, True, 12),
        cue_budget_s=32.0,
    )
    assert report["ok"] is True
    assert report["short_source"] is True
    assert report["over_budget"] is False


def test_evaluate_preview_delivery_fails_without_audio(tmp_path: Path) -> None:
    video = tmp_path / "preview.mp4"
    dest = write_preview_report(
        tmp_path,
        evaluate_preview_delivery(
            VideoProbe(video, 75.0, True, False, 12),
            cue_budget_s=75.0,
        ),
    )
    assert dest.name == "qc-report.json"
    payload = dest.read_text(encoding="utf-8")
    assert "试播无音频轨" in payload


@pytest.mark.asyncio
async def test_shortdrama_residual_marks_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hevi.season_planner.production as production
    from hevi.season_planner.schemas import EpisodePlan
    from hevi.storygraph.schemas import StoryCharacter, StoryGraph, StoryMeta

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
            "shots": [
                {
                    "index": 0,
                    "path": "clip.mp4",
                    "passed": False,
                    "degraded": True,
                    "quality_checks": {"keyframe_degraded": True},
                }
            ],
        }

    async def fake_presenter(*, output_dir: Path, renderer, presentation_kind: str):
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
    assert result["status"] == "failed"
    assert result["error"]
    assert result["completed_shots"] == 0
    assert result["config_json"]["failed_shots"] == 1
