"""Virtual-clock recorder (``video.virtual_clock_recorder``).

Clean-room minimal recorder for the frame-capture discipline
described in ``hevi-vs-open-3d-skills.md`` section 2.8. Every
line here is newly written; no script from the source
repository is copied. The recorder reuses only hevi's own
harness: Playwright Chromium with SwiftShader, the vendored
Three.js module, and the ``__hf`` settle protocol from
``hevi.capabilities.athenaion_browser``. It does not use CDP
BeginFrame capture: frames are whole screenshots taken only
after the ``__hf`` settle confirmation reads back, exactly as
the deterministic-render discipline requires.

How it works: before any page script runs, an init script
replaces the time sources -- ``performance.now`` and
``Date.now`` read a virtual clock, ``requestAnimationFrame``
queues callbacks that run only when the clock advances, and
``setTimeout`` / ``setInterval`` are routed through a
``later()`` queue that runs on virtual time. Each output frame
advances the virtual clock by exactly one frame interval, pins
CSS/Web Animations to virtual time, seeks every ``<video>`` to
the frame time, calls ``window.__recordFrame(t)`` when the page
exposes it, and then drives ``window.__hf.seekFrame`` and waits
for the settle confirmation. The served page answers HTTP Range
requests (a plain static server that ignores Range would record
the first frame repeatedly for video-backed pages); the
harness serves the page, the vendored Three.js module, and any
caller-supplied extra files with Range support.

Determinism is measured, not claimed: the same page is
recorded twice in fresh browsers and the per-frame PNG hashes
must match exactly, in order. A missing Playwright/Chromium,
vendored Three.js module, or ffmpeg raises
:class:`CapabilityError` -- the recorder never returns a fake
frame or a fake video. No author-reported number is used: the
output frame rate is a caller-supplied parameter of each
recording, and no stall rate or frame-time threshold is
asserted.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hevi.capabilities.athenaion_browser import (
    CHROMIUM_ARGS,
    page_html,
    resolve_three_module,
    three_revision,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

VIRTUAL_CLOCK_INIT = """
window.__vclock = { t: 0, epoch: 1700000000000, rafQueue: [], laterQueue: [], rafId: 0, timerId: 0 };
(function () {
  const vc = window.__vclock;
  performance.now = function () { return vc.t; };
  Date.now = function () { return vc.epoch + vc.t; };
  window.requestAnimationFrame = function (cb) {
    const id = ++vc.rafId;
    vc.rafQueue.push({ id: id, cb: cb });
    return id;
  };
  window.cancelAnimationFrame = function (id) {
    vc.rafQueue = vc.rafQueue.filter(function (e) { return e.id !== id; });
  };
  window.later = function (fn, delayMs) {
    vc.laterQueue.push({ fn: fn, at: vc.t + (delayMs || 0), repeat: 0, delay: 0 });
  };
  window.setTimeout = function (fn, delayMs) {
    const id = ++vc.timerId;
    vc.laterQueue.push({ fn: fn, at: vc.t + (delayMs || 0), repeat: 0, delay: 0, id: id });
    return id;
  };
  window.clearTimeout = function (id) {
    vc.laterQueue = vc.laterQueue.filter(function (e) { return e.id !== id; });
  };
  window.setInterval = function (fn, delayMs) {
    const id = ++vc.timerId;
    vc.laterQueue.push({ fn: fn, at: vc.t + (delayMs || 0), repeat: 1, delay: delayMs || 0, id: id });
    return id;
  };
  window.clearInterval = function (id) {
    vc.laterQueue = vc.laterQueue.filter(function (e) { return e.id !== id; });
  };
  window.__vcSetTime = function (tMs) {
    vc.t = tMs;
    let guard = 0;
    while (guard++ < 1000) {
      const due = vc.laterQueue.filter(function (e) { return e.at <= tMs; });
      if (!due.length) break;
      due.sort(function (a, b) { return a.at - b.at; });
      const first = due[0];
      vc.laterQueue = vc.laterQueue.filter(function (e) { return e !== first; });
      if (first.repeat) {
        vc.laterQueue.push({ fn: first.fn, at: tMs + first.delay, repeat: 1, delay: first.delay, id: first.id });
      }
      try { first.fn(); } catch (err) { window.__hfError = String(err); }
    }
    const cbs = vc.rafQueue.splice(0, vc.rafQueue.length);
    cbs.forEach(function (e) {
      try { e.cb(tMs); } catch (err) { window.__hfError = String(err); }
    });
  };
  window.__vcFrame = function (tMs, frame) {
    window.__vcSetTime(tMs);
    try {
      document.getAnimations().forEach(function (a) {
        try { a.pause(); a.currentTime = tMs; } catch (err) {}
      });
    } catch (err) {}
    const vids = Array.from(document.querySelectorAll('video'));
    vids.forEach(function (v) {
      try {
        v.pause();
        const target = tMs / 1000;
        if (Math.abs(v.currentTime - target) > 0.001) v.currentTime = target;
      } catch (err) {}
    });
    if (typeof window.__recordFrame === 'function') {
      try { window.__recordFrame(tMs / 1000); } catch (err) { window.__hfError = String(err); }
    }
    if (window.__hf && typeof window.__hf.seekFrame === 'function') {
      return window.__hf.seekFrame(frame);
    }
    return null;
  };
  document.addEventListener('DOMContentLoaded', function () {
    const style = document.createElement('style');
    style.textContent = '*{transition-duration:0s !important;}';
    document.head.appendChild(style);
  });
})();
"""


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    if not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    if start < 0 or end < start or start >= size:
        return None
    return (start, min(end, size - 1))


class _RangeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def _serve(self, *, head_only: bool) -> None:
        files: dict[str, tuple[bytes, str]] = self.server.files  # type: ignore[attr-defined]
        entry = files.get(self.path)
        if entry is None:
            self.send_response(404)
            self.end_headers()
            return
        body, ctype = entry
        ranged = _parse_range(self.headers.get("Range", ""), len(body))
        if ranged is not None:
            start, end = ranged
            chunk = body[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            if not head_only:
                self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(head_only=True)


def build_test_page(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    with_video: bool = False,
    clip_url: str = "/clip.mp4",
) -> str:
    """Build the deterministic test page used for evidence.

    The page renders with the vendored Three.js module (the
    same WebGL path the Athenaion harness captures reliably in
    headless Chromium): a box whose position and hue are a pure
    function of ``t`` only, plus a CSS-animated spinner pinned
    by the recorder, and -- when ``with_video`` -- a video
    element the recorder seeks per frame. No wall clock, no
    unseeded randomness.
    """
    total = max(1, round(duration_s * fps))
    video_js = ""
    if with_video:
        video_js = f"""
const video = document.createElement('video');
video.id = 'clip';
video.src = {json.dumps(clip_url)};
video.muted = true;
video.preload = 'auto';
video.playsInline = true;
video.style.cssText = 'position:absolute;left:8px;top:8px;width:120px;height:68px;z-index:2;';
video.addEventListener('loadeddata', function () {{ window.__vclockVideoReady = true; }});
document.body.appendChild(video);
"""
    js = f"""
import * as THREE from 'three';
const W = {width}, H = {height}, FPS = {fps}, TOTAL = {total};
const renderer = new THREE.WebGLRenderer({{ antialias: false, preserveDrawingBuffer: true }});
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
document.getElementById('stage').appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0b12);
const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
camera.position.set(0, 0, 6);
camera.lookAt(0, 0, 0);
scene.add(new THREE.AmbientLight(0xffffff, 1.0));
const boxMat = new THREE.MeshBasicMaterial({{ color: 0xe2552e }});
const box = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), boxMat);
scene.add(box);
const spinner = document.createElement('div');
spinner.id = 'spinner';
spinner.style.cssText = 'position:absolute;width:24px;height:24px;left:200px;top:20px;background:#3f7fa8;animation:spin 2s linear infinite;z-index:2;';
const spinStyle = document.createElement('style');
spinStyle.textContent = '@keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}';
document.head.appendChild(spinStyle);
document.body.appendChild(spinner);
const label = document.createElement('div');
label.id = 'label';
label.style.cssText = 'position:absolute;left:8px;top:120px;font:16px monospace;color:#fff;z-index:2;';
document.body.appendChild(label);
{video_js}
function update(t) {{
  const x = -2.2 + ((t * 1.6) % 4.4);
  box.position.x = x;
  box.rotation.y = t * 1.5;
  boxMat.color.setHSL(((t * 90) % 360) / 360, 0.7, 0.55);
  label.textContent = 't=' + t.toFixed(3);
  renderer.render(scene, camera);
}}
window.__recordFrame = function (t) {{ update(t); }};
window.__hfSettledFrame = -1;
window.__hf = {{
  getDurationFrames() {{ return TOTAL; }},
  seekFrame(frame) {{
    if (!Number.isInteger(frame) || frame < 0 || frame >= TOTAL) throw new RangeError('frame out of range: ' + frame);
    const t = Math.floor(frame) / FPS;
    update(t);
    window.__hfSettledFrame = frame;
    return {{ frame: frame, t: t, settled: true }};
  }},
  destroy() {{ renderer.dispose(); }}
}};
update(0);
window.__hfReady = true;
"""
    return page_html(js)


def _encode_mp4(frames_dir: Path, *, fps: int, out_path: Path) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise CapabilityError(
            "video.virtual_clock_recorder: ffmpeg is required to encode mp4"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", str(out_path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        raise CapabilityError(
            "video.virtual_clock_recorder: ffmpeg encode failed: "
            + proc.stderr[-500:]
        )
    ffprobe = shutil.which("ffprobe")
    probe: dict[str, Any] = {}
    if ffprobe is not None:
        probe_proc = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(out_path)],
            capture_output=True, text=True, timeout=60,
        )
        try:
            probe = json.loads(probe_proc.stdout) if probe_proc.stdout else {}
        except json.JSONDecodeError:
            probe = {"unparseable": probe_proc.stdout[:200]}
    return {"mp4": str(out_path), "bytes": out_path.stat().st_size, "ffprobe": probe}


def record_virtual_clock(
    *,
    html: str,
    out_dir: Path,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    extra_files: dict[str, tuple[bytes, str]] | None = None,
    runs: int = 2,
    encode: bool = True,
) -> dict[str, Any]:
    """Record ``html`` ``runs`` times under the virtual clock.

    ``fps`` is a caller-supplied recording parameter; it has no
    default in this function. Returns a report; a hash mismatch
    between runs is ``verdict: "fail"`` in the report, while
    missing infrastructure raises :class:`CapabilityError`.
    """
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise CapabilityError("video.virtual_clock_recorder: fps must be a positive integer")
    if duration_s <= 0:
        raise CapabilityError("video.virtual_clock_recorder: duration_s must be > 0")
    if runs < 1:
        raise CapabilityError("video.virtual_clock_recorder: runs must be >= 1")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise CapabilityError(
            f"video.virtual_clock_recorder: Playwright is required: {exc}"
        ) from exc
    three_path = resolve_three_module()
    total = max(1, round(duration_s * fps))
    files: dict[str, tuple[bytes, str]] = {
        "/": (html.encode("utf-8"), "text/html; charset=utf-8"),
        "/three.module.js": (three_path.read_bytes(), "text/javascript; charset=utf-8"),
    }
    if extra_files:
        files.update(extra_files)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    server.files = files  # type: ignore[attr-defined]
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_runs: list[dict[str, Any]] = []
    try:
        with sync_playwright() as pw:
            for run_index in range(runs):
                browser = pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
                try:
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1,
                    )
                    page.add_init_script(VIRTUAL_CLOCK_INIT)
                    page.goto(f"http://127.0.0.1:{port}/", wait_until="load", timeout=30000)
                    page.wait_for_function("window.__hfReady === true", timeout=30000)
                    error = page.evaluate("window.__hfError")
                    if error:
                        raise CapabilityError(
                            f"video.virtual_clock_recorder: page failed to load: {error}"
                        )
                    has_record_frame = bool(page.evaluate("typeof window.__recordFrame === 'function'"))
                    has_hf = bool(page.evaluate("!!window.__hf && typeof window.__hf.seekFrame === 'function'"))
                    has_video = bool(page.evaluate("document.querySelectorAll('video').length > 0"))
                    if has_video:
                        page.wait_for_function(
                            "window.__vclockVideoReady === true", timeout=30000
                        )
                    run_dir = out_dir / f"run_{run_index}"
                    run_dir.mkdir(parents=True, exist_ok=True)
                    frames: list[dict[str, Any]] = []
                    for frame in range(total):
                        t_ms = round((frame / fps) * 1000.0)
                        page.evaluate(
                            "(args) => window.__vcFrame(args[0], args[1])", [t_ms, frame]
                        )
                        if has_hf:
                            page.wait_for_function(
                                f"window.__hfSettledFrame === {frame}", timeout=5000
                            )
                        if has_video:
                            page.wait_for_function(
                                f"Math.abs(document.querySelector('video').currentTime - {frame / fps}) < 0.06",
                                timeout=5000,
                            )
                        shot = page.screenshot()
                        if not shot.startswith(b"\x89PNG"):
                            raise CapabilityError(
                                "video.virtual_clock_recorder: capture did not return a PNG frame"
                            )
                        path = run_dir / f"frame_{frame:04d}.png"
                        path.write_bytes(shot)
                        frames.append({
                            "frame": frame,
                            "t_s": frame / fps,
                            "sha256": hashlib.sha256(shot).hexdigest(),
                            "bytes": len(shot),
                            "settled": has_hf,
                            "file": path.name,
                        })
                    all_runs.append({
                        "run": run_index,
                        "frames": frames,
                        "record_frame_present": has_record_frame,
                        "hf_present": has_hf,
                        "video_present": has_video,
                    })
                finally:
                    browser.close()
    finally:
        server.shutdown()
        server.server_close()
    hashes = [[f["sha256"] for f in r["frames"]] for r in all_runs]
    identical = all(h == hashes[0] for h in hashes) if hashes else True
    issues: list[dict[str, Any]] = []
    if not identical:
        issues.append({
            "code": "frame_hash_mismatch",
            "message": "two virtual-clock recordings of the same page differ; not deterministic on this machine",
        })
    encoded: dict[str, Any] = {}
    if encode and all_runs:
        encoded = _encode_mp4(
            out_dir / "run_0", fps=fps,
            out_path=out_dir / f"recording_{fps}fps.mp4",
        )
    return {
        "verdict": "fail" if issues else "pass",
        "issues": issues,
        "fps": fps,
        "duration_s": float(duration_s),
        "frame_count": total,
        "width": width,
        "height": height,
        "runs": all_runs,
        "hashes_identical": identical,
        "clock_replacement": {
            "performance_now": True, "date_now": True,
            "raf_virtual": True, "later_queue": True,
            "css_pinned": "web_animations_current_time_plus_transition_freeze",
        },
        "capture_method": (
            "whole-frame screenshot after __hf settle confirmation; "
            "not BeginFrame capture"
        ),
        "range_server": True,
        "three_module": str(three_path),
        "three_revision": three_revision(three_path),
        "encoded": encoded,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    width = int(params.get("width", 320))
    height = int(params.get("height", 180))
    fps = int(params.get("fps", 10))
    duration_s = float(params.get("duration_s", duration or 1.0))
    mode = str(params.get("mode", "test_page"))
    if mode == "html":
        html = params.get("html")
        if not isinstance(html, str) or not html.strip():
            raise CapabilityError(
                "video.virtual_clock_recorder: mode 'html' requires an 'html' string"
            )
    else:
        html = build_test_page(
            width=width, height=height, fps=fps, duration_s=duration_s,
            with_video=bool(params.get("with_video", False)),
        )
    report = record_virtual_clock(
        html=html, out_dir=out_dir, width=width, height=height,
        fps=fps, duration_s=duration_s,
        runs=int(params.get("runs", 2)),
        encode=bool(params.get("encode", True)),
    )
    report_path = out_dir / "virtual_clock_recorder_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    mp4 = report.get("encoded", {}).get("mp4")
    return CapabilityResult(
        mp4=mp4,
        duration_s=float(report.get("duration_s", 0.0)),
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "ok": report["verdict"] == "pass",
            "hashes_identical": report.get("hashes_identical")},
    )


def register_virtual_clock_recorder_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.virtual_clock_recorder",
            kind="video",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "html": {"type": "string"},
                    "with_video": {"type": "boolean"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "fps": {"type": "integer"},
                    "duration_s": {"type": "number"},
                    "runs": {"type": "integer"},
                    "encode": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=1.0,
            render=_render,
            has_media_output=True,
            description=(
                "Virtual-clock recorder (open-3d-skills frame-capture "
                "discipline, clean-room): replaces the page time "
                "sources with a virtual clock before page scripts run, "
                "pins CSS/Web Animations to virtual time, routes "
                "timers through a later() queue, seeks video per "
                "frame, calls __recordFrame, and captures whole "
                "frames only after __hf settle confirmation; two runs "
                "must hash identically. Range-serving harness, "
                "vendored Three.js only, no BeginFrame capture. See "
                "OPEN_3D_SKILLS_ATTRIBUTION.md."
            ),
            line="video",
        )
    )
    return ["video.virtual_clock_recorder"]


register_virtual_clock_recorder_capabilities_once()
