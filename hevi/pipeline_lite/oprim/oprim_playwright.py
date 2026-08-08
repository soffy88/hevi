"""oprim:oprim_playwright —— 无头浏览器录屏原子能力(绝对无状态)。

只负责:接收一个本地 HTML 文件路径/URL,用 Playwright 无头 Chromium
录制滚动/音频驱动过程,输出视频文件路径。不做任何业务校验与状态写入。

v9.1 音频驱动:若 HTML 由 oprim_html_gen 生成(含 <audio> + JS 轮询), 页面会
在音频 onended 时置 window.__heviAudioEnded=true —— 录制循环轮询该标记结束,
画面翻页由页面内 JS 随 audio.currentTime 驱动(scrollIntoView), 实现音画同步。

双通道实现(自动降级):
  1. 首选 Playwright 原生 record_video(screencast webm);
     但 screencast 依赖 GPU 合成器 —— 在受限容器(嵌套容器/无 /dev/dri)
     里会产出 0 字节文件;
  2. 空产物自动降级为「定时截图 + FFmpeg 合成」:page.screenshot() 逐帧 →
     ffmpeg -framerate 拼成 h264/yuv420p mp4(与 GPU 合成器无关)。

两个通道都会对空产物做硬校验:绝不向编排层返回 0 字节的"成功"。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 无头自动播放 + file:// 子资源(音频)跨目录访问。
_LAUNCH_ARGS = [
    "--no-sandbox",
    "--autoplay-policy=no-user-gesture-required",
    "--allow-file-access-from-files",
]


class EmptyVideoError(RuntimeError):
    """录屏通道未产出任何有效帧。"""


async def record_html_to_video(
    html_path: str | Path,
    output_path: str | Path,
    *,
    width: int = 720,
    height: int = 1280,
    fps: int = 24,
    duration_s: float = 5.0,
    scroll: bool = True,
    convert_to_mp4: bool = True,
) -> Path:
    """录制 HTML 页面过程,输出视频。

    依赖 ``playwright`` + ``playwright install chromium`` + ``ffmpeg``(降级路径)。
    * 音频驱动: 轮询 window.__heviAudioEnded 结束录制(硬超时兜底);
    * 无音频(任意 HTML): 按 duration_s 定时滚动(向后兼容)。
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - 环境缺失
        raise RuntimeError(
            "playwright 未安装: pip install playwright && playwright install chromium"
        ) from exc

    try:
        raw = await _record_via_screencast(
            html_path, output, async_playwright, width, height, fps, duration_s, scroll
        )
        if convert_to_mp4:
            converted = convert_webm_to_mp4(raw, fps=fps)
            converted.replace(output)
        else:
            raw.replace(output)
        # 时长可信度校验: 受限容器 screencast 可能产出非空但极短的 webm
        # (如 6.2s vs 音频 11.8s) —— 时长 < 期望 60% 视为不可信, 降级截图通道。
        if _probe_duration(output) < duration_s * 0.6:
            raise EmptyVideoError(
                f"screencast 时长过短({_probe_duration(output):.1f}s < {duration_s * 0.6:.1f}s)"
            )
    except EmptyVideoError as exc:
        logger.warning("record_video 不可信(%s), 降级截图+ffmpeg 通道", exc)
        return await _record_via_frames(
            html_path, output, async_playwright, width, height, fps, duration_s, scroll
        )
    return output


async def _record_via_screencast(
    html_path: str | Path,
    output: Path,
    async_playwright: object,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    scroll: bool,
) -> Path:
    """Playwright 原生 screencast 通道。空产物抛 EmptyVideoError。"""
    async with async_playwright() as p:  # type: ignore[attr-defined]
        browser = await p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        try:
            page = await browser.new_page(
                viewport={"width": width, "height": height},
                record_video_dir=str(output.parent / "_rec"),
                record_video_size={"width": width, "height": height},
            )
            await _drive_page(page, html_path, width, height, duration_s, scroll)
            video = page.video
            if video is None:
                raise EmptyVideoError("Playwright 未产出视频文件")
            raw = Path(await video.path())
        finally:
            # screencast 文件在浏览器关闭后才 finalize, 关闭后再读。
            await browser.close()
    if not raw.exists() or raw.stat().st_size == 0:
        raise EmptyVideoError(f"screencast 产出空文件: {raw}")
    return raw


async def _record_via_frames(
    html_path: str | Path,
    output: Path,
    async_playwright: object,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    scroll: bool,
) -> Path:
    """降级通道:定时截图 + FFmpeg 合成 mp4(h264/yuv420p)。"""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("record_video 空产物且 ffmpeg 缺失, 无法走截图合成通道")
    frames_dir = output.parent / "_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        deadline = time.monotonic() + _safety_seconds(duration_s)
        frame = 0
        ended = False
        shot_start = time.monotonic()
        async with async_playwright() as p:  # type: ignore[attr-defined]
            browser = await p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            try:
                page = await browser.new_page(viewport={"width": width, "height": height})
                audio_driven = await _load_page(page, html_path)
                while time.monotonic() < deadline and not ended:
                    await page.screenshot(path=str(frames_dir / f"{frame:04d}.png"))
                    frame += 1
                    if audio_driven:
                        ended = await page.evaluate(  # type: ignore[attr-defined]
                            "window.__heviAudioEnded === true"
                        )
                    # 目标帧节流:按帧号对齐真实时间轴, 防截图耗时导致 fps 漂移
                    # (否则 24fps 下 11s 音频只截出 ~6s 的帧, 成片音画错位)。
                    target_ms = (shot_start + frame / fps - time.monotonic()) * 1000
                    await page.wait_for_timeout(max(0, int(target_ms)))  # type: ignore[attr-defined]
            finally:
                await browser.close()
        if frame < 2:
            raise EmptyVideoError(f"截图通道仅 {frame} 帧, 视为空产物")
        # 真实平均帧率: 截图耗时不可控(无 GPU 环境 ~80ms/帧), 固定 24fps 会让
        # 成片时长缩水(11s 音频只截出 ~6s 帧) → 用 帧数/实际耗时 编码对齐音频。
        elapsed = max(time.monotonic() - shot_start, 0.1)
        actual_fps = max(1.0, frame / elapsed)
        logger.info("截图通道: %d 帧 / %.2fs → 实际帧率 %.2f", frame, elapsed, actual_fps)
        mp4 = _frames_to_mp4(frames_dir, output, fps=round(actual_fps, 3))
        if not mp4.exists() or mp4.stat().st_size == 0:
            raise EmptyVideoError("截图合成通道产出空文件")
        mp4.replace(output)
        return output
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


async def _load_page(page: object, html_path: str | Path) -> bool:
    """加载页面; 返回是否音频驱动(页面暴露 __heviAudioEnded)。不等待结束。"""
    target = str(html_path)
    if not target.startswith(("http://", "https://", "file://")):
        target = Path(target).resolve().as_uri()
    # wait_until="load": 含外部 B-roll 视频的页面 networkidle 会被视频流拖住,
    # 视频就绪由页面 JS 的 bgReady() 门控(loadeddata), 录制循环等 __heviAudioEnded。
    await page.goto(target, wait_until="load", timeout=30_000)  # type: ignore[attr-defined]
    return bool(
        await page.evaluate("typeof window.__heviAudioEnded !== 'undefined'")  # type: ignore[attr-defined]
    )


async def _wait_audio_ended(page: object, deadline: float, duration_s: float) -> None:
    """轮询 __heviAudioEnded 直至结束或硬超时。"""
    while time.monotonic() < deadline:
        if await page.evaluate("window.__heviAudioEnded === true"):  # type: ignore[attr-defined]
            return
        await page.wait_for_timeout(250)  # type: ignore[attr-defined]
    logger.warning("音频驱动录制超时(%.1fs), 强制结束", _safety_seconds(duration_s))


async def _drive_page(
    page: object,
    html_path: str | Path,
    width: int,
    height: int,
    duration_s: float,
    scroll: bool,
) -> bool:
    """加载页面并驱动录制进程(screencast 通道用); 返回是否音频驱动。"""
    audio_driven = await _load_page(page, html_path)
    if audio_driven:
        # 音频驱动:页面 JS 随 currentTime 翻页; 这里只等待结束标记。
        await _wait_audio_ended(
            page, time.monotonic() + _safety_seconds(duration_s), duration_s
        )
        return True

    # 无音频(外部 HTML): 定时滚动(向后兼容)。
    if scroll:
        total = await page.evaluate("document.body.scrollHeight")  # type: ignore[attr-defined]
        viewport = height
        steps = max(1, int(total // (viewport * 0.98)))
        step_ms = max(30, int(duration_s * 1000 / max(1, steps)))
        for _ in range(steps):
            await page.mouse.wheel(0, int(viewport * 0.98))  # type: ignore[attr-defined]
            await page.wait_for_timeout(step_ms)  # type: ignore[attr-defined]
    else:
        await page.wait_for_timeout(int(duration_s * 1000))  # type: ignore[attr-defined]
    return False


def _probe_duration(video: Path) -> float:
    """ffprobe 探测视频时长; 失败返回 0(触发降级)。"""
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (ValueError, OSError):
        pass
    return 0.0


def _safety_seconds(duration_s: float) -> float:
    """音频驱动硬超时: 音频时长 + 缓冲, 最少 45s。"""
    return max(duration_s * 2 + 10, 45.0)


def _frames_to_mp4(frames_dir: Path, output: Path, *, fps: int) -> Path:
    """PNG 帧序列 → h264 mp4。"""
    mp4 = output.with_suffix(".mp4")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "%04d.png"),
        "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"截图合成 ffmpeg 失败: {result.stderr[-300:]}")
    return mp4


def convert_webm_to_mp4(webm: Path, *, fps: int) -> Path:
    """webm → mp4 (h264 + yuv420p 兼容播放器)。ffmpeg 缺失时保留 webm。"""
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg 不可用,保留 webm 格式: %s", webm)
        return webm
    mp4 = webm.with_suffix(".mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(webm),
        "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        str(mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        logger.warning("webm→mp4 转码失败,保留 webm: %s", result.stderr[-300:])
        return webm
    webm.unlink(missing_ok=True)
    return mp4


__all__ = ["convert_webm_to_mp4", "record_html_to_video"]
