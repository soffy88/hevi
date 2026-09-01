from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from hevi.audio.speech_platform import build_batch_plan, diagnostics, list_engines
from hevi.director.pipeline_schemas import Screenplay, ScreenplayScene
from hevi.shortdrama.screenwriter import review_screenplay, screenplay_markdown
from hevi.studio.nle import ffmpeg_recut_args, plan_recut
from hevi.studio.screenshot_studio import (
    animation_plan,
    new_project,
    render_project,
    reset_projects,
)
from hevi.studio.timeline import reset_timelines, split_at, timeline_from_edit_plan


def test_speech_platform_has_truthful_catalog_and_batch_validation() -> None:
    engines = list_engines()
    assert {item.kind for item in engines} == {"tts", "asr"}
    plan = build_batch_plan([{"text": "你好", "engine": "edge_tts"}, {"text": ""}])
    assert plan["valid"] is False
    assert plan["jobs"][0]["text"] == "你好"
    assert diagnostics()["ffmpeg"] is not None or diagnostics()["ffprobe"] is not None


def test_screenshot_studio_renders_local_frame_and_keyframes(tmp_path: Path) -> None:
    reset_projects()
    source = tmp_path / "screen.png"
    Image.new("RGB", (400, 240), "#ffffff").save(source)
    project = new_project(title="demo", screenshot_path=str(source), frame="browser")
    project.keyframes = [{"layer_id": "screen-1", "time_s": 0}, {"layer_id": "screen-1", "time_s": 1.2}]
    assert animation_plan(project)["valid"] is True
    result = render_project(project, tmp_path / "out.png")
    assert Path(result["output_path"]).exists()
    assert result["missing_sources"] == []


def test_shortdrama_review_is_script_only() -> None:
    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(
                scene_no=1,
                location="巷口",
                characters_present=["阿宁"],
                narration="阿宁停下脚步。",
            )
        ]
    )
    report = review_screenplay(screenplay)
    assert report["passed"] is True
    assert report["scope"].startswith("script-only")
    assert "巷口" in screenplay_markdown(screenplay)


def test_nle_plan_carries_speed_and_reverse_into_ffmpeg_contract() -> None:
    plan = plan_recut(
        [{"source": "a.mp4", "duration_s": 2, "speed": 2, "reverse": True, "effect": "mono"}],
        output="out.mp4",
    )
    assert plan.segments[0].speed == 2
    args = ffmpeg_recut_args(plan)
    assert "-filter_complex" in args
    assert "reverse" in args[args.index("-filter_complex") + 1]
    assert "hue=s=0" in args[args.index("-filter_complex") + 1]


def test_timeline_split_preserves_nle_clip_properties() -> None:
    reset_timelines()
    timeline = timeline_from_edit_plan(
        {
            "cuts": [
                {
                    "source": "a.mp4",
                    "duration_s": 4,
                    "speed": 2,
                    "reverse": True,
                    "transition": "dissolve",
                    "effect": "warm",
                }
            ]
        }
    )
    split_at(timeline.timeline_id, 2)
    right = next(clip for clip in timeline.clips if clip.clip_id.startswith("v0s"))
    assert (right.speed, right.reverse, right.transition, right.effect) == (2, True, "dissolve", "warm")
    assert right.source_in_s == 4


@pytest.mark.asyncio
async def test_shortdrama_writer_has_explicit_offline_fallback(monkeypatch) -> None:
    from hevi.api.routers.shortdrama_writer import WriterDraftRequest, draft

    monkeypatch.setattr(
        "hevi.director.screenplay._resolve_llm",
        lambda _llm: (_ for _ in ()).throw(RuntimeError("provider not configured")),
    )
    result = await draft(WriterDraftRequest(title="离线草稿", premise="一个人走进雨里"))
    assert result["scope"] == "script-only"
    assert result["review"]["passed"] is True
    assert "一个人走进雨里" in result["markdown"]
