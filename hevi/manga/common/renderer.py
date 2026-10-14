"""CPU-only Three.js renderer via Playwright + SwiftShader.

This is the single shared rendering engine for the MANGA unit (roomgacha,
locscout, namegen background plates).  It is a clean-room re-implementation
of the approach used by the scene3d unit: serve a self-contained HTML page
that exposes ``window.__setTime(t)`` and ``window.__framePixels()``, drive
frames deterministically, and encode with ffmpeg.

No GPU, no paid API.  The browser is launched with SwiftShader so WebGL runs
on CPU.
"""

from __future__ import annotations

import base64
import json
import math
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

# Locate system binaries.
import shutil as _shutil

_FFMPEG = _shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
_FFPROBE = _shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"

_CHROMIUM_ARGS = [
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--no-sandbox",
    "--disable-gpu-sandbox",
    "--ignore-gpu-blocklist",
    "--disable-dev-shm-usage",
]


def _vendor_dst(workdir: Path) -> Path:
    return workdir / "vendor" / "three"


def copy_three_vendor(workdir: Path) -> None:
    """Copy the vendored MIT three.js next to the page so relative imports resolve."""
    src = Path(__file__).resolve().parents[1] / "three_vendor" / "three"
    dst = _vendor_dst(workdir)
    if dst.exists() and any(dst.iterdir()):
        return
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _start_server(workdir: Path):
    """Serve ``workdir`` over 127.0.0.1 random port (ES modules need http)."""
    import http.server
    import socketserver

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(workdir), **kwargs)

    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def ffprobe(path: str | Path) -> dict[str, Any]:
    """Stable dict of stream facts for a media file."""
    cmd = [
        _FFPROBE,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    out = subprocess.run(cmd, check=True, capture_output=True).stdout
    data = json.loads(out)
    video = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    return {
        "duration": float(data.get("format", {}).get("duration", 0.0)),
        "size_bytes": int(data.get("format", {}).get("size", 0)),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "codec": video.get("codec_name", ""),
        "nb_frames": video.get("nb_frames", ""),
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    }


class FrameRenderer:
    """Render a Three.js page to PNG frames deterministically on CPU.

    The page must expose (normally via a module-injected global):

        window.__setTime(t)      -> advance simulation to absolute time t
        window.__framePixels()   -> data:image/png;base64 of current canvas
        window.__SCENE3D_DONE    -> true once ready

    ``frame_count`` is derived from ``duration_s`` and ``fps``.
    """

    def __init__(
        self,
        html: str,
        workdir: str | Path,
        width: int,
        height: int,
        duration_s: float,
        fps: int = 30,
    ) -> None:
        self.html = html
        self.workdir = Path(workdir)
        self.frames_dir = self.workdir / "frames"
        self.width = width
        self.height = height
        self.duration_s = duration_s
        self.fps = fps

    @property
    def frame_count(self) -> int:
        return max(1, math.ceil(self.duration_s * self.fps))

    def _write(self) -> Path:
        self.workdir.mkdir(parents=True, exist_ok=True)
        copy_three_vendor(self.workdir)
        html_path = self.workdir / "scene.html"
        html_path.write_text(self.html, encoding="utf-8")
        return html_path

    def render_frames(self) -> list[Path]:
        from playwright.sync_api import sync_playwright

        html_path = self._write()
        httpd, port = _start_server(self.workdir)
        page_url = f"http://127.0.0.1:{port}/{html_path.name}"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        n = self.frame_count
        paths: list[Path] = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=_CHROMIUM_ARGS)
                page = browser.new_page(
                    viewport={"width": self.width, "height": self.height},
                    device_scale_factor=1,
                )
                page.goto(page_url)
                page.wait_for_function(
                    "() => window.__SCENE3D_DONE === true", timeout=60000
                )
                for i in range(n):
                    t = (i / self.fps) if n > 1 else 0.0
                    if i == n - 1:
                        t = self.duration_s
                    page.evaluate(f"window.__setTime({t!r})")
                    b64 = page.evaluate(
                        """async () => {
                          const c = document.getElementById('c');
                          return await new Promise((resolve, reject) => {
                            c.toBlob(blob => {
                              const r = new FileReader();
                              r.onload = () => resolve(r.result);
                              r.onerror = reject;
                              r.readAsDataURL(blob);
                            }, 'image/png');
                          });
                        }"""
                    )
                    payload = base64.b64decode(b64.split(",", 1)[1])
                    fp = self.frames_dir / f"frame_{i+1:05d}.png"
                    fp.write_bytes(payload)
                    paths.append(fp)
                browser.close()
        finally:
            httpd.shutdown()
        return paths


def encode_video(
    frames_dir: Path,
    out_path: str | Path,
    fps: int = 30,
    start_number: int = 1,
) -> Path:
    cmd = [
        _FFMPEG,
        "-y",
        "-framerate", str(fps),
        "-start_number", str(start_number),
        "-i", (Path(frames_dir) / "frame_%05d.png").as_posix(),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        "-crf", "20",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return Path(out_path)


def make_contact_sheet(
    frames: list[Path], out: str | Path, cols: int = 5, thumb_w: int = 320
) -> Path:
    import math

    out = Path(out)
    if not frames:
        raise ValueError("no frames to montage")
    rows = math.ceil(len(frames) / cols)
    tmp = out.parent / (out.stem + "_cs_frames")
    tmp.mkdir(parents=True, exist_ok=True)
    for idx, fr in enumerate(frames):
        dst = tmp / f"{idx:05d}.png"
        if not dst.exists():
            shutil.copy(fr, dst)
    cmd = [
        _FFMPEG, "-y",
        "-framerate", "1",
        "-start_number", "0",
        "-i", (tmp / "%05d.png").as_posix(),
        "-vf", f"scale={thumb_w}:-1,tile={cols}x{rows}",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out
