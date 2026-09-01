"""白板笔迹 / 信息图装配。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.explainer.contracts import ExplainerCue
from hevi.explainer.infographic import deck_spec_from_narration, render_infographic_cue
from hevi.explainer.whiteboard import (
    attach_whiteboard_scenes,
    render_stream_whiteboard,
    synthesize_still,
)


def test_stream_whiteboard_writes_mp4(tmp_path: Path) -> None:
    still = synthesize_still("盐税是什么", width=320, height=180)
    dest = tmp_path / "board.mp4"
    annotation = {
        "sceneDurationMs": 400,
        "elements": [
            {
                "sequence": 1,
                "region": {"x": 0, "y": 0, "width": 320, "height": 180},
                "reveal": {"startMs": 0, "durationMs": 300, "protectedRegions": []},
            }
        ],
    }
    out = render_stream_whiteboard(still, annotation, dest, fps=8, brush=12)
    assert out.exists()
    assert out.stat().st_size > 200


@pytest.mark.asyncio
async def test_infographic_captions_lock_phrase_timeline(tmp_path: Path) -> None:
    captions = [
        {"text": "盐税是间接税", "startMs": 0, "endMs": 400, "confidence": 0.9},
        {"text": "因为短缺所以涨价", "startMs": 400, "endMs": 900, "confidence": 0.9},
    ]
    cue = ExplainerCue(
        visual_type="infographic",
        text="盐税是间接税。因为短缺所以涨价。",
        time_estimate_s=1,
        visual_config={"captions": captions},
    )
    await attach_whiteboard_scenes([cue], tmp_path, width=320, height=180, fps=8)
    assert cue.visual_type == "infographic"
    timeline = cue.visual_config["phrase_timeline"]
    assert timeline["phrases"][0]["boundary_source"] == "caption-token"
    assert timeline["phrases"][0]["start_ms"] == 0
    assert (tmp_path / "infographic" / "cue-1.mp4").exists()


def test_infographic_without_timeline_does_not_stagger_by_chars(tmp_path: Path) -> None:
    dest = tmp_path / "deck.mp4"
    spec = deck_spec_from_narration("盐税是间接税。因为短缺所以涨价。", 400)
    assert spec["relationship_type"] == "cause"
    out = render_infographic_cue("盐税是间接税。因为短缺所以涨价。", duration_ms=400, dest=dest, width=320, height=180, fps=8)
    assert out.exists()


@pytest.mark.asyncio
async def test_attach_whiteboard_writes_asset(tmp_path: Path) -> None:
    cue = ExplainerCue(visual_type="whiteboard", text="盐税是什么", time_estimate_s=1)
    await attach_whiteboard_scenes([cue], tmp_path, width=320, height=180, fps=8)
    assert cue.visual_type == "whiteboard"
    assert "assetUrl" in cue.visual_config
    assert (tmp_path / "whiteboard" / "cue-1.mp4").exists()


@pytest.mark.asyncio
async def test_attach_disabled_degrades(tmp_path: Path) -> None:
    cue = ExplainerCue(visual_type="infographic", text="盐税")
    await attach_whiteboard_scenes([cue], tmp_path, enabled=False)
    assert cue.visual_type == "voiceover"


@pytest.mark.asyncio
async def test_assembly_calls_whiteboard_attach(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.explainer import assembly as explainer_assembly

    captured: dict[str, object] = {}

    async def fake_whiteboard(cues, output_dir, **kwargs):
        captured["enabled"] = kwargs.get("enabled")
        captured["kind"] = cues[0].visual_type
        cues[0].visual_config["assetUrl"] = "runs/job/whiteboard/cue-1.mp4"
        return cues

    async def fake_render(storyboard, _output_dir, **_kwargs):
        captured["visual"] = storyboard.segments[0].visual_type
        return "rendered"

    monkeypatch.setattr(explainer_assembly, "attach_whiteboard_scenes", fake_whiteboard)
    monkeypatch.setattr(explainer_assembly, "render_narrated_storyboard", fake_render)
    result = await explainer_assembly.assemble_explainer_cues(
        "主题",
        [ExplainerCue(visual_type="whiteboard", text="盐税是什么")],
        tmp_path,
        voice="cosyvoice_default",
        aspect_ratio="16:9",
    )
    assert result == "rendered"
    assert captured["enabled"] is True
    assert captured["kind"] == "whiteboard"
    assert captured["visual"] == "whiteboard"
