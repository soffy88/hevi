"""通鉴 V2 讲解段写实渲染(SPEC-005-V2 固化,2026-07-24)。

讲解段(narration)不走 produce_v2 多角色参考图路径,走 **qwen-image 写实静帧 + ffmpeg 确定性
推拉运镜 + 旁白 VO** —— 便宜(一张几分钱,非视频)、GPU 免费(edge_tts/ffmpeg),且和演绎段同引擎
调性(qwen-image 也是演绎段 canon/空景板用的引擎)。

★★ 跨栈接缝能接上的根本原因(写进代码,别再踩):**讲解段与演绎段必须共用同一份 `world_bible`**
——讲解静帧的负面约束用 `world_bible.visual.negative_list`(考据 negatives:禁砖砌拱券/明清冠服/
纸/马镫…),画风锚用 `world_bible.visual.style_render_directive`(historical directive)。演绎段的
canon/生成也读同一份 world_bible。两栈同源同调,才不会出现"讲解水墨插画 vs 演绎写实照片"那种硬切
落差(2026-07-24 商鞅立木实证:讲解一开始用手写 negatives→飞檐/砖穿帮 + 早期 sdxl 版水墨插画→接缝
严重跳;改共用 world_bible + qwen-image 写实后,接缝 smooth)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# 讲解静帧的写实历史正剧取景框(具体画风/考据由 world_bible directive + negatives 决定,这里只定
# "写实电影空景"的通用框,不写死时代——时代靠 world_bible)。
_JIANGJIE_FRAME_FRAMING = "写实历史正剧电影空景,胶片实拍质感,大景深纵深构图,自然光,写实照片级"


def _jiangjie_prompt(visual_prompt: str, world_bible: Any) -> str:
    """讲解静帧 prompt = 写实取景框 + 这镜视觉描述 + world_bible 画风锚(共用,见模块 docstring)。"""
    directive = ""
    if world_bible is not None:
        directive = getattr(world_bible.visual, "style_render_directive", "") or ""
    parts = [_JIANGJIE_FRAME_FRAMING, visual_prompt.strip()]
    if directive:
        parts.append(directive)
    return ",".join(p for p in parts if p)


def _jiangjie_negatives(world_bible: Any) -> str:
    """★ 讲解静帧负面 = 演绎段同一份 world_bible 的 negative_list(考据 negatives 共用)。"""
    if world_bible is None:
        return ""
    return ",".join(getattr(world_bible.visual, "negative_list", []) or [])


async def render_jiangjie_clip(
    *,
    visual_prompt: str,
    narration_text: str,
    world_bible: Any,
    out_dir: Path,
    clip_id: str,
    drift_sign: int = 1,
    width: int = 720,
    height: int = 1280,
    fps: int = 24,
    seed: int = 42,
    voice: str = "zh-CN-YunjianNeural",
    image_gen_fn: Any = None,
    tts_fn: Any = None,
) -> Path:
    """渲一个讲解镜 → clip(qwen-image 写实静帧 + 旁白 VO + ffmpeg 确定性推拉,归一到 w×h@fps)。

    `world_bible`:**必须传演绎段同一份**(negatives + directive 共用,见模块 docstring)。
    `image_gen_fn`/`tts_fn`:依赖注入(默认 qwen_image_generate / edge_tts_synthesize_smart),供测试
    替身。返回 clip 路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = out_dir / f"{clip_id}.png"
    vo = out_dir / f"{clip_id}.mp3"
    clip = out_dir / f"{clip_id}.mp4"

    if image_gen_fn is None:
        from hevi.image.qwen_image_service import qwen_image_generate

        image_gen_fn = qwen_image_generate
    if tts_fn is None:
        from hevi.audio.edge_tts_custom import edge_tts_synthesize_smart

        tts_fn = edge_tts_synthesize_smart

    await image_gen_fn(
        prompt=_jiangjie_prompt(visual_prompt, world_bible),
        output_path=frame,
        seed=seed,
        negative_prompt=_jiangjie_negatives(world_bible),
    )
    from hevi.tongjian.schemas import ScriptLine

    await tts_fn(
        script=[
            ScriptLine(line_id=clip_id, type="narration", speaker="NARRATOR", text=narration_text)
        ],
        output_path=vo,
        voice=voice,
        emotion=None,
    )
    dur = _probe_duration(vo)
    _kenburns(frame, vo, clip, dur, drift_sign, width, height, fps)
    return clip


def _probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    ).strip()
    return float(out)


def _kenburns(
    frame: Path, vo: Path, out: Path, dur: float, drift_sign: int, w: int, h: int, fps: int
) -> None:
    """静帧 → clip:确定性缓推 + 轻微水平漂移(drift_sign 交替避免全片同向),归一 w×h@fps + 挂 VO。"""
    frames = int(dur * fps)
    drift = "+on*0.3" if drift_sign >= 0 else "-on*0.3"
    zp = (
        f"scale={w * 2}:{h * 2},zoompan=z='min(zoom+0.0006,1.12)':d={frames}:"
        f"x='iw/2-(iw/zoom/2){drift}':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},format=yuv420p"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(frame),
            "-i",
            str(vo),
            "-vf",
            zp,
            "-t",
            f"{dur:.2f}",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "128k",
            "-shortest",
            "-r",
            str(fps),
            str(out),
        ],
        check=True,
    )
