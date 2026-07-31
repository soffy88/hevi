"""动画 overlay 生成管线（对标 video-use 多引擎并行子 agent）。

支持多种动画引擎并行生成 overlay：
  - HyperFrames（HTML/CSS/GSAP → 确定性 MP4）
  - PIL（简单图形/文字 overlay）
  - Manim（数学/科学动画）
  - Remotion（React 视频合成）

每种引擎生成独立的 overlay MP4，由 edit_render.apply_overlays_and_subtitles 合成。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class OverlayTask:
    """单个 overlay 生成任务。"""

    task_id: str
    engine: str  # "hyperframes" | "pil" | "manim" | "remotion"
    spec: dict[str, Any]  # 引擎特定参数
    start_in_output: float = 0.0
    duration: float = 0.0
    output_path: Path | None = None
    status: str = "pending"  # pending | running | done | failed
    error: str = ""

    def to_overlay_spec(self) -> dict[str, Any]:
        """转为 edit_craft.OverlaySpec 兼容的 dict。"""
        return {
            "file": str(self.output_path or ""),
            "start_in_output": self.start_in_output,
            "duration": self.duration,
        }


@dataclass
class OverlayPlan:
    """EDL 的 overlay 生成计划。"""

    tasks: list[OverlayTask] = field(default_factory=list)
    parallel: bool = True  # 是否并行生成

    def add_task(
        self,
        task_id: str,
        engine: str,
        spec: dict[str, Any],
        *,
        start: float,
        duration: float,
    ) -> OverlayTask:
        task = OverlayTask(
            task_id=task_id,
            engine=engine,
            spec=spec,
            start_in_output=start,
            duration=duration,
        )
        self.tasks.append(task)
        return task


# ── 引擎适配器 ────────────────────────────────────────────────────────


async def _render_hyperframes(task: OverlayTask, output_dir: Path) -> Path:
    """通过 HyperFrames 渲染 HTML → MP4 overlay。"""
    from hevi.video.hyperframes_service import render_html_video

    output = output_dir / f"overlay_{task.task_id}.mp4"
    html_content = task.spec.get("html", "")
    if not html_content:
        raise ValueError(f"hyperframes task {task.task_id}: missing html spec")

    result = await render_html_video(
        html_content=html_content,
        output_path=output,
        width=task.spec.get("width", 1920),
        height=task.spec.get("height", 1080),
        fps=task.spec.get("fps", 30),
        duration_s=task.duration,
    )
    return result.path


async def _render_pil(task: OverlayTask, output_dir: Path) -> Path:
    """通过 PIL 生成简单图形/文字 overlay。"""
    output = output_dir / f"overlay_{task.task_id}.mp4"

    # 尝试导入 PIL
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise ImportError("PIL required for pil overlay engine: pip install Pillow")

    width = task.spec.get("width", 1920)
    height = task.spec.get("height", 1080)
    fps = task.spec.get("fps", 30)
    total_frames = int(task.duration * fps)
    text = task.spec.get("text", "")
    bg_color = task.spec.get("bg_color", (0, 0, 0, 0))  # transparent
    text_color = task.spec.get("text_color", (255, 255, 255))

    frames_dir = output_dir / f"frames_{task.task_id}"
    frames_dir.mkdir(parents=True, exist_ok=True)

    for i in range(total_frames):
        img = Image.new("RGBA", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        if text:
            try:
                font = ImageFont.truetype(
                    task.spec.get("font", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                    task.spec.get("font_size", 48),
                )
            except (OSError, IOError):
                font = ImageFont.load_default()
            # 居中
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = (width - tw) // 2
            y = (height - th) // 2
            draw.text((x, y), text, fill=text_color, font=font)
        img.save(frames_dir / f"frame_{i:04d}.png")

    # FFmpeg 编码
    from obase.ffmpeg import run as ffmpeg_run
    await ffmpeg_run(args=[
        "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuva420p",
        "-preset", "veryfast",
        "-crf", "18",
        str(output),
    ], expected_output=output)

    return output


async def _render_manim(task: OverlayTask, output_dir: Path) -> Path:
    """通过 Manim 生成数学/科学动画 overlay。"""
    output = output_dir / f"overlay_{task.task_id}.mp4"

    manim_script = task.spec.get("script", "")
    if not manim_script:
        raise ValueError(f"manim task {task.task_id}: missing script spec")

    # 写入临时脚本并执行
    script_path = output_dir / f"manim_{task.task_id}.py"
    script_path.write_text(manim_script, encoding="utf-8")

    proc = await asyncio.create_subprocess_exec(
        "manim",
        "-qm",  # medium quality
        "-o", str(output),
        str(script_path),
        task.spec.get("scene_class", "MainScene"),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"manim failed: {stderr.decode(errors='replace')}")

    return output


async def _render_remotion(task: OverlayTask, output_dir: Path) -> Path:
    """通过 Remotion 渲染 React 视频 overlay。"""
    output = output_dir / f"overlay_{task.task_id}.mp4"

    component = task.spec.get("component", "")
    props = task.spec.get("props", {})
    if not component:
        raise ValueError(f"remotion task {task.task_id}: missing component spec")

    # 调用 remotion_service
    from hevi.video.remotion_service import render_video

    result = await render_video(
        component=component,
        props=props,
        output_path=output,
        fps=task.spec.get("fps", 30),
        duration_frames=int(task.duration * task.spec.get("fps", 30)),
    )
    return result.path


_ENGINE_MAP = {
    "hyperframes": _render_hyperframes,
    "pil": _render_pil,
    "manim": _render_manim,
    "remotion": _render_remotion,
}


# ── 主入口 ────────────────────────────────────────────────────────────


async def generate_overlay(task: OverlayTask, output_dir: Path) -> OverlayTask:
    """生成单个 overlay。"""
    engine_fn = _ENGINE_MAP.get(task.engine)
    if not engine_fn:
        task.status = "failed"
        task.error = f"unknown engine: {task.engine}"
        return task

    task.status = "running"
    try:
        output = await engine_fn(task, output_dir)
        task.output_path = output
        task.status = "done"
    except Exception as e:
        logger.error("overlay %s failed: %s", task.task_id, e)
        task.status = "failed"
        task.error = str(e)

    return task


async def generate_all_overlays(
    plan: OverlayPlan,
    output_dir: Path,
) -> list[OverlayTask]:
    """按计划生成所有 overlay（可选并行）。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    if plan.parallel:
        tasks_coro = [generate_overlay(t, output_dir) for t in plan.tasks]
        results = await asyncio.gather(*tasks_coro, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                plan.tasks[i].status = "failed"
                plan.tasks[i].error = str(r)
    else:
        for task in plan.tasks:
            await generate_overlay(task, output_dir)

    return plan.tasks


def get_successful_overlays(tasks: list[OverlayTask]) -> list[dict[str, Any]]:
    """提取成功的 overlay 规格（可直接放入 EDL.overlays）。"""
    return [
        t.to_overlay_spec()
        for t in tasks
        if t.status == "done" and t.output_path and t.output_path.exists()
    ]
