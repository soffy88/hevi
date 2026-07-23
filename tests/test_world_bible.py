"""World Bible 影像美学预设(visual_style)测试——2026-07-22 写实度探针坐实 style_manifesto
是画风主控杠杆后落地:短剧默认 realistic,inkwash 可选。断言预设指令真进了 visual 卷的
LLM prompt(不是只验字段被赋值)。"""

from unittest.mock import patch

import pytest

from hevi.director import world_bible as wb_mod
from hevi.director.pipeline_schemas import Concept, DesignList
from hevi.director.world_bible import generate_world_bible_draft

_REALISTIC_MARK = "照片级真人实拍电影帧"
_INKWASH_MARK = "宣纸渗染、墨色晕化、留白构图"


async def _run_and_capture(visual_style: str | None) -> list[str]:
    captured: list[str] = []

    async def _fake_call(llm, prompt, **_kw):  # 镜像 _call_llm_json(llm, prompt, *, ...)
        captured.append(prompt)
        return {}

    kwargs = {} if visual_style is None else {"visual_style": visual_style}
    with patch.object(wb_mod, "_call_llm_json", side_effect=_fake_call):
        await generate_world_bible_draft(
            concept=Concept(),
            material_text="许姓渔夫与河中鬼友王六郎的故事。",
            design_list=DesignList(),
            llm=lambda **_k: None,
            **kwargs,
        )
    # visual 卷的 prompt 是唯一含"视觉风格宣言"的那条
    return [p for p in captured if "视觉风格宣言" in p]


@pytest.mark.asyncio
async def test_default_visual_style_is_realistic() -> None:
    """不传 visual_style → 默认写实(短剧产品目标)。"""
    visual_prompts = await _run_and_capture(None)
    assert visual_prompts, "没捕获到 visual 卷 prompt"
    assert _REALISTIC_MARK in visual_prompts[0]
    assert _INKWASH_MARK not in visual_prompts[0]


@pytest.mark.asyncio
async def test_visual_style_realistic_injects_directive() -> None:
    visual_prompts = await _run_and_capture("realistic")
    assert _REALISTIC_MARK in visual_prompts[0]
    assert _INKWASH_MARK not in visual_prompts[0]


@pytest.mark.asyncio
async def test_visual_style_inkwash_injects_directive() -> None:
    visual_prompts = await _run_and_capture("inkwash")
    assert _INKWASH_MARK in visual_prompts[0]
    assert _REALISTIC_MARK not in visual_prompts[0]
