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
_HISTORICAL_MARK = "史诗历史正剧"


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


@pytest.mark.asyncio
async def test_visual_style_historical_injects_directive() -> None:
    # SPEC-005-V2 §4:通鉴历史正剧档,火把/烛火光源 + 禁浅景深糖水 + 考据。
    visual_prompts = await _run_and_capture("historical")
    assert _HISTORICAL_MARK in visual_prompts[0]
    assert "火把" in visual_prompts[0] and "考据" in visual_prompts[0]
    assert _INKWASH_MARK not in visual_prompts[0]


@pytest.mark.asyncio
async def test_visual_volume_prompts_and_parses_style_render_directive() -> None:
    # 画风锁②:visual 卷 prompt 要求 style_render_directive,且 LLM 返回后被解析进 VisualVolume。
    captured: list[str] = []

    async def _fake_call(llm, prompt, **_kw):
        captured.append(prompt)
        if "视觉风格宣言" in prompt:
            return {
                "style_manifesto": "一大段抽象散文……",
                "style_render_directive": "水墨渲染质感,青灰主调,写实人物比例——全片统一",
                "camera_persona": {"persona_id": "static_watch"},
            }
        return {}

    with patch.object(wb_mod, "_call_llm_json", side_effect=_fake_call):
        wb = await generate_world_bible_draft(
            concept=Concept(),
            material_text="许姓渔夫与河中鬼友王六郎。",
            design_list=DesignList(),
            llm=lambda **_k: None,
        )
    # prompt 里显式要了这个字段
    assert any("style_render_directive" in p for p in captured)
    # 解析进了 VisualVolume
    assert wb.visual.style_render_directive == "水墨渲染质感,青灰主调,写实人物比例——全片统一"
    assert wb.visual.style_manifesto == "一大段抽象散文……"


@pytest.mark.asyncio
async def test_historical_domain_directive_reaches_character_and_world_prompts() -> None:
    # SPEC-005-V2 §2.2:历史档时代考据硬约束必须到达角色卷 + 世界卷 prompt(不只 visual volume)。
    captured: list[str] = []

    async def _fake_call(llm, prompt, **_kw):
        captured.append(prompt)
        return {}

    from hevi.director.pipeline_schemas import DesignCharacter, DesignScene

    dl = DesignList(
        characters=[DesignCharacter(name="商鞅")],
        scenes=[DesignScene(name="秦国市集")],
    )
    with patch.object(wb_mod, "_call_llm_json", side_effect=_fake_call):
        await generate_world_bible_draft(
            concept=Concept(),
            material_text="商鞅立木。",
            design_list=dl,
            llm=lambda **_k: None,
            visual_style="historical",
        )
    char_prompts = [p for p in captured if "定妆手册" in p]
    world_prompts = [p for p in captured if "环境设定" in p]
    assert char_prompts and "时代考据硬约束" in char_prompts[0]
    assert world_prompts and "时代考据硬约束" in world_prompts[0]
    # realistic 档不注入(默认空)
    captured.clear()
    with patch.object(wb_mod, "_call_llm_json", side_effect=_fake_call):
        await generate_world_bible_draft(
            concept=Concept(),
            material_text="x。",
            design_list=dl,
            llm=lambda **_k: None,
            visual_style="realistic",
        )
    assert all("时代考据硬约束" not in p for p in captured)
