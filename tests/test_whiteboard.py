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
    out = render_infographic_cue(
        "盐税是间接税。因为短缺所以涨价。", duration_ms=400, dest=dest, width=320, height=180, fps=8
    )
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


def test_whiteboard_compiler_extracts_meaningful_content() -> None:
    from hevi.layer4_legacy.whiteboard.oskill_impl.compiler import (
        compile_storyboard_to_dsl,
        extract_beat_content,
        parse_storyboard,
    )

    storyboard = {
        "topic": "大语言模型如何思考",
        "segments": [
            {
                "sceneType": "intro",
                "narration": "今天我们要给大家介绍什么是大语言模型。| 核心原理是预测下一个词。| 让你一看就明白！",
                "keywords": ["大模型介绍", "预测下一个词"],
            }
        ],
    }

    title0, points0 = extract_beat_content(
        "今天我们要给大家介绍什么是大语言模型。",
        keywords=["大模型介绍"],
        beat_index=0,
    )
    assert title0 == "大模型介绍"
    assert len(points0) > 0

    segments = parse_storyboard(storyboard)
    assert len(segments) == 1
    assert len(segments[0].beats) == 3
    assert segments[0].beats[0].title == "大模型介绍"

    dsl_landscape = compile_storyboard_to_dsl(
        storyboard,
        orientation="landscape",
        runtime_root="/path/to/whiteboard",
    )
    assert "Beat 0" not in dsl_landscape
    assert "大语言模型如何思考" in dsl_landscape
    assert "大模型介绍" in dsl_landscape

    dsl_portrait = compile_storyboard_to_dsl(
        storyboard,
        orientation="portrait",
        runtime_root="/path/to/whiteboard",
    )
    assert "CX_P" in dsl_portrait
    assert "Beat 0" not in dsl_portrait
    assert "大模型介绍" in dsl_portrait


def test_align_words_to_segments() -> None:
    from hevi.layer4_legacy.whiteboard.omodul_impl.tts_asr import align_words_to_segments

    segments = ["第一句内容介绍。", "第二句详细分析。", "第三句给出结论。"]
    words = [
        {"w": "第一句", "s": 0.1, "e": 0.5},
        {"w": "内容", "s": 0.5, "e": 0.9},
        {"w": "介绍", "s": 0.9, "e": 1.4},
        {"w": "第二句", "s": 1.7, "e": 2.1},
        {"w": "详细", "s": 2.1, "e": 2.5},
        {"w": "分析", "s": 2.5, "e": 3.0},
        {"w": "第三句", "s": 3.4, "e": 3.8},
        {"w": "给出", "s": 3.8, "e": 4.2},
        {"w": "结论", "s": 4.2, "e": 4.7},
    ]
    starts = align_words_to_segments(segments, words, 4.8)
    assert len(starts) == 3
    assert starts[0] == 0.0
    assert starts[1] >= 1.5
    assert starts[2] >= 3.2
    assert starts[1] < starts[2]


def test_capabilities_includes_whiteboard_explainer() -> None:
    from hevi.production.capabilities import _CATALOG, capability_catalog

    assert "whiteboard_explainer" in _CATALOG
    catalog_ids = {item["id"] for item in capability_catalog()}
    assert "whiteboard_explainer" in catalog_ids
    desc = _CATALOG["whiteboard_explainer"]
    assert desc.id == "whiteboard_explainer"
    assert "/api/explainer/run" in desc.routes

