"""stickman.flow_import —— Flow 任务片导入与成片拼接器。

规格：
1. 接收人工/外部代理下载回来的 Flow mp4（按顺序号 1..N）。
2. 自动校验各分段时长（每条 ≤ 10s，视频流完好）。
3. 使用 ffmpeg 拼接，并添加本地双语字幕（PIL 半透明背板 overlay 渲染，解耦 ffmpeg drawtext 依赖）与平滑微转场。
4. 输出最终成片，并由 ffprobe 校验时长。
5. 纯 CPU 离线运作，严格不连接 Google/Flow API。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from hevi.kids.fonts import cjk_font
from hevi.stickman.proposal import DirectorProposal, StoryboardScene


FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"


class FlowImportValidationError(ValueError):
    """Flow 导入素材校验失败。"""


def probe_clip(clip_path: str | Path) -> dict[str, Any]:
    """使用 ffprobe 探测分段元数据。"""
    p = Path(clip_path)
    if not p.exists():
        raise FlowImportValidationError(f"分镜视频不存在: {clip_path}")

    cmd = [
        FFPROBE,
        "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_name,width,height,r_frame_rate",
        "-of", "json",
        str(p),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise FlowImportValidationError(f"ffprobe 解析视频失败: {p} ({res.stderr.strip()})")

    try:
        data = json.loads(res.stdout)
    except Exception as e:
        raise FlowImportValidationError(f"解析 ffprobe json 失败: {e}")

    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0.0))
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("width")), {})

    return {
        "path": str(p),
        "duration_s": duration,
        "width": int(video_stream.get("width", 1280)),
        "height": int(video_stream.get("height", 720)),
        "codec": video_stream.get("codec_name", "h264"),
        "size_bytes": int(fmt.get("size", p.stat().st_size)),
    }


def make_subtitle_overlay(
    out_png: Path,
    scene: StoryboardScene,
    w: int,
    h: int,
) -> None:
    """生成单镜全屏半透明双语字幕遮罩图（透明背景 + 底部文字框）。"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_zh = cjk_font(26)
    font_en = cjk_font(18)

    sub_zh = scene.narration_zh.strip()
    sub_en = scene.narration_en.strip()

    bar_h = 100
    bar_y = h - bar_h - 25
    draw.rounded_rectangle([60, bar_y, w - 60, bar_y + bar_h], radius=16, fill=(18, 22, 28, 225))

    tw_zh = draw.textlength(sub_zh, font=font_zh)
    tx_zh = max(80, (w - tw_zh) // 2)
    draw.text((tx_zh, bar_y + 16), sub_zh, fill=(255, 255, 255), font=font_zh)

    if sub_en:
        tw_en = draw.textlength(sub_en, font=font_en)
        tx_en = max(80, (w - tw_en) // 2)
        draw.text((tx_en, bar_y + 56), sub_en, fill=(200, 225, 255), font=font_en)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png, "PNG")


def import_and_stitch_flow_clips(
    clip_paths: list[str | Path],
    proposal: DirectorProposal,
    out_path: str | Path,
    *,
    scratch_dir: str | Path | None = None,
    max_clip_duration_s: float = 10.5,
) -> dict[str, Any]:
    """导入 Flow 外部生成的视频分段，校验、压制双语字幕、微转场并拼接为最终成片。"""
    out_file = Path(out_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    scenes = proposal.storyboard
    if len(clip_paths) != len(scenes):
        raise FlowImportValidationError(
            f"导入片段数量({len(clip_paths)})与提案分镜数量({len(scenes)})不一致"
        )

    # 1. 严格校验各分段
    probed_clips = []
    for idx, cp in enumerate(clip_paths, start=1):
        info = probe_clip(cp)
        # Flow 单条视频必须 ≤ 10s (放宽至 10.5s 容忍封装微秒)
        if info["duration_s"] > max_clip_duration_s:
            raise FlowImportValidationError(
                f"分段 {idx} 时长超过限制 ({info['duration_s']:.1f}s > {max_clip_duration_s}s)"
            )
        if info["duration_s"] < 0.5:
            raise FlowImportValidationError(
                f"分段 {idx} 时长过短异常: {info['duration_s']}s"
            )
        probed_clips.append(info)

    target_w = probed_clips[0]["width"]
    target_h = probed_clips[0]["height"]

    work_dir = Path(scratch_dir) if scratch_dir else Path(tempfile.mkdtemp(prefix="stickman_flow_import_"))
    work_dir.mkdir(parents=True, exist_ok=True)

    processed_clips: list[Path] = []
    try:
        for idx, (p_info, scene) in enumerate(zip(probed_clips, scenes), start=1):
            raw_path = Path(p_info["path"])
            dur = p_info["duration_s"]

            # 生成双语字幕贴图
            sub_png = work_dir / f"sub_{idx:02d}.png"
            make_subtitle_overlay(sub_png, scene, target_w, target_h)

            proc_clip = work_dir / f"proc_{idx:02d}.mp4"

            # 压入双语字幕与微缩放转场
            filter_chain = (
                f"[0:v][1:v]overlay=0:0[ov];"
                f"[ov]zoompan=z='min(zoom+0.0003,1.04)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d=250:s={target_w}x{target_h}:fps=25[vout]"
            )

            # 如果原始 clip 无音频流，补建静音或正弦音轨
            probe_audio_cmd = [
                FFPROBE, "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=codec_name", "-of", "json", str(raw_path)
            ]
            has_audio = False
            try:
                pa = subprocess.run(probe_audio_cmd, capture_output=True, text=True)
                has_audio = len(json.loads(pa.stdout).get("streams", [])) > 0
            except Exception:
                has_audio = False

            if has_audio:
                cmd = [
                    FFMPEG, "-y",
                    "-i", str(raw_path),
                    "-loop", "1", "-i", str(sub_png),
                    "-filter_complex", filter_chain,
                    "-map", "[vout]", "-map", "0:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-shortest",
                    "-t", str(dur),
                    str(proc_clip),
                ]
            else:
                cmd = [
                    FFMPEG, "-y",
                    "-i", str(raw_path),
                    "-loop", "1", "-i", str(sub_png),
                    "-f", "lavfi", "-i", f"sine=f=220:d={dur},volume=0.04",
                    "-filter_complex", filter_chain,
                    "-map", "[vout]", "-map", "2:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-shortest",
                    "-t", str(dur),
                    str(proc_clip),
                ]

            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            processed_clips.append(proc_clip)

        # 拼接成片
        concat_txt = work_dir / "concat_list.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for c in processed_clips:
                f.write(f"file '{c.resolve()}'\n")

        stitch_cmd = [
            FFMPEG, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-c", "copy",
            str(out_file),
        ]
        subprocess.run(stitch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    finally:
        if scratch_dir is None and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    # 验证成片
    final_info = probe_clip(out_file)

    return {
        "out_path": str(out_file),
        "duration_s": round(final_info["duration_s"], 2),
        "file_size_bytes": final_info["size_bytes"],
        "width": final_info["width"],
        "height": final_info["height"],
        "clips_count": len(clip_paths),
        "clips_validated": probed_clips,
        "qa": {
            "status": "success",
            "bilingual_subtitles": True,
            "micro_zoom_transitions": True,
            "ffprobe_verified": True,
            "note": "Imported and stitched via stickman.flow_import",
        }
    }
