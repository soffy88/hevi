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

**画风由 `params.style` 统一驱动**(默认 `_DEFAULT_STYLE` = 国画水墨),前端可切换成
其它风格预设(如卡通动画)——所有 prompt 拼接点都从这一个变量取词,不再各处写死
"国画水墨"(2026-07-12 前是写死的,现代观众/小孩不吃这套,故改成可切换)。

可调参数(LayerConfig.params):
  style(画风词,默认水墨)/resolution/watermark/crossfade(留给 L8)/seed/say_char_sec(每字秒数)。
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from hevi.image.qwen_image_service import qwen_image_edit, qwen_image_generate
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

_DEFAULT_STYLE = "国画水墨写意人物画,单色水墨,写意笔触,宣纸质感"
# 人物角色描述本身跟画风解耦——style 参数已经在 _canonical() 里前缀画风,这里只留
# 外貌/身份描述,不再重复写死"国画水墨",否则跟卡通等其它 style 预设叠在一起会打架。
_NARRATOR_DESC = (
    "一位年长儒雅的说书人史官,须发斑白,身着素色长袍,面容睿智平和,"
    "正襟危坐,近景半身像,身后淡淡书卷与薄雾"
)
# 描述的是"人物本身"(古装说书人史官),不是画风形容词——跟 style 一样解耦,可通过
# LayerConfig.params["narrator_desc"] 按调用方覆盖(短剧走"现代都市"风格,旁白该是
# 当代讲述者而不是古装史官,见 tongjian_bridge.py 的 DEFAULT_SHORTDRAMA_NARRATOR_DESC)。
_EDIT_PREFIX = "严格保持画中人物的相貌、胡须、服饰、头冠和画风完全不变,只改变神态动作:"


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

    lines_by_id = {ln.line_id: ln for ln in script.lines}
    appearance_by_id = {
        c.character_id: (c.appearance or c.name) for c in character_bible.characters
    }
    ref_image_by_id = {
        c.character_id: c.ref_image for c in character_bible.characters if c.ref_image
    }
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
                    await qwen_image_edit(image_path=canon, instruction=instruction, output_path=kf)
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
                # 旁白/场景:史官音轨 + 画面(角色闭嘴 or 纯场景空镜)
                narr = work / f"{sid}_narr.mp4"
                if not narr.exists():
                    await happyhorse_animate(
                        image_path=narrator_ref,
                        prompt=f'{style},一位史官说书人{narr_tone}地讲述:"{text or shot.visual_prompt}"',
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
                vis = work / f"{sid}_vis.mp4"
                if not vis.exists():
                    if lead:
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
                            await qwen_image_edit(
                                image_path=canon,
                                instruction=instruction,
                                output_path=kf,
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
        except Exception as e:  # noqa: BLE001 —— 单镜失败不拖垮整条,标降级
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


def gate_avatar_manifest(manifest: FrameManifest) -> "GateResult":
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
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{f.shot_id}: 探测失败 {e}")
            continue
        if mean <= -40.0:
            errors.append(f"{f.shot_id}: 疑似无人声(mean_volume={mean:.0f}dB)")
        if adur > 0 and abs(vdur - adur) > 1.0:
            errors.append(f"{f.shot_id}: 音画时长偏移 {vdur - adur:+.1f}s(口型/配音不同步)")
    coverage = checked / len(manifest.frames) if manifest.frames else 1.0
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)
