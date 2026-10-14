"""SCENE3D renderer: drives the Three.js template with Playwright headless
Chromium through SwiftShader (CPU WebGL), stepping deterministically via
``window.__setTime`` and saving one PNG per frame, then encoding to h264 with
ffmpeg at 30 fps.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .schema import SceneSpec
from .template import build_html


def _find_bin(name: str, *fallbacks: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for fb in fallbacks:
        if Path(fb).is_file():
            return fb
    return name


FFMPEG = _find_bin("ffmpeg", "/home/soffy/.local/bin/ffmpeg")
FFPROBE = _find_bin("ffprobe", "/home/soffy/.local/bin/ffprobe")

# Chromium is provided by the python ``playwright`` package; we locate the
# bundled browser through the package without executing pip installs at runtime.
_CHROMIUM_ARGS = [
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--no-sandbox",
    "--disable-gpu-sandbox",
    "--ignore-gpu-blocklist",
    "--disable-dev-shm-usage",
]


def vendor_dir() -> Path:
    return Path(__file__).resolve().parent / "vendor" / "three"


class SceneRenderer:
    """Render a :class:`SceneSpec` to a video deterministically on CPU."""

    def __init__(self, spec: SceneSpec, workdir: str | Path) -> None:
        self.spec = spec
        self.workdir = Path(workdir)
        self.frames_dir = self.workdir / "frames"
        self.video_path = self.workdir / f"{spec.name}.mp4"

    # -- frame count ------------------------------------------------------ #
    @property
    def frame_count(self) -> int:
        import math

        return max(1, math.ceil(self.spec.duration_s * self.spec.fps))

    def _start_server(self) -> tuple[Any, int]:
        """Serve ``workdir`` over a local HTTP server (module imports need http).

        Returns (server, port). The server runs in a background thread.
        """
        import http.server
        import socketserver
        import threading

        workdir = str(self.workdir)

        class _Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=workdir, **kwargs)

        handler = _Handler
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return httpd, port

    # -- browser rendering ------------------------------------------------ #
    def _write_html(self) -> Path:
        self.workdir.mkdir(parents=True, exist_ok=True)
        html_path = self.workdir / "scene.html"
        html_path.write_text(build_html(self.spec), encoding="utf-8")
        # Copy vendored three.js next to the html so relative imports resolve.
        dst = self.workdir / "vendor" / "three"
        if not dst.exists():
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copytree(vendor_dir(), dst, dirs_exist_ok=True)
        return html_path

    def render_frames(self) -> list[Path]:
        """Step every frame via Playwright + SwiftShader and save PNGs.

        Returns the list of frame paths (frame_0001.png …)."""
        from playwright.sync_api import sync_playwright

        html_path = self._write_html()
        httpd, port = self._start_server()
        page_url = f"http://127.0.0.1:{port}/{html_path.name}"
        self.frames_dir.mkdir(parents=True, exist_ok=True)

        n = self.frame_count
        paths: list[Path] = []
        duration = self.spec.duration_s

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=_CHROMIUM_ARGS)
                page = browser.new_page(
                    viewport={"width": self.spec.width, "height": self.spec.height},
                    device_scale_factor=1,
                )
                page.goto(page_url)
                # Wait until the page signals readiness.
                page.wait_for_function("() => window.__SCENE3D_DONE === true", timeout=60000)

                for i in range(n):
                    t = (i / self.spec.fps) if n > 1 else 0.0
                    # Clamp last frame to end of timeline.
                    if i == n - 1:
                        t = duration
                    page.evaluate(f"window.__setTime({t!r})")
                    frame_path = self.frames_dir / f"frame_{i+1:05d}.png"
                    # Read the canvas pixels from inside the page and POST them
                    # back to our local server as a binary blob.  This avoids
                    # the element-screenshot stability check, which races with
                    # the continuous WebGL repaint driven by `__setTime`.
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
                    import base64 as _b64
                    payload = _b64.b64decode(b64.split(",", 1)[1])
                    frame_path.write_bytes(payload)
                    paths.append(frame_path)
                browser.close()
        finally:
            httpd.shutdown()
        return paths

    # -- diagnostics (collision / framing) -------------------------------- #
    def _with_page(self, fn):
        """Serve the scene, open it in Chromium, run ``fn(page)``, tear down."""
        from playwright.sync_api import sync_playwright

        html_path = self._write_html()
        httpd, port = self._start_server()
        page_url = f"http://127.0.0.1:{port}/{html_path.name}"
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=_CHROMIUM_ARGS)
                page = browser.new_page(
                    viewport={"width": self.spec.width, "height": self.spec.height},
                    device_scale_factor=1,
                )
                page.goto(page_url)
                page.wait_for_function("() => window.__SCENE3D_DONE === true", timeout=60000)
                result = fn(page)
                browser.close()
        finally:
            httpd.shutdown()
        return result

    def probe_collisions(self) -> dict[str, Any]:
        """Return the in-page geometry collision report (rings vs trees, fields vs props)."""
        return self._with_page(lambda page: page.evaluate("() => window.__collisionReport()"))

    def probe_subject_bbox(self, t: float) -> dict[str, Any] | None:
        """Project the primary subject bbox to screen space at time ``t``.

        Returns ``{x0,y0,x1,y1,width,height}`` normalised to [0,1] with y=0 at
        the top of frame, or ``None`` when the scene has no subject.
        """
        return self._with_page(
            lambda page: page.evaluate(
                "(t) => { window.__setTime(t); return window.__subjectScreenBBox(); }", t
            )
        )

    def probe_subject_bboxes(self, times: list[float]) -> list[dict[str, Any] | None]:
        """Project the subject bbox at several times within a single page session."""
        return self._with_page(
            lambda page: page.evaluate(
                "(ts) => ts.map(t => { window.__setTime(t); return window.__subjectScreenBBox(); })",
                times,
            )
        )

    def render_frame_at(self, t: float, out: str | Path) -> Path:
        """Render exactly one frame at time ``t`` to ``out`` (no video encode).

        Used by determinism tests that need a byte-stable single frame.
        """
        import base64 as _b64

        out = Path(out)

        def _grab(page):
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
            return b64

        b64 = self._with_page(_grab)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_b64.b64decode(b64.split(",", 1)[1]))
        return out

    def probe_instance_positions(self) -> list[dict[str, Any]]:
        """Return the placed field instances (kind/x/y/z/tip_y)."""
        return self._with_page(
            lambda page: page.evaluate("() => window.__instancePositions()")
        )

    # -- encode ----------------------------------------------------------- #
    def encode(self, frame_paths: list[Path] | None = None) -> Path:
        if frame_paths is None:
            frame_paths = sorted(self.frames_dir.glob("frame_*.png"))
        pattern = (self.frames_dir / "frame_%05d.png").as_posix()
        cmd = [
            FFMPEG,
            "-y",
            "-framerate", str(self.spec.fps),
            "-start_number", "1",
            "-i", pattern,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "20",
            "-movflags", "+faststart",
            str(self.video_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return self.video_path

    # -- convenience ------------------------------------------------------ #
    def render(self) -> dict[str, Any]:
        """Full pipeline: frames -> video. Returns a metrics dict."""
        import time

        t0 = time.perf_counter()
        paths = self.render_frames()
        encode_t = time.perf_counter()
        self.encode(paths)
        total = time.perf_counter() - t0
        n = len(paths)
        return {
            "video": str(self.video_path),
            "frames": [str(p) for p in paths],
            "frame_count": n,
            "duration_s": self.spec.duration_s,
            "fps": self.spec.fps,
            "width": self.spec.width,
            "height": self.spec.height,
            "total_render_s": round(total, 3),
            "per_frame_s": round(total / max(1, n), 4),
            "encode_s": round(time.perf_counter() - encode_t, 3),
        }


def ffprobe(path: str | Path) -> dict[str, Any]:
    """Return a small, stable dict of stream facts for a media file."""
    cmd = [
        FFPROBE,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    out = subprocess.run(cmd, check=True, capture_output=True).stdout
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration": float(data.get("format", {}).get("duration", 0.0)),
        "size_bytes": int(data.get("format", {}).get("size", 0)),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "codec": video.get("codec_name", ""),
        "nb_frames": video.get("nb_frames", ""),
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    }


def ffprobe_frames(path: str | Path) -> dict[str, Any]:
    """Probe a video and actually *count* its decoded frames.

    ``nb_frames`` from ``ffprobe`` is a container metadata field and is absent
    for some muxers; ``-count_frames`` decodes the stream and reports
    ``nb_read_frames``, which is the ground truth for an integrity gate.  A
    dropped/truncated encode (e.g. the last frame missing) is caught here.
    """
    cmd = [
        FFPROBE,
        "-v", "error",
        "-select_streams", "v:0",
        "-count_frames",
        "-print_format", "json",
        "-show_entries", "stream=nb_read_frames,duration,width,height,r_frame_rate",
        "-show_entries", "format=duration",
        str(path),
    ]
    out = subprocess.run(cmd, check=True, capture_output=True).stdout
    data = json.loads(out)
    streams = data.get("streams", [])
    video = streams[0] if streams else {}
    frames_raw = video.get("nb_read_frames", "")
    return {
        "nb_read_frames": int(frames_raw) if str(frames_raw).isdigit() else -1,
        "duration": float(video.get("duration", 0.0) or data.get("format", {}).get("duration", 0.0)),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "r_frame_rate": video.get("r_frame_rate", ""),
    }


def sha256(path: str | Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_contact_sheet(
    frames: list[Path],
    out: str | Path,
    cols: int = 5,
    thumb_w: int = 320,
) -> Path:
    """Montage sampled frames into a single contact sheet PNG via ffmpeg."""
    import math

    out = Path(out)
    if not frames:
        raise ValueError("no frames to montage")
    rows = math.ceil(len(frames) / cols)
    tmp_dir = out.parent / (out.stem + "_cs_frames")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for idx, fr in enumerate(frames):
        dst = tmp_dir / f"{idx:05d}.png"
        if not dst.exists():
            shutil.copy(fr, dst)
    cmd = [
        FFMPEG, "-y",
        "-framerate", "1",
        "-start_number", "0",
        "-i", (tmp_dir / "%05d.png").as_posix(),
        "-vf", f"scale={thumb_w}:-1,tile={cols}x{rows}",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def iter_frame_step(n: int, step: int) -> Iterator[int]:
    """Yield indices for a contact sheet sample."""
    yield from range(0, n, step)
