"""L6 云数字人渲染路径(motion_mode/config model = "cloud_avatar")—— 把 scene_v5 那套
happyhorse 数字人流程接进通鉴的 ShotList/Script/CharacterBible 契约。

跟本地 SDXL 静帧路(`scene_render.build_frame_manifest`)并列,由 `render_shots` 按
`LayerConfig.model` 路由。核心:**happyhorse-1.1-r2v 是"会说话的数字人"**——喂参考图
+ 台词,一步生成带**配音+口型同步+动作**的视频(用 ALIBABA_MAAS key)。所以:
- **对白镜头**(shot 命中 dialogue 行):happyhorse(角色 canonical 像 + 该角色台词)→ 直接用它
  自带的配音和口型,存 ShotFrame.clip_path。
- **旁白镜头**:happyhorse(史官像 + 旁白文本)取音轨 + wan2.2-i2v(人物闭嘴/场景空镜)画面,
  合成后存 clip_path。
- **纯场景/过场**(无角色):qwen-image 文生场景 + i2v。

全云端、零本地 GPU。角色参考图:优先用 CharacterBible.ref_image;缺失/本地失效时按
appearance 用 qwen-image 现出一张云端 canonical(缓存)。产物是逐镜头 talking clip,
L8 装配识别 clip_path 直接 concat(见 assemble.py)。

**画风由 `params.style` 统一驱动**(默认 `_DEFAULT_STYLE` = 卡通动画),前端可切换成
其它风格预设(如国画水墨)——所有 prompt 拼接点都从这一个变量取词,不再各处写死
单一画风。2026-07-12 先把水墨从写死改成可切换;2026-07-13 default 从水墨换成卡通
动画——水墨是成年观众取向,小孩不喜欢,而通鉴受众里儿童向内容占比不小。

可调参数(LayerConfig.params):
  style(画风词,默认卡通动画)/resolution/watermark/crossfade(留给 L8)/seed/say_char_sec(每字秒数)。
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path
from typing import Any

from hevi.image.qwen_image_service import QwenImageError, qwen_image_edit, qwen_image_generate
from hevi.image.sdxl_local_service import sdxl_local_generate
from hevi.tongjian.schemas import (
    CharacterBible,
    Constitution,
    FrameManifest,
    GateResult,
    LayerConfig,
    Script,
    ShotFrame,
    ShotList,
)
from hevi.video.alibaba_maas_service import alibaba_maas_keyframe_generate
from hevi.video.dashscope_i2v_service import happyhorse_animate, i2v_animate

logger = logging.getLogger(__name__)

_DEFAULT_STYLE = "现代卡通动画风格,鲜艳色彩,简洁线条,可爱插画风,3D渲染质感"
# 人物角色描述本身跟画风解耦——style 参数已经在 _canonical() 里前缀画风,这里只留
# 外貌/身份描述,不重复写死具体某个画风,否则跟水墨等其它 style 预设叠在一起会打架。
_NARRATOR_DESC = (
    "一位年长儒雅的说书人史官,须发斑白,身着素色长袍,面容睿智平和,"
    "正襟危坐,近景半身像,身后淡淡书卷与薄雾"
)
# 描述的是"人物本身"(古装说书人史官),不是画风形容词——跟 style 一样解耦,可通过
# LayerConfig.params["narrator_desc"] 按调用方覆盖(短剧走"现代都市"风格,旁白该是
# 当代讲述者而不是古装史官,见 tongjian_bridge.py 的 DEFAULT_SHORTDRAMA_NARRATOR_DESC)。
_EDIT_PREFIX = "严格保持画中人物的相貌、胡须、服饰、头冠和画风完全不变,只改变神态动作:"
# 表情克制约束(2026-07-14 用户反馈"说话时瞪大眼睛、AI 痕迹太大"):情绪推断出的强词
# (惊惧/大惊等)被 qwen-image-edit 渲成夸张瞪眼、五官变形。给关键帧统一加一句"真人演员
# 微表演、眼神平和不瞪眼、五官比例正常"的约束,把表演压回自然区间。
_EXPRESSION_GUARD = (
    ",但表情要自然克制、像真人演员的微表演:眼睛正常睁开不要瞪大瞪圆、"
    "五官比例正常不变形、情绪含蓄不夸张"
)

# 服饰负面词(2026-07-17 审计缺口#4):参考图阶段有一组强负面词压住"奇幻战场风格惯性"
# (director_pipeline._PORTRAIT_NEGATIVE,注释明写"实测能压住"),但它**只在参考图那一步生效**
# ——关键帧走的是 sdxl 的 _DEFAULT_NEGATIVE,里面一个铠甲/肩甲/金饰词都没有。于是"参考图是
# 干净的定妆照,一进关键帧就重新长出圣斗士肩甲"是可预测的结果(用户实测反馈"穿戴像圣斗士")。
# 身份链条(确定性 seed + 真照 canon + IP-Adapter + CLIP 打分 + rewrite 返工)是全仓最完整的
# 一环,同样的严谨此前完全没延伸到服饰,这里补上跨阶段那一步。
#
# **必须是英文**:sdxl_local_service 只对正向 prompt 做中→英翻译(:186),negative_prompt 原样
# 透传(:195),而 base SDXL 不认中文——照抄中文的 _PORTRAIT_NEGATIVE 会是个无声的空操作
# (INC-002 derive_negatives 派生的中文负面词至今就是这么死的,见该函数注释)。
#
# 只收"服饰奇幻化"这一类,不含 _PORTRAIT_NEGATIVE 里的"动漫风"——本模块 _DEFAULT_STYLE 就是
# 卡通风格,把画风词写死进负面会跟卡通/水墨等 style 预设直接打架。画风由 style 正向词管。
_WARDROBE_NEGATIVE_EN = (
    "fantasy armor, glowing armor, spiked pauldrons, oversized shoulder armor, "
    "demonic face pauldrons, dragon-engraved armor, ornate gold ornaments, "
    "exaggerated ornamentation, saint seiya style armor, game character armor, "
    "cosplay costume, anachronistic clothing"
)

# INC-001 §C 首帧未完成态:i2v 只能让关键帧"微微动一下"。若关键帧生成的是动作**完成态**
# (人已经转过身/已经站定),动画里就没有真动作,只有静态图呼吸感。检测到连续反应链动词时,
# 把关键帧拉到"动作刚开始、进行到一半、尚未完成"的那一瞬间,happyhorse 才能补出真正的运动。
# 这直接治用户反馈的"人物没有连续的电影一样真实动作"。
_REACTION_CHAIN_KEYS = (
    "突然",
    "下意识",
    "脱手",
    "蹲下",
    "转身",
    "回头",
    "伸手",
    "抬手",
    "挥",
    "扑",
    "跌",
    "摔",
    "推",
    "拉",
    "拽",
    "起身",
    "冲",
    "猛地",
    "一把",
    "瞬间",
    "夺",
    "扑向",
    "抓住",
    "举起",
    "抬起",
    "低头",
    "俯身",
    "跪",
    "站起",
    "拔",
)
_INCOMPLETE_STATE_SUFFIX = (
    ",这一帧要抓拍这个动作**刚开始、进行到一半、尚未完成**的那一瞬间"
    "(身体正处在动态过程中,不是动作做完后的定格姿态)"
)


def _incomplete_state_suffix(action_src: str) -> str:
    """动作源文本里出现连续反应链动词 → 返回"未完成态"约束,否则空串。"""
    return _INCOMPLETE_STATE_SUFFIX if any(k in action_src for k in _REACTION_CHAIN_KEYS) else ""


def _action_keyword_score(text: str) -> int:
    """一段动作文本里命中多少连续反应链动词——动作强度的粗代理,用来在中间拍里挑峰值拍。"""
    return sum(1 for k in _REACTION_CHAIN_KEYS if k in text)


def _infer_action_phases(beats: list[str]) -> tuple[str, str, str]:
    """INC-001 §B:有序 action_beats → (trigger, peak, aftermath) 三阶段文本(轻量启发式)。

    首拍=trigger(动作触发),末拍=aftermath(收束/结果),峰值=中间拍里动作动词最密的一拍
    (只有两拍时取两拍中动作更强者;只有一拍时三阶段同拍)。beats 为空 → 三个空串,
    调用方据此退回现状行为(§C 未完成态 + _action_end_state,不依赖 beats)。
    """
    beats = [b.strip() for b in beats if b and b.strip()]
    if not beats:
        return "", "", ""
    if len(beats) == 1:
        return beats[0], beats[0], beats[0]
    trigger, aftermath = beats[0], beats[-1]
    middle = beats[1:-1]
    peak = max(middle or beats, key=_action_keyword_score)
    return trigger, peak, aftermath


_AXIS_CONSTRAINT = "保持人物左右站位与面部朝向稳定、空间轴线一致,避免跳轴和朝向突变"


def _same_scene_shared(shots: list, idx: int, shot) -> bool:
    """§J:当前镜与上一镜同场景且有共同在场角色 → True(轴线连续风险,该守稳)。"""
    if idx <= 0:
        return False
    prev = shots[idx - 1]
    return (
        bool(shot.scene_id)
        and prev.scene_id == shot.scene_id
        and bool(set(prev.characters) & set(shot.characters))
    )


def _shot_edge(shot, *, end: bool) -> str:
    """一个镜的"结尾/起始"文本:优先取 action_beats 收束拍/触发拍,无 beats 退回 visual_prompt。"""
    beats = shot.action_beats or []
    if beats:
        return (beats[-1] if end else beats[0]).strip()
    return (shot.visual_prompt or "").strip()


def _adjacent_context(shots: list, idx: int) -> tuple[str, str]:
    """INC-001 §J 完整版:相邻镜头上下文。返回(承接上镜, 过渡下镜)两句连续性建议——
    当前镜与相邻镜同场景时,用相邻镜的收束/触发态(见 _shot_edge)提示承接与过渡。换场不给。
    (与观察态 4.0.1b 叠加:此处是计划态双向照应;实际末帧覆盖起始态由观察态另行处理。)"""
    shot = shots[idx]
    carry = lead_out = ""
    if idx > 0 and shot.scene_id and shots[idx - 1].scene_id == shot.scene_id:
        prev_end = _shot_edge(shots[idx - 1], end=True)
        if prev_end:
            carry = f"承接上一镜的收束态({prev_end}),延续其动作、视线与空间方向"
    if idx < len(shots) - 1 and shot.scene_id and shots[idx + 1].scene_id == shot.scene_id:
        next_start = _shot_edge(shots[idx + 1], end=False)
        if next_start:
            lead_out = f"收束到能自然过渡到下一镜({next_start})的停留态"
    return carry, lead_out


def _director_command_summary(
    *, frame_role: str, incomplete: str, eyeline: str, axis: bool, carry: str, lead_out: str
) -> str:
    """INC-001 §E:导演命令摘要——把各项 guidance 按帧风险**动态分级并排序**,不是扁平拼接。

    风险提级到「必须」级:同场景连续(轴线,§J)、对视(对白受话者,§H)。§C 未完成态在触发/
    峰值帧是「必须」、收束帧不强加。相邻镜承接/过渡(§J)为「优先」级。因此首(first)/关
    (peak)/尾(aftermath)帧看到的必须/优先摘要并不相同。返回附加到关键帧 instruction 的有序块。
    """
    must: list[str] = []
    prefer: list[str] = []
    if axis:  # §J 同场景连续 → 轴线必守
        must.append(_AXIS_CONSTRAINT)
    if eyeline and frame_role != "aftermath":  # §H 对视风险 → 视线必守(收束帧弱化)
        must.append("说话者" + eyeline.lstrip("，,"))
    if incomplete and frame_role in ("first", "peak"):  # §C 未完成态:触发/峰值必守
        must.append(incomplete.lstrip("，,"))
    if carry and frame_role in ("first", "peak"):  # 承接上镜:起势帧优先
        prefer.append(carry)
    if lead_out and frame_role in ("first", "aftermath"):  # 过渡下镜:收束帧优先
        prefer.append(lead_out)
    blocks: list[str] = []
    if must:
        blocks.append("必须:" + ";".join(must))
    if prefer:
        blocks.append("优先:" + ";".join(prefer))
    return ("。" + "。".join(blocks)) if blocks else ""


def _p(config: LayerConfig | None, key: str, default: Any) -> Any:
    return config.params.get(key, default) if config and config.params else default


def _ffprobe_dur(p: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(p),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


_MAX_CLIP_DURATION_S = 15  # happyhorse-1.1-r2v 平台硬顶(见 capability_guard.py 同款声明)

_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,.;!?:，。;!?:、])")


def _say_dur(text: str, per_char: float) -> int:
    return max(3, min(_MAX_CLIP_DURATION_S, round(len(text) * per_char) + 1))


def _split_text_for_dialogue(text: str, per_char: float) -> list[str]:
    """台词太长、单个 clip 撑不满这句话时(超过 happyhorse 的 {_MAX_CLIP_DURATION_S}s 硬顶),
    按标点切成几段分别渲染再拼接——而不是让 _say_dur 把整句压进一个 clip 里,逼着模型用不
    自然的语速一口气念完(观感"说话太快"、口型跟不上语速)。
    """
    if _say_dur(text, per_char) < _MAX_CLIP_DURATION_S:
        return [text]
    # _say_dur 在字数时长上另加 1 秒余量,这里同步扣掉,确保每段都稳落在硬顶以内。
    max_chars = max(1, int((_MAX_CLIP_DURATION_S - 1) / per_char))
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(text) if c]
    chunks: list[str] = []
    cur = ""
    for clause in clauses:
        while len(clause) > max_chars:  # 单个分句本身超长(无标点可切),硬切兜底
            head, clause = clause[:max_chars], clause[max_chars:]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if cur and len(cur) + len(clause) > max_chars:
            chunks.append(cur)
            cur = clause
        else:
            cur += clause
    if cur:
        chunks.append(cur)
    return chunks or [text]


def _concat_clips(clips: list[Path], out: Path) -> None:
    """按顺序直接首尾拼接(不溶解),用于同一句台词切段渲染后的子 clip 拼回一条。"""
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    n = len(clips)
    parts = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            parts,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


async def _canonical(
    cid: str, appearance: str, work: Path, style: str, *, ref_image: str | None = None
) -> Path:
    """角色 canonical(缓存)。优先复用 Subject 的真实参考图(`ref_image`,来自
    CharacterBible.ref_image,见 tongjian_bridge.py::character_bible_for_episode)——
    锁的是同一张真实照片/生成像,而不是"同一段文字 + 固定 seed"这种弱一致性假设
    (2026-07-12 前的行为:每次都用 qwen-image 从文字重新生成一张陌生的脸,集内靠
    文件缓存凑巧一致,跨集/跨角色绑定的参考图完全没被用上)。ref_image 缺失时
    (如 narrator,或该角色未绑定 Subject)才退回原来的文生图。
    """
    out = work / f"canon_{cid}.png"
    if out.exists():
        return out
    if ref_image and Path(ref_image).exists():
        from PIL import Image

        Image.open(ref_image).convert("RGB").save(out)
        return out
    # "朝堂木柱"是资治通鉴的宫廷场景描述,2026-07-12 前跟 style 完全解耦、对所有画风
    # 硬编码——短剧接进来后用"现代都市"风格也会生出这句宫廷背景,不再写死具体场景,
    # 交给 style 前缀词自己定调(同上面"人物角色描述本身跟画风解耦"的既有设计)。
    prompt = f"{style},{appearance},近景半身像,背景虚化"
    await qwen_image_generate(prompt=prompt, output_path=out, size="1280*720", seed=42)
    return out


def _score_consistency(frame_path: Path, canon_path: Path) -> float | None:
    """镜头首帧 vs canonical 的 CLIP 余弦相似度——身份漂移信号(复用 verdict 主管线
    同一套打分原语 subject_embed/cosine_similarity,见 hevi/verdict/scorecard.py,不是
    另起一套)。canon 是这一集里该角色实际用来生成画面的那张锚图(真实 Subject 参考图
    或退化文生图,见 _canonical()),分数低说明生成出来的脸跟锚图对不上,而不是跟某个
    抽象"标准脸"比——衡量的正是这条 cloud_avatar 管线本该有、之前完全没有的信号:
    生成结果有没有跑偏。抽帧/嵌入失败 → None,不阻断渲染,只是这一帧没有漂移信号。
    """
    from hevi.subjects.subject_embed import SubjectEmbedError, cosine_similarity, subject_embed

    try:
        frame_emb = subject_embed(image_path=frame_path, kind="style")
        canon_emb = subject_embed(image_path=canon_path, kind="style")
        return cosine_similarity(frame_emb, canon_emb)
    except SubjectEmbedError as e:
        logger.warning(
            "scene_render_avatar: consistency score 失败(%s vs %s): %s", frame_path, canon_path, e
        )
        return None


def _extract_frame(clip: Path, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "0", "-i", str(clip), "-frames:v", "1", str(out)],
        check=True,
        capture_output=True,
    )


def _extract_last_frame(clip: Path, out: Path) -> None:
    """抽末帧(Gap 2 观察态用)。-sseof -0.1:定位到片尾前 0.1s 再取一帧,比按时长算稳。"""
    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(clip), "-frames:v", "1", str(out)],
        check=True,
        capture_output=True,
    )


# resolution 参数(前端下拉直接给这些键)→ 横屏画幅(宽,高)。
_RES = {"480P": (854, 480), "720P": (1280, 720), "1080P": (1920, 1080)}


def _resolve_dimensions(resolution: str, aspect_ratio: str) -> tuple[int, int]:
    """resolution 分档 + Constitution.visual_style.aspect_ratio → 最终交付画幅。

    2026-07-12 真实撞见:短剧设计上是 9:16 竖屏(手机观看),但此前这里只按 _RES
    出横屏尺寸,aspect_ratio 字段设了从没人读过——真实跑出来的成片是 1280×720
    横屏。happyhorse/i2v 底层云端 API 的 resolution 参数只是画质分档(480P/720P/
    1080P),不控制横竖(见 dashscope_i2v_service.py),真正决定最终画幅的是
    _fit_dialogue/_fit_narration 那步 ffmpeg scale+crop——所以只需要把交付宽高
    按 aspect_ratio 转置,不用碰 API 调用本身。
    """
    w, h = _RES.get(resolution, _RES["720P"])
    return (h, w) if aspect_ratio == "9:16" else (w, h)


def _fit_dialogue(clip: Path, out: Path, w: int, h: int) -> None:
    """对白 clip 自带配音+口型,保留音轨,只规整到 w×h + 轻微 zoompan 缓推。"""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(clip),
            "-filter_complex",
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=24,"
            f"zoompan=z='min(zoom+0.0004,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={w}x{h}:fps=24[v]",
            "-map",
            "[v]",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


def _fit_narration(visual: Path, audio: Path, out: Path, w: int, h: int) -> None:
    """旁白:画面循环填满旁白音轨时长(不冻结)+ zoompan;挂旁白音轨,输出 w×h。"""
    hold = _ffprobe_dur(audio) + 0.4
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(visual),
            "-i",
            str(audio),
            "-filter_complex",
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"trim=0:{hold:.3f},setpts=PTS-STARTPTS,fps=24,"
            f"zoompan=z='min(zoom+0.0004,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={w}x{h}:fps=24[v]",
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            f"{hold:.3f}",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


def _fit_silent(visual: Path, out: Path, w: int, h: int, duration: float) -> None:
    """静默动作/空镜:画面循环填满 `duration` 秒 + zoompan(轻微运镜),挂一条静音音轨
    (让每个 clip 都有音频流,跟对白 clip 一致,xfade 拼接不会因缺流出错)。不加任何旁白。"""
    hold = max(1.5, duration)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(visual),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex",
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"trim=0:{hold:.3f},setpts=PTS-STARTPTS,fps=24,"
            f"zoompan=z='min(zoom+0.0004,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={w}x{h}:fps=24[v]",
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            f"{hold:.3f}",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


# _edit_keyframe 实际走通的引擎标签(返回值)。canon 复制 = 导演层完全没落地,视为降级。
_KF_SDXL_IMG2IMG = "sdxl_img2img"  # SPEC-004 v2:从 Subject3D 朝向视图 img2img
_KF_SDXL_IP_ADAPTER = "sdxl_ip_adapter"  # 默认路:本地 sdxl + IP-Adapter 锁脸
_KF_CLOUD_EDIT = "cloud_edit"  # 云端 qwen-image-edit
_KF_CANON_COPY = "canon_copy"  # 保底:直接抄定妆照(= 这一镜没有关键帧)
_KF_CACHED = "cached"  # 上一轮已产出,本轮复用(re_roll 保 kf;真伪由 _is_canon_copy 兜)
# 落 ShotFrame.degrade_reason → 桥接层转成 shot_states.diagnosis_category(同 "avatar 生成失败"
# 的既有自由文本口径)。写明白是哪一层没落地,人在 SeasonBoard 上一眼能看懂。
_KF_DEGRADE_REASON = "构图:关键帧降级为定妆照(本地 sdxl 与云端 edit 均不可用),导演命令未落地"


def _is_canon_copy(kf: Path, canon: Path | None) -> bool:
    """这张关键帧是不是 canon 定妆照的字节级复制品(= _edit_keyframe 走了保底,导演层没落地)。

    比返回值标签更权威:标签只覆盖"本轮现生成"的帧,而 kf 命中缓存(_KF_CACHED,如 re_roll
    保 kf 重掷、或进程重启后复用 run_dir)时,上一轮抄来的定妆照会原样留下。字节比对对两种
    情形都成立,且零误报——真生成的帧不可能与 canon 逐字节相同。"""
    if canon is None or not kf.exists() or not canon.exists():
        return False
    try:
        if kf.stat().st_size != canon.stat().st_size:
            return False  # 先比大小,绝大多数情形一步排除,不读盘
        return kf.read_bytes() == canon.read_bytes()
    except OSError as e:
        logger.warning("关键帧 canon 复制比对失败(按未降级处理)%s: %s", kf.name, e)
        return False


# ── Gap 1 阶段1:多角色走位几何底图 ─────────────────────────────────────────────
# 缺口(2026-07-17 审计):走位/朝向/落位全程是中文文本喂 prompt,渲染层无任何几何控制。
# SPEC-004 v2 的 Subject3D 朝向视图 img2img 是唯一的几何路,但只接了对白镜的 lead 一人;
# 多角色同框——走位最需要几何的场合——零覆盖。这里把每个在场角色的朝向视图,按其走位落位
# (同前端俯视图那套 左/中/右 单一真相源词表)合成到一张画布上,当多角色关键帧的 img2img 底图。
#
# **这是与 ControlNet(阶段2)共用的地基**:同一张合成图,阶段1 拿它当 img2img init(几何软约束,
# strength 0.45),阶段2 拿它当 ControlNet 控制图(几何硬约束 + IP-Adapter 锁脸可共存)。
#
# **已知取舍**(诚实标注,别当免费午餐):img2img 与 IP-Adapter 在本地 worker 里互斥
# (_sdxl_worker.py 约束),走这条 = 让出 IP-Adapter 锁脸,身份改押在 Subject3D 视图上,而后者
# 实测比 2D 真照糊(CLIP 0.61 vs 0.77-0.84,见 subject3d_local.py)。多角色镜本来 lead 之外就
# 没有锁脸(只 canons[0] 一张),用几何换"全员位置对"在多角色场合大概率划算,但**需真跑验证**,
# 不是纸面定论。阶段2 的 ControlNet+IP-Adapter 共存才是架构正解,阶段1 是它的次优近似。
def _layout_col(pos_desc: str, order: int, total: int) -> float:
    """走位文本 → 画布水平中心比例(0..1)。命中"左/中/右"用词表(同前端俯视图单一真相源);
    没命中则按在场顺序均匀铺开(2 人→0.3/0.7,3 人→0.2/0.5/0.8),保证至少不重叠堆一起。"""
    t = pos_desc or ""
    if "左" in t:
        return 0.22
    if "右" in t:
        return 0.78
    if "中" in t or "居中" in t:
        return 0.5
    return (order + 1) / (total + 1)


def _knockout_near_white(img: Any) -> Any:
    """Subject3D 渲染帧是近白底(实测 251,251,252)无 alpha。抠成透明,才能干净地贴到布局画布上
    (否则白底方块互相遮挡)。阈值 235:比这亮的像素判背景。返回 RGBA。"""
    rgba = img.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            if r >= 235 and g >= 235 and b >= 235:
                px[x, y] = (r, g, b, 0)
    return rgba


def _parse_blocking_positions(
    blocking: list[str], present: list[str], name_by_id: dict[str, str]
) -> dict[str, str]:
    """把 Shot.blocking 的"角色名:位置,朝向"短句反解成 {cid: 位置文本}。blocking 用的是显示名,
    present 是 cid——按 name_by_id 双向对齐(cid 与显示名在通鉴常相等,但不保证)。给 _layout_col
    取 左/中/右。解析不出的角色不进 dict(_compose_layout_base 会退回均匀铺开)。"""
    name_to_cid = {name_by_id.get(cid, cid): cid for cid in present}
    name_to_cid.update({cid: cid for cid in present})  # cid 自身也可直接命中
    out: dict[str, str] = {}
    for entry in blocking or []:
        if ":" not in entry:
            continue
        name, rest = entry.split(":", 1)
        cid = name_to_cid.get(name.strip())
        if cid:
            out[cid] = rest.strip()
    return out


def _compose_layout_base(
    *,
    present: list[str],
    view_path_by_cid: dict[str, Path],
    pos_desc_by_cid: dict[str, str],
    size: tuple[int, int],
    out_path: Path,
) -> Path | None:
    """把在场角色的 Subject3D 朝向视图按走位落位合成一张几何底图。≥2 张视图才产(单角色走
    SPEC-004 单 lead 路,不需要合成)。任一角色无视图 → 返回 None,调用方退回原文本路。

    确定性、纯 PIL、零模型调用、零花费——可脱离 GPU 单测。"""
    from PIL import Image

    placeable = [c for c in present if c in view_path_by_cid and view_path_by_cid[c].exists()]
    if len(placeable) < 2:
        return None
    w, h = size
    canvas = Image.new("RGB", (w, h), (128, 128, 128))  # 中性灰:img2img 要清晰的图/地分离
    fig_h = int(h * 0.85)
    total = len(placeable)
    try:
        for order, cid in enumerate(placeable):
            fig = _knockout_near_white(Image.open(view_path_by_cid[cid]))
            scale = fig_h / fig.height
            fig = fig.resize((max(1, int(fig.width * scale)), fig_h))
            cx = _layout_col(pos_desc_by_cid.get(cid, ""), order, total)
            x = int(cx * w - fig.width / 2)
            y = h - fig.height  # 脚底贴画布底,近地面站位
            canvas.paste(fig, (x, y), fig)  # 第三参 = alpha 蒙版
        canvas.save(out_path)
        return out_path
    except OSError as e:
        logger.warning("多角色走位底图合成失败,退回文本路 %s: %s", out_path.name, e)
        return None


# OpenPose(BODY_25 的常用 18 点子集)骨架:相对坐标(x 相对该人中心列半宽、y 相对画布高)。
# 一个正面站立的人形骨架——ControlNet-OpenPose 的控制图靠这个点集连线,不需要真实姿势估计
# (走位是中文文本无坐标,pose estimator 也没装)。x 以人物中心为 0,左负右正,单位=人物半宽。
_POSE_KEYPOINTS: dict[str, tuple[float, float]] = {
    "nose": (0.0, 0.08),
    "neck": (0.0, 0.18),
    "r_shoulder": (-0.35, 0.20),
    "l_shoulder": (0.35, 0.20),
    "r_elbow": (-0.45, 0.42),
    "l_elbow": (0.45, 0.42),
    "r_wrist": (-0.5, 0.62),
    "l_wrist": (0.5, 0.62),
    "r_hip": (-0.25, 0.58),
    "l_hip": (0.25, 0.58),
    "r_knee": (-0.28, 0.8),
    "l_knee": (0.28, 0.8),
    "r_ankle": (-0.28, 0.99),
    "l_ankle": (0.28, 0.99),
}
# OpenPose 标准骨架连线 + 每条线的标准配色(ControlNet-OpenPose 训练时用的固定色板,颜色本身
# 是模型认的信号,不能随便改)。
_POSE_LIMBS: tuple[tuple[str, str, tuple[int, int, int]], ...] = (
    ("neck", "nose", (0, 0, 255)),
    ("neck", "r_shoulder", (255, 0, 0)),
    ("neck", "l_shoulder", (255, 85, 0)),
    ("r_shoulder", "r_elbow", (255, 170, 0)),
    ("r_elbow", "r_wrist", (255, 255, 0)),
    ("l_shoulder", "l_elbow", (170, 255, 0)),
    ("l_elbow", "l_wrist", (85, 255, 0)),
    ("neck", "r_hip", (0, 255, 0)),
    ("r_hip", "r_knee", (0, 255, 85)),
    ("r_knee", "r_ankle", (0, 255, 170)),
    ("neck", "l_hip", (0, 255, 255)),
    ("l_hip", "l_knee", (0, 170, 255)),
    ("l_knee", "l_ankle", (0, 85, 255)),
)


def _compose_pose_control(
    *,
    present: list[str],
    pos_desc_by_cid: dict[str, str],
    size: tuple[int, int],
    out_path: Path,
) -> Path | None:
    """Gap 1 阶段2 地基:多角色 OpenPose 骨架控制图(黑底 + 每个在场角色一副正面站立骨架,按
    走位落列)。给 ControlNet-OpenPose 当 control image——**与 img2img 底图互补**:img2img 给
    "长什么样",骨架给"站哪、身体朝向"。≥2 人才产(单人不需要走位约束)。

    纯 PIL/几何,零模型、零花费、可脱离 GPU 单测。真正吃它的 worker 分支尚未接(见
    sdxl_local_service 的 controlnet TODO):现在产出物已就绪,等 GPU 两条腿修好 + 权重下到
    宿主机后,worker 一接即用。**产不产它与 config['controlnet'] 开关解耦**:图先备好,消费端
    没就绪也不浪费(纯 CPU 画线,毫秒级)。

    **已知局限(诚实标注)**:当前每个人画的都是同一副正面直立骨架,只落"站在哪(左/中/右)",
    不落"身体朝哪"——朝向信息在 shot_view(front/left/right/back)里,这里还没消费。所以它约束
    的是站位不是姿态。要落朝向,下一步是按 shot_view 出侧面/背面骨架点集(或直接从 Subject3D
    的 GLB 渲骨架),与阶段1 img2img 底图那条朝向路对齐。接 worker 前先补这个才有完整价值。"""
    from PIL import Image, ImageDraw

    if len(present) < 2:
        return None
    w, h = size
    canvas = Image.new("RGB", (w, h), (0, 0, 0))  # OpenPose 控制图是黑底
    draw = ImageDraw.Draw(canvas)
    half_w = w / (len(present) + 1) * 0.5  # 每人半宽,按人数均分画布避免骨架重叠
    total = len(present)
    try:
        for order, cid in enumerate(present):
            cx = _layout_col(pos_desc_by_cid.get(cid, ""), order, total) * w
            pts = {name: (cx + rx * half_w, ry * h) for name, (rx, ry) in _POSE_KEYPOINTS.items()}
            for a, b, color in _POSE_LIMBS:
                draw.line([pts[a], pts[b]], fill=color, width=max(2, int(h * 0.012)))
            for x, y in pts.values():  # 关节点:白圆
                r = max(2, int(h * 0.008))
                draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255))
        canvas.save(out_path)
        return out_path
    except (OSError, KeyError) as e:
        logger.warning("骨架控制图合成失败,不影响出片 %s: %s", out_path.name, e)
        return None


def _local_kf_prompt(
    style: str,
    appearance: str,
    emotion: str,
    action_hint: str,
    *,
    scene_space: str = "",
    mouth_closed: bool = False,
    wide: bool = False,
    command_summary: str = "",
) -> str:
    """拼 sdxl_local 关键帧生成 prompt。**语言:此处拼的是中文(appearance/scene_space 都是中文
    作者写的),但 base SDXL 对中文人物 prompt 会渲成通用少女(G-S1 2026-07-16 实证:中文"白胡子
    老道士"→银发少女);中→英转换由唯一漏斗 `sdxl_local_generate` 统一做(prompt_language),此处
    不用管。** 精确姿势跟不住是 base SDXL 无 ControlNet 的已知代价(SPEC-004 v2 拟接 Subject3D 机位
    帧解决朝向),靠 kf2v 运动补动作感。IP-Adapter 另传 canon 锁脸。

    scene_space:SPEC-004 断链#3——场景空间描述(环境/光照/氛围,来自 DesignScene)。此前
    DesignScene 的空间描述从桥接层到这里全程零消费,画面里根本没有场景。按 §F.1 口径空间项
    靠前(风格→空间→相貌→情绪→动作)。空串则行为不变(向后兼容 tongjian 管线)。

    command_summary:INC-001 §E 导演命令摘要(§C 未完成态/§H eyeline/§J 轴线与相邻镜承接)+
    INC-002 §1.1 时刻表演切片。**此前它只拼进云端 edit 的 instruction,而 local 是默认引擎——
    等于这些导演命令只在 GPU 掉线走云端兜底时才生效(2026-07-17 审计发现)。** 排在最后:前面
    是"画什么",它是"必须守什么",尾部约束不挤占主体描述。空串则行为不变。"""
    parts = [style, scene_space, appearance, emotion]
    if action_hint:
        parts.append(f"动作:{action_hint}")
    if mouth_closed:
        parts.append("闭着嘴不说话")
    if wide:
        parts.append("全身,宽景,交代环境与站位")
    if command_summary:
        # _director_command_summary 出的是"。必须:…。优先:…"(给 instruction 用的句式),
        # 这里是逗号分隔的 prompt,剥掉首尾句号再并进来。
        parts.append(command_summary.strip("。"))
    return ",".join(p for p in parts if p)


async def _edit_keyframe(
    *,
    image_path: Path | list[Path],
    instruction: str,
    output_path: Path,
    fallback_from: Path,
    engine: str = "local",
    local_prompt: str | None = None,
    ip_adapter_image: Path | None = None,
    init_image: Path | None = None,
    init_strength: float = 0.45,
    size: tuple[int, int] = (1024, 1024),
    negative_prompt: str = "",  # INC-002 v0.2:schema 派生的负面词,追加到 sdxl 默认负面后
) -> str:
    """出关键帧:把该镜的情绪+动作+构图落成一张锁脸的关键帧。**返回实际走通的引擎标签**
    (见 _KF_*):调用方据此判断这一镜的关键帧是真生成的还是抄的定妆照。引擎可切
    (config.keyframe_engine):

    - **engine="local"(默认,免费)**:本地 sdxl_local + IP-Adapter,拿角色 canon 脸做身份
      条件,按 `local_prompt`(风格+相貌+情绪+动作)生成**任意构图/姿势**——能真正摆动作、出
      宽景,而不只是把情绪叠回原构图。GPU 在总线上时走这条,不花钱(用户 2026-07-15 决定走
      本地而非为云端 edit 开付费,且要求做成可切换选项、不写死)。IP-Adapter 保脸偏软(权重
      0.6),身份漂移由 verdict 的 CLIP 打分兜底。
    - **engine="cloud"**:直接走云端 qwen-image-edit 参考图编辑(精确姿势/多脸合成更强),
      随时可切回;但该模型免费额度墙(AllocationQuota.FreeTierOnly)时会快速抛。

    两种引擎都以 canon 复制保底:本地/云端都不可用时直接用 canonical 像当关键帧,整镜不降级
    空镜、整集不卡 G6 装配门(只少了动作/情绪注入,happyhorse 后面仍加口型+表情)。多角色镜头
    保底只保 lead 一张脸(fallback_from 传 canons[0])。

    **保底不是免费的**(2026-07-17 审计实证:task da0bbeff 一次真实产集,20 镜里 14 镜的关键帧
    与 canon 定妆照字节级相同,成片退化成"大头念台词",而当时只有一条 warning、交付门全过)。
    两条腿同时不可用时,保底就从"兜底"变成常态路径。**那次两条腿各自为何失败没有留下证据**
    (无日志),只知道结果;别据此臆断成因。故返回 _KF_CANON_COPY 让调用方标成 degraded →
    进 verdict 返工闸,把"没人知道"变成"当场就知道"。"""
    # 服饰负面词跨阶段落地(缺口#4):这里是所有**角色**关键帧的唯一漏斗(纯场景空镜走
    # qwen_image_generate,不经过本函数),一处注入即覆盖对白/多角色/单角色静默/kf2v 首中尾
    # 全部调用点。只对 sdxl 两条路生效——云端 qwen_image_edit 没有负面词入参(它靠
    # _EDIT_PREFIX"严格保持服饰不变"约束,是另一套机制)。
    negative_prompt = (
        f"{_WARDROBE_NEGATIVE_EN}, {negative_prompt}" if negative_prompt else _WARDROBE_NEGATIVE_EN
    )
    # 0. SPEC-004 v2:非正面朝向镜 → img2img 从 Subject3D 朝向视图当底图(朝向真落画面,不走
    #    IP-Adapter[只迁身份不迁姿势]。gs1 2026-07-16 验证)。仅 local 引擎且备好朝向视图时。
    if engine == "local" and local_prompt and init_image and Path(init_image).exists():
        try:
            await sdxl_local_generate(
                prompt=local_prompt,
                output_path=output_path,
                width=size[0],
                height=size[1],
                extra={"init_image": str(init_image), "strength": init_strength},
                negative_prompt=negative_prompt,
                require_gpu=True,
            )
            if output_path.exists() and output_path.stat().st_size > 1024:
                return _KF_SDXL_IMG2IMG
        except Exception as e:  # img2img 失败退下面的 IP-Adapter/云端路,不拖垮整镜
            logger.warning("sdxl_local img2img(朝向视图)失败,退 IP-Adapter/云端: %s", e)

    # 1. 本地 sdxl_local(IP-Adapter 锁脸 + 任意姿势/构图)—— 仅 local 引擎且备好本地素材时
    if engine == "local" and local_prompt and ip_adapter_image and Path(ip_adapter_image).exists():
        try:
            # 每帧独立子进程:冷启动加载 SDXL+IP-Adapter+VAE(~90s)再出图(~60s),约 137s/帧。
            # worker 超时是模块常量 _SDXL_TIMEOUT_S=600s,够;离线加载见 sdxl_local_service。
            await sdxl_local_generate(
                prompt=local_prompt,
                output_path=output_path,
                width=size[0],
                height=size[1],
                extra={"ip_adapter_image": str(ip_adapter_image), "ip_adapter_weight": 0.6},
                negative_prompt=negative_prompt,
                require_gpu=True,
            )
            if output_path.exists() and output_path.stat().st_size > 1024:
                return _KF_SDXL_IP_ADAPTER
        except Exception as e:  # GPU 掉总线/本地失败都退云端,不拖垮整镜
            logger.warning("sdxl_local 关键帧失败,退云端 edit: %s", e)

    # 2. 云 qwen-image-edit
    try:
        await qwen_image_edit(
            image_path=image_path, instruction=instruction, output_path=output_path
        )
        return _KF_CLOUD_EDIT
    except QwenImageError as e:
        # 3. canon 复制保底 —— 这一镜的导演层(景别/动作/情绪/§E 命令)一个字都没落地。
        #    error 级:它不是"稍差一点",是这一镜退化成了定妆照。调用方标 degraded 送返工。
        logger.error(
            "关键帧降级:本地 sdxl 与云端 edit 均不可用,直接抄 canonical 像(%s)—— "
            "该镜无关键帧,导演命令未落地: %s",
            fallback_from.name,
            e,
        )
        shutil.copyfile(fallback_from, output_path)
        return _KF_CANON_COPY


def _resolve_llm() -> Any:
    """取 qwen_cloud LLM(拆动作起止状态用,funded、结构化可靠;见 e2e-local-llm-json-blocker)。"""
    from obase.provider_registry import ProviderRegistry

    try:
        return ProviderRegistry.get().llm("qwen_cloud")
    except Exception:
        try:
            return ProviderRegistry.get().llm("default")
        except Exception:
            return None


# Gap 2 观察态注入(2026-07-17 审计):镜间连贯此前只有 _adjacent_context 的**计划态**文本
# (拿上一镜剧本里的收束拍描述当承接锚),而 _adjacent_context 的 docstring(:189)白纸黑字承诺
# "实际末帧覆盖起始态由观察态另行处理"——审计 grep 全仓,那个"另行处理"不存在。这里把它补上:
# VLM 看上一镜**真实渲出的末帧**,产一句客观停留态,取代计划态当下一镜的承接锚。
#
# 为什么不是"上一镜末帧直接当下一镜首帧"(用户否掉的字面接法):切镜=换机位换景别,像素直连
# 会把每个剪辑点变成无缝 morph,景别/机位变化全废(是"大头念台词"的另一种形态)。顶级出片要的
# 是**状态连续**(人在哪、穿什么、动作到哪一阶段),不是**像素连续**。故走文本观察态,机位/景别
# 仍由分镜自由决定。
_END_STATE_VLM_PROMPT = (
    "这是一个镜头的最后一帧。用一句话客观描述画面里主要人物此刻的**停留态**:"
    "各人所在位置(画面左/中/右)、身体朝向、以及动作是否已收束"
    "(例:'张飞已收刀入鞘、立于画面左侧、面向右方,刘备立于画面中央')。"
    "只描述看得见的,不要脑补剧情或情绪。只输出这一句话,不加引号。"
)


async def _observe_end_state(clip: Path, vlm: Any, out: Path) -> str:
    """VLM 看一个镜头的真实末帧 → 一句观察态停留描述。vlm 不可用/抽帧失败/VLM 失败一律返回 ""
    (调用方退回计划态 _carry,行为完全不变,绝不阻断出片)。"""
    if vlm is None or not clip.exists():
        return ""
    try:
        _extract_last_frame(clip, out)
    except Exception as e:
        logger.warning("观察态抽末帧失败,退计划态: %s", e)
        return ""
    if not out.exists():
        return ""
    try:
        resp = await vlm(
            messages=[{"role": "user", "content": _END_STATE_VLM_PROMPT}],
            image_paths=[str(out)],
            max_tokens=120,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        return str(content or "").strip().strip('"').strip()
    except Exception as e:
        logger.warning("观察态 VLM 失败,退计划态: %s", e)
        return ""


def _resolve_vlm() -> Any:
    """取 VLM(观察态用,本地 qwen2.5-vl,基本免费;同 verdict 的取用方式)。取不到返回 None。"""
    from obase.provider_registry import ProviderRegistry

    try:
        return ProviderRegistry.get().vlm("default")
    except Exception:
        return None


_ACTION_END_PROMPT = """一个电影动作镜头的画面描述如下:
{action}

请只输出这个动作**完成之后那一瞬间**的静止画面描述(动作的结果态),用于生成结束关键帧。
例:动作是"张飞举剑自刎,刘备扑上夺剑掷地,一把抱住他"→ 结束态是"宝剑被打落在地上,
刘备双手紧紧箍住张飞的肩膀,两人贴在一起"。
只输出一句中文画面描述,不要解释、不要加引号。"""


async def _action_end_state(action: str, llm: Any) -> str:
    """把动作描述拆出"完成态"结束画面(kf2v 的尾帧)。LLM 失败则退化成动作原文 + 完成态提示,
    至少让尾帧 prompt 跟首帧(未完成态)不同,kf2v 才有得插。"""
    if llm is not None and action.strip():

        def _invoke() -> Any:
            return llm(
                messages=[{"role": "user", "content": _ACTION_END_PROMPT.format(action=action)}],
                max_tokens=200,
            )

        try:
            obj = await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=30.0)
            resp = await obj if hasattr(obj, "__await__") else obj
            content = resp.get("content") if hasattr(resp, "get") else str(resp)
            text = str(content or "").strip().strip('"').strip()
            if text:
                return text
        except Exception as e:  # LLM 失败不阻断,退化提示
            logger.warning("动作结束态 LLM 拆解失败,退化: %s", e)
    return f"{action}(动作已完成、结果态)"


async def _gen_action_keyframe(
    *,
    action_ip: Path,
    style: str,
    appear: str,
    emotion: str,
    desc: str,
    out_path: Path,
    engine: str,
    size: tuple[int, int],
    command_summary: str = "",
    scene_space: str = "",
    negative_prompt: str = "",  # INC-002 v0.2:透传到 _edit_keyframe → sdxl 负面词
) -> str:
    """从锁脸参考(action_ip)+ 相貌(appear)生成一张"闭嘴做某动作(desc)"的关键帧,供 kf2v
    的首/中(peak)/尾(aftermath)帧复用。command_summary=§E 该帧的导演命令摘要(必须/优先约束),
    instruction 与 local_prompt **两条引擎路都要给**(此前只给了 instruction,见 _local_kf_prompt)。
    scene_space=SPEC-004 断链#3 场景空间描述(见 _local_kf_prompt)。已存在则跳过(缓存,返回
    _KF_CACHED)。返回实际走通的引擎标签。"""
    if out_path.exists():
        return _KF_CACHED
    return await _edit_keyframe(
        image_path=action_ip,
        instruction=_EDIT_PREFIX
        + emotion
        + ",闭着嘴,动作:"
        + desc
        + _EXPRESSION_GUARD
        + command_summary,
        output_path=out_path,
        fallback_from=action_ip,
        engine=engine,
        local_prompt=_local_kf_prompt(
            style,
            appear,
            emotion,
            desc,
            scene_space=scene_space,
            mouth_closed=True,
            wide=True,
            command_summary=command_summary,
        ),
        ip_adapter_image=action_ip,
        size=size,
        negative_prompt=negative_prompt,
    )


async def build_frame_manifest_avatar(
    shotlist: ShotList,
    script: Script,
    character_bible: CharacterBible,
    constitution: Constitution,
    *,
    run_dir: Path,
    config: LayerConfig | None = None,
) -> FrameManifest:
    """L6 云数字人主入口。逐 shot 出 talking clip,返回 FrameManifest(frames[].clip_path 已填)。"""
    work = run_dir
    work.mkdir(parents=True, exist_ok=True)
    style = _p(config, "style", _DEFAULT_STYLE)
    per_char = float(_p(config, "say_char_sec", 0.32))
    reso = str(_p(config, "resolution", "720P"))
    w, h = _resolve_dimensions(reso, constitution.visual_style.aspect_ratio)
    narr_tone = str(_p(config, "narr_tone", "沉稳"))  # 旁白语气(沉稳/激昂/凝重…)
    narrator_desc = str(_p(config, "narrator_desc", _NARRATOR_DESC))
    # 非对白镜头怎么处理:"narrator"=史官旁白配音(通鉴/短剧默认,行为不变);
    # "silent_action"=纯静默动作/空镜(只有画面动作,不加任何旁白配音)——导演流水线用,
    # 治"全是大头对白、没有场景/动作镜头"(用户要求电影语言:开场空镜、人物动作、
    # 刺杀/擒拿等动作镜头,不要旁白念白)。silent_action 下动作镜头时长按视觉节拍给,
    # 不跟旁白文字长度走。
    non_dialogue_mode = str(_p(config, "non_dialogue_mode", "narrator"))
    # 关键帧引擎开关(用户 2026-07-15 要求可切换、不写死):"local"=本地 sdxl_local+IP-Adapter
    # (免费,默认);"cloud"=云端 qwen-image-edit(精确姿势/多脸更强,随时可切回)。见 _edit_keyframe。
    keyframe_engine = str(_p(config, "keyframe_engine", "local"))
    # 动作镜引擎开关(P3):"kf2v"=动作镜生成起始帧+结束帧→wan2.2-kf2v-flash 插真运动(默认,
    # 治"演不出动作");"i2v"=旧的单帧微动。只作用于非对白的动作镜(有反应链动作),纯场景镜
    # 与对白镜不受影响。见非对白分支。
    action_engine = str(_p(config, "action_engine", "kf2v"))
    # 动作弧采样档(INC-001 §B):"2point"=首帧(trigger)→尾帧(aftermath)单段 kf2v(默认,
    # 零额外成本);"3point"=首帧→关键帧(peak)→尾帧,中间多插一张 peak 关键帧并做两段 kf2v
    # 拼接,动作弧有真正的峰值,但每个动作镜的视频生成调用数翻倍(成本约 2×)。仅当有
    # 结构化 action_beats 时 3point 才生效;无 beats 一律退回单段(现状)。
    action_arc = str(_p(config, "action_arc", "2point"))
    # SPEC-004 断链#3:场景空间描述(scene_id → "环境,光照,氛围",来自 DesignScene)。
    # 桥接层 render_director_episode 经 config.params 传入;不传即空 dict(tongjian 管线行为不变)。
    scene_desc_by_id = _p(config, "scene_desc_by_id", None) or {}
    # SPEC-004 阶段 3:逐镜场事实投影(shot_id → 落位/焦点/正方向,从 SceneStage 确定性投影)。
    shot_space_by_id = _p(config, "shot_space_by_id", None) or {}
    # SPEC-004 v2:逐镜每角色该用的 Subject3D 视图(shot_id → {char_id: front/left/right/back})+
    # 每角色各视图的图片路径(char_id → {view: path})。非正面视图 → 该镜 lead 走 img2img 从该
    # 视图当底图(朝向落地);正面/无 3D 视图 → 退回原 IP-Adapter 路(2D 真照,身份最强)。
    # 都不传(tongjian 管线/未建 3D 视图)→ 空 dict,行为完全不变。
    shot_view_by_id = _p(config, "shot_view_by_id", None) or {}
    subject3d_views_by_id = _p(config, "subject3d_views_by_id", None) or {}
    resolved_llm = _resolve_llm() if action_engine == "kf2v" else None
    # Gap 2:观察态 VLM(看上一镜真实末帧当下一镜承接锚)。可切关(默认开;取不到 VLM 自动退
    # 计划态)。免费本地模型,一镜一次调用,只在同场景连续镜才触发。
    observe_continuity = bool(_p(config, "observe_continuity", True))
    continuity_vlm = _resolve_vlm() if observe_continuity else None

    lines_by_id = {ln.line_id: ln for ln in script.lines}
    appearance_by_id = {
        c.character_id: (c.appearance or c.name) for c in character_bible.characters
    }
    ref_image_by_id = {
        c.character_id: c.ref_image for c in character_bible.characters if c.ref_image
    }
    name_by_id = {c.character_id: c.name for c in character_bible.characters}
    narrator_ref = await _canonical("narrator", narrator_desc, work, style)

    frames: list[ShotFrame] = []
    for idx, shot in enumerate(shotlist.shots):
        sid = shot.shot_id
        # SPEC-004:关键帧空间项 = 场景描述(断链#3,per-scene)+ 逐镜场事实投影(阶段 3,per-shot,
        # 落位/焦点/正方向)。都空则各关键帧退回原行为(向后兼容)。
        scene_space = "；".join(
            x
            for x in (
                str(scene_desc_by_id.get(shot.scene_id, "") or ""),
                str(shot_space_by_id.get(sid, "") or ""),
            )
            if x
        )
        lines = [lines_by_id[lid] for lid in shot.line_ids if lid in lines_by_id]
        text = "".join(ln.text for ln in lines).strip()
        dlg_line = next(
            (ln for ln in lines if ln.type == "dialogue" and ln.speaker != "NARRATOR"), None
        )
        is_dialogue = dlg_line is not None
        lead = (
            dlg_line.speaker if is_dialogue else (shot.characters[0] if shot.characters else None)
        )
        emotion = (
            dlg_line.emotion if dlg_line else (lines[0].emotion if lines else "")
        ) or "神情自然"
        # visual_hint 是剧本里对这一镜具体动作的描述(如"伸手递出玉圭""伏地叩首");
        # 不接入的话 qwen-image-edit 只有 emotion 一个形容词可用,会退化成同一套"拱手肃立"
        # 通用姿势,跟台词描述的具体动作对不上。
        action_hint = (
            dlg_line.visual_hint if dlg_line else (lines[0].visual_hint if lines else "")
        ) or ""
        # INC-001 §B:结构化动作弧 → (trigger, peak, aftermath)。首帧动作源优先取 trigger 拍,
        # 否则退回剧本 visual_hint(现状不变)。尾帧优先取 aftermath 拍(省掉一次 LLM 拆解)。
        _trigger, _peak, _aftermath = _infer_action_phases(list(shot.action_beats or []))
        act_hint = _trigger or action_hint  # 动作镜首帧关键帧的动作描述
        # INC-001 §C:该镜含连续反应链动词 → 关键帧拉到"动作未完成态",治"没有真动作"。
        _incomplete = _incomplete_state_suffix(
            f"{text} {shot.visual_prompt} {action_hint} {' '.join(shot.action_beats or [])}"
        )
        # INC-001 §H:说话者目光看向受话者(eyeline)——target 是桥接层已校验的已锁定角色。
        _eyeline = ""
        if dlg_line and getattr(dlg_line, "target", ""):
            _eyeline = f",目光看向{name_by_id.get(dlg_line.target, dlg_line.target)}"
        # INC-001 §J:同场景连续轴线(必守)+ 相邻镜承接/过渡上下文(优先)。
        _axis = _same_scene_shared(shotlist.shots, idx, shot)
        _carry, _lead_out = _adjacent_context(shotlist.shots, idx)
        # Gap 2:观察态覆盖计划态。上一镜与本镜同场景且已渲出 clip → VLM 看它真实末帧,用观察到
        # 的停留态当承接锚(渲染是顺序的,idx-1 此刻已出片)。**独立于计划态 _carry**:观察态是比
        # 剧本收束拍更强的信号,即便本镜没有计划态 carry(上一镜没写 action_beats/visual_prompt)
        # 也该给。失败则保留计划态 _carry(可能为空)。_observed_carry 记进 debug_context 供排查。
        _observed_carry = ""
        if (
            continuity_vlm is not None
            and idx > 0
            and shot.scene_id
            and shotlist.shots[idx - 1].scene_id == shot.scene_id
        ):
            prev_clip = work / f"{shotlist.shots[idx - 1].shot_id}_clip.mp4"
            _observed_carry = await _observe_end_state(
                prev_clip, continuity_vlm, work / f"{sid}_carry_obs.png"
            )
            if _observed_carry:
                _carry = f"承接上一镜的实际收束态({_observed_carry}),延续其位置、朝向与动作方向"
        # INC-001 §E:各帧的导演命令摘要(必须/优先分级,首/关/尾帧不同)。
        _cmd = {
            role: _director_command_summary(
                frame_role=role,
                incomplete=_incomplete,
                eyeline=_eyeline,
                axis=_axis,
                carry=_carry,
                lead_out=_lead_out,
            )
            for role in ("first", "peak", "aftermath")
        }
        # 走位提示(治"走位乱七八糟"):shot.blocking 已是"角色:位置,朝向"短句,拼进多角色
        # 关键帧指令,让 qwen-image-edit/sdxl 按走位摆人,而不是把人瞎堆到同一画面。
        _blocking_hint = (
            ("。按走位安排各人位置与朝向:" + ";".join(shot.blocking)) if shot.blocking else ""
        )
        # INC-002 §1.1 render 消费:把该时刻(首/关键/尾)的表演切片并进导演命令,一处并入 →
        # 下面 5 个 _cmd[role] 注入点(对白/多角色/动作首帧 + kf2v 关键/尾帧)全自动带上。空 → inert。
        _temporal_role = shot.temporal_by_role or {}
        for _role in ("first", "peak", "aftermath"):
            if _temporal_role.get(_role):
                _cmd[_role] = _cmd[_role] + "。该时刻表演:" + _temporal_role[_role]
        did_kf2v = False  # §K 可观察性用;下面动作镜分支若走 kf2v 会置 True
        # 关键帧真伪追踪:kf_source=本轮实际走通的引擎(缓存命中/纯场景镜则留 ""),
        # kf_canon=该镜关键帧对应的 canon(供 _is_canon_copy 字节比对,权威判据)。
        kf_source = ""
        kf_canon: Path | None = None
        _layout_base: Path | None = None  # Gap 1:多角色走位几何底图,命中则记进 debug_context
        _pose_control: Path | None = None  # Gap 1 阶段2:骨架控制图(已产出,worker 消费端待接)
        dur = _say_dur(text or shot.visual_prompt, per_char)
        clip = work / f"{sid}_clip.mp4"

        try:
            if clip.exists():
                pass
            elif is_dialogue and lead:
                # 对白:角色 keyframe(qwen-image-edit 上情绪+动作)→ happyhorse 说台词
                canon = await _canonical(
                    lead,
                    appearance_by_id.get(lead, lead),
                    work,
                    style,
                    ref_image=ref_image_by_id.get(lead),
                )
                kf_canon = canon
                kf = work / f"{sid}_kf.png"
                if not kf.exists():
                    instruction = _EDIT_PREFIX + emotion
                    if action_hint:
                        instruction += f",动作:{action_hint}"
                    instruction += _EXPRESSION_GUARD + _cmd["first"]
                    # SPEC-004 v2:lead 该镜的 Subject3D 视图非正面且已建 → img2img 从该视图当底图
                    # (朝向落地);否则 init_view=None → 走原 IP-Adapter(2D 真照,身份最强)。
                    _view = shot_view_by_id.get(sid, {}).get(lead, "front")
                    _init_view = (
                        subject3d_views_by_id.get(lead, {}).get(_view)
                        if _view and _view != "front"
                        else None
                    )
                    kf_source = await _edit_keyframe(
                        image_path=canon,
                        instruction=instruction,
                        output_path=kf,
                        fallback_from=canon,
                        engine=keyframe_engine,
                        local_prompt=_local_kf_prompt(
                            style,
                            appearance_by_id.get(lead, lead),
                            emotion,
                            action_hint,
                            scene_space=scene_space,
                            command_summary=_cmd["first"],
                        ),
                        ip_adapter_image=canon,
                        init_image=Path(_init_view) if _init_view else None,
                        size=(w, h),
                        negative_prompt=shot.negative_prompt,
                    )
                talk = work / f"{sid}_talk.mp4"
                if not talk.exists():
                    text_chunks = _split_text_for_dialogue(text, per_char)
                    if len(text_chunks) == 1:
                        await happyhorse_animate(
                            image_path=kf,
                            prompt=f"{style},保持画风不变,画中人物{emotion},"
                            f'郑重说道:"{text}",嘴巴随说话自然清晰地张合',
                            output_path=talk,
                            duration=dur,
                            resolution=reso,
                        )
                    else:
                        # 台词太长,单个 clip 撑不下(会被迫用不自然的语速念完)——按标点切
                        # 成几段分别渲染再首尾拼接,每段都在 happyhorse 的时长硬顶以内。
                        chunk_clips = []
                        for i, chunk in enumerate(text_chunks):
                            chunk_out = work / f"{sid}_talk_{i + 1:02d}.mp4"
                            if not chunk_out.exists():
                                await happyhorse_animate(
                                    image_path=kf,
                                    prompt=f"{style},保持画风不变,画中人物{emotion},"
                                    f'郑重说道:"{chunk}",嘴巴随说话自然清晰地张合',
                                    output_path=chunk_out,
                                    duration=_say_dur(chunk, per_char),
                                    resolution=reso,
                                )
                            chunk_clips.append(chunk_out)
                        _concat_clips(chunk_clips, talk)
                _fit_dialogue(talk, clip, w, h)
            else:
                # 非对白镜头:先出"静默动作/空镜"画面(vis)——角色闭嘴做动作 or 纯场景
                # 空镜。再按 non_dialogue_mode 决定挂史官旁白配音,还是纯静默(见 vis 之后)。
                vis = work / f"{sid}_vis.mp4"
                if not vis.exists():
                    present = [cid for cid in shot.characters if cid in appearance_by_id]
                    # P3 动作镜:首帧=已生成的 kf(未完成态),尾帧另生成;下面按分支填 action_ip
                    # (kf2v 尾帧用的锁脸参考)+ action_appear(尾帧 prompt 的人物相貌)。
                    action_ip: Path | None = None
                    action_appear = ""
                    if len(present) >= 2:
                        # 多角色同框(2026-07-13 真实反馈:provider 的 i2v/happyhorse 每镜
                        # 只吃1张参考图,此前这里跟对白分支一样只锁 shot.characters[0],
                        # 同框的其他角色完全没有身份锚点,靠模型瞎猜脸)。qwen-image-edit
                        # 官方文档实测确认支持1-3张输入图的多图融合——在"出关键帧"这一步
                        # 把每个在场角色的真实 canonical 像都传进去合成同一张图,i2v 只需要
                        # 吃这一张已经每张脸都对的合成关键帧,不需要 provider 支持多图。
                        # 硬上限3张(qwen-image-edit 的 API 约束),超出的角色仍靠文字描述,
                        # 不再新起一个模型请求把限制推到别处。
                        present = present[:3]
                        canons = [
                            await _canonical(
                                cid,
                                appearance_by_id.get(cid, cid),
                                work,
                                style,
                                ref_image=ref_image_by_id.get(cid),
                            )
                            for cid in present
                        ]
                        kf_canon = canons[0]
                        # Gap 1 阶段1:多角色走位几何底图。每个在场角色的 Subject3D 朝向视图按
                        # 走位落位合成一张 img2img 底图(≥2 张视图才产;任一角色无视图 → None,退
                        # 回原文本路)。命中时 IP-Adapter 让位给 img2img(worker 约束),几何换锁脸。
                        _views_for_shot = shot_view_by_id.get(sid, {})
                        _view_path_by_cid: dict[str, Path] = {}
                        for cid in present:
                            v = _views_for_shot.get(cid, "front")
                            vp = (
                                subject3d_views_by_id.get(cid, {}).get(v)
                                if v and v != "front"
                                else None
                            )
                            if vp:
                                _view_path_by_cid[cid] = Path(vp)
                        _pos_desc_by_cid = _parse_blocking_positions(
                            shot.blocking, present, name_by_id
                        )
                        _layout_base = _compose_layout_base(
                            present=present,
                            view_path_by_cid=_view_path_by_cid,
                            pos_desc_by_cid=_pos_desc_by_cid,
                            size=(w, h),
                            out_path=work / f"{sid}_layout.png",
                        )
                        # Gap 1 阶段2 地基:骨架控制图。毫秒级纯 CPU,先备好放盘上;真正吃它的
                        # ControlNet worker 分支未接(见 sdxl_local_service controlnet TODO),等
                        # 权重下宿主机 + GPU 修好即用。与阶段1 底图互补(底图给相貌,骨架给站位)。
                        _pose_control = _compose_pose_control(
                            present=present,
                            pos_desc_by_cid=_pos_desc_by_cid,
                            size=(w, h),
                            out_path=work / f"{sid}_pose.png",
                        )
                        kf = work / f"{sid}_kf.png"
                        if not kf.exists():
                            names = "、".join(name_by_id.get(cid, cid) for cid in present)
                            instruction = (
                                f"这{len(present)}张图分别是{names}各自的真实长相,"
                                f"把他们合成到同一个画面里{_blocking_hint},每个人物的相貌、服饰、画风都要"
                                f"跟各自对应的参考图保持一致,神情{emotion},都闭着嘴"
                            )
                            if act_hint:
                                instruction += f",动作:{act_hint}"
                            instruction += _EXPRESSION_GUARD + _cmd["first"]
                            kf_source = await _edit_keyframe(
                                image_path=canons,
                                instruction=instruction,
                                output_path=kf,
                                fallback_from=canons[0],
                                engine=keyframe_engine,
                                # 本地 IP-Adapter 只吃 1 张参考,只能锁 lead 一张脸,其余角色
                                # 靠文字描述(多脸精确合成是云端 edit 的强项,可切 cloud)。
                                local_prompt=_local_kf_prompt(
                                    style,
                                    f"{names}同框:"
                                    + "、".join(appearance_by_id.get(cid, cid) for cid in present)
                                    + _blocking_hint,
                                    emotion,
                                    act_hint,
                                    scene_space=scene_space,
                                    mouth_closed=True,
                                    wide=True,
                                    command_summary=_cmd["first"],
                                ),
                                ip_adapter_image=canons[0],
                                # 有走位底图 → img2img 从它起(几何软约束);无 → None,走原
                                # 多图 edit + IP-Adapter lead 锁脸路。
                                init_image=_layout_base,
                                size=(w, h),
                                negative_prompt=shot.negative_prompt,
                            )
                        vis_src = kf
                        action_ip = canons[0]
                        action_appear = f"{names}同框:" + "、".join(
                            appearance_by_id.get(cid, cid) for cid in present
                        )
                        motion = f"人物{emotion},细微神态与身体动作,闭着嘴不说话"
                    elif lead:
                        canon = await _canonical(
                            lead,
                            appearance_by_id.get(lead, lead),
                            work,
                            style,
                            ref_image=ref_image_by_id.get(lead),
                        )
                        kf_canon = canon
                        kf = work / f"{sid}_kf.png"
                        if not kf.exists():
                            instruction = _EDIT_PREFIX + emotion + ",闭着嘴"
                            if act_hint:
                                instruction += f",动作:{act_hint}"
                            instruction += _EXPRESSION_GUARD + _cmd["first"]
                            kf_source = await _edit_keyframe(
                                image_path=canon,
                                instruction=instruction,
                                output_path=kf,
                                fallback_from=canon,
                                engine=keyframe_engine,
                                local_prompt=_local_kf_prompt(
                                    style,
                                    appearance_by_id.get(lead, lead),
                                    emotion,
                                    act_hint,
                                    scene_space=scene_space,
                                    mouth_closed=True,
                                    wide=True,
                                    command_summary=_cmd["first"],
                                ),
                                ip_adapter_image=canon,
                                size=(w, h),
                                negative_prompt=shot.negative_prompt,
                            )
                        vis_src = kf
                        action_ip = canon
                        action_appear = appearance_by_id.get(lead, lead)
                        motion = f"人物{emotion},细微神态与身体动作,闭着嘴不说话"
                    else:
                        scene = work / f"{sid}_scene.png"
                        if not scene.exists():
                            await qwen_image_generate(
                                prompt=f"{style},{shot.visual_prompt}",
                                output_path=scene,
                                size="1280*720",
                            )
                        vis_src = scene
                        motion = "画面细微流动,烟云飘动"
                    # P3 动作镜:有动作弧(结构化 action_beats 或反应链动词)+ 锁脸参考 + kf2v
                    # 引擎 → 关键帧序列喂 wan2.2-kf2v-flash 插出真运动,治"演不出动作"。首帧
                    # (kf,trigger/未完成态)已在上面出好;尾帧取 aftermath 拍(§B,有则省一次
                    # LLM),否则 LLM 拆完成态。action_arc="3point" 且有独立 peak 拍时,中间多插
                    # 一张 peak 关键帧做两段拼接(成本翻倍,默认关)。纯场景镜/i2v 引擎走旧单帧微动。
                    did_kf2v = False
                    if (
                        action_engine == "kf2v"
                        and action_ip is not None
                        and (_incomplete or shot.action_beats)
                        and vis_src == kf
                    ):
                        action_desc = act_hint or text or shot.visual_prompt
                        end_kf = work / f"{sid}_kf_end.png"
                        if not end_kf.exists():
                            end_desc = _aftermath or await _action_end_state(
                                action_desc, resolved_llm
                            )
                            await _gen_action_keyframe(
                                action_ip=action_ip,
                                style=style,
                                appear=action_appear,
                                emotion=emotion,
                                desc=end_desc,
                                out_path=end_kf,
                                engine=keyframe_engine,
                                size=(w, h),
                                command_summary=_cmd["aftermath"],
                                scene_space=scene_space,
                                negative_prompt=shot.negative_prompt,
                            )
                        # 关键帧序列:首帧(trigger)→[peak]→尾帧(aftermath)。
                        seq = [kf]
                        if action_arc == "3point" and _peak and _peak != _aftermath:
                            peak_kf = work / f"{sid}_kf_peak.png"
                            await _gen_action_keyframe(
                                action_ip=action_ip,
                                style=style,
                                appear=action_appear,
                                emotion=emotion,
                                desc=_peak,
                                out_path=peak_kf,
                                engine=keyframe_engine,
                                size=(w, h),
                                command_summary=_cmd["peak"],
                                scene_space=scene_space,
                                negative_prompt=shot.negative_prompt,
                            )
                            seq.append(peak_kf)
                        seq.append(end_kf)
                        pairs = list(pairwise(seq))
                        seg_dur = min(5.0, max(3.0, float(dur) / len(pairs)))
                        try:
                            seg_clips: list[Path] = []
                            for i, (a, b) in enumerate(pairs):
                                seg_out = vis if len(pairs) == 1 else work / f"{sid}_seg{i + 1}.mp4"
                                if not seg_out.exists():
                                    await alibaba_maas_keyframe_generate(
                                        first_frame=a,
                                        last_frame=b,
                                        output_path=seg_out,
                                        prompt=f"{style},{action_desc}",
                                        resolution=reso,
                                        duration_s=seg_dur,
                                    )
                                seg_clips.append(seg_out)
                            if len(seg_clips) > 1:
                                _concat_clips(seg_clips, vis)
                            did_kf2v = True
                        except Exception as e:
                            logger.warning("kf2v 首尾帧生视频失败,退 i2v 单帧微动: %s", e)
                    if not did_kf2v:
                        await i2v_animate(
                            image_path=vis_src,
                            prompt=f"{style}保持不变,{motion}",
                            output_path=vis,
                            resolution=reso,
                        )
                if non_dialogue_mode == "silent_action":
                    # 纯静默动作/空镜:不加任何旁白配音,只保留画面动作(电影建场/动作镜头)。
                    # 时长按视觉节拍(封顶 6s),不跟旁白文字长度走。
                    _fit_silent(vis, clip, w, h, min(float(dur), 6.0))
                else:
                    # 史官旁白配音(通鉴/短剧默认):旁白 talking clip → 抽音轨 → 挂到 vis 上。
                    narr = work / f"{sid}_narr.mp4"
                    _narr_text = text or shot.visual_prompt
                    if not narr.exists():
                        await happyhorse_animate(
                            image_path=narrator_ref,
                            prompt=f'{style},一位史官说书人{narr_tone}地讲述:"{_narr_text}"',
                            output_path=narr,
                            duration=dur,
                            resolution=reso,
                        )
                    narr_audio = work / f"{sid}_narr.aac"
                    if not narr_audio.exists():
                        subprocess.run(
                            [
                                "ffmpeg",
                                "-y",
                                "-i",
                                str(narr),
                                "-vn",
                                "-acodec",
                                "copy",
                                str(narr_audio),
                            ],
                            check=True,
                            capture_output=True,
                        )
                    _fit_narration(vis, narr_audio, clip, w, h)

            first = work / f"{sid}_first.png"
            _extract_frame(clip, first)
            consistency = None
            if lead:
                canon_path = work / f"canon_{lead}.png"
                if canon_path.exists():
                    consistency = _score_consistency(first, canon_path)
            # INC-001 §K:关键帧编译的 decision_trail(实际用了哪些风格/情绪/动作弧阶段/视线/轴线)。
            debug_context = {
                "style": style,
                "emotion": emotion,
                "is_dialogue": is_dialogue,
                "lead": lead,
                "action_hint": act_hint,
                "action_beats": list(shot.action_beats or []),
                "phases": {"trigger": _trigger, "peak": _peak, "aftermath": _aftermath},
                "frame_consumes": (
                    {"keyframe": "trigger"}
                    if is_dialogue
                    else {
                        "first": "trigger",
                        "peak": (
                            "peak"
                            if action_arc == "3point" and _peak and _peak != _aftermath
                            else None
                        ),
                        "last": "aftermath",
                    }
                ),
                "eyeline": _eyeline.lstrip("，,"),
                "same_scene_axis": _axis,
                "carry": _carry,
                "lead_out": _lead_out,
                # Gap 2:非空=承接锚来自 VLM 观察上一镜真实末帧(非计划态文本)。
                "observed_carry": _observed_carry,
                "action_arc": action_arc,
                "keyframe_source": kf_source,  # 实际走通的引擎(见 _KF_*)
                # Gap 1:多角色走位几何底图是否命中(None=退回文本路,没有几何约束)。
                "layout_base": bool(_layout_base),
                "pose_control": bool(_pose_control),  # 阶段2 骨架控制图已备(消费端 worker 待接)
            }
            # §K 可观察性。**判据是"导演命令是否真落进了实际用的那张关键帧",不是"这个字符串
            # 构造成功了"**——旧版按 bool(_eyeline) 报 eyeline_applied,而 _eyeline 只进云端
            # instruction、不进默认的 local prompt(F-0),于是全是假阳性,这个断链因此半个月没
            # 被任何验收抓到(2026-07-17 审计)。现在两条引擎路都注入了,只剩"抄了 canon 定妆照
            # = 这一镜压根没有关键帧"这一种落空,故统一以 kf_degraded 折算。
            kf_degraded = kf_source == _KF_CANON_COPY or _is_canon_copy(
                work / f"{sid}_kf.png", kf_canon
            )
            kf_landed = not kf_degraded
            quality_checks = {
                "incomplete_state_applied": bool(_incomplete) and kf_landed,  # §C
                "eyeline_applied": bool(_eyeline) and kf_landed,  # §H
                "continuity_applied": bool(_axis or _carry or _lead_out) and kf_landed,  # §J
                "kf2v_action_arc": bool(did_kf2v),  # §B(真动作弧生视频)
                "has_action_beats": bool(shot.action_beats),
                "keyframe_degraded": kf_degraded,  # True = 抄了定妆照,导演层未落地
            }
            frames.append(
                ShotFrame(
                    shot_id=sid,
                    scene_id=shot.scene_id,
                    clip_path=str(clip),
                    frame_path=str(first),
                    characters=shot.characters,
                    character_consistency=consistency,
                    # 抄了定妆照 = 走了降级链(与"生成失败退空镜"同级),据此进 verdict 返工闸。
                    # 身份分对这一镜必然满分(它就是那张 canon),挡不住;必须靠这条标出来。
                    degraded=kf_degraded,
                    degrade_reason=(_KF_DEGRADE_REASON if kf_degraded else ""),
                    debug_context=debug_context,
                    quality_checks=quality_checks,
                )
            )
            logger.info(
                "[avatar %s] %s dur~%ds → %s%s",
                sid,
                "对白" if is_dialogue else "旁白/场景",
                dur,
                clip.name,
                "(关键帧降级:定妆照)" if kf_degraded else "",
            )
        except Exception as e:
            logger.warning("[avatar %s] 生成失败,降级空镜: %s", sid, e)
            frames.append(
                ShotFrame(
                    shot_id=sid,
                    scene_id=shot.scene_id,
                    characters=shot.characters,
                    degraded=True,
                    degrade_reason=f"avatar 生成失败: {e}",
                )
            )

    return FrameManifest(frames=frames)


def _audio_video_dur(clip: Path) -> tuple[float, float, float]:
    """返回 (视频时长, 音频时长, 音频 mean_volume dB)。无音轨则音频时长/音量为 0/-91。"""
    import subprocess

    def _dur(sel: str) -> float:
        out = (
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    sel,
                    "-show_entries",
                    "stream=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(clip),
                ],
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .splitlines()
        )
        return float(out[0]) if out and out[0] not in ("", "N/A") else 0.0

    vol = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(clip),
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "/dev/null",
        ],
        capture_output=True,
        text=True,
    ).stderr
    mean = -91.0
    for ln in vol.splitlines():
        if "mean_volume:" in ln:
            try:
                mean = float(ln.split("mean_volume:")[1].strip().split()[0])
            except Exception:
                pass
    return _dur("v:0"), _dur("a:0"), mean


def gate_avatar_manifest(manifest: FrameManifest) -> GateResult:
    """avatar 成片门禁(影响观感的语音/口型/音画同步项,确定性检查,不阻塞):
    - 每镜 talking clip **有人声**(mean_volume > -40dB);
    - **音画不脱节**(|视频时长 - 音频时长| ≤ 1.0s;抓"口型比语音慢/快"那类偏移);
    - 无 clip 的镜头(降级)计入 warnings。
    (逐字口型/CER 需 ASR,留待接入 ASR 后细化;此处先给确定性代理指标。)
    """
    errors: list[str] = []
    warnings: list[str] = []
    checked = 0
    for f in manifest.frames:
        if not f.clip_path:
            warnings.append(f"{f.shot_id}: 无 talking clip(已降级)")
            continue
        checked += 1
        try:
            vdur, adur, mean = _audio_video_dur(Path(f.clip_path))
        except Exception as e:
            warnings.append(f"{f.shot_id}: 探测失败 {e}")
            continue
        if mean <= -40.0:
            errors.append(f"{f.shot_id}: 疑似无人声(mean_volume={mean:.0f}dB)")
        if adur > 0 and abs(vdur - adur) > 1.0:
            errors.append(f"{f.shot_id}: 音画时长偏移 {vdur - adur:+.1f}s(口型/配音不同步)")
    coverage = checked / len(manifest.frames) if manifest.frames else 1.0
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)
