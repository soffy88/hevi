"""HyperFrames 逐帧截图 + 编码 —— obase（外部工具适配：Playwright Chromium / FFmpeg）。"""
from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Mapping, Sequence

from hevi.video.hyperframes_seek import HF_ORIGIN, VENDOR_FILES, frame_digest

__all__ = [
    "VENDOR_DIR",
    "vendor_paths",
    "resolve_playwright_browsers",
    "seek_capture_available",
    "capture_seek_frames",
    "encode_frames_mp4",
]

VENDOR_DIR = Path(__file__).resolve().parent / "hyperframes_vendor"
_THREE_FALLBACKS = [
    Path(__file__).resolve().parents[1] / "layer4_legacy" / "scene3d" / "vendor" / "three" / "three.module.js",
    Path(__file__).resolve().parents[1] / "manga" / "three_vendor" / "three" / "three.module.js",
]

CHROMIUM_ARGS = [
    "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
    "--no-sandbox", "--disable-gpu-sandbox", "--disable-dev-shm-usage",
    "--font-render-hinting=none", "--disable-lcd-text", "--disable-font-subpixel-positioning",
    "--hide-scrollbars", "--force-color-profile=srgb",
]


def vendor_paths() -> dict[str, Path]:
    """本地 vendor 文件名 -> 磁盘路径（three 复用仓库已 vendored 的 three.module.js）。"""
    out: dict[str, Path] = {}
    for key, name in VENDOR_FILES.items():
        p = VENDOR_DIR / name
        if not p.is_file() and key == "three":
            p = next((c for c in _THREE_FALLBACKS if c.is_file()), p)
        out[name] = p
    return out


def resolve_playwright_browsers() -> str | None:
    cands = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), str(Path.home() / ".cache" / "ms-playwright"),
             "/home/soffy/.cache/ms-playwright"]
    for c in cands:
        if c and Path(c).is_dir() and any("chromium" in d.name for d in Path(c).iterdir()):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = c
            return c
    return None


def find_chromium_executable() -> str | None:
    """Playwright 期望的 build 号可能与已装浏览器不一致：直接找已装的可执行文件。"""
    env = os.environ.get("HYPERFRAMES_CHROMIUM")
    if env and Path(env).is_file():
        return env
    base = resolve_playwright_browsers()
    if base:
        pats = ["chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
                "chromium-*/chrome-linux*/chrome"]
        for pat in pats:
            hits = sorted(Path(base).glob(pat), reverse=True)
            if hits:
                return str(hits[0])
    for c in ("/snap/chromium/current/usr/lib/chromium-browser/chrome",):
        if Path(c).is_file():
            return c
    return None


async def _launch(pw):
    try:
        return await pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
    except Exception:
        exe = find_chromium_executable()
        if not exe:
            raise
        return await pw.chromium.launch(headless=True, args=CHROMIUM_ARGS, executable_path=exe)


def seek_capture_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except Exception:
        return False
    return find_chromium_executable() is not None and (VENDOR_DIR / VENDOR_FILES["gsap"]).is_file()


async def capture_seek_frames(
    page_html: str,
    frames_dir: Path,
    times: Sequence[float],
    *,
    width: int,
    height: int,
    asset_dir: Path | None = None,
    extra_files: Mapping[str, Path] | None = None,
    ready_timeout_ms: int = 30000,
    stable_check: bool = False,
) -> dict:
    """加载页面 → 等 HF.whenReady → 逐帧 HF.seek(t, n) → 截图 PNG。

    所有资源通过 page.route 从本地磁盘提供（origin=http://hyperframes.local），不访问网络。
    返回 {"digests": [...], "timeline_duration": float, "console_errors": [...]}。
    """
    from playwright.async_api import async_playwright

    resolve_playwright_browsers()
    frames_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {f"/vendor/{n}": p for n, p in vendor_paths().items()}
    for k, v in (extra_files or {}).items():
        files["/" + k.lstrip("/")] = Path(v)
    page_bytes = page_html.encode("utf-8")
    errors: list[str] = []

    async def handle(route):
        url = route.request.url
        if not url.startswith(HF_ORIGIN):
            await route.abort()  # 禁止外网，保证确定性
            return
        path = url[len(HF_ORIGIN):].split("?", 1)[0] or "/"
        if path in ("/", "/index.html"):
            await route.fulfill(status=200, body=page_bytes, content_type="text/html; charset=utf-8")
            return
        fp = files.get(path)
        if fp is None and asset_dir is not None:
            cand = (asset_dir / path.lstrip("/")).resolve()
            if str(cand).startswith(str(asset_dir.resolve())) and cand.is_file():
                fp = cand
        if fp is None or not fp.is_file():
            await route.fulfill(status=404, body=b"")
            return
        ctype = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
        if fp.suffix == ".js":
            ctype = "text/javascript"
        await route.fulfill(status=200, body=fp.read_bytes(), content_type=ctype)

    digests: list[str] = []
    async with async_playwright() as pw:
        browser = await _launch(pw)
        try:
            ctx = await browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                            reduced_motion="no-preference", color_scheme="light")
            page = await ctx.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            await page.route("**/*", handle)
            await page.goto(f"{HF_ORIGIN}/index.html", wait_until="load")
            await page.wait_for_function("window.HF !== undefined", timeout=ready_timeout_ms)
            await asyncio.wait_for(page.evaluate("HF.whenReady()"), timeout=ready_timeout_ms / 1000)
            tl_dur = float(await page.evaluate("HF.timelineDuration()"))
            clip = {"x": 0, "y": 0, "width": width, "height": height}

            async def shot(t: float, n: int) -> bytes:
                await page.evaluate("([t, n]) => HF.seek(t, n)", [t, n])
                return await page.screenshot(type="png", caret="hide", clip=clip)

            # 预热：首帧前合成器/CSS 动画可能尚未提交，丢弃一次截图
            await shot(times[0] if times else 0.0, 0)
            for n, t in enumerate(times):
                png = await shot(t, n)
                if n == 0 or stable_check:
                    # 稳定性校验：重新 seek 同一时刻，连续两次一致才采用（最多 4 次）
                    for _ in range(3):
                        again = await shot(t, n)
                        if again == png:
                            break
                        png = again
                (frames_dir / f"frame_{n:05d}.png").write_bytes(png)
                digests.append(frame_digest(png))
        finally:
            await browser.close()
    return {"digests": digests, "timeline_duration": tl_dur, "console_errors": errors}


async def encode_frames_mp4(frames_dir: Path, output: Path, fps: int, *, crf: int = 18,
                            preset: str = "medium", audio: Path | None = None) -> None:
    """FFmpeg 帧序列 → H.264 MP4（bitexact、单线程，输出可复现）。"""
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg not found")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames_dir / "frame_%05d.png")]
    if audio:
        cmd += ["-i", str(audio), "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", preset, "-crf", str(crf), "-threads", "1",
            "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-movflags", "+faststart",
            str(output)]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg encode failed (exit {proc.returncode}): {err.decode(errors='replace')[-400:]}")
