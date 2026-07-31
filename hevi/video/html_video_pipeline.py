"""HTML 模板视频管线 — 对标 nexu-io/html-video。

架构: 内容图 (ContentGraph) → 分镜 (Storyboard) → HTML 模板 → MP4。
与 hyperframes_service 的区别: 本模块提供高层模板 API + 内容图 IR,
hyperframes_service 是底层渲染引擎。

参考: https://github.com/nexu-io/html-video
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hevi.video.html_templates import get_html_template, list_html_templates

logger = logging.getLogger(__name__)

__all__ = [
    "StoryboardFrame",
    "Storyboard",
    "HtmlVideoTemplate",
    "HtmlVideoRequest",
    "HtmlVideoResult",
    "render_html_video",
    "build_storyboard",
    "list_html_templates",
    "get_html_template",
    "render_storyboard",
]


class StoryboardFrame(BaseModel):
    """分镜中的单帧。"""
    frame_index: int
    duration: float = 3.0
    html_template: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    transitions: dict[str, Any] = Field(default_factory=dict)


class Storyboard(BaseModel):
    """分镜序列 — 帧级渲染指令。"""
    frames: list[StoryboardFrame] = Field(default_factory=list)
    total_duration: float = 0.0
    resolution: str = "1920x1080"
    fps: int = 30

    @property
    def width(self) -> int:
        try:
            return int(self.resolution.split("x")[0])
        except (ValueError, IndexError):
            return 1920

    @property
    def height(self) -> int:
        try:
            return int(self.resolution.split("x")[1])
        except (ValueError, IndexError):
            return 1080


class HtmlVideoTemplate(BaseModel):
    """HTML 视频模板元数据。"""
    id: str
    name: str
    description: str = ""
    html_source: str = ""
    css: str = ""
    variables: list[dict[str, Any]] = Field(default_factory=list)
    preview_thumbnail: str = ""
    category: str = ""


class HtmlVideoRequest(BaseModel):
    """HTML 视频渲染请求。"""
    template_id: str | None = None
    raw_html: str | None = None
    storyboard: Storyboard | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    output_path: str = "output.mp4"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    add_soundtrack: bool = False
    soundtrack_path: str | None = None


class HtmlVideoResult(BaseModel):
    """HTML 视频渲染结果。"""
    output_path: str = ""
    duration: float = 0.0
    resolution: str = ""
    frames_rendered: int = 0
    success: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Template variable resolution
# ---------------------------------------------------------------------------

def _resolve_template_vars(
    html_source: str, data: dict[str, Any], variables: list[dict[str, Any]],
) -> str:
    """Replace ``{{variable}}`` placeholders with actual values."""
    result = html_source
    for var in variables:
        name = var["name"]
        result = result.replace(f"{{{{{name}}}}}", str(data.get(name, var.get("default", ""))))
    for key, val in data.items():
        result = result.replace(f"{{{{{key}}}}}", str(val))
    return result


def _build_frame_html(
    tpl_dict: dict[str, Any], data: dict[str, Any], width: int, height: int,
) -> str:
    """Build complete HTML document for a single frame."""
    from hevi.video.html_templates import BASE_CSS
    body = _resolve_template_vars(tpl_dict["html_source"], data, tpl_dict["variables"])
    css = BASE_CSS + "\n" + tpl_dict.get("css", "")
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{css}body{{width:{width}px;height:{height}px;overflow:hidden}}</style>"
        f"</head><body>{body}</body></html>"
    )


# ---------------------------------------------------------------------------
# Chrome Headless capture
# ---------------------------------------------------------------------------

async def _capture_frame(
    html_path: Path, output_path: Path, width: int, height: int,
) -> bool:
    """Capture a single frame via Chrome Headless."""
    chrome_bin = (
        shutil.which("google-chrome-stable")
        or shutil.which("chrome")
        or shutil.which("chromium-browser")
    )
    if not chrome_bin:
        logger.warning("Chrome not found; generating blank frame")
        return await _blank_frame(output_path, width, height)

    cmd = [
        chrome_bin, "--headless=new", "--disable-gpu", "--no-sandbox",
        f"--window-size={width},{height}", f"--screenshot={output_path}",
        "--run-all-compositor-stages-before-draw", "--virtual-time-budget=200",
        str(html_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
        return output_path.exists()
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Chrome capture failed: %s", exc)
        return await _blank_frame(output_path, width, height)


async def _blank_frame(path: Path, width: int, height: int) -> bool:
    """Generate a blank PNG frame as fallback."""
    try:
        from PIL import Image
        Image.new("RGB", (width, height), (0, 0, 0)).save(path)
        return True
    except ImportError:
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return True


# ---------------------------------------------------------------------------
# FFmpeg encoding & audio merge
# ---------------------------------------------------------------------------

async def _encode_mp4(
    frames_dir: Path, output: Path, fps: int, width: int, height: int,
) -> bool:
    """Encode frame sequence to MP4 via FFmpeg."""
    cmd = [
        "ffmpeg", "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", f"scale={width}:{height}",
        "-preset", "medium", "-crf", "18", str(output),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error("FFmpeg encode failed: %s", stderr.decode(errors="replace")[-500:])
        return False
    return True


async def _merge_audio(
    video_path: Path, audio_path: Path, output_path: Path, duration: float,
) -> bool:
    """Merge audio track into video."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path), "-i", str(audio_path),
        "-c:v", "copy", "-c:a", "aac",
        "-shortest", "-t", str(duration), str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def render_storyboard(
    storyboard: Storyboard, output: Path, *, soundtrack_path: str | None = None,
) -> HtmlVideoResult:
    """Render a Storyboard to MP4 video."""
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height, fps = storyboard.width, storyboard.height, storyboard.fps
    frames_rendered = 0

    with tempfile.TemporaryDirectory(prefix="htmlvid_") as tmp:
        work_dir = Path(tmp)
        frames_dir = work_dir / "frames"
        frames_dir.mkdir()
        global_idx = 0

        for frame in storyboard.frames:
            tpl_dict: dict[str, Any] | None = None
            if frame.html_template:
                try:
                    tpl_dict = get_html_template(frame.html_template)
                except ValueError:
                    logger.warning("Template %r not found", frame.html_template)

            if tpl_dict is None and not frame.data.get("html"):
                logger.warning("No template or HTML for frame %d", frame.frame_index)
                continue

            html = (
                _build_frame_html(tpl_dict, frame.data, width, height)
                if tpl_dict else frame.data["html"]
            )

            # Write HTML and capture one unique frame
            unique_html = work_dir / f"u_{frame.frame_index}.html"
            unique_html.write_text(html, encoding="utf-8")
            unique_png = work_dir / f"u_{frame.frame_index}.png"
            await _capture_frame(unique_html, unique_png, width, height)

            # Duplicate captured frame for the frame's duration
            for _ in range(max(1, int(frame.duration * fps))):
                shutil.copy(unique_png, frames_dir / f"frame_{global_idx:06d}.png")
                global_idx += 1
                frames_rendered += 1

        if frames_rendered == 0:
            return HtmlVideoResult(
                output_path=str(output), resolution=f"{width}x{height}",
                error="no frames rendered",
            )

        video_path = work_dir / "video_noaudio.mp4"
        if not await _encode_mp4(frames_dir, video_path, fps, width, height):
            return HtmlVideoResult(
                output_path=str(output), frames_rendered=frames_rendered,
                resolution=f"{width}x{height}", error="FFmpeg encoding failed",
            )

        total_dur = storyboard.total_duration or sum(f.duration for f in storyboard.frames)
        if soundtrack_path and Path(soundtrack_path).exists():
            if not await _merge_audio(video_path, Path(soundtrack_path), output, total_dur):
                logger.warning("Audio merge failed; video without audio")
                shutil.move(str(video_path), str(output))
        else:
            shutil.move(str(video_path), str(output))

    return HtmlVideoResult(
        output_path=str(output), duration=total_dur,
        resolution=f"{width}x{height}",
        frames_rendered=frames_rendered, success=True,
    )


async def render_html_video(request: HtmlVideoRequest) -> HtmlVideoResult:
    """High-level HTML→video rendering entry point.

    Supports: (1) template + Storyboard, (2) template + data, (3) raw_html.
    """
    output = Path(request.output_path)

    if request.storyboard:
        return await render_storyboard(
            request.storyboard, output,
            soundtrack_path=request.soundtrack_path if request.add_soundtrack else None,
        )

    if request.template_id:
        tpl_dict = get_html_template(request.template_id)
        html = _build_frame_html(tpl_dict, request.data, request.width, request.height)
    elif request.raw_html:
        html = request.raw_html
    else:
        return HtmlVideoResult(
            output_path=str(output),
            error="template_id, raw_html, or storyboard required",
        )

    sb = Storyboard(
        frames=[StoryboardFrame(frame_index=0, duration=5.0, data={"html": html})],
        resolution=f"{request.width}x{request.height}", fps=request.fps,
    )
    return await render_storyboard(
        sb, output,
        soundtrack_path=request.soundtrack_path if request.add_soundtrack else None,
    )


def build_storyboard(graph: Any, template_pack: str = "default") -> Storyboard:
    """Build a Storyboard from a ContentGraph."""
    from hevi.video.content_graph import graph_to_storyboard
    return graph_to_storyboard(graph, template_pack)
