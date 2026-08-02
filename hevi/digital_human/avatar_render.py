"""通用云数字人渲染服务 — 3O §3 Task 3.2 抽离自 hevi/tongjian/scene_render_avatar.py。

与通鉴史实无关的通用渲染原语(Scale/Crop/FPS 过滤链、clip 拼接、抽帧、一致性打分、
时长探测)收拢于此;tongjian 通道仅通过本服务函数调用,保留其水墨/卡通风格切换能力。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# resolution 分档(前端下拉直接给这些键)→ 横屏画幅(宽,高)。
_RES = {"480P": (854, 480), "720P": (1280, 720), "1080P": (1920, 1080)}


def probe_duration(path: Path) -> float:
    """ffprobe 实测媒体时长(秒)。"""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


def resolve_dimensions(resolution: str, aspect_ratio: str) -> tuple[int, int]:
    """resolution 分档 + aspect_ratio → 最终交付画幅。

    2026-07-12 真实撞见:短剧设计上是 9:16 竖屏(手机观看),但此前这里只按 _RES
    出横屏尺寸,aspect_ratio 字段设了从没人读过——真实跑出来的成片是 1280×720
    横屏。happyhorse/i2v 底层云端 API 的 resolution 参数只是画质分档(480P/720P/
    1080P),不控制横竖(见 dashscope_i2v_service.py),真正决定最终画幅的是
    fit_dialogue_clip/fit_narration_clip 那步 ffmpeg scale+crop——所以只需要把交付
    宽高按 aspect_ratio 转置,不用碰 API 调用本身。
    """
    w, h = _RES.get(resolution, _RES["720P"])
    return (h, w) if aspect_ratio == "9:16" else (w, h)


def fit_dialogue_clip(clip: Path, out: Path, w: int, h: int) -> None:
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


def fit_narration_clip(visual: Path, audio: Path, out: Path, w: int, h: int) -> None:
    """旁白:画面循环填满旁白音轨时长(不冻结)+ zoompan;挂旁白音轨,输出 w×h。"""
    hold = probe_duration(audio) + 0.4
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


def fit_silent_clip(visual: Path, out: Path, w: int, h: int, duration: float) -> None:
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


def concat_clips(clips: list[Path], out: Path) -> None:
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


def extract_frame(clip: Path, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "0", "-i", str(clip), "-frames:v", "1", str(out)],
        check=True,
        capture_output=True,
    )


def score_consistency(frame_path: Path, canon_path: Path) -> float | None:
    """镜头首帧 vs canonical 的 CLIP 余弦相似度——身份漂移信号(复用 verdict 主管线
    同一套打分原语 subject_embed/cosine_similarity,见 hevi/verdict/scorecard.py)。
    抽帧/嵌入失败 → None,不阻断渲染,只是这一帧没有漂移信号。
    """
    from hevi.subjects.subject_embed import SubjectEmbedError, cosine_similarity, subject_embed

    try:
        frame_emb = subject_embed(image_path=frame_path, kind="style")
        canon_emb = subject_embed(image_path=canon_path, kind="style")
        return cosine_similarity(frame_emb, canon_emb)
    except SubjectEmbedError as e:
        logger.warning(
            "avatar_render: consistency score 失败(%s vs %s): %s",
            frame_path,
            canon_path,
            e,
        )
        return None
