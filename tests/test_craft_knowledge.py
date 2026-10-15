"""中文制作手艺知识库:阶段枚举、加载、别名、截断标记、clean-room 与 studio 工具面。"""

from __future__ import annotations

import pytest

from hevi.production.craft_knowledge import (
    ALL_STAGE_IDS,
    STAGE_FILES,
    knowledge_dir,
    list_stages,
    load_stage,
    load_stages,
    resolve_stage,
)

EXPECTED_STAGES = (
    "research",
    "proposal",
    "screenplay",
    "storyboard",
    "materials",
    "editing",
    "composite",
    "review",
    "subtitle",
    "grading",
    "music",
    "voice_acting",
    "shot_prompt",
)

TRUNCATION_MARKER = "<!-- truncated at 600 chars -->"


def test_all_stage_ids_are_the_thirteen_expected_ones() -> None:
    assert set(ALL_STAGE_IDS) == set(EXPECTED_STAGES)
    assert len(ALL_STAGE_IDS) == 13
    assert set(STAGE_FILES) == set(EXPECTED_STAGES)


def test_load_stage_returns_real_content_with_its_title() -> None:
    text = load_stage("storyboard")
    assert text.strip()
    assert "分镜阶段手艺手册" in text
    assert len(text) > 500


def test_every_stage_file_is_substantive_and_indexed() -> None:
    rows = list_stages()
    assert [row["stage"] for row in rows] == list(EXPECTED_STAGES)
    for row in rows:
        assert row["title"], f"{row['stage']} 缺 title"
        assert row["files"], f"{row['stage']} 缺文件清单"
        assert row["chars"] > 500, f"{row['stage']} 只有 {row['chars']} 字,像占位"


def test_resolve_stage_is_case_insensitive_and_alias_tolerant() -> None:
    assert resolve_stage("分镜") == "storyboard"
    assert resolve_stage("SUBTITLE") == "subtitle"
    assert resolve_stage("  调色  ") == "grading"
    assert resolve_stage("voice acting") == "voice_acting"
    assert resolve_stage("04") == "storyboard"
    assert resolve_stage("不存在的阶段") is None
    assert resolve_stage("") is None


def test_unknown_stage_raises_value_error() -> None:
    with pytest.raises(ValueError, match="未知制作阶段"):
        load_stage("没有这个阶段")
    with pytest.raises(ValueError, match="未知制作阶段"):
        load_stages(["subtitle", "也不存在"])


def test_max_chars_truncates_and_leaves_a_visible_marker() -> None:
    full = load_stage("subtitle")
    assert len(full) > 600

    clipped = load_stage("subtitle", max_chars=600)
    assert clipped.startswith(full[:600])
    assert TRUNCATION_MARKER in clipped
    assert len(clipped) <= 600 + len(TRUNCATION_MARKER) + 2

    # 不截断时不留任何标记
    assert "truncated at" not in full
    assert load_stage("subtitle", max_chars=len(full)) == full


def test_load_stages_sections_every_requested_stage() -> None:
    text = load_stages(["research", "subtitle"])
    assert "制作手艺知识:research" in text
    assert "制作手艺知识:subtitle" in text
    assert "研究阶段手艺手册" in text
    assert "字幕手艺手册" in text
    assert "分镜阶段手艺手册" not in text


def test_knowledge_dir_is_the_packaged_markdown_directory() -> None:
    d = knowledge_dir()
    assert d.name == "knowledge"
    assert d.parent.name == "skills"
    assert (d / "README.md").is_file()
    # 纯数据目录:不能有 __init__.py,否则会被当成 Python 包导入
    assert not (d / "__init__.py").exists()


def test_no_knowledge_file_mentions_the_reference_implementation() -> None:
    for row in list_stages():
        for name in row["files"]:
            text = (knowledge_dir() / name).read_text(encoding="utf-8")
            assert "OpenMontage" not in text, f"{name} 出现了 clean-room 禁止字符串"


@pytest.mark.asyncio
async def test_studio_op_is_registered_and_returns_ok() -> None:
    from hevi.studio.catalog import ALL_CATALOG
    from hevi.studio.ops import OPS, run_op

    assert "craft.knowledge" in {tool_id for tool_id, *_ in ALL_CATALOG}
    assert "craft_knowledge" in OPS

    res = await run_op("craft_knowledge", {"stage": "subtitle"})
    assert res["status"] == "ok"
    assert res["stage"] == "subtitle"
    assert "字幕手艺手册" in res["title"]
    assert "字幕手艺手册" in res["text"]

    # 中文别名也要通
    alias = await run_op("craft_knowledge", {"stage": "分镜"})
    assert alias["status"] == "ok"
    assert alias["stage"] == "storyboard"

    # 不传 stage → 返回目录
    index = await run_op("craft_knowledge", {})
    assert index["status"] == "ok"
    assert index["count"] == 13

    # 未知阶段 → 明确失败,不是静默空串
    bad = await run_op("craft_knowledge", {"stage": "没有这个阶段"})
    assert bad["status"] == "failed"
