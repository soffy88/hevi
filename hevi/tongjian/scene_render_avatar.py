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

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.image.qwen_image_service import QwenImageError, qwen_image_edit, qwen_image_generate
from hevi.tongjian.schemas import (
    CharacterBible,
    Constitution,
    FrameManifest,
    LayerConfig,
    Script,
    ShotFrame,
    ShotList,
)
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


async def _edit_keyframe(
    *,
    image_path: Path | list[Path],
    instruction: str,
    output_path: Path,
    fallback_from: Path,
) -> Path:
    """出关键帧:qwen-image-edit 把该镜情绪+动作叠到 canonical 像上。

    **降级路线(用户 2026-07-15 决定:不为 qwen-image-edit 开付费)**:edit 不可用时——
    典型是免费额度墙 `AllocationQuota.FreeTierOnly`(账户开了「仅使用免费额度」),也含其它
    生成失败——直接复制 canonical 像当关键帧。身份/画风保住(用的是真 canon 脸),只是少了
    "把情绪/动作烤进关键帧"那步(happyhorse 后面仍会加口型+表情),整镜不至于降级空镜、
    整集不至于卡在 G6 装配门。多角色镜头降级只保 lead 一张脸(fallback_from 传 canons[0])。"""
    try:
        return await qwen_image_edit(
            image_path=image_path, instruction=instruction, output_path=output_path
        )
    except QwenImageError as e:
        logger.warning(
            "qwen-image-edit 不可用,关键帧降级直接用 canonical 像(%s): %s", fallback_from.name, e
        )
        shutil.copyfile(fallback_from, output_path)
        return output_path


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
    for shot in shotlist.shots:
        sid = shot.shot_id
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
        # INC-001 §C:该镜含连续反应链动词 → 关键帧拉到"动作未完成态",治"没有真动作"。
        _incomplete = _incomplete_state_suffix(f"{text} {shot.visual_prompt} {action_hint}")
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
                kf = work / f"{sid}_kf.png"
                if not kf.exists():
                    instruction = _EDIT_PREFIX + emotion
                    if action_hint:
                        instruction += f",动作:{action_hint}"
                    instruction += _EXPRESSION_GUARD + _incomplete
                    await _edit_keyframe(
                        image_path=canon,
                        instruction=instruction,
                        output_path=kf,
                        fallback_from=canon,
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
                        kf = work / f"{sid}_kf.png"
                        if not kf.exists():
                            names = "、".join(name_by_id.get(cid, cid) for cid in present)
                            instruction = (
                                f"这{len(present)}张图分别是{names}各自的真实长相,"
                                f"把他们合成到同一个画面里,每个人物的相貌、服饰、画风都要"
                                f"跟各自对应的参考图保持一致,神情{emotion},都闭着嘴"
                            )
                            if action_hint:
                                instruction += f",动作:{action_hint}"
                            instruction += _EXPRESSION_GUARD + _incomplete
                            await _edit_keyframe(
                                image_path=canons,
                                instruction=instruction,
                                output_path=kf,
                                fallback_from=canons[0],
                            )
                        vis_src = kf
                        motion = f"人物{emotion},细微神态与身体动作,闭着嘴不说话"
                    elif lead:
                        canon = await _canonical(
                            lead,
                            appearance_by_id.get(lead, lead),
                            work,
                            style,
                            ref_image=ref_image_by_id.get(lead),
                        )
                        kf = work / f"{sid}_kf.png"
                        if not kf.exists():
                            instruction = _EDIT_PREFIX + emotion + ",闭着嘴"
                            if action_hint:
                                instruction += f",动作:{action_hint}"
                            instruction += _EXPRESSION_GUARD + _incomplete
                            await _edit_keyframe(
                                image_path=canon,
                                instruction=instruction,
                                output_path=kf,
                                fallback_from=canon,
                            )
                        vis_src = kf
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
            frames.append(
                ShotFrame(
                    shot_id=sid,
                    scene_id=shot.scene_id,
                    clip_path=str(clip),
                    frame_path=str(first),
                    characters=shot.characters,
                    character_consistency=consistency,
                )
            )
            logger.info(
                "[avatar %s] %s dur~%ds → %s",
                sid,
                "对白" if is_dialogue else "旁白/场景",
                dur,
                clip.name,
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
    from hevi.tongjian.schemas import GateResult

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
