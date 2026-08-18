"""Explainer manim_scene 装配接线。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.explainer import assembly as explainer_assembly
from hevi.explainer.contracts import ExplainerAssembleRequest, ExplainerCue
from hevi.explainer.manim_scene import attach_manim_scenes
from hevi.explainer.research import _sanitise_raw_scripts


@pytest.mark.asyncio
async def test_attach_writes_asset_url(tmp_path: Path) -> None:
    async def fake_render(**kwargs):
        dest = Path(kwargs["output_path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x00\x00fake-mp4")
        return dest

    cue = ExplainerCue(
        visual_type="manim_scene",
        text="质量能量等价 $E=mc^2$",
        time_estimate_s=6,
        visual_config={"recipe": "equation", "tex": "E=mc^2"},
    )
    await attach_manim_scenes([cue], tmp_path, renderer=fake_render, width=320, height=180)
    assert cue.visual_type == "manim_scene"
    assert str(cue.visual_config["assetUrl"]).endswith("cue-1.mp4")
    assert (tmp_path / "manim" / "cue-1.mp4").exists()
    assert cue.visual_config["scene"]["tex"] == "E=mc^2"


@pytest.mark.asyncio
async def test_attach_disabled_degrades_to_voiceover(tmp_path: Path) -> None:
    cue = ExplainerCue(visual_type="manim_scene", text="公式")
    await attach_manim_scenes([cue], tmp_path, enabled=False)
    assert cue.visual_type == "voiceover"


@pytest.mark.asyncio
async def test_attach_render_failure_degrades(tmp_path: Path) -> None:
    async def boom(**_kwargs):
        raise RuntimeError("no ffmpeg")

    cue = ExplainerCue(visual_type="manim_scene", text="公式")
    await attach_manim_scenes([cue], tmp_path, renderer=boom)
    assert cue.visual_type == "voiceover"


@pytest.mark.asyncio
async def test_assembly_calls_attach_before_remotion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    async def fake_attach(cues, output_dir, **kwargs):
        captured["enabled"] = kwargs.get("enabled")
        captured["size"] = (kwargs.get("width"), kwargs.get("height"))
        cues[0].visual_config["assetUrl"] = "runs/job/manim/cue-1.mp4"
        return cues

    async def fake_render(storyboard, _output_dir, **_kwargs):
        captured["storyboard"] = storyboard
        return "rendered"

    monkeypatch.setattr(explainer_assembly, "attach_manim_scenes", fake_attach)
    monkeypatch.setattr(explainer_assembly, "render_narrated_storyboard", fake_render)
    result = await explainer_assembly.assemble_explainer_cues(
        "主题",
        [ExplainerCue(visual_type="manim_scene", text="开场公式 $E=mc^2$")],
        tmp_path,
        voice="cosyvoice_default",
        aspect_ratio="16:9",
    )
    assert result == "rendered"
    assert captured["enabled"] is True
    assert captured["size"] == (1920, 1080)
    storyboard = captured["storyboard"]
    assert storyboard.segments[0].visual_type == "manim_scene"
    assert storyboard.segments[0].visual_config["assetUrl"] == "runs/job/manim/cue-1.mp4"


def test_assemble_request_defaults_manim_on() -> None:
    req = ExplainerAssembleRequest(
        selected_hook="h",
        final_script_cues=[ExplainerCue(visual_type="manim_scene", text="公式")],
    )
    assert req.enable_manim_render is True


def test_research_keeps_manim_scene_visual_type() -> None:
    raw = {
        "scripts": [
            {
                "id": "A",
                "title": "t",
                "cues": [
                    {
                        "text": "质量能量",
                        "visual_type": "manim_scene",
                        "visual_config": {"tex": "E=mc^2"},
                    }
                ],
            }
        ]
    }
    scripts = _sanitise_raw_scripts(raw)
    assert scripts[0]["cues"][0]["visual_type"] == "manim_scene"
