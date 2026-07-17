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
    _compose_layout_base,
    _compose_pose_control,
    _layout_col,
    _observe_end_state,
    _parse_blocking_positions,
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
async def test_director_command_reaches_local_prompt_not_only_cloud_instruction(tmp_path):
    """F-0 回归(2026-07-17 审计):INC-001 §E 的导演命令摘要(§C 未完成态/§H eyeline/§J 轴线)
    此前**只拼进云端 edit 的 instruction**,而 `_local_kf_prompt` 的签名里根本没有这个参数——
    默认引擎恰恰是 local。等于这四节的全部约束只在 GPU 掉线走云端兜底时才生效,正常成功路径
    上一个字都不进 prompt。更糟的是 §K 的 quality_checks 按 `bool(_eyeline)`(字符串构造成功
    与否)报 `eyeline_applied: True`,于是全是假阳性,这个断链半个月没被任何验收抓到。

    这里钉的是**两条引擎路都得给**:instruction(云端)和 local_prompt(本地)必须同时带上
    eyeline。用 SH002 而非 SH001,以便同时触发 §J 同场景轴线约束。"""
    script = Script(
        lines=[
            ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。"),
            ScriptLine(
                line_id="LN002",
                type="dialogue",
                speaker="C003",
                text="您三思。",
                emotion="决绝",
                target="C004",  # §H:说话者目光看向受话者
            ),
        ]
    )
    shotlist = ShotList(
        shots=[
            Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"], scene_id="堂上"),
            # 与上一镜同场景 + 有共同在场角色 → §J 轴线必守
            Shot(shot_id="SH002", line_ids=["LN002"], characters=["C003"], scene_id="堂上"),
        ]
    )
    bible = CharacterBible(
        characters=[
            CharacterBibleEntry(character_id="C003", name="智果", appearance="清瘦谋士"),
            CharacterBibleEntry(character_id="C004", name="智宣子", appearance="威严家主"),
        ]
    )

    edit_kf = AsyncMock(
        side_effect=lambda **kw: (kw["output_path"].write_bytes(b"kf"), "sdxl_ip_adapter")[1]
    )

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"canon")
        return output_path

    with (
        patch("hevi.tongjian.scene_render_avatar._edit_keyframe", edit_kf),
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
        manifest = await build_frame_manifest_avatar(
            shotlist, script, bible, Constitution(), run_dir=tmp_path
        )

    # SH002 那一镜的关键帧调用(第二次 await)
    kw = edit_kf.await_args_list[1].kwargs
    assert "目光看向智宣子" in kw["instruction"]  # 云端路(此前就有)
    assert "目光看向智宣子" in kw["local_prompt"]  # 本地路 = 默认路(此前完全缺失)
    assert "轴线" in kw["local_prompt"]  # §J 同场景连续 → 轴线必守也得进本地路
    assert "必须:" in kw["local_prompt"]  # §E 的必须/优先分级结构保留

    # §K 可观察性说真话:关键帧真生成了(非 canon 复制)→ eyeline 确实落地了。
    checks = manifest.frames[1].quality_checks
    assert checks["eyeline_applied"] is True
    assert checks["continuity_applied"] is True
    assert checks["keyframe_degraded"] is False


@pytest.mark.asyncio
async def test_wardrobe_negative_reaches_sdxl_keyframe_in_english(tmp_path):
    """缺口#4 回归(2026-07-17 审计):压"奇幻铠甲/尖角肩甲"的那组强负面词此前**只在参考图
    阶段生效**(director_pipeline._PORTRAIT_NEGATIVE),关键帧走 sdxl 的 _DEFAULT_NEGATIVE,
    里面一个铠甲词都没有 → "参考图是干净定妆照、一进关键帧就长出圣斗士肩甲"。

    钉两点:(1) 服饰负面词确实到了 sdxl 的 negative_prompt;(2) **必须是英文**——
    sdxl_local_service 只翻译正向 prompt(:186),负面词原样透传(:195),base SDXL 不认中文,
    照抄中文的 _PORTRAIT_NEGATIVE 会是个无声空操作。同时验证调用方自带的负面词不被顶掉。"""
    from hevi.image.sdxl_local_service import _has_chinese

    script, shotlist = _one_dialogue_shot()
    shotlist.shots[0].negative_prompt = "caller-supplied-negative"

    sdxl = AsyncMock(
        side_effect=lambda **kw: kw["output_path"].write_bytes(b"x" * 2048)  # >1024 才算成功
    )
    with (
        patch("hevi.tongjian.scene_render_avatar.sdxl_local_generate", sdxl),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(
                side_effect=lambda **kw: (
                    kw["output_path"].write_bytes(b"canon") or kw["output_path"]
                )
            ),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate", AsyncMock(side_effect=_fake_hh)
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

    neg = sdxl.await_args.kwargs["negative_prompt"]
    assert "spiked pauldrons" in neg  # 服饰负面词到了关键帧
    assert "fantasy armor" in neg
    assert not _has_chinese(neg)  # 中文负面词对 base SDXL 是空操作,必须英文
    assert "caller-supplied-negative" in neg  # 调用方自带的负面词没被顶掉


@pytest.mark.asyncio
async def test_quality_checks_report_false_when_keyframe_degraded_to_canon(tmp_path):
    """F-0 的另一半:关键帧降级成定妆照时,§K 不许再报 eyeline/连续性"已应用"。

    旧判据是 `bool(_eyeline)`——只要那个字符串构造出来了就报 True,哪怕实际用的关键帧是抄的
    定妆照(导演命令一个字都没落地)。这正是断链能长期隐身的原因:可观察性在替它打掩护。"""
    script = Script(
        lines=[
            ScriptLine(
                line_id="LN001",
                type="dialogue",
                speaker="C003",
                text="请分宗。",
                target="C004",
            ),
        ]
    )
    shotlist = ShotList(shots=[Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"])])
    bible = CharacterBible(
        characters=[
            CharacterBibleEntry(character_id="C003", name="智果", appearance="清瘦谋士"),
            CharacterBibleEntry(character_id="C004", name="智宣子", appearance="威严家主"),
        ]
    )

    async def _fake_qwen_edit(*, image_path, instruction, output_path):
        raise QwenImageError("qwen-image-edit 免费额度已用尽")  # 云端墙

    async def _fake_qwen_gen(*, prompt, output_path, size, seed=None):
        output_path.write_bytes(b"CANON-BYTES")
        return output_path

    with (
        # 本地 sdxl 也不可用(GPU 掉总线/争用)→ 两条腿全断 → 抄定妆照
        patch(
            "hevi.tongjian.scene_render_avatar.sdxl_local_generate",
            AsyncMock(side_effect=RuntimeError("GPU fell off the bus")),
        ),
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
        manifest = await build_frame_manifest_avatar(
            shotlist, script, bible, Constitution(), run_dir=tmp_path
        )

    checks = manifest.frames[0].quality_checks
    assert checks["keyframe_degraded"] is True
    assert checks["eyeline_applied"] is False  # 构造出来了 ≠ 落地了
    assert manifest.frames[0].degraded


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

    2026-07-17 修订:出片照旧(clip 仍在,不退空镜),但**这一镜必须被标成 degraded**。旧版
    断言的是 `not degraded`,把"抄定妆照"当成了无代价的兜底——实证代价极大:一次真实产集
    20 镜里 14 镜的关键帧是定妆照的字节级复制品,成片退化成"大头念台词",而 verdict 三项检查
    对这种镜全过(画面不黑;身份分满分——它就是那张 canon 本人),于是静默交付。degraded 的
    既有语义就是"走了降级链、非首选路径产出",canon 复制正属此列 → 进 verdict 的 rewrite 闸。

    验证:(1) 喂给 happyhorse 的关键帧就是 canonical 那张(fallback 复制);(2) 该镜出了片
    (clip_path 非空,没退空镜);(3) 该镜被标 degraded + 写明原因;(4) §K quality_checks 不撒谎。"""
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

    frame = manifest.frames[0]
    assert kf_bytes_seen == [b"CANON-BYTES"]  # happyhorse 拿到的正是 canonical 像
    assert frame.clip_path  # 仍然出片,没退空镜(这条是 2026-07-15 决定的兜底行为,不变)
    assert frame.degraded  # 但抄定妆照 = 走了降级链,必须标出来送 verdict 返工
    assert "定妆照" in frame.degrade_reason
    assert frame.quality_checks["keyframe_degraded"] is True
    assert frame.debug_context["keyframe_source"] == "canon_copy"


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

    async def _fake_sdxl(*, prompt, output_path, width, height, extra, require_gpu, **_):
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


# ── Gap 1 阶段1:多角色走位几何底图 ─────────────────────────────────────────────


def test_layout_col_keyword_and_spread():
    """走位文本 → 画布水平中心比例。命中 左/中/右 用词表;没命中按顺序均匀铺开。"""
    assert _layout_col("阶下左侧", 0, 2) == 0.22
    assert _layout_col("画面右方", 1, 2) == 0.78
    assert _layout_col("居中而立", 0, 1) == 0.5
    # 没命中方位词 → 均匀铺开(2 人 → 1/3, 2/3)
    assert _layout_col("", 0, 2) == pytest.approx(1 / 3)
    assert _layout_col("", 1, 2) == pytest.approx(2 / 3)


def test_parse_blocking_positions_maps_names_to_cids():
    """ "角色名:位置" → {cid: 位置文本}。blocking 用显示名,present 是 cid,按 name_by_id 对齐。"""
    blocking = ["张飞:阶下左侧,面向刘备", "刘备:居中端坐", "旁人:角落"]
    present = ["C_张飞", "C_刘备"]
    name_by_id = {"C_张飞": "张飞", "C_刘备": "刘备"}
    got = _parse_blocking_positions(blocking, present, name_by_id)
    assert got == {"C_张飞": "阶下左侧,面向刘备", "C_刘备": "居中端坐"}  # 旁人不在 present,丢弃


def _fake_subject3d_view(path, fill=(60, 90, 160)) -> None:
    """造一张 Subject3D 风格的视图:近白底(251,251,252)+ 中间一个纯色人形块,无 alpha。"""
    from PIL import Image

    im = Image.new("RGB", (256, 256), (251, 251, 252))
    for y in range(40, 230):
        for x in range(90, 166):
            im.putpixel((x, y), fill)
    im.save(path)


def test_compose_layout_base_knocks_out_bg_and_positions(tmp_path):
    """核心几何底图:≥2 张视图按走位落位合成。验证 (1) 近白底被抠掉(灰画布透出);
    (2) 左侧角色的人形块落在画布左半,右侧角色落在右半。纯 PIL,零 GPU。"""
    from PIL import Image

    va, vb = tmp_path / "a.png", tmp_path / "b.png"
    _fake_subject3d_view(va, fill=(200, 40, 40))  # 红:左侧角色
    _fake_subject3d_view(vb, fill=(40, 40, 200))  # 蓝:右侧角色
    out = _compose_layout_base(
        present=["A", "B"],
        view_path_by_cid={"A": va, "B": vb},
        pos_desc_by_cid={"A": "左侧", "B": "右侧"},
        size=(1280, 720),
        out_path=tmp_path / "layout.png",
    )
    assert out is not None and out.exists()
    canvas = Image.open(out).convert("RGB")
    w, h = canvas.size
    assert (w, h) == (1280, 720)

    # 近白底被抠掉 → 画布该处是中性灰(128),不是白;上方中带(人形只占 85% 高、脚底贴底,
    # 顶部一条是纯背景)取样。
    assert canvas.getpixel((w // 2, 8))[0] < 200  # 灰,不是白底残留

    # 红色人形块的重心在左半,蓝色在右半:按列扫描找每种颜色的平均 x。
    def _mean_x(target):
        xs = [
            x
            for x in range(0, w, 4)
            for y in range(0, h, 8)
            if _close(canvas.getpixel((x, y)), target)
        ]
        return sum(xs) / len(xs) if xs else None

    red_x = _mean_x((200, 40, 40))
    blue_x = _mean_x((40, 40, 200))
    assert red_x is not None and blue_x is not None
    assert red_x < w / 2 < blue_x  # 红在左、蓝在右 = 走位落地


def _close(px, target, tol=60) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(px, target, strict=False))


def test_compose_layout_base_none_when_fewer_than_two_views(tmp_path):
    """只有 1 张视图 → None(单角色走 SPEC-004 单 lead 路,不需要合成)。"""
    va = tmp_path / "a.png"
    _fake_subject3d_view(va)
    out = _compose_layout_base(
        present=["A", "B"],
        view_path_by_cid={"A": va},  # B 无视图
        pos_desc_by_cid={},
        size=(1280, 720),
        out_path=tmp_path / "layout.png",
    )
    assert out is None


@pytest.mark.asyncio
async def test_multichar_shot_feeds_layout_base_as_img2img_init(tmp_path):
    """端到端接线:多角色同框镜,当每个在场角色都有非正面 Subject3D 视图时,走位几何底图被合成
    并作为 init_image 传给关键帧生成(→ 触发 img2img 几何路)。这是"多角色走位零覆盖"的补齐。"""
    # 两个非对白角色同框(action_beats 触发 vis 路)
    script = Script(
        lines=[ScriptLine(line_id="LN001", type="narration", speaker="NARRATOR", text="二人对峙。")]
    )
    shot = Shot(
        shot_id="SH001",
        line_ids=["LN001"],
        characters=["C_张飞", "C_刘备"],
        scene_id="堂上",
        blocking=["张飞:左侧,面向刘备", "刘备:右侧"],
    )
    shotlist = ShotList(shots=[shot])
    bible = CharacterBible(
        characters=[
            CharacterBibleEntry(character_id="C_张飞", name="张飞", appearance="豹头环眼"),
            CharacterBibleEntry(character_id="C_刘备", name="刘备", appearance="双耳垂肩"),
        ]
    )
    # 每个角色备一张非正面 Subject3D 视图
    va, vb = tmp_path / "zf_left.png", tmp_path / "lb_right.png"
    _fake_subject3d_view(va, fill=(200, 40, 40))
    _fake_subject3d_view(vb, fill=(40, 40, 200))

    seen_init: list = []

    async def _spy_sdxl(**kw):
        seen_init.append(kw.get("extra", {}).get("init_image"))
        kw["output_path"].write_bytes(b"x" * 2048)

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.sdxl_local_generate",
            AsyncMock(side_effect=_spy_sdxl),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(
                side_effect=lambda **kw: (
                    kw["output_path"].write_bytes(b"canon") or kw["output_path"]
                )
            ),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.i2v_animate",
            AsyncMock(
                side_effect=lambda **kw: kw["output_path"].write_bytes(b"vis") or kw["output_path"]
            ),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_silent",
            lambda vis, out, w, h, duration: out.write_bytes(b"c"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_narration",
            lambda vis, audio, out, w, h: out.write_bytes(b"c"),
        ),
    ):
        manifest = await build_frame_manifest_avatar(
            shotlist,
            script,
            bible,
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(
                model="cloud_avatar",
                params={
                    "keyframe_engine": "local",
                    "non_dialogue_mode": "silent_action",  # 纯静默,避开旁白 provider
                    "action_engine": "i2v",  # 不走 kf2v,收窄到关键帧一次生成
                    "shot_view_by_id": {"SH001": {"C_张飞": "left", "C_刘备": "right"}},
                    "subject3d_views_by_id": {
                        "C_张飞": {"left": str(va)},
                        "C_刘备": {"right": str(vb)},
                    },
                },
            ),
        )

    # 关键帧生成收到的 init_image 就是合成出来的走位底图
    layout = tmp_path / "SH001_layout.png"
    assert layout.exists()  # 底图真的合成了
    assert str(layout) in seen_init  # 且作为 img2img init 传给了 sdxl
    assert manifest.frames[0].debug_context["layout_base"] is True


# ── Gap 2:观察态注入(镜间连贯) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observe_end_state_returns_vlm_description(tmp_path):
    """VLM 看真实末帧 → 一句停留态。抽帧走 mock,验证 VLM 拿到的是末帧图 + 返回被清洗。"""
    clip = tmp_path / "SH001_clip.mp4"
    clip.write_bytes(b"fake-clip")
    seen_images: list = []

    async def _fake_vlm(*, messages, image_paths, max_tokens):
        seen_images.extend(image_paths)
        return {"content": '"张飞已收刀入鞘、立于画面左侧、面向右方"'}

    with patch(
        "hevi.tongjian.scene_render_avatar._extract_last_frame",
        lambda clip, out: out.write_bytes(b"endframe"),
    ):
        got = await _observe_end_state(clip, _fake_vlm, tmp_path / "obs.png")

    assert got == "张飞已收刀入鞘、立于画面左侧、面向右方"  # 引号被清掉
    assert seen_images == [str(tmp_path / "obs.png")]  # VLM 拿到的是抽出的末帧


@pytest.mark.asyncio
async def test_observe_end_state_falls_back_when_no_vlm(tmp_path):
    """vlm=None(取不到模型)→ 返回 ""(调用方退回计划态 _carry,不阻断)。"""
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    assert await _observe_end_state(clip, None, tmp_path / "o.png") == ""


@pytest.mark.asyncio
async def test_second_shot_carry_uses_observed_end_state_of_first(tmp_path):
    """端到端:同场景两连镜,第二镜的承接锚来自 VLM 观察第一镜真实末帧,而非剧本计划态文本。
    _adjacent_context 的 docstring 承诺过"实际末帧覆盖起始态由观察态另行处理",此前没实现。"""
    script = Script(
        lines=[
            ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。"),
            ScriptLine(line_id="LN002", type="dialogue", speaker="C003", text="您三思。"),
        ]
    )
    shotlist = ShotList(
        shots=[
            Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"], scene_id="堂上"),
            Shot(shot_id="SH002", line_ids=["LN002"], characters=["C003"], scene_id="堂上"),
        ]
    )

    async def _fake_vlm(*, messages, image_paths, max_tokens):
        return {"content": "谋士已起身、立于画面右侧、面向左方"}

    edit_kf = AsyncMock(
        side_effect=lambda **kw: (kw["output_path"].write_bytes(b"kf"), "sdxl_ip_adapter")[1]
    )

    with (
        patch("hevi.tongjian.scene_render_avatar._edit_keyframe", edit_kf),
        patch(
            "hevi.tongjian.scene_render_avatar._resolve_vlm",
            lambda: _fake_vlm,
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(
                side_effect=lambda **kw: kw["output_path"].write_bytes(b"c") or kw["output_path"]
            ),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate", AsyncMock(side_effect=_fake_hh)
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_frame",
            lambda clip, out: out.write_bytes(b"f"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._extract_last_frame",
            lambda clip, out: out.write_bytes(b"end"),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar._fit_dialogue",
            lambda talk, clip, w, h: clip.write_bytes(b"c"),
        ),
    ):
        manifest = await build_frame_manifest_avatar(
            shotlist, script, _bible(), Constitution(), run_dir=tmp_path
        )

    # 第一镜无上文,observed_carry 空;第二镜承接锚来自 VLM 观察
    assert manifest.frames[0].debug_context["observed_carry"] == ""
    assert (
        manifest.frames[1].debug_context["observed_carry"] == "谋士已起身、立于画面右侧、面向左方"
    )
    # 且该观察态真的进了第二镜的关键帧 prompt(命令摘要 → local_prompt,承 Gap F-0)
    sh002_kw = edit_kf.await_args_list[1].kwargs
    assert "谋士已起身" in sh002_kw["local_prompt"]


@pytest.mark.asyncio
async def test_continuity_observation_off_keeps_plan_state(tmp_path):
    """observe_continuity=False → 不调 VLM,承接锚退回计划态(observed_carry 空)。"""
    script = Script(
        lines=[
            ScriptLine(line_id="LN001", type="dialogue", speaker="C003", text="请分宗。"),
            ScriptLine(line_id="LN002", type="dialogue", speaker="C003", text="您三思。"),
        ]
    )
    shotlist = ShotList(
        shots=[
            Shot(shot_id="SH001", line_ids=["LN001"], characters=["C003"], scene_id="堂上"),
            Shot(shot_id="SH002", line_ids=["LN002"], characters=["C003"], scene_id="堂上"),
        ]
    )
    # 给上一镜一个 visual_prompt,让 _adjacent_context 的计划态 carry 非空(验证关掉观察后它仍在)
    shotlist.shots[0].visual_prompt = "谋士拱手而立"
    vlm_called: list = []

    def _spy_resolve_vlm():
        vlm_called.append(True)
        return object()

    with (
        patch(
            "hevi.tongjian.scene_render_avatar._edit_keyframe",
            AsyncMock(
                side_effect=lambda **kw: (kw["output_path"].write_bytes(b"kf"), "sdxl_ip_adapter")[
                    1
                ]
            ),
        ),
        patch("hevi.tongjian.scene_render_avatar._resolve_vlm", _spy_resolve_vlm),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(
                side_effect=lambda **kw: kw["output_path"].write_bytes(b"c") or kw["output_path"]
            ),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate", AsyncMock(side_effect=_fake_hh)
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
            shotlist,
            script,
            _bible(),
            Constitution(),
            run_dir=tmp_path,
            config=LayerConfig(model="cloud_avatar", params={"observe_continuity": False}),
        )

    assert vlm_called == []  # 关掉时根本不取 VLM
    assert manifest.frames[1].debug_context["observed_carry"] == ""
    # 但计划态 carry 仍在(§J 没被关掉)
    assert manifest.frames[1].debug_context["carry"]


# ── Gap 1 阶段2:骨架控制图(ControlNet 地基) ─────────────────────────────────


def test_compose_pose_control_draws_skeletons_by_position(tmp_path):
    """OpenPose 骨架控制图:黑底,每个在场角色一副骨架,按走位落列。验证 (1) 黑底;(2) 有彩色
    骨架线(非全黑);(3) 左位角色骨架在左半、右位在右半。纯 PIL,零 GPU。"""
    from PIL import Image

    out = _compose_pose_control(
        present=["A", "B"],
        pos_desc_by_cid={"A": "左侧", "B": "右侧"},
        size=(1280, 720),
        out_path=tmp_path / "pose.png",
    )
    assert out is not None and out.exists()
    canvas = Image.open(out).convert("RGB")
    w, h = canvas.size
    assert (w, h) == (1280, 720)
    assert canvas.getpixel((5, 5)) == (0, 0, 0)  # 角落黑底

    # 每半画布都有非黑像素(= 两副骨架各就位)
    def _has_ink(x0, x1):
        return any(
            canvas.getpixel((x, y)) != (0, 0, 0) for x in range(x0, x1, 6) for y in range(0, h, 12)
        )

    assert _has_ink(0, w // 2)  # 左半有骨架
    assert _has_ink(w // 2, w)  # 右半有骨架


def test_compose_pose_control_none_for_single_char(tmp_path):
    """单人不需要走位约束 → None。"""
    out = _compose_pose_control(
        present=["A"],
        pos_desc_by_cid={"A": "中"},
        size=(1280, 720),
        out_path=tmp_path / "pose.png",
    )
    assert out is None
