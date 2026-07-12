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
    _NARRATOR_DESC,
    _say_dur,
    _split_text_for_dialogue,
    build_frame_manifest_avatar,
)
from hevi.tongjian.schemas import (
    CharacterBible,
    CharacterBibleEntry,
    Constitution,
    LayerConfig,
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


def _bible(ref_image: str | None = None) -> CharacterBible:
    return CharacterBible(
        characters=[
            CharacterBibleEntry(
                character_id="C003", name="智果", appearance="清瘦谋士", ref_image=ref_image
            )
        ]
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
async def test_canonical_reuses_subject_reference_image_when_present(tmp_path):
    """CharacterBible.ref_image(Subject 真实参考图路径)存在时,canonical 像必须直接
    复用那张真实图,而不是从文字描述现场重新生成一张陌生的脸——2026-07-12 真实撞见:
    短剧建号阶段真的会存参考图,但这条 cloud_avatar 渲染路径此前完全没读过这个字段。
    """
    from PIL import Image

    ref_path = tmp_path / "subject_ref.png"
    Image.new("RGB", (64, 64), color=(10, 20, 30)).save(ref_path)

    script = Script(
        lines=[
            ScriptLine(
                line_id="LN001",
                type="dialogue",
                speaker="C003",
                text="请分宗。",
                emotion="决绝",
            )
        ]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"fake-kf")
        return output_path

    qwen_gen = AsyncMock()

    async def _fake_happyhorse(*, image_path, prompt, output_path, duration, resolution):
        output_path.write_bytes(b"fake-talk")
        return output_path

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_edit",
            AsyncMock(side_effect=_fake_qwen_edit),
        ),
        patch("hevi.tongjian.scene_render_avatar.qwen_image_generate", qwen_gen),
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
            shotlist, script, _bible(ref_image=str(ref_path)), Constitution(), run_dir=tmp_path
        )

    # narrator(没有 Subject/ref_image)仍会走文生图这条老路,但 C003 有真实参考图,
    # 不该现场生成一张新脸——qwen_image_generate 的调用里不能有一个是给它的。
    for call in qwen_gen.await_args_list:
        assert "C003" not in str(call.kwargs["output_path"])
    canon = tmp_path / "canon_C003.png"
    assert canon.exists()
    assert Image.open(canon).convert("RGB").getpixel((0, 0)) == (10, 20, 30)


@pytest.mark.asyncio
async def test_shot_frame_carries_consistency_score_against_canon(tmp_path):
    """2026-07-12 补:生成时把身份锚定住了(见上一条测试),但此前没人在事后校验有没有
    漂移——character_consistency 恒为 None。有 lead 角色 + canon 存在时,必须真的算出
    一个分数写进 ShotFrame,而不是继续摆设。"""
    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。")]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    async def _write(*, output_path, **_kwargs):
        output_path.write_bytes(b"fake")
        return output_path

    with (
        patch("hevi.tongjian.scene_render_avatar.qwen_image_edit", AsyncMock(side_effect=_write)),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate", AsyncMock(side_effect=_write)
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate", AsyncMock(side_effect=_write)
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_dialogue",
            lambda talk, clip, w, h: clip.write_bytes(b"c"),
        ),
        patch("hevi.tongjian.scene_render_avatar._score_consistency", lambda frame, canon: 0.42),
    ):
        manifest = await build_frame_manifest_avatar(
            shotlist, script, _bible(), Constitution(), run_dir=tmp_path
        )

    assert manifest.frames[0].character_consistency == 0.42


@pytest.mark.asyncio
async def test_shot_frame_consistency_none_when_no_lead_character(tmp_path):
    """没有角色的纯场景/空镜没有身份可言,不该硬凑一个分数出来。"""
    script = Script(lines=[ScriptLine(line_id="LN001", type="narration", text="山间薄雾弥漫。")])
    shotlist = ShotList(
        shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=[], visual_prompt="空山")]
    )

    async def _write(*, output_path, **_kwargs):
        output_path.write_bytes(b"fake")
        return output_path

    score_fn = AsyncMock()
    with (
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate", AsyncMock(side_effect=_write)
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate", AsyncMock(side_effect=_write)
        ),
        patch("hevi.tongjian.scene_render_avatar.i2v_animate", AsyncMock(side_effect=_write)),
        patch(
            "hevi.tongjian.scene_render_avatar.subprocess.run",
            lambda cmd, **kwargs: Path(cmd[-1]).write_bytes(b"a"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_narration",
            lambda vis, audio, out, w, h: out.write_bytes(b"c"),
        ),
        patch("hevi.tongjian.scene_render_avatar._score_consistency", score_fn),
    ):
        manifest = await build_frame_manifest_avatar(
            shotlist, script, _bible(), Constitution(), run_dir=tmp_path
        )

    assert manifest.frames[0].character_consistency is None
    score_fn.assert_not_called()


@pytest.mark.asyncio
async def test_narrator_desc_overridable_via_config(tmp_path):
    """旁白/说书人形象默认写死"古装说书人史官"(资治通鉴专用),短剧走"现代都市"风格时
    不该套这身行头——LayerConfig.params["narrator_desc"] 传了就该覆盖默认值,不传则
    保留原有史官形象(资治通鉴自己的调用方不受影响)。
    """
    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。")]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    qwen_gen = AsyncMock(
        side_effect=lambda *, prompt, output_path, size, seed=None: (
            output_path.write_bytes(b"fake"),
            output_path,
        )[1]
    )

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_edit",
            AsyncMock(
                side_effect=lambda *, image_path, instruction, output_path: (
                    output_path.write_bytes(b"fake-kf"),
                    output_path,
                )[1]
            ),
        ),
        patch("hevi.tongjian.scene_render_avatar.qwen_image_generate", qwen_gen),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate",
            AsyncMock(
                side_effect=lambda *, image_path, prompt, output_path, duration, resolution: (
                    output_path.write_bytes(b"fake-talk"),
                    output_path,
                )[1]
            ),
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
            shotlist,
            script,
            _bible(),
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(model="cloud_avatar", params={"narrator_desc": "当代讲述者,便装"}),
        )

    narrator_calls = [
        c for c in qwen_gen.await_args_list if "canon_narrator" in str(c.kwargs["output_path"])
    ]
    assert len(narrator_calls) == 1
    assert "当代讲述者" in narrator_calls[0].kwargs["prompt"]
    assert "史官" not in narrator_calls[0].kwargs["prompt"]


@pytest.mark.asyncio
async def test_narrator_desc_defaults_to_tongjian_persona_when_not_overridden(tmp_path):
    """不传 narrator_desc(资治通鉴自己的调用方)时,行为不能变——仍是原来的史官形象。"""
    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。")]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    qwen_gen = AsyncMock(
        side_effect=lambda *, prompt, output_path, size, seed=None: (
            output_path.write_bytes(b"fake"),
            output_path,
        )[1]
    )

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_edit",
            AsyncMock(
                side_effect=lambda *, image_path, instruction, output_path: (
                    output_path.write_bytes(b"fake-kf"),
                    output_path,
                )[1]
            ),
        ),
        patch("hevi.tongjian.scene_render_avatar.qwen_image_generate", qwen_gen),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate",
            AsyncMock(
                side_effect=lambda *, image_path, prompt, output_path, duration, resolution: (
                    output_path.write_bytes(b"fake-talk"),
                    output_path,
                )[1]
            ),
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

    narrator_calls = [
        c for c in qwen_gen.await_args_list if "canon_narrator" in str(c.kwargs["output_path"])
    ]
    assert len(narrator_calls) == 1
    assert _NARRATOR_DESC in narrator_calls[0].kwargs["prompt"]


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
