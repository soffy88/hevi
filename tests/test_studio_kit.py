"""三条管线共享能力:通鉴/短剧/解说互借 + 10 库内化点。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.studio.assets import list_assets, reset_assets
from hevi.studio.kit import (
    explainer_cues_from_text,
    freeze_profile,
    nle_recut,
    shot_export,
    tongjian_l0,
    tongjian_provenance,
    verify_profile,
    watch_video_tool,
)
from hevi.studio.mix import plan_history_mix, split_history_script
from hevi.studio.tools import invoke_tool
from hevi.tongjian.schemas import Script, ScriptLine


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_assets()
    yield
    reset_assets()


def test_kit_tools_are_registered() -> None:
    ids = {t.tool_id for t in __import__("hevi.studio.tools", fromlist=["list_tools"]).list_tools()}
    assert {
        "watch.video",
        "tongjian.l0",
        "tongjian.provenance",
        "explainer.manim",
        "avatar.compose",
        "tts.synth",
        "shot.export",
        "nle.recut",
        "profile.freeze",
    } <= ids


def test_split_history_is_commentary_plus_drama() -> None:
    script = Script(
        lines=[
            ScriptLine(
                line_id="n1", type="narration", speaker="NARRATOR", text="智伯向韩康子索地。"
            ),
            ScriptLine(
                line_id="d1",
                type="dialogue",
                speaker="智伯",
                text="把万家之邑给我。",
                quote_id="Q001",
            ),
            ScriptLine(
                line_id="c1", type="commentary", speaker="NARRATOR", text="这是权力失衡的开始。"
            ),
        ]
    )
    commentary, drama = split_history_script(script)
    assert len(commentary) == 2
    assert len(drama) == 1
    assert drama[0]["speaker"] == "智伯"


@pytest.mark.asyncio
async def test_mix_borrows_explainer_cues_and_provenance() -> None:
    script = Script(
        lines=[
            ScriptLine(
                line_id="n1", type="narration", speaker="NARRATOR", text="讲解盐税如何发军饷。"
            ),
            ScriptLine(line_id="d1", type="dialogue", speaker="韩康子", text="不可。"),
        ]
    )
    mix = await plan_history_mix(script)
    assert mix.commentary_cues
    assert mix.commentary_cues[0]["text"].startswith("讲解")
    assert mix.drama_lines
    assert mix.provenance["passed"] is False
    assert mix.provenance["errors"]


def test_provenance_passes_when_quote_or_dramatized() -> None:
    ok = tongjian_provenance(
        {
            "lines": [
                {"type": "dialogue", "text": "把地给我", "quote_id": "Q1"},
                {"type": "dialogue", "text": "你敢拒我", "dramatized": True},
            ]
        }
    )
    assert ok["passed"] is True


@pytest.mark.asyncio
async def test_explainer_can_borrow_l0_without_llm() -> None:
    result = await tongjian_l0(
        {"source_name": "周纪", "raw_text": "智伯请地于韩康子。", "llm": object()}
    )
    assert result["status"] == "ok"
    assert "chapter_ir" in result


@pytest.mark.asyncio
async def test_watch_and_shot_export_and_profile(tmp_path: Path) -> None:
    watched = await watch_video_tool(
        {"transcript": "先钩子后盐路。", "duration_s": 20, "source": "inline"}
    )
    assert watched["status"] == "ok"
    assert watched["concepts"]

    exported = shot_export(
        {
            "shot_id": "SH001",
            "line_id": "director_pipeline",
            "prompt": "对峙",
            "duration_s": 4,
        }
    )
    assert exported["status"] == "ok"
    shots = list_assets(kind="shot")
    assert any(s.label == "SH001" for s in shots)

    frozen = freeze_profile(
        {
            "workspace": {"voice": "edge", "canvas": "16:9"},
            "project": {"cta": "订阅"},
            "dest": str(tmp_path / "resolved.json"),
        }
    )
    assert frozen["sha256"]
    assert verify_profile({"resolved_path": frozen["resolved_path"]})["passed"] is True
    Path(frozen["resolved_path"]).write_text('{"tampered": true}', encoding="utf-8")
    assert verify_profile({"resolved_path": frozen["resolved_path"]})["passed"] is False


@pytest.mark.asyncio
async def test_nle_recut_single_clip(tmp_path: Path) -> None:
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"fake-mp4")
    dest = tmp_path / "out.mp4"
    result = nle_recut({"clips": [str(clip)], "output_path": str(dest)})
    assert result["status"] == "ok"
    assert dest.exists()


@pytest.mark.asyncio
async def test_invoke_cross_pipeline_tools() -> None:
    cues = await explainer_cues_from_text({"texts": ["这是讲解。"]})
    assert cues["cues"][0]["visual_type"] == "voiceover"
    via = await invoke_tool("tongjian.provenance", {"lines": [{"type": "narration", "text": "x"}]})
    assert via.status == "ok"
    assert via.payload["passed"] is True
