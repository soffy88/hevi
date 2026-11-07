"""obase: Playwright (SwiftShader CPU WebGL) frame capture + ffmpeg encode.

Reuses the legacy scene3d chromium resolver / vendored three.js / ffprobe helpers
so there is one browser + ffmpeg adapter in the repo.
"""
from __future__ import annotations

import base64
import http.server
import shutil
import socketserver
import subprocess
import threading
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.scene3d.browser import resolve_browsers_path
from hevi.layer4_legacy.scene3d.renderer import _CHROMIUM_ARGS, FFMPEG, vendor_dir

_SNAP_CHROME = "/snap/chromium/current/usr/lib/chromium-browser/chrome"
_GRAB = """async () => { const c = document.getElementById('c');
  return await new Promise((res, rej) => c.toBlob(b => { const r = new FileReader();
    r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(b); }, 'image/png')); }"""


def stage_workdir(workdir: Path, html: str) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    dst = workdir / "vendor" / "three"
    if not (dst / "three.module.js").is_file():
        shutil.copytree(vendor_dir(), dst, dirs_exist_ok=True)
    page = workdir / "scene.html"
    page.write_text(html, encoding="utf-8")
    return page


def _serve(root: Path):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)
        def log_message(self, *a):  # quiet
            pass
    httpd = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def capture_frames(workdir: Path, page_name: str, *, width: int, height: int,
                   times: list[float], frames_dir: Path, timeout_ms: int = 120000) -> list[Path]:
    """Load the page, step ``__setFrame(i, t)`` for each time, save PNG per frame."""
    from playwright.sync_api import sync_playwright

    frames_dir.mkdir(parents=True, exist_ok=True)
    httpd, port = _serve(workdir)
    out: list[Path] = []
    try:
        with sync_playwright() as p:
            if resolve_browsers_path() is not None:
                browser = p.chromium.launch(args=_CHROMIUM_ARGS)
            else:
                browser = p.chromium.launch(executable_path=_SNAP_CHROME, args=_CHROMIUM_ARGS)
            try:
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{port}/{page_name}")
                page.wait_for_function("() => window.__READY === true", timeout=timeout_ms)
                err = page.evaluate("() => window.__ERROR || null")
                if err or errors:
                    raise RuntimeError(f"scene page error: {err or errors[0]}")
                for i, t in enumerate(times):
                    page.evaluate("([i, t]) => window.__setFrame(i, t)", [i, t])
                    b64 = page.evaluate(_GRAB)
                    fp = frames_dir / f"frame_{i + 1:05d}.png"
                    fp.write_bytes(base64.b64decode(b64.split(",", 1)[1]))
                    out.append(fp)
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
    return out


def encode_mp4(frames_dir: Path, fps: int, out: Path, *, crf: int = 20) -> Path:
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-framerate", str(fps), "-start_number", "1",
           "-i", (frames_dir / "frame_%05d.png").as_posix(), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-preset", "veryfast", "-crf", str(crf), "-threads", "1", "-movflags", "+faststart",
           "-fflags", "+bitexact", "-flags:v", "+bitexact", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def contact_sheet(frames: list[Path], out: Path, cols: int = 4, thumb_w: int = 320) -> Path:
    import math
    tmp = out.parent / "_sheet"
    tmp.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        shutil.copyfile(f, tmp / f"{i:05d}.png")
    rows = math.ceil(len(frames) / cols)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-framerate", "1", "-i", (tmp / "%05d.png").as_posix(),
                    "-vf", f"scale={thumb_w}:-1,tile={cols}x{rows}", "-frames:v", "1", str(out)],
                   check=True, capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return out
