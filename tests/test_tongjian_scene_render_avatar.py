"""L6 云数字人渲染路径(scene_render_avatar)测试。

覆盖两个从真实成片里定位到的问题:
1. 对白 keyframe 生成没接入 visual_hint,退化成同一套通用手势(如"抱拳")。
2. 长台词被 _say_dur 硬压进 happyhorse 15s 时长上限,逼出"说话太快+口型对不上"。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.tongjian.scene_render_avatar import (
    _MAX_CLIP_DURATION_S,
    _say_dur,
    _split_text_for_dialogue,
    build_frame_manifest_avatar,
)
from hevi.tongjian.schemas import (
    CharacterBible,
    CharacterBibleEntry,
    Constitution,
    Script,
    ScriptLine,
    Shot,
    ShotList,
)

_LONG_QUOTE_TEXT = (
    "智瑶不如您另一位庶子智宵。智瑶有五项超人的优点，只有一项缺点。五项优点是："
    "相貌英俊，精于骑马射箭，通晓各项技能，文辞流畅，处事坚决果断。一项缺点是："
    "心胸狭窄，刻薄少恩。五种才能再加上没有容人之量，谁能够和他和平共处？"
    "如果让智瑶做您的继承人，智氏家族必定灭亡。"
)


# ── _split_text_for_dialogue / _say_dur ─────────────────────────────────────


def test_split_text_keeps_short_line_whole():
    assert _split_text_for_dialogue("瑶儿，跪受圭璋。", 0.32) == ["瑶儿，跪受圭璋。"]


def test_split_text_breaks_long_quote_under_duration_cap():
    chunks = _split_text_for_dialogue(_LONG_QUOTE_TEXT, 0.32)
    assert len(chunks) > 1
    assert "".join(chunks) == _LONG_QUOTE_TEXT  # 拼回去不丢字
    for chunk in chunks:
        assert _say_dur(chunk, 0.32) <= _MAX_CLIP_DURATION_S


def test_split_text_hard_splits_clause_with_no_punctuation():
    text = "无" * 100  # 单个分句本身就超长,没有标点可切
    chunks = _split_text_for_dialogue(text, 0.32)
    assert len(chunks) > 1
    assert "".join(chunks) == text
    for chunk in chunks:
        assert _say_dur(chunk, 0.32) <= _MAX_CLIP_DURATION_S


def test_say_dur_capped_at_platform_limit():
    assert _say_dur(_LONG_QUOTE_TEXT, 0.32) == _MAX_CLIP_DURATION_S


# ── build_frame_manifest_avatar ─────────────────────────────────────────────


def _bible() -> CharacterBible:
    return CharacterBible(
        characters=[CharacterBibleEntry(character_id="C003", name="智果", appearance="清瘦谋士")]
    )


@pytest.mark.asyncio
async def test_dialogue_keyframe_includes_visual_hint(tmp_path):
    """qwen-image-edit 的 instruction 里必须带上 visual_hint 描述的具体动作,
    不能只有 emotion——否则会退化成同一套"拱手"通用姿势(真实产物里复现过的问题)。
    """
    script = Script(
        lines=[
            ScriptLine(
                line_id="LN001",
                type="dialogue",
                speaker="C003",
                text="请分宗。",
                emotion="决绝",
                visual_hint="智果解下腰间玉珏掷于阶前",
            )
        ]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"fake-kf")
        return output_path

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"fake-canon")
        return output_path

    async def _fake_happyhorse(*, image_path, prompt, output_path, duration, resolution):
        output_path.write_bytes(b"fake-talk")
        return output_path

    qwen_edit = AsyncMock(side_effect=_fake_qwen_edit)
    with (
        patch("hevi.tongjian.scene_render_avatar.qwen_image_edit", qwen_edit),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(side_effect=_fake_qwen_gen),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate",
            AsyncMock(side_effect=_fake_happyhorse),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_dialogue",
            lambda talk, clip, w, h: clip.write_bytes(b"c"),
        ),
    ):
        await build_frame_manifest_avatar(
            shotlist, script, _bible(), Constitution(), run_dir=tmp_path
        )

    instruction = qwen_edit.await_args.kwargs["instruction"]
    assert "智果解下腰间玉珏掷于阶前" in instruction


@pytest.mark.asyncio
async def test_long_dialogue_line_renders_as_multiple_chunks(tmp_path):
    """超过 15s 硬顶的长台词要被切成多段分别渲染再拼接,而不是塞进一个被迫加速的 clip。"""
    script = Script(
        lines=[
            ScriptLine(
                line_id="LN001",
                type="dialogue",
                speaker="C003",
                text=_LONG_QUOTE_TEXT,
                emotion="恳切而凛然",
                visual_hint="智果伏地叩首",
            )
        ]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"fake-kf")
        return output_path

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"fake-canon")
        return output_path

    happyhorse_calls: list[tuple[str, int]] = []

    async def _fake_happyhorse(*, image_path, prompt, output_path, duration, resolution):
        happyhorse_calls.append((prompt, duration))
        output_path.write_bytes(b"fake-talk")
        return output_path

    concat_calls: list[list[Path]] = []

    def _fake_concat(clips, out):
        concat_calls.append(clips)
        out.write_bytes(b"concatenated")

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_edit",
            AsyncMock(side_effect=_fake_qwen_edit),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(side_effect=_fake_qwen_gen),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate",
            AsyncMock(side_effect=_fake_happyhorse),
        ),
        patch("hevi.tongjian.scene_render_avatar._concat_clips", _fake_concat),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_dialogue",
            lambda talk, clip, w, h: clip.write_bytes(b"c"),
        ),
    ):
        await build_frame_manifest_avatar(
            shotlist, script, _bible(), Constitution(), run_dir=tmp_path
        )

    assert len(happyhorse_calls) > 1  # 切成了多段
    for _, duration in happyhorse_calls:
        assert duration <= _MAX_CLIP_DURATION_S
    assert len(concat_calls) == 1
    assert len(concat_calls[0]) == len(happyhorse_calls)
