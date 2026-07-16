"""L6 云数字人渲染路径(scene_render_avatar)测试。

覆盖两个从真实成片里定位到的问题:
1. 对白 keyframe 生成没接入 visual_hint,退化成同一套通用手势(如"抱拳")。
2. 长台词被 _say_dur 硬压进 happyhorse 15s 时长上限,逼出"说话太快+口型对不上"。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


async def _fake_kf2v(*, first_frame, last_frame, output_path, **_kw):
    Path(output_path).write_bytes(b"kf2v-vis")
    return output_path


@pytest.fixture(autouse=True)
def _stub_sdxl_local():
    """关键帧引擎默认 engine="local"(本地 sdxl_local + IP-Adapter)。测试里不真跑本地 GPU
    (151s/帧),默认桩成"GPU 不可用"→ 让关键帧退到各测试自己 patch 的云端 qwen-image-edit,
    使既有断言(围绕 qwen-image-edit 的行为)保持有效。要测本地引擎本身的测试,自行覆盖它。

    同时桩掉 P3 动作镜的云端依赖:kf2v 首尾帧(不打真 MAAS)+ _resolve_llm(返回 None,
    _action_end_state 走无 LLM 退化),测试不触网。要测 kf2v 行为的测试自行覆盖。"""
    with (
        patch(
            "hevi.tongjian.scene_render_avatar.sdxl_local_generate",
            AsyncMock(side_effect=RuntimeError("GPU 不可用(测试桩)")),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.alibaba_maas_keyframe_generate",
            AsyncMock(side_effect=_fake_kf2v),
        ),
        patch("hevi.tongjian.scene_render_avatar._resolve_llm", lambda: None),
    ):
        yield


from hevi.image.qwen_image_service import QwenImageError
from hevi.tongjian.scene_render_avatar import (
    _MAX_CLIP_DURATION_S,
    _NARRATOR_DESC,
    _resolve_dimensions,
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
    VisualStyle,
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


# ── _resolve_dimensions ──────────────────────────────────────────────────────


def test_resolve_dimensions_landscape_default():
    assert _resolve_dimensions("720P", "16:9") == (1280, 720)


def test_resolve_dimensions_portrait_swaps_wh():
    """2026-07-12 真实撞见:短剧设计上是 9:16 竖屏,但此前这里从不读 aspect_ratio,
    真实跑出来的成片是 1280×720 横屏——9:16 必须把 _RES 的横屏尺寸转置。"""
    assert _resolve_dimensions("720P", "9:16") == (720, 1280)


def test_resolve_dimensions_unknown_resolution_falls_back_to_720p():
    assert _resolve_dimensions("bogus", "16:9") == (1280, 720)


# ── build_frame_manifest_avatar ─────────────────────────────────────────────


def _bible(ref_image: str | None = None) -> CharacterBible:
    return CharacterBible(
        characters=[
            CharacterBibleEntry(
                character_id="C003", name="智果", appearance="清瘦谋士", ref_image=ref_image
            )
        ]
    )


async def _fake_hh(*, image_path, prompt, output_path, duration, resolution):
    Path(output_path).write_bytes(b"fake-talk")
    return output_path


@pytest.mark.asyncio
async def test_portrait_aspect_ratio_reaches_final_crop_dimensions(tmp_path):
    """2026-07-12 真实撞见:短剧设计上是 9:16 竖屏(手机观看),但 Constitution.
    visual_style.aspect_ratio 此前从没被读过,真实跑出来的成片是 1280×720 横屏。
    aspect_ratio="9:16" 必须让最终交付给 _fit_dialogue 的 w×h 是竖屏(720×1280)。
    """
    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。")]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    async def _write(*, output_path, **_kwargs):
        output_path.write_bytes(b"fake")
        return output_path

    fit_calls = []

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
            lambda talk, clip, w, h: (fit_calls.append((w, h)), clip.write_bytes(b"c")),
        ),
    ):
        await build_frame_manifest_avatar(
            shotlist,
            script,
            _bible(),
            Constitution(visual_style=VisualStyle(aspect_ratio="9:16")),
            run_dir=tmp_path,
        )

    assert fit_calls == [(720, 1280)]


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
async def test_scene_desc_from_config_reaches_keyframe_prompt(tmp_path):
    """SPEC-004 断链#3 端到端接线:config.params['scene_desc_by_id'] 按 shot.scene_id 取切片,
    经主循环拼进关键帧的 local_prompt。验证 config → 循环 → _local_kf_prompt 调用点全程接通。"""
    from hevi.tongjian.schemas import LayerConfig

    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。")]
    )
    shotlist = ShotList(
        shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"], scene_id="书房")]
    )

    edit_kf = AsyncMock(
        side_effect=lambda **kw: (kw["output_path"].write_bytes(b"kf"), kw["output_path"])[1]
    )

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"canon")
        return output_path

    async def _fake_happyhorse(*, image_path, prompt, output_path, duration, resolution):
        output_path.write_bytes(b"talk")
        return output_path

    with (
        patch("hevi.tongjian.scene_render_avatar._edit_keyframe", edit_kf),
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
            shotlist,
            script,
            _bible(),
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(
                model="cloud_avatar",
                params={"scene_desc_by_id": {"书房": "古朴书房,烛光昏黄,静谧"}},
            ),
        )

    local_prompt = edit_kf.await_args.kwargs["local_prompt"]
    assert "古朴书房,烛光昏黄,静谧" in local_prompt


@pytest.mark.asyncio
async def test_shot_space_projection_reaches_keyframe_prompt(tmp_path):
    """SPEC-004 阶段 3 端到端:config.params['shot_space_by_id'] 按 shot.shot_id 取逐镜投影,
    与断链#3 的 scene_desc 一起拼进关键帧 local_prompt(镜头从场事实切视角)。"""
    from hevi.tongjian.schemas import LayerConfig

    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。")]
    )
    shotlist = ShotList(
        shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"], scene_id="书房")]
    )

    edit_kf = AsyncMock(
        side_effect=lambda **kw: (kw["output_path"].write_bytes(b"kf"), kw["output_path"])[1]
    )

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"canon")
        return output_path

    async def _fake_happyhorse(*, image_path, prompt, output_path, duration, resolution):
        output_path.write_bytes(b"talk")
        return output_path

    with (
        patch("hevi.tongjian.scene_render_avatar._edit_keyframe", edit_kf),
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
            shotlist,
            script,
            _bible(),
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(
                model="cloud_avatar",
                params={
                    "scene_desc_by_id": {"书房": "古朴书房,烛光昏黄"},
                    "shot_space_by_id": {"SH001": "C003在案前、面向来客;焦点在C003(主焦点)"},
                },
            ),
        )

    local_prompt = edit_kf.await_args.kwargs["local_prompt"]
    assert "古朴书房,烛光昏黄" in local_prompt  # 断链#3 场景描述
    assert "C003在案前、面向来客" in local_prompt  # 阶段 3 逐镜落位投影
    assert "焦点在C003" in local_prompt  # 阶段 3 焦点投影


async def _run_manifest_with_views(tmp_path, view_map, views_by_id, tag="a"):
    """跑一遍 build_frame_manifest_avatar,patch 掉 _edit_keyframe 捕获 init_image kwarg。
    每次用独立子目录(否则 SH001_kf.png 缓存会让第二次跳过关键帧生成)。"""
    from hevi.tongjian.schemas import LayerConfig

    tmp_path = tmp_path / tag
    tmp_path.mkdir(parents=True, exist_ok=True)

    script = Script(
        lines=[ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。")]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])
    edit_kf = AsyncMock(
        side_effect=lambda **kw: (kw["output_path"].write_bytes(b"kf"), kw["output_path"])[1]
    )

    async def _gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"canon")
        return output_path

    async def _hh(*, image_path, prompt, output_path, duration, resolution):
        output_path.write_bytes(b"talk")
        return output_path

    with (
        patch("hevi.tongjian.scene_render_avatar._edit_keyframe", edit_kf),
        patch("hevi.tongjian.scene_render_avatar.qwen_image_generate", AsyncMock(side_effect=_gen)),
        patch("hevi.tongjian.scene_render_avatar.happyhorse_animate", AsyncMock(side_effect=_hh)),
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
            config=LayerConfig(
                model="cloud_avatar",
                params={"shot_view_by_id": view_map, "subject3d_views_by_id": views_by_id},
            ),
        )
    return edit_kf.await_args.kwargs


@pytest.mark.asyncio
async def test_nonfront_view_routes_keyframe_to_img2img_init_image(tmp_path):
    """SPEC-004 v2:lead 视图=right 且已建 3D 视图 → _edit_keyframe 收到 init_image(img2img)。"""
    kw = await _run_manifest_with_views(
        tmp_path,
        {"SH001": {"C003": "right"}},
        {"C003": {"right": "/fake/c003_right.png"}},
    )
    assert kw["init_image"] is not None
    assert str(kw["init_image"]).endswith("c003_right.png")


@pytest.mark.asyncio
async def test_front_view_keeps_2d_ref_no_init_image(tmp_path):
    """视图=front(或无 3D 视图)→ init_image=None,退回原 IP-Adapter 2D 真照路。"""
    kw = await _run_manifest_with_views(
        tmp_path, {"SH001": {"C003": "front"}}, {"C003": {"right": "/fake/x.png"}}, tag="front"
    )
    assert kw["init_image"] is None
    # 无任何 3D 视图映射时同理
    kw2 = await _run_manifest_with_views(tmp_path, {"SH001": {"C003": "right"}}, {}, tag="noviews")
    assert kw2["init_image"] is None


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
async def test_multi_character_narration_shot_composes_all_canonicals(tmp_path):
    """2026-07-13 真实反馈:i2v/happyhorse 每镜只吃1张参考图,此前多角色同框的旁白/
    场景镜头只锁 shot.characters[0],同框的其他角色完全没有身份锚点。qwen-image-edit
    支持1-3张输入图的多图融合(阿里云文档实测确认)——多角色同框时必须把每个在场
    角色的 canonical 像都传给它,不能仍然只传第一个人的。
    """
    bible = CharacterBible(
        characters=[
            CharacterBibleEntry(character_id="C001", name="王生", appearance="青衫书生"),
            CharacterBibleEntry(character_id="C002", name="道士", appearance="白须道人"),
        ]
    )
    script = Script(lines=[ScriptLine(line_id="LN001", type="narration", text="二人对坐无言。")])
    shotlist = ShotList(
        shots=[
            Shot(
                shot_id="SH001",
                line_ids=["LN001"],
                characters=["C001", "C002"],
                visual_prompt="对坐",
            )
        ]
    )

    edit_calls: list[list] = []

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        edit_calls.append(image_path if isinstance(image_path, list) else [image_path])
        output_path.write_bytes(b"fake-kf")
        return output_path

    async def _write(*, output_path, **_kwargs):
        output_path.write_bytes(b"fake")
        return output_path

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_edit",
            AsyncMock(side_effect=_fake_qwen_edit),
        ),
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
    ):
        await build_frame_manifest_avatar(shotlist, script, bible, Constitution(), run_dir=tmp_path)

    assert len(edit_calls) == 1
    canon_names = {Path(p).name for p in edit_calls[0]}
    assert canon_names == {"canon_C001.png", "canon_C002.png"}


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


@pytest.mark.asyncio
async def test_keyframe_falls_back_to_canonical_when_edit_unavailable(tmp_path):
    """用户 2026-07-15 决定走降级路线(不为 qwen-image-edit 开付费):edit 撞免费额度墙
    (QwenImageError)时,直接用 canonical 像当关键帧,整镜照常出片、不降级空镜。
    验证:(1) 该镜没有降级;(2) 喂给 happyhorse 的关键帧就是 canonical 那张(fallback 复制)。"""
    script = Script(
        lines=[
            ScriptLine(
                line_id="LN001",
                type="dialogue",
                speaker="C003",
                text="请分宗。",
                emotion="决绝",
                visual_hint="智果掷玉珏于阶前",
            )
        ]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        raise QwenImageError("qwen-image-edit 免费额度已用尽:仅使用免费额度模式")

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"CANON-BYTES")  # canonical 像的可识别内容
        return output_path

    kf_bytes_seen: list[bytes] = []

    async def _fake_happyhorse(*, image_path, prompt, output_path, duration, resolution):
        kf_bytes_seen.append(Path(image_path).read_bytes())  # happyhorse 实际拿到的关键帧
        output_path.write_bytes(b"fake-talk")
        return output_path

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
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_dialogue",
            lambda talk, clip, w, h: clip.write_bytes(b"c"),
        ),
    ):
        manifest = await build_frame_manifest_avatar(
            shotlist, script, _bible(), Constitution(), run_dir=tmp_path
        )

    assert not manifest.frames[0].degraded  # 没有因 edit 失败而降级空镜
    assert kf_bytes_seen == [b"CANON-BYTES"]  # happyhorse 拿到的正是 canonical 像


def _one_dialogue_shot():
    script = Script(
        lines=[
            ScriptLine(
                line_id="LN001",
                type="dialogue",
                speaker="C003",
                text="请分宗。",
                emotion="决绝",
                visual_hint="掷玉珏于阶前",
            )
        ]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])
    return script, shotlist


@pytest.mark.asyncio
async def test_local_engine_uses_sdxl_not_cloud(tmp_path):
    """engine="local"(默认):关键帧走本地 sdxl_local + IP-Adapter,不调云端 qwen-image-edit。
    验证本地引擎优先、且拿 canon 当 IP-Adapter 参考(锁脸)。"""
    script, shotlist = _one_dialogue_shot()

    sdxl_calls: list[dict] = []

    async def _fake_sdxl(*, prompt, output_path, width, height, extra, require_gpu):
        sdxl_calls.append({"prompt": prompt, "extra": extra})
        Path(output_path).write_bytes(b"sdxl-kf" * 200)  # >1024B,过 _edit_keyframe 的有效性门槛
        return {"output_path": str(output_path)}

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"fake-canon")
        return output_path

    qwen_edit = AsyncMock()  # 不应被调到
    with (
        patch("hevi.tongjian.scene_render_avatar.sdxl_local_generate", _fake_sdxl),
        patch("hevi.tongjian.scene_render_avatar.qwen_image_edit", qwen_edit),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(side_effect=_fake_qwen_gen),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate",
            AsyncMock(side_effect=_fake_hh),
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

    assert len(sdxl_calls) == 1  # 本地引擎被用
    assert sdxl_calls[0]["extra"].get("ip_adapter_image")  # 拿 canon 锁脸
    qwen_edit.assert_not_awaited()  # 没走云端


@pytest.mark.asyncio
async def test_cloud_engine_skips_local(tmp_path):
    """engine="cloud"(可切换):跳过本地 sdxl_local,直接走云端 qwen-image-edit。
    验证开关生效——本地引擎完全不被调用。"""
    script, shotlist = _one_dialogue_shot()

    sdxl = AsyncMock(side_effect=RuntimeError("本地不该被调用"))

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"cloud-kf")
        return output_path

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"fake-canon")
        return output_path

    with (
        patch("hevi.tongjian.scene_render_avatar.sdxl_local_generate", sdxl),
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
            AsyncMock(side_effect=_fake_hh),
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
            config=LayerConfig(params={"keyframe_engine": "cloud"}),
        )

    sdxl.assert_not_awaited()  # cloud 引擎下本地完全不碰


@pytest.mark.asyncio
async def test_action_shot_uses_kf2v_not_i2v(tmp_path):
    """P3:非对白动作镜(含反应链动词"拔")→ 生成起始帧+结束帧喂 kf2v 插真运动,
    不走 i2v 单帧微动。验证:kf2v 被调(首帧=SH001_kf、尾帧=SH001_kf_end),i2v 没被调。"""
    bible = _bible()  # C003
    script = Script(lines=[ScriptLine(line_id="LN001", type="action", text="张飞拔剑要自刎")])
    shotlist = ShotList(
        shots=[
            Shot(
                shot_id="SH001",
                line_ids=["LN001"],
                characters=["C003"],
                visual_prompt="张飞拔剑自刎",
            )
        ]
    )

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"kf" * 600)  # >1024,过有效性门槛
        return output_path

    async def _fake_qwen_gen(*, output_path, **_k):
        output_path.write_bytes(b"canon")
        return output_path

    kf2v_calls: list[tuple[str, str]] = []

    async def _spy_kf2v(*, first_frame, last_frame, output_path, **_k):
        kf2v_calls.append((Path(first_frame).name, Path(last_frame).name))
        Path(output_path).write_bytes(b"kf2v-vis")
        return output_path

    async def _i2v(*, output_path, **_k):
        output_path.write_bytes(b"i2v")
        return output_path

    i2v_spy = AsyncMock(side_effect=_i2v)

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
            "hevi.tongjian.scene_render_avatar.alibaba_maas_keyframe_generate",
            AsyncMock(side_effect=_spy_kf2v),
        ),
        patch("hevi.tongjian.scene_render_avatar.i2v_animate", i2v_spy),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_silent",
            lambda vis, out, w, h, dur: out.write_bytes(b"c"),
        ),
    ):
        await build_frame_manifest_avatar(
            shotlist,
            script,
            bible,
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(
                params={"non_dialogue_mode": "silent_action", "action_engine": "kf2v"}
            ),
        )

    assert kf2v_calls == [("SH001_kf.png", "SH001_kf_end.png")]  # 首帧+结束帧喂 kf2v
    i2v_spy.assert_not_awaited()  # 动作镜不走 i2v 单帧微动


@pytest.mark.asyncio
async def test_action_engine_i2v_keeps_old_single_frame_path(tmp_path):
    """开关可切回:action_engine="i2v" 时动作镜仍走旧的单帧微动,不碰 kf2v。"""
    bible = _bible()
    script = Script(lines=[ScriptLine(line_id="LN001", type="action", text="张飞拔剑要自刎")])
    shotlist = ShotList(
        shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"], visual_prompt="拔剑")]
    )

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"kf" * 600)
        return output_path

    async def _fake_qwen_gen(*, output_path, **_k):
        output_path.write_bytes(b"canon")
        return output_path

    kf2v = AsyncMock(side_effect=_fake_kf2v)

    async def _i2v(*, output_path, **_k):
        output_path.write_bytes(b"i2v")
        return output_path

    i2v_spy = AsyncMock(side_effect=_i2v)

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_edit",
            AsyncMock(side_effect=_fake_qwen_edit),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(side_effect=_fake_qwen_gen),
        ),
        patch("hevi.tongjian.scene_render_avatar.alibaba_maas_keyframe_generate", kf2v),
        patch("hevi.tongjian.scene_render_avatar.i2v_animate", i2v_spy),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_silent",
            lambda vis, out, w, h, dur: out.write_bytes(b"c"),
        ),
    ):
        await build_frame_manifest_avatar(
            shotlist,
            script,
            bible,
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(
                params={"non_dialogue_mode": "silent_action", "action_engine": "i2v"}
            ),
        )

    kf2v.assert_not_awaited()  # i2v 开关下不碰 kf2v
    i2v_spy.assert_awaited()  # 走旧单帧微动


# ── INC-001 §B 动作弧 action_beats ──────────────────────────────────────────


def test_infer_action_phases_empty_returns_blanks():
    """无 action_beats → 三阶段全空,调用方据此退回现状(§C 未完成态 + LLM 拆完成态)。"""
    from hevi.tongjian.scene_render_avatar import _infer_action_phases

    assert _infer_action_phases([]) == ("", "", "")
    assert _infer_action_phases(["  ", ""]) == ("", "", "")


def test_infer_action_phases_single_beat_same_all():
    """只有一拍 → trigger/peak/aftermath 同拍。"""
    from hevi.tongjian.scene_render_avatar import _infer_action_phases

    assert _infer_action_phases(["张飞拔剑"]) == ("张飞拔剑", "张飞拔剑", "张飞拔剑")


def test_infer_action_phases_picks_ends_and_densest_middle_peak():
    """首拍=trigger、末拍=aftermath、峰值=中间拍里动作动词最密的一拍。"""
    from hevi.tongjian.scene_render_avatar import _infer_action_phases

    trigger, peak, aftermath = _infer_action_phases(
        [
            "张飞猛地抽剑架上脖颈",  # trigger
            "两人静静站着",  # 中间-弱(0 动作词)
            "刘备一把攥住剑身猛地扑上夺剑",  # 中间-强(一把/猛地/扑/夺)→ 峰值
            "宝剑坠地,刘备紧抱住张飞",  # aftermath
        ]
    )
    assert trigger == "张飞猛地抽剑架上脖颈"
    assert aftermath == "宝剑坠地,刘备紧抱住张飞"
    assert peak == "刘备一把攥住剑身猛地扑上夺剑"


def test_local_kf_prompt_injects_scene_space_before_appearance():
    """SPEC-004 断链#3:场景空间描述(DesignScene 环境/光照/氛围)必须拼进关键帧 prompt,
    且按 §F.1 口径排在相貌之前(风格→空间→相貌→情绪→动作)。此前 DesignScene 空间描述从
    桥接层到 L6 全程零消费,画面里根本没有场景。"""
    from hevi.tongjian.scene_render_avatar import _local_kf_prompt

    p = _local_kf_prompt("水墨风", "老者布衣", "肃穆", "拱手", scene_space="昏暗客栈,烛光,压抑")
    assert "昏暗客栈,烛光,压抑" in p
    assert p.index("昏暗客栈") < p.index("老者布衣")  # 空间在相貌前


def test_local_kf_prompt_empty_scene_space_is_backward_compatible():
    """空 scene_space(如 tongjian 管线不传该字段)→ 行为完全不变。"""
    from hevi.tongjian.scene_render_avatar import _local_kf_prompt

    assert _local_kf_prompt("水墨风", "老者布衣", "肃穆", "拱手").startswith("水墨风,老者布衣,肃穆")


@pytest.mark.asyncio
async def test_action_arc_default_2point_uses_aftermath_beat(tmp_path):
    """默认 2point:有 action_beats 的动作镜 → 单段 kf2v(首帧→尾帧),尾帧关键帧直接用
    aftermath 拍文本(省掉 _action_end_state LLM 拆解),不产生 peak 段。"""
    bible = _bible()  # C003
    script = Script(lines=[ScriptLine(line_id="LN001", type="action", text="张飞拔剑要自刎")])
    shotlist = ShotList(
        shots=[
            Shot(
                shot_id="SH001",
                line_ids=["LN001"],
                characters=["C003"],
                visual_prompt="张飞拔剑自刎",
                action_beats=["张飞猛地抽剑架颈", "刘备扑上攥住剑身", "宝剑坠地刘备紧抱住张飞"],
            )
        ]
    )

    edit_instructions: list[str] = []

    async def _spy_qwen_edit(*, image_path, instruction, output_path):
        edit_instructions.append(instruction)
        output_path.write_bytes(b"kf" * 600)
        return output_path

    async def _fake_qwen_gen(*, output_path, **_k):
        output_path.write_bytes(b"canon")
        return output_path

    kf2v_calls: list[tuple[str, str]] = []

    async def _spy_kf2v(*, first_frame, last_frame, output_path, **_k):
        kf2v_calls.append((Path(first_frame).name, Path(last_frame).name))
        Path(output_path).write_bytes(b"kf2v-vis")
        return output_path

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_edit",
            AsyncMock(side_effect=_spy_qwen_edit),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(side_effect=_fake_qwen_gen),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.alibaba_maas_keyframe_generate",
            AsyncMock(side_effect=_spy_kf2v),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_silent",
            lambda vis, out, w, h, dur: out.write_bytes(b"c"),
        ),
    ):
        await build_frame_manifest_avatar(
            shotlist,
            script,
            bible,
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(
                params={"non_dialogue_mode": "silent_action", "action_engine": "kf2v"}
            ),
        )

    assert kf2v_calls == [("SH001_kf.png", "SH001_kf_end.png")]  # 单段,无 peak
    # 尾帧关键帧用 aftermath 拍文本,不是 LLM 退化的"(动作已完成、结果态)"
    end_instrs = [i for i in edit_instructions if "宝剑坠地刘备紧抱住张飞" in i]
    assert end_instrs, "尾帧关键帧未使用 aftermath 拍文本"
    assert not any("动作已完成、结果态" in i for i in edit_instructions)


@pytest.mark.asyncio
async def test_action_arc_3point_inserts_peak_segment(tmp_path):
    """action_arc="3point":有独立 peak 拍时,首帧→peak→尾帧两段 kf2v 拼接(成本翻倍)。"""
    bible = _bible()
    script = Script(lines=[ScriptLine(line_id="LN001", type="action", text="张飞拔剑要自刎")])
    shotlist = ShotList(
        shots=[
            Shot(
                shot_id="SH001",
                line_ids=["LN001"],
                characters=["C003"],
                visual_prompt="张飞拔剑自刎",
                action_beats=["张飞猛地抽剑架颈", "刘备一把扑上攥住剑身", "宝剑坠地刘备紧抱住张飞"],
            )
        ]
    )

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"kf" * 600)
        return output_path

    async def _fake_qwen_gen(*, output_path, **_k):
        output_path.write_bytes(b"canon")
        return output_path

    kf2v_calls: list[tuple[str, str]] = []

    async def _spy_kf2v(*, first_frame, last_frame, output_path, **_k):
        kf2v_calls.append((Path(first_frame).name, Path(last_frame).name))
        Path(output_path).write_bytes(b"kf2v-vis")
        return output_path

    concat_calls: list[int] = []

    def _spy_concat(clips, out):
        concat_calls.append(len(clips))
        Path(out).write_bytes(b"concat")

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
            "hevi.tongjian.scene_render_avatar.alibaba_maas_keyframe_generate",
            AsyncMock(side_effect=_spy_kf2v),
        ),
        patch("hevi.tongjian.scene_render_avatar._concat_clips", _spy_concat),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_silent",
            lambda vis, out, w, h, dur: out.write_bytes(b"c"),
        ),
    ):
        await build_frame_manifest_avatar(
            shotlist,
            script,
            bible,
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(
                params={
                    "non_dialogue_mode": "silent_action",
                    "action_engine": "kf2v",
                    "action_arc": "3point",
                }
            ),
        )

    assert kf2v_calls == [
        ("SH001_kf.png", "SH001_kf_peak.png"),
        ("SH001_kf_peak.png", "SH001_kf_end.png"),
    ]
    assert concat_calls == [2]  # 两段拼接


# ── INC-001 §H 视线(target→eyeline) + §J 相邻镜头连续性 ──────────────────────


def _bible2() -> CharacterBible:
    return CharacterBible(
        characters=[
            CharacterBibleEntry(character_id="C003", name="智果", appearance="清瘦谋士"),
            CharacterBibleEntry(character_id="C005", name="赵襄子", appearance="华服君主"),
        ]
    )


@pytest.mark.asyncio
async def test_dialogue_keyframe_includes_eyeline_toward_target(tmp_path):
    """INC-001 §H:对白行带 target → 关键帧 instruction 里说话者"目光看向"受话者(赵襄子)。"""
    script = Script(
        lines=[
            ScriptLine(
                line_id="LN001",
                type="dialogue",
                speaker="C003",
                text="请分宗。",
                emotion="决绝",
                target="C005",
            )
        ]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"kf" * 600)
        return output_path

    async def _fake_qwen_gen(*, output_path, **_k):
        output_path.write_bytes(b"canon")
        return output_path

    async def _fake_happyhorse(*, image_path, prompt, output_path, duration, resolution):
        output_path.write_bytes(b"talk")
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
            shotlist, script, _bible2(), Constitution(), run_dir=tmp_path
        )

    assert "目光看向赵襄子" in qwen_edit.await_args.kwargs["instruction"]


@pytest.mark.asyncio
async def test_consecutive_same_scene_shots_get_continuity_hint(tmp_path):
    """INC-001 §J:同场景连续镜头(有共同人物)→ 第 2 镜关键帧带"保持朝向/轴线稳定"约束;
    首镜不带。"""
    script = Script(
        lines=[
            ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="其一。"),
            ScriptLine(line_id="LN002", type="dialogue", speaker="C003", text="其二。"),
        ]
    )
    shotlist = ShotList(
        shots=[
            Shot(shot_id="SH001", line_ids=["LN001"], scene_id="宫殿", characters=["C003"]),
            Shot(shot_id="SH002", line_ids=["LN002"], scene_id="宫殿", characters=["C003"]),
        ]
    )

    instrs: list[str] = []

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        instrs.append(instruction)
        output_path.write_bytes(b"kf" * 600)
        return output_path

    async def _fake_qwen_gen(*, output_path, **_k):
        output_path.write_bytes(b"canon")
        return output_path

    async def _fake_happyhorse(*, image_path, prompt, output_path, duration, resolution):
        output_path.write_bytes(b"talk")
        return output_path

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

    assert len(instrs) == 2
    assert "避免跳轴" not in instrs[0]  # 首镜无上镜可承接
    assert "避免跳轴" in instrs[1]  # 第 2 镜同场景连续 → 稳轴线


@pytest.mark.asyncio
async def test_action_end_state_runs_llm_path_no_nameerror():
    """回归:scene_render_avatar 从前漏 import asyncio,_action_end_state 的 asyncio.to_thread
    一直 NameError → 静默退化。修复后 LLM 路真实跑通,返回 LLM 结果而非退化文案。"""
    from hevi.tongjian.scene_render_avatar import _action_end_state

    def _fake_llm(*, messages, **_kw):
        return {"content": "宝剑坠地,刘备紧抱住张飞"}

    out = await _action_end_state("张飞拔剑,刘备夺剑", _fake_llm)
    assert out == "宝剑坠地,刘备紧抱住张飞"  # LLM 结果,不是"(动作已完成、结果态)"退化
    # llm=None 仍安全退化(不触发 asyncio)
    fallback = await _action_end_state("张飞拔剑", None)
    assert "动作已完成、结果态" in fallback


# ── INC-001 §E 导演命令摘要(必须/优先动态分级) + §J 完整版相邻镜上下文 ──────────


def test_director_command_summary_levels_and_risk_promotion():
    """§E:对视(eyeline)+同场景连续(axis)+未完成态 → 首帧全进「必须」级,承接/过渡进「优先」。"""
    from hevi.tongjian.scene_render_avatar import _director_command_summary

    s = _director_command_summary(
        frame_role="first",
        incomplete="，动作未完成态",
        eyeline="，目光看向赵襄子",
        axis=True,
        carry="承接上一镜收束态",
        lead_out="收束到可过渡下一镜",
    )
    assert s.startswith("。必须:")
    assert "避免跳轴" in s  # axis 必守
    assert "说话者目光看向赵襄子" in s  # eyeline 必守
    assert "动作未完成态" in s  # §C 必守
    assert "优先:" in s and "承接上一镜收束态" in s


def test_director_command_summary_differs_by_frame_role():
    """§E:尾帧(aftermath)不强加未完成态、弱化视线 → 与首帧摘要不同。"""
    from hevi.tongjian.scene_render_avatar import _director_command_summary

    kw = {
        "incomplete": "，动作未完成态",
        "eyeline": "，目光看向赵襄子",
        "axis": True,
        "carry": "",
        "lead_out": "",
    }
    first = _director_command_summary(frame_role="first", **kw)
    after = _director_command_summary(frame_role="aftermath", **kw)
    assert "目光看向赵襄子" in first and "目光看向赵襄子" not in after  # 视线仅起势帧必守
    assert "动作未完成态" in first and "动作未完成态" not in after  # 未完成态尾帧不强加
    assert "避免跳轴" in after  # 轴线两帧都守
    assert first != after


def test_director_command_summary_empty_when_no_constraints():
    from hevi.tongjian.scene_render_avatar import _director_command_summary

    assert (
        _director_command_summary(
            frame_role="first", incomplete="", eyeline="", axis=False, carry="", lead_out=""
        )
        == ""
    )


def test_adjacent_context_uses_beats_edges_same_scene_only():
    """§J 完整版:相邻镜同场景 → 用相邻镜 action_beats 的收束/触发拍给承接/过渡;换场不给。"""
    from hevi.tongjian.scene_render_avatar import _adjacent_context

    shots = [
        Shot(shot_id="A", scene_id="宫殿", action_beats=["起", "承", "甲收束"]),
        Shot(shot_id="B", scene_id="宫殿", action_beats=["乙触发", "乙峰"]),
        Shot(shot_id="C", scene_id="郊野", visual_prompt="换场"),  # 不同场景
    ]
    carry, lead_out = _adjacent_context(shots, 1)  # B:上镜A同场景,下镜C换场
    assert "甲收束" in carry  # 承接上一镜(A)的收束拍
    assert lead_out == ""  # 下一镜(C)换场 → 无过渡

    carry0, lead0 = _adjacent_context(shots, 0)  # A:无上镜,下镜B同场景
    assert carry0 == ""  # 首镜无承接
    assert "乙触发" in lead0  # 过渡到下一镜(B)的触发拍


# ── INC-001 §K 可观察性:debug_context + quality_checks ───────────────────────


@pytest.mark.asyncio
async def test_shot_frame_carries_debug_context_and_quality_checks(tmp_path):
    """§K:动作镜(带 action_beats)生成的 ShotFrame 带 decision_trail——动作弧阶段 + 各项
    质量检查(未完成态/kf2v/有无 beats)。"""
    bible = _bible()  # C003
    script = Script(lines=[ScriptLine(line_id="LN001", type="action", text="张飞拔剑要自刎")])
    shotlist = ShotList(
        shots=[
            Shot(
                shot_id="SH001",
                line_ids=["LN001"],
                characters=["C003"],
                visual_prompt="张飞拔剑自刎",
                action_beats=["张飞猛地抽剑架颈", "刘备扑上夺剑", "宝剑坠地紧抱"],
            )
        ]
    )

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        output_path.write_bytes(b"kf" * 600)
        return output_path

    async def _fake_qwen_gen(*, output_path, **_k):
        output_path.write_bytes(b"canon")
        return output_path

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
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_silent",
            lambda vis, out, w, h, dur: out.write_bytes(b"c"),
        ),
    ):
        manifest = await build_frame_manifest_avatar(
            shotlist,
            script,
            bible,
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(
                params={"non_dialogue_mode": "silent_action", "action_engine": "kf2v"}
            ),
        )

    dctx = manifest.frames[0].debug_context
    qc = manifest.frames[0].quality_checks
    assert dctx["phases"]["trigger"] == "张飞猛地抽剑架颈"
    assert dctx["phases"]["aftermath"] == "宝剑坠地紧抱"
    assert dctx["frame_consumes"]["first"] == "trigger"  # 首帧抓 trigger
    assert dctx["frame_consumes"]["last"] == "aftermath"  # 尾帧抓 aftermath
    assert qc["has_action_beats"] is True
    assert qc["kf2v_action_arc"] is True  # 走了 kf2v 真动作弧
    assert qc["incomplete_state_applied"] is True  # 含"拔/猛地"反应链 → §C
