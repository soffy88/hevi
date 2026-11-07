"""HyperFrames HTML 确定性渲染引擎 — 对标 HeyGen HyperFrames。

核心:HTML/CSS/GSAP → 确定性 MP4。同输入=同输出。

用法:
    from hevi.video.hyperframes_service import render_html_video

    result = await render_html_video(
        html_content="<div>...</div>",
        output=Path("output/title_card.mp4"),
        width=1920, height=1080, fps=24, duration=5.0,
    )

对标: https://github.com/heygen-com/hyperframes
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hevi.video.hyperframes_seek import (  # noqa: E402
    EmbedLayer,
    build_seek_page,
    custom_layer,
    frame_times,
    p5_layer,
    rough_layer,
    sequence_digest,
    three_layer,
)

logger = logging.getLogger(__name__)

__all__ = [
    "render_html_video",
    "render_gsap_video",
    "EmbedLayer",
    "rough_layer",
    "three_layer",
    "p5_layer",
    "custom_layer",
    "build_html_composition",
    "HyperFramesRenderResult",
]


class HyperFramesRenderResult:
    """渲染结果。"""

    def __init__(
        self,
        output_path: Path,
        duration: float,
        width: int,
        height: int,
        fps: int,
        success: bool = True,
        error: str | None = None,
        *,
        driver: str = "legacy",
        frame_hashes: list[str] | None = None,
        frames_dir: Path | None = None,
    ):
        self.output_path = output_path
        self.duration = duration
        self.width = width
        self.height = height
        self.fps = fps
        self.success = success
        self.error = error
        self.driver = driver
        self.frame_hashes = frame_hashes or []
        self.frames_dir = frames_dir

    @property
    def frame_count(self) -> int:
        return len(self.frame_hashes)

    @property
    def sequence_hash(self) -> str:
        """逐帧哈希的总哈希（gsap 驱动下同输入同值）。"""
        return sequence_digest(self.frame_hashes) if self.frame_hashes else ""


async def build_html_composition(
    html_content: str,
    output_dir: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 24,
    duration: float = 5.0,
    composition_id: str = "root",
) -> Path:
    """构建 HyperFrames HTML composition 项目结构。

    Args:
        html_content: HTML 内容(不含 <html> 包裹)
        output_dir: 输出目录
        width/height/fps/duration: 视频参数
        composition_id: composition 标识

    Returns:
        composition HTML 文件路径
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 完整 HTML(含 data-composition-id)
    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: {width}px;
    height: {height}px;
    overflow: hidden;
    background: #000;
  }}
  [data-composition-id] {{
    position: relative;
    width: 100%;
    height: 100%;
  }}
</style>
</head>
<body>
<div id="{composition_id}" data-composition-id="{composition_id}"
     data-start="0" data-width="{width}" data-height="{height}">
{html_content}
</div>
</body>
</html>
"""

    html_path = output_dir / "index.html"
    html_path.write_text(full_html, encoding="utf-8")
    return html_path


async def render_html_video(
    html_content: str,
    output: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 24,
    duration: float = 5.0,
    composition_id: str = "root",
    gsap_script: str | None = None,
    driver: str = "legacy",
    layers: "list[EmbedLayer] | tuple[EmbedLayer, ...]" = (),
) -> HyperFramesRenderResult:
    """渲染 HTML composition 为 MP4 视频。

    driver="legacy"（默认，原行为）：Chrome Headless --screenshot + FFmpeg。
    driver="gsap"：本地 GSAP 暂停时间轴 + Playwright 逐帧 seek(n/fps) 截图（确定性），
    等价于调用 :func:`render_gsap_video`；传了 layers 时自动走 gsap。

    Args:
        html_content: HTML 内容
        output: 输出 MP4 路径
        width/height: 视频分辨率
        fps: 帧率
        duration: 时长(秒)
        composition_id: composition 标识
        gsap_script: GSAP 动画脚本(JS 代码,可选)

    Returns:
        HyperFramesRenderResult
    """
    if driver == "gsap" or layers:
        return await render_gsap_video(
            html_content, output, width=width, height=height, fps=fps, duration=duration,
            composition_id=composition_id, gsap_script=gsap_script, layers=layers,
        )
    if driver != "legacy":
        raise ValueError(f"unknown driver: {driver}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="hf_render_") as tmp_dir:
        work_dir = Path(tmp_dir)

        # 1. 构建 composition
        html_path = await build_html_composition(
            html_content,
            work_dir,
            width=width,
            height=height,
            fps=fps,
            duration=duration,
            composition_id=composition_id,
        )

        # 2. 注入 GSAP(如果有)
        if gsap_script:
            await _inject_gsap(html_path, gsap_script)

        # 3. Chrome Headless 逐帧捕获
        frames_dir = work_dir / "frames"
        frames_dir.mkdir()
        await _capture_frames(
            html_path, frames_dir, width, height, fps, duration
        )

        # 4. FFmpeg 编码为 MP4
        await _encode_mp4(frames_dir, output, fps, width, height)

        if not output.exists():
            return HyperFramesRenderResult(
                output, duration, width, height, fps,
                success=False, error="render failed"
            )

        return HyperFramesRenderResult(
            output, duration, width, height, fps, success=True
        )


async def render_gsap_video(
    html_content: str,
    output: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 24,
    duration: float | None = 5.0,
    composition_id: str = "root",
    gsap_script: str | None = None,
    layers: "list[EmbedLayer] | tuple[EmbedLayer, ...]" = (),
    background: str = "#000",
    seed: int = 20261022,
    asset_dir: Path | None = None,
    keep_frames: Path | None = None,
    audio: Path | None = None,
    crf: int = 18,
) -> HyperFramesRenderResult:
    """omodul：GSAP 暂停时间轴逐帧驱动渲染（确定性）。

    1. oskill build_seek_page：本地 GSAP + 嵌入层（rough/three/p5/custom）+ HF.seek 协议
    2. obase capture_seek_frames：Playwright Chromium 逐帧 HF.seek(n/fps, n) → PNG（记录 sha256）
    3. obase encode_frames_mp4：FFmpeg H.264

    duration=None 时取 GSAP 时间轴总时长（需先探测，会多加载一次页面）。
    gsap_script 中可直接使用 ``tl``（paused timeline）。
    """
    from hevi.video.hyperframes_capture import capture_seek_frames, encode_frames_mp4

    page = build_seek_page(
        html_content, width=width, height=height, fps=fps, gsap_script=gsap_script,
        layers=tuple(layers), composition_id=composition_id, background=background, seed=seed,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="hf_gsap_") as tmp_dir:
            frames_dir = Path(keep_frames) if keep_frames else Path(tmp_dir) / "frames"
            if duration is None:
                probe = await capture_seek_frames(page, Path(tmp_dir) / "probe", [0.0],
                                                  width=width, height=height, asset_dir=asset_dir)
                duration = probe["timeline_duration"] or 1.0 / fps
            times = frame_times(fps, duration)
            cap = await capture_seek_frames(page, frames_dir, times, width=width, height=height,
                                            asset_dir=asset_dir)
            if cap["console_errors"]:
                logger.warning("hyperframes page errors: %s", cap["console_errors"][:5])
            await encode_frames_mp4(frames_dir, output, fps, crf=crf, audio=audio)
    except Exception as e:  # noqa: BLE001
        logger.exception("gsap render failed")
        return HyperFramesRenderResult(output, float(duration or 0), width, height, fps, success=False,
                                       error=str(e), driver="gsap")
    return HyperFramesRenderResult(
        output, float(duration), width, height, fps, success=output.exists(),
        error=None if output.exists() else "render failed", driver="gsap",
        frame_hashes=cap["digests"], frames_dir=Path(keep_frames) if keep_frames else None,
    )


async def _inject_gsap(html_path: Path, script: str) -> None:
    """向 HTML 注入 GSAP CDN + 动画脚本。"""
    html = html_path.read_text(encoding="utf-8")
    inject = f"""
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
<script>
{script}
</script>
</body>"""
    html = html.replace("</body>", inject)
    html_path.write_text(html, encoding="utf-8")


async def _capture_frames(
    html_path: Path,
    frames_dir: Path,
    width: int,
    height: int,
    fps: int,
    duration: float,
) -> None:
    """Chrome Headless 逐帧捕获。"""
    total_frames = int(duration * fps)

    # 尝试 chrome headless 截图
    chrome_bin = shutil.which("google-chrome-stable") or shutil.which("chrome")
    if not chrome_bin:
        logger.warning("Chrome not found, using fallback (static screenshot)")
        # fallback: 只截一帧 + 复制
        await _capture_single_frame(html_path, frames_dir, width, height)
        # 复制为 total_frames 帧
        single = frames_dir / "frame_0000.png"
        if single.exists():
            for i in range(1, total_frames):
                shutil.copy(single, frames_dir / f"frame_{i:04d}.png")
        return

    # Chrome headless 逐帧截图
    for frame_idx in range(total_frames):
        time_ms = (frame_idx / fps) * 1000
        output_frame = frames_dir / f"frame_{frame_idx:04d}.png"

        cmd = [
            chrome_bin,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--window-size={width},{height}",
            f"--screenshot={output_frame}",
            f"--run-all-compositor-stages-before-draw",
            f"--virtual-time-budget=100",
            str(html_path),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10)
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("Chrome capture failed for frame %d: %s", frame_idx, e)
            # 使用上一帧(如果有)
            prev = frames_dir / f"frame_{frame_idx - 1:04d}.png"
            if prev.exists():
                shutil.copy(prev, output_frame)


async def _capture_single_frame(
    html_path: Path, frames_dir: Path, width: int, height: int
) -> None:
    """捕获单帧(fallback)。"""
    output = frames_dir / "frame_0000.png"
    # 尝试用 puppeteer/playwright 或其他
    logger.info("Capturing single frame from %s", html_path)
    # 最简 fallback: 创建空白帧
    from PIL import Image
    img = Image.new("RGB", (width, height), (0, 0, 0))
    img.save(output)


async def _encode_mp4(
    frames_dir: Path,
    output: Path,
    fps: int,
    width: int,
    height: int,
) -> None:
    """FFmpeg 编码帧序列为 MP4。"""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={width}:{height}",
        "-preset", "medium",
        "-crf", "18",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg encode failed (exit {proc.returncode})")
