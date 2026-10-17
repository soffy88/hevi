"""Explainer Render Engine — 低清快速预览帧 + 最终 MP4 合成（FFmpeg 纯 CPU 本地渲染）。

能力: explainer.render
纯 CPU、本地 FFmpeg 合成，无外部 Remotion/Node 依赖，无付费 API。
生成:
1. 快速低清预览帧序列 + 预览分镜大图 (preview_storyboard.png)
2. 最终广播级 MP4 视频，集成旁白音轨、动态逐层图示、转场与画中画布局
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import Capability, CapabilityResult, register
from hevi.explainer.visual_plan import VisualPlan, VisualScene
from hevi.explainer.voice import VoiceoverPackage, probe_audio_duration_ms

logger = logging.getLogger(__name__)


def generate_preview_frames(
    plan: VisualPlan,
    out_dir: Path,
    *,
    preview_w: int = 640,
    preview_h: int = 360,
) -> list[Path]:
    """快速生成低清关键帧预览图序列（毫秒级）。"""
    out_dir = Path(out_dir) / "preview_frames"
    out_dir.mkdir(parents=True, exist_ok=True)

    preview_paths: list[Path] = []
    frame_idx = 0

    for s_idx, scene in enumerate(plan.scenes):
        # 1. 场景基础帧
        src_img_p = Path(scene.base_image_path)
        if src_img_p.is_file():
            im = Image.open(src_img_p)
            resized = im.resize((preview_w, preview_h), Image.Resampling.BILINEAR)
            dest = out_dir / f"frame_{frame_idx:03d}_{scene.scene_id}_base.png"
            resized.save(dest, format="PNG")
            preview_paths.append(dest)
            frame_idx += 1

        # 2. 流程图逐层展开子帧
        for layer in scene.diagram_layers:
            layer_p = Path(layer.image_path)
            if layer_p.is_file() and layer.image_path != scene.base_image_path:
                im = Image.open(layer_p)
                resized = im.resize((preview_w, preview_h), Image.Resampling.BILINEAR)
                dest = out_dir / f"frame_{frame_idx:03d}_{scene.scene_id}_step_{layer.step_index}.png"
                resized.save(dest, format="PNG")
                preview_paths.append(dest)
                frame_idx += 1

    return preview_paths


def render_storyboard_sheet(
    plan: VisualPlan,
    out_dir: Path,
    preview_frames: list[Path] | None = None,
    cols: int = 3,
) -> Path:
    """把预览关键帧拼装成一览式分镜接触印样 (Storyboard Contact Sheet)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    frames = preview_frames or generate_preview_frames(plan, out_dir)
    if not frames:
        # 兜底生成空白
        blank = Image.new("RGB", (640, 360), (30, 41, 59))
        p = out_dir / "preview_storyboard.png"
        blank.save(p)
        return p

    cell_w, cell_h = 480, 270
    n = len(frames)
    rows = math.ceil(n / cols)

    sheet_w = cols * cell_w + (cols + 1) * 20
    sheet_h = rows * cell_h + (rows + 1) * 20 + 80

    sheet = Image.new("RGB", (sheet_w, sheet_h), (15, 23, 42))
    draw = ImageDraw.Draw(sheet)

    # 标题头
    draw.text((24, 24), f"分镜快速预览图表（共 {len(plan.scenes)} 镜，总长 {plan.total_duration_ms / 1000.0:.1f} 秒）", fill=(255, 255, 255))

    for idx, fpath in enumerate(frames):
        r = idx // cols
        c = idx % cols
        x = 20 + c * (cell_w + 20)
        y = 80 + r * (cell_h + 20)

        thumb = Image.open(fpath).resize((cell_w, cell_h), Image.Resampling.BILINEAR)
        sheet.paste(thumb, (x, y))
        draw.rectangle([x, y, x + cell_w, y + cell_h], outline=(56, 189, 248), width=2)
        draw.text((x + 8, y + 8), f"#{idx+1}", fill=(255, 255, 255))

    dest = out_dir / "preview_storyboard.png"
    sheet.save(dest, format="PNG")
    return dest


def _composite_pip_badge(base_img_path: Path, out_path: Path, name: str = "科普解说员") -> Path:
    """在底板图像右下角合成小窗主讲人 PiP 圆形徽标。"""
    base = Image.open(base_img_path).convert("RGBA")
    w, h = base.size

    pip_size = int(h * 0.28)
    margin = int(h * 0.05)
    x = w - pip_size - margin
    y = h - pip_size - margin

    # 绘制圆形画中画头像
    pip_img = Image.new("RGBA", (pip_size, pip_size), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(pip_img)
    # 底色
    pdraw.ellipse([0, 0, pip_size, pip_size], fill=(30, 58, 95, 255), outline=(56, 189, 248, 255), width=4)
    # 人形剪影
    cx = pip_size // 2
    pdraw.ellipse([cx - 24, pip_size // 2 - 40, cx + 24, pip_size // 2 + 10], fill=(148, 163, 184, 255))
    pdraw.pieslice([cx - 45, pip_size // 2, cx + 45, pip_size - 10], start=180, end=360, fill=(148, 163, 184, 255))

    base.paste(pip_img, (x, y), pip_img)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(out_path, format="PNG")
    return out_path


def render_scene_video(
    scene: VisualScene,
    out_dir: Path,
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 25,
) -> Path:
    """为单场景渲染无声微视频片段，支持逐层展开或静态 hold。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    clip_path = out_dir / f"{scene.scene_id}.mp4"
    dur_s = max(round(scene.duration_ms / 1000.0, 3), 0.5)

    # 检查是否有 PiP 需求
    base_path = Path(scene.base_image_path)
    if scene.layout == "presenter_pip" and base_path.is_file():
        pip_path = out_dir / f"{scene.scene_id}_with_pip.png"
        _composite_pip_badge(base_path, pip_path)
        active_img = pip_path
    else:
        active_img = base_path

    # 若有多层图示展开，生成 concat 清单按时间切换
    if len(scene.diagram_layers) > 1:
        concat_txt = out_dir / f"{scene.scene_id}_concat.txt"
        lines: list[str] = []
        n_layers = len(scene.diagram_layers)
        layer_dur = dur_s / n_layers
        for l_idx, layer in enumerate(scene.diagram_layers):
            l_path = Path(layer.image_path)
            if scene.layout == "presenter_pip":
                l_pip = out_dir / f"{scene.scene_id}_layer_{l_idx}_pip.png"
                _composite_pip_badge(l_path, l_pip)
                active_l_path = l_pip
            else:
                active_l_path = l_path
            lines.append(f"file '{active_l_path.resolve()}'")
            lines.append(f"duration {layer_dur:.3f}")
        # ffmpeg concat demuxer 需末帧再写一次
        lines.append(f"file '{active_l_path.resolve()}'")
        concat_txt.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-t",
            str(dur_s),
            "-vf",
            f"scale={width}:{height},format=yuv420p",
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(clip_path),
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        concat_txt.unlink(missing_ok=True)
    else:
        # 单图像直接循环生成指定时长
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(active_img.resolve()),
            "-t",
            str(dur_s),
            "-vf",
            f"scale={width}:{height},format=yuv420p",
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(clip_path),
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    return clip_path


def render_final_explainer_mp4(
    plan: VisualPlan,
    voiceover: VoiceoverPackage,
    out_dir: Path,
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 25,
) -> Path:
    """最终全流程本地合成：分镜视频渲染 + 转场拼接 + 混入配音音轨。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scenes_dir = out_dir / "scene_clips"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: list[Path] = []
    for scene in plan.scenes:
        clip = render_scene_video(scene, scenes_dir, width=width, height=height, fps=fps)
        clip_paths.append(clip)

    if not clip_paths:
        raise RuntimeError("No scenes to render!")

    # 1. 拼接视频轨
    concat_list = out_dir / "video_concat.txt"
    concat_list.write_text("\n".join([f"file '{c.resolve()}'" for c in clip_paths]), encoding="utf-8")

    stitched_video = out_dir / "stitched_visual.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(stitched_video),
        ],
        capture_output=True,
        check=True,
    )
    concat_list.unlink(missing_ok=True)

    # 2. 混流完整配音音轨出最终 MP4
    final_mp4 = out_dir / f"{plan.script_id}_{plan.version_id}_final.mp4"
    audio_src = Path(voiceover.full_audio_path)

    cmd_mux = [
        "ffmpeg",
        "-y",
        "-i",
        str(stitched_video),
        "-i",
        str(audio_src),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(final_mp4),
    ]
    subprocess.run(cmd_mux, capture_output=True, check=True)

    if stitched_video.exists():
        stitched_video.unlink(missing_ok=True)

    return final_mp4


# ─────────────────────────────────────────────────────────────────────────────
# 统一能力注册: explainer.render
# ─────────────────────────────────────────────────────────────────────────────
def _render_explainer(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    """explainer.render 统一能力入口。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    plan_dict = params.get("plan")
    voiceover_dict = params.get("voiceover")
    if not plan_dict or not voiceover_dict:
        raise CapabilityError("explainer.render: 'plan' and 'voiceover' parameters are required")

    # 重构模型对象
    from hevi.explainer.visual_plan import DiagramStepLayer, ImageCardEvent, KeywordHighlight

    scenes: list[VisualScene] = []
    for s in plan_dict.get("scenes", []):
        hl = [KeywordHighlight(**h) for h in s.get("highlights", [])]
        dl = [DiagramStepLayer(**d) for d in s.get("diagram_layers", [])]
        ic = [ImageCardEvent(**c) for c in s.get("image_cards", [])]
        scenes.append(
            VisualScene(
                scene_id=s["scene_id"],
                section_id=s["section_id"],
                role=s["role"],
                start_ms=s["start_ms"],
                end_ms=s["end_ms"],
                duration_ms=s["duration_ms"],
                layout=s["layout"],
                transition_type=s["transition_type"],
                transition_duration_ms=s.get("transition_duration_ms", 500),
                base_image_path=s.get("base_image_path", ""),
                highlights=hl,
                diagram_layers=dl,
                image_cards=ic,
            )
        )

    plan = VisualPlan(
        plan_id=plan_dict["plan_id"],
        script_id=plan_dict["script_id"],
        version_id=plan_dict["version_id"],
        aspect=plan_dict.get("aspect", aspect),
        width=int(plan_dict.get("width", 1280)),
        height=int(plan_dict.get("height", 720)),
        total_duration_ms=int(plan_dict.get("total_duration_ms", 0)),
        scenes=scenes,
        all_highlights=[KeywordHighlight(**h) for h in plan_dict.get("all_highlights", [])],
        metadata=plan_dict.get("metadata", {}),
    )
    voiceover = VoiceoverPackage.from_dict(voiceover_dict)

    # 1. 快速低清预览帧生成
    preview_frames = generate_preview_frames(plan, out_dir)
    sheet_p = render_storyboard_sheet(plan, out_dir, preview_frames=preview_frames)

    fast_only = params.get("fast_preview_only", False)
    if fast_only:
        sha = hashlib.sha256(sheet_p.read_bytes()).hexdigest()
        return CapabilityResult(
            png=str(sheet_p),
            mp4=None,
            wav=None,
            duration_s=round(plan.total_duration_ms / 1000.0, 2),
            sha256=sha,
            qa={
                "preview_sheet": str(sheet_p),
                "preview_frames_count": len(preview_frames),
                "mode": "preview_only",
            },
        )

    # 2. 完整 MP4 视频渲染
    mp4_path = render_final_explainer_mp4(
        plan=plan,
        voiceover=voiceover,
        out_dir=out_dir,
        width=plan.width,
        height=plan.height,
    )
    actual_dur_ms = probe_audio_duration_ms(mp4_path)
    sha = hashlib.sha256(mp4_path.read_bytes()).hexdigest()

    return CapabilityResult(
        png=str(sheet_p),
        mp4=str(mp4_path),
        wav=voiceover.full_audio_path,
        duration_s=round(actual_dur_ms / 1000.0, 2),
        sha256=sha,
        qa={
            "mp4_path": str(mp4_path),
            "preview_sheet": str(sheet_p),
            "preview_frames_count": len(preview_frames),
            "actual_duration_ms": actual_dur_ms,
        },
    )


def register_explainer_render_capability() -> Capability:
    cap = Capability(
        name="explainer.render",
        kind="line",
        aspects=["16:9", "9:16"],
        cpu_cost_hint=0.2,
        render=_render_explainer,
        description="解说视频快速低清预览帧与纯 CPU 本地 FFmpeg MP4 最终视频渲染",
        line="explainer",
        params_schema={
            "type": "object",
            "required": ["plan", "voiceover"],
            "properties": {
                "plan": {"type": "object"},
                "voiceover": {"type": "object"},
                "fast_preview_only": {"type": "boolean"},
            },
        },
    )
    register(cap)
    return cap
