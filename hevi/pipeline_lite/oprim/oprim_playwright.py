"""oprim:oprim_playwright —— 无头浏览器录屏原子能力(绝对无状态)。

只负责:接收一个本地 HTML 文件路径/URL,用 Playwright 无头 Chromium
录制滚动/音频驱动过程,输出视频文件路径。不做任何业务校验与状态写入。

v9.1 音频驱动:若 HTML 由 oprim_html_gen 生成(含 <audio> + JS 轮询), 页面会
在音频 onended 时置 window.__heviAudioEnded=true —— 录制循环轮询该标记结束,
画面翻页由页面内 JS 随 audio.currentTime 驱动(scrollIntoView), 实现音画同步。

html-video 工程化并入(2026-08):
  * 字体冻结: 加载前 pause 全部 CSS/SMIL 动画, fonts.ready 后再 unfreeze,
    避免 fallback 字体闪烁与开场动画被录进 lead-in;
  * 动画时长探测: 读 CSS @keyframes + 有限 GSAP tween, 非音频驱动时
    用 max(用户 duration, 探测时长) 覆盖录制窗口。

双通道实现(自动降级):
  1. 首选 Playwright 原生 record_video(screencast webm);
  2. 空产物自动降级为「定时截图 + FFmpeg 合成」。
"""

from __future__ import annotations

import contextlib
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

# 注入: 在任何 stylesheet 生效前冻结动画(html-video 同款)。
_FREEZE_INIT_JS = """
(() => {
  const style = document.createElement('style');
  style.id = '__hevi_freeze';
  style.textContent =
    '*, *::before, *::after { animation-play-state: paused !important;' +
    ' -webkit-animation-play-state: paused !important; }';
  const attach = () => (document.head || document.documentElement).appendChild(style);
  if (document.head || document.documentElement) attach();
  else document.addEventListener('DOMContentLoaded', attach, { once: true });
  window.__heviUnfreeze = () => { document.getElementById('__hevi_freeze')?.remove(); };
})();
"""

# 等 stylesheet + fonts.load + fonts.ready(带硬超时)。
_WAIT_FONTS_JS = """
() => new Promise((resolve) => {
  const fonts = document.fonts;
  if (!fonts || typeof fonts.ready?.then !== 'function') { resolve(); return; }
  let settled = false;
  const finish = () => {
    if (settled) return;
    settled = true;
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  };
  const cap = setTimeout(finish, 8000);
  const links = Array.from(document.querySelectorAll('link[rel="stylesheet"]'));
  const linkDone = links.map((link) => {
    try { if (link.sheet && link.sheet.cssRules) return Promise.resolve(); } catch (e) {}
    return new Promise((r) => {
      const done = () => r();
      link.addEventListener('load', done, { once: true });
      link.addEventListener('error', done, { once: true });
      setTimeout(done, 6000);
    });
  });
  Promise.all(linkDone)
    .then(() => {
      const loads = [];
      fonts.forEach((face) => {
        try { loads.push(face.load().catch(() => undefined)); } catch (e) {}
      });
      return Promise.all(loads);
    })
    .then(() => fonts.ready)
    .then(() => { clearTimeout(cap); finish(); })
    .catch(() => { clearTimeout(cap); finish(); });
});
"""

# 探测有限 CSS / GSAP 动画时长(ms);忽略 infinite。
_PROBE_ANIM_MS_JS = """
() => {
  let maxMs = 0;
  Array.from(document.querySelectorAll('*')).forEach((el) => {
    const s = getComputedStyle(el);
    const durs = (s.animationDuration || '').split(',');
    const dels = (s.animationDelay || '').split(',');
    const iters = (s.animationIterationCount || '').split(',');
    durs.forEach((d, i) => {
      if ((iters[i] || '').trim() === 'infinite') return;
      maxMs = Math.max(
        maxMs,
        ((parseFloat(d) || 0) + (parseFloat(dels[i] || '0') || 0)) * 1000
      );
    });
  });
  let gsapMs = 0;
  try {
    const g = window.gsap;
    const children = g?.globalTimeline?.getChildren?.(true, true, true) || [];
    for (const c of children) {
      const repeat = typeof c.repeat === 'function' ? c.repeat() : (c.vars?.repeat ?? 0);
      if (repeat === -1) continue;
      const td = typeof c.totalDuration === 'function' ? c.totalDuration() : 0;
      if (Number.isFinite(td)) gsapMs = Math.max(gsapMs, td * 1000);
    }
  } catch (e) {}
  return Math.max(maxMs, gsapMs);
}
"""


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
    freeze_until_fonts: bool = True,
    probe_animation: bool = True,
) -> Path:
    """录制 HTML 页面过程,输出视频。

    依赖 ``playwright`` + ``playwright install chromium`` + ``ffmpeg``(降级路径)。
    * 音频驱动: 轮询 window.__heviAudioEnded 结束录制(硬超时兜底);
    * 无音频(任意 HTML): 按 duration_s / 探测动画时长 定时滚动。
    * freeze_until_fonts: html-video 字体冻结(默认开);
    * probe_animation: 无音频时探测 CSS/GSAP 时长并延长录制窗口。
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
        raw, effective_dur = await _record_via_screencast(
            html_path,
            output,
            async_playwright,
            width,
            height,
            fps,
            duration_s,
            scroll,
            freeze_until_fonts=freeze_until_fonts,
            probe_animation=probe_animation,
        )
        if convert_to_mp4:
            converted = convert_webm_to_mp4(raw, fps=fps)
            converted.replace(output)
        else:
            raw.replace(output)
        # 时长可信度校验: 受限容器 screencast 可能产出非空但极短的 webm
        if _probe_duration(output) < effective_dur * 0.6:
            raise EmptyVideoError(
                f"screencast 时长过短({_probe_duration(output):.1f}s < {effective_dur * 0.6:.1f}s)"
            )
    except EmptyVideoError as exc:
        logger.warning("record_video 不可信(%s), 降级截图+ffmpeg 通道", exc)
        return await _record_via_frames(
            html_path,
            output,
            async_playwright,
            width,
            height,
            fps,
            duration_s,
            scroll,
            freeze_until_fonts=freeze_until_fonts,
            probe_animation=probe_animation,
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
    *,
    freeze_until_fonts: bool,
    probe_animation: bool,
) -> tuple[Path, float]:
    """Playwright 原生 screencast 通道。空产物抛 EmptyVideoError。返回 (path, effective_dur)。"""
    effective = duration_s
    async with async_playwright() as p:  # type: ignore[operator]
        browser = await p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        try:
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=str(output.parent / "_rec"),
                record_video_size={"width": width, "height": height},
            )
            page = await context.new_page()
            effective = await _drive_page(
                page,
                html_path,
                width,
                height,
                duration_s,
                scroll,
                freeze_until_fonts=freeze_until_fonts,
                probe_animation=probe_animation,
            )
            video = page.video
            if video is None:
                raise EmptyVideoError("Playwright 未产出视频文件")
            await context.close()
            raw = Path(await video.path())
        finally:
            await browser.close()
    if not raw.exists() or raw.stat().st_size == 0:
        raise EmptyVideoError(f"screencast 产出空文件: {raw}")
    return raw, effective


async def _record_via_frames(
    html_path: str | Path,
    output: Path,
    async_playwright: object,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    scroll: bool,
    *,
    freeze_until_fonts: bool = True,
    probe_animation: bool = True,
) -> Path:
    """降级通道:定时截图 + FFmpeg 合成 mp4(h264/yuv420p)。"""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("record_video 空产物且 ffmpeg 缺失, 无法走截图合成通道")
    frames_dir = output.parent / "_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        frame = 0
        ended = False
        shot_start = time.monotonic()
        effective_dur = duration_s
        async with async_playwright() as p:  # type: ignore[operator]
            browser = await p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            try:
                page = await browser.new_page(viewport={"width": width, "height": height})
                audio_driven, effective_dur = await _prepare_page(
                    page,
                    html_path,
                    duration_s,
                    freeze_until_fonts=freeze_until_fonts,
                    probe_animation=probe_animation,
                )
                deadline = time.monotonic() + _safety_seconds(effective_dur)
                while time.monotonic() < deadline and not ended:
                    await page.screenshot(path=str(frames_dir / f"{frame:04d}.png"))
                    frame += 1
                    if audio_driven:
                        ended = await page.evaluate(
                            "window.__heviAudioEnded === true"
                        )
                    target_ms = (shot_start + frame / fps - time.monotonic()) * 1000
                    await page.wait_for_timeout(max(0, int(target_ms)))
            finally:
                await browser.close()
        if frame < 2:
            raise EmptyVideoError(f"截图通道仅 {frame} 帧, 视为空产物")
        elapsed = max(time.monotonic() - shot_start, 0.1)
        actual_fps = max(1.0, frame / elapsed)
        logger.info("截图通道: %d 帧 / %.2fs → 实际帧率 %.2f", frame, elapsed, actual_fps)
        mp4 = _frames_to_mp4(frames_dir, output, fps=round(actual_fps))
        if not mp4.exists() or mp4.stat().st_size == 0:
            raise EmptyVideoError("截图合成通道产出空文件")
        mp4.replace(output)
        return output
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


async def _prepare_page(
    page: object,
    html_path: str | Path,
    duration_s: float,
    *,
    freeze_until_fonts: bool,
    probe_animation: bool,
) -> tuple[bool, float]:
    """加载 + 字体冻结/解冻 + 可选动画时长探测。返回 (audio_driven, effective_duration_s)。"""
    if freeze_until_fonts:
        await page.add_init_script(_FREEZE_INIT_JS)  # type: ignore[attr-defined]

    target = str(html_path)
    if not target.startswith(("http://", "https://", "file://")):
        target = Path(target).resolve().as_uri()
    # domcontentloaded: 避免跨域 B-roll 拖死 load(html-video 同款取舍)
    await page.goto(target, wait_until="domcontentloaded", timeout=30_000)  # type: ignore[attr-defined]

    if freeze_until_fonts:
        try:
            await page.evaluate(_WAIT_FONTS_JS)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("fonts wait skipped: %s", exc)
        with contextlib.suppress(Exception):
            await page.evaluate(  # type: ignore[attr-defined]
                "() => { window.__heviUnfreeze && window.__heviUnfreeze(); }"
            )
        await page.wait_for_timeout(50)  # type: ignore[attr-defined]

    audio_driven = bool(
        await page.evaluate(  # type: ignore[attr-defined]
            "typeof window.__heviAudioEnded !== 'undefined' "
            "&& document.getElementById('hevi-master') != null"
        )
    )

    effective = float(duration_s)
    if probe_animation and not audio_driven:
        try:
            anim_ms = float(await page.evaluate(_PROBE_ANIM_MS_JS))  # type: ignore[attr-defined]
            # +0.4s settle; 上限 30s 防 runaway
            needed = min(30.0, (anim_ms + 400.0) / 1000.0)
            if needed > effective:
                logger.info(
                    "动画时长探测: %.1fs > 请求 %.1fs, 延长录制窗口", needed, effective
                )
                effective = needed
        except Exception as exc:
            logger.debug("animation probe failed: %s", exc)

    return audio_driven, effective


async def _load_page(page: object, html_path: str | Path) -> bool:
    """兼容旧调用:加载页面; 返回是否音频驱动。"""
    audio_driven, _ = await _prepare_page(
        page, html_path, duration_s=5.0, freeze_until_fonts=True, probe_animation=False
    )
    return audio_driven


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
    *,
    freeze_until_fonts: bool = True,
    probe_animation: bool = True,
) -> float:
    """加载页面并驱动录制; 返回有效录制时长(秒)。"""
    audio_driven, effective = await _prepare_page(
        page,
        html_path,
        duration_s,
        freeze_until_fonts=freeze_until_fonts,
        probe_animation=probe_animation,
    )
    if audio_driven:
        await _wait_audio_ended(
            page, time.monotonic() + _safety_seconds(effective), effective
        )
        return effective

    if scroll:
        total = await page.evaluate("document.body.scrollHeight")  # type: ignore[attr-defined]
        viewport = height
        steps = max(1, int(total // (viewport * 0.98)))
        step_ms = max(30, int(effective * 1000 / max(1, steps)))
        for _ in range(steps):
            await page.mouse.wheel(0, int(viewport * 0.98))  # type: ignore[attr-defined]
            await page.wait_for_timeout(step_ms)  # type: ignore[attr-defined]
    else:
        await page.wait_for_timeout(int(effective * 1000))  # type: ignore[attr-defined]
    return effective


def _probe_duration(video: Path) -> float:
    """ffprobe 探测视频时长; 失败返回 0(触发降级)。"""
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(video),
            ],
            capture_output=True,
            text=True,
            timeout=30,
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
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "%04d.png"),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
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
        "ffmpeg",
        "-y",
        "-i",
        str(webm),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        str(mp4),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        logger.warning("webm→mp4 转码失败,保留 webm: %s", result.stderr[-300:])
        return webm
    webm.unlink(missing_ok=True)
    return mp4


__all__ = ["convert_webm_to_mp4", "record_html_to_video"]
