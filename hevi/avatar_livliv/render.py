"""Playwright-based offline renderer for LivLiv 2.5D characters."""
from __future__ import annotations

import base64
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

VENDOR = Path(os.environ.get("HEVI_LIVLIV_VENDOR", "").strip() or "/data/soffy/vendor/livliv-player")


def _tmp_root() -> Path:
    root = os.environ.get("HEVI_LIVLIV_TMP", "").strip()
    if root:
        p = Path(root)
    else:
        p = Path(tempfile.gettempdir()) / "livliv"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _launch_kwargs() -> dict[str, Any]:
    args = [
        "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
        "--no-sandbox", "--disable-dev-shm-usage",
    ]
    kwargs: dict[str, Any] = {"args": args}
    chrome = os.environ.get("HEVI_LIVLIV_CHROME", "").strip()
    if chrome and Path(chrome).is_file():
        kwargs["executable_path"] = chrome
    return kwargs

RENDER_HTML = """<!doctype html>
<html><body style="margin:0;background:transparent">
<canvas id="c" width="{w}" height="{h}" style="background:transparent"></canvas>
<script type="module">
import {{ Player }} from '/dist/index.js';
const canvas = document.getElementById('c');
const player = new Player(canvas, {{ idle: true, autoplay: false }});
window.__player = player;
window.__ready = false;
(async () => {{
  await player.load('/characters/{cid}.livliv');
  player.pause();
  // disable pointer follow to avoid nondeterminism
  player.followPointer = false;
  window.__ready = true;
}})();
window.renderFrame = (mo, v, dt) => {{
  const p = player;
  p.params.mouthOpen = mo;
  p.params.vowel = v;
  p.draw(dt || 1/30);
  return canvas.toDataURL('image/png');
}};
window.setExpression = (id) => {{ try {{ player.setExpression(id); }} catch(e){{}} }};
window.act = (a) => {{ try {{ player.act(a); }} catch(e){{}} }};
// Render several frames per CDP round-trip; expressions/actions are applied
// inside the loop so batching never changes the animation schedule.
window.renderBatch = (items) => {{
  const out = [];
  for (const it of items) {{
    if (it[3]) window.setExpression(it[3]);
    if (it[4]) window.act(it[4]);
    out.push(window.renderFrame(it[0], it[1], it[2]));
  }}
  return out;
}};
// Fast-forward a worker's page to its segment start without PNG encoding.
window.advanceFrame = (mo, v, dt, ex, ac) => {{
  if (ex) window.setExpression(ex);
  if (ac) window.act(ac);
  const p = player;
  p.params.mouthOpen = mo;
  p.params.vowel = v;
  p.draw(dt || 1/30);
}};
</script>
</body></html>
"""


def plan_performance(
    nframes: int,
    fps: int = 30,
    expressions_available: list[str] | None = None,
    sentences: list[dict] | None = None,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Deterministic expression/action schedule from actual player.expressions.

    Blink/breath/sway come from ``idle: true``; this schedules the
    deliberate expressions and gestures on top. Sentence ``func`` values
    (koubo_cut classification) map to expressions when available.
    """
    avail = set(expressions_available or [])
    expressions: list[tuple[int, str]] = []
    actions: list[tuple[int, str]] = []
    func_expr = {
        "data": ["surprised", "smile"],
        "example": ["smile"],
        "turn": ["surprised"],
        "cta": ["smile"],
        "viewpoint": ["smile"],
    }

    def _pick(cands: list[str]) -> str | None:
        for c in cands:
            if c in avail:
                return c
        return None

    def _frame(t: float) -> int:
        return max(0, min(nframes - 1, int(round(t * fps))))

    if sentences:
        for s in sentences:
            fr = _frame(float(s.get("start", 0.0)))
            expr = _pick(func_expr.get(str(s.get("func", "")), ["smile"]))
            if expr:
                expressions.append((fr, expr))
            actions.append((fr, "nod"))
            if s.get("func") == "turn":
                actions.append((fr, "shake"))
    else:
        # Default: smile at start, then nod every ~4s with occasional tilt.
        expr = _pick(["smile"])
        if expr:
            expressions.append((0, expr))
        t = 2.0
        i = 0
        while t * fps < nframes:
            actions.append((_frame(t), "nod" if i % 2 == 0 else "tilt"))
            t += 4.0
            i += 1
    # dedupe, keep order
    expressions = sorted(set(expressions))
    # one action per frame (first wins) to avoid overlapping drivers
    seen: dict[int, str] = {}
    for fr, a in actions:
        seen.setdefault(fr, a)
    actions = sorted(seen.items())
    return expressions, actions


def _serve_root(tmp: Path, w: int, h: int, cid: str) -> Path:
    root = tmp / "srv"
    root.mkdir(parents=True, exist_ok=True)
    (root / "dist").symlink_to(VENDOR / "dist", target_is_directory=True)
    (root / "characters").symlink_to(VENDOR / "characters", target_is_directory=True)
    html = RENDER_HTML.format(w=w, h=h, cid=cid)
    (root / "index.html").write_text(html, encoding="utf-8")
    return root


def _wait_ready(page: Any, *, attempts: int = 100) -> None:
    for _ in range(attempts):
        if page.evaluate("window.__ready") is True:
            return
        time.sleep(0.1)
    raise RuntimeError("LivLiv player did not load")


def _render_segment(
    *,
    port: int,
    width: int,
    height: int,
    mouth_frames: list[dict[str, float]],
    fps: int,
    start: int,
    end: int,
    out_dir: Path,
    expr_map: dict[int, str],
    act_map: dict[int, str],
    batch_size: int,
) -> None:
    """Fast-forward to ``start`` on a private page, then capture [start, end)."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_launch_kwargs())
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(f"http://127.0.0.1:{port}/index.html")
            _wait_ready(page)
            dt = 1.0 / fps
            # Idle breathing/blink depends on accumulated draw time, so a worker
            # must replay (render, without encoding) every frame before its
            # segment.  Splitting frames without this would make the idle phase
            # jump at every splice.
            for i in range(0, start):
                fr = mouth_frames[i]
                page.evaluate(
                    "([mo,v,dt,ex,ac]) => window.advanceFrame(mo,v,dt,ex,ac)",
                    [float(fr.get("mouthOpen", 0.0)), float(fr.get("vowel", 0.0)),
                     dt, expr_map.get(i), act_map.get(i)],
                )
            for base in range(start, end, batch_size):
                items = []
                for i in range(base, min(end, base + batch_size)):
                    fr = mouth_frames[i]
                    items.append(
                        [float(fr.get("mouthOpen", 0.0)), float(fr.get("vowel", 0.0)),
                         dt, expr_map.get(i), act_map.get(i)]
                    )
                urls = page.evaluate("window.renderBatch", items)
                for offset, data_url in enumerate(urls):
                    b64 = data_url.split(",", 1)[1]
                    (out_dir / f"frame_{base + offset:05d}.png").write_bytes(
                        base64.b64decode(b64)
                    )
        finally:
            browser.close()


def render_frames(
    character_id: str,
    out_dir: Path,
    mouth_frames: list[dict[str, float]],
    fps: int = 30,
    width: int = 512,
    height: int = 512,
    expressions: list[tuple[int, str]] | None = None,
    actions: list[tuple[int, str]] | None = None,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("frame_*.png"):
        try:
            stale.unlink()
        except OSError:
            pass
    if not mouth_frames:
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="livliv_", dir=str(_tmp_root())))
    root = _serve_root(tmp, width, height, character_id)
    import subprocess as sp
    port = _free_port()
    srv = sp.Popen(["python3", "-m", "http.server", str(port)], cwd=str(root),
                   stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    time.sleep(0.5)
    try:
        if expressions is None or actions is None:
            # Probe the schedule once; the actual pages are opened per worker.
            with sync_playwright() as pw:
                browser = pw.chromium.launch(**_launch_kwargs())
                try:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(f"http://127.0.0.1:{port}/index.html")
                    _wait_ready(page)
                    try:
                        avail = page.evaluate(
                            "() => (window.__player.expressions || []).map(e => e.id)"
                        )
                    except Exception:
                        avail = []
                finally:
                    browser.close()
            d_expr, d_act = plan_performance(
                len(mouth_frames), fps=fps, expressions_available=avail, sentences=None
            )
            if expressions is None:
                expressions = d_expr
            if actions is None:
                actions = d_act
        expr_map = {f: e for f, e in (expressions or [])}
        act_map: dict[int, str] = {}
        for f, a in (actions or []):
            act_map.setdefault(f, a)

        n = len(mouth_frames)
        try:
            workers = int(os.environ.get("HEVI_LIVLIV_WORKERS", "0") or 0)
        except ValueError:
            workers = 0
        if workers <= 0:
            # The API container is CPU-capped (2 cpus); three workers each replay
            # the idle animation from frame 0, so on a small quota they add work
            # instead of removing it (S9: 452 s).  Default to one page; opt into
            # parallelism with HEVI_LIVLIV_WORKERS on a larger quota.
            workers = 1
        workers = max(1, min(workers, n))
        chunk = (n + workers - 1) // workers
        segments = [(i * chunk, min(n, (i + 1) * chunk)) for i in range(workers)]
        segments = [seg for seg in segments if seg[0] < seg[1]]
        try:
            batch_size = max(1, int(os.environ.get("HEVI_LIVLIV_BATCH", "12")))
        except ValueError:
            batch_size = 12
        if len(segments) == 1:
            _render_segment(
                port=port, width=width, height=height, mouth_frames=mouth_frames,
                fps=fps, start=segments[0][0], end=segments[0][1], out_dir=out_dir,
                expr_map=expr_map, act_map=act_map, batch_size=batch_size,
            )
        else:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=len(segments)) as pool:
                futures = [
                    pool.submit(
                        _render_segment,
                        port=port, width=width, height=height,
                        mouth_frames=mouth_frames, fps=fps, start=a, end=b,
                        out_dir=out_dir, expr_map=expr_map, act_map=act_map,
                        batch_size=batch_size,
                    )
                    for a, b in segments
                ]
                for future in futures:
                    future.result()
    finally:
        srv.terminate()
        srv.wait()
        shutil.rmtree(tmp, ignore_errors=True)
    return len(mouth_frames)


def frames_to_video(frames_dir: Path, out_path: Path, fps: int = 30, audio: Path | None = None, alpha: bool = True) -> Path:
    frames_dir = Path(frames_dir)
    pattern = str(frames_dir / "frame_%05d.png")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if alpha:
        # webm vp9 with alpha
        if out_path.suffix.lower() == ".webm":
            cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", pattern,
                   "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "2M",
                   str(out_path)]
        elif out_path.suffix.lower() == ".mov":
            cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", pattern,
                   "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
                   str(out_path)]
        else:
            cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", pattern,
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)]
    else:
        cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", pattern,
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)]
    subprocess.run(cmd, capture_output=True, check=False)
    if audio is not None and out_path.exists() and out_path.suffix.lower() in (".mp4", ".mov", ".webm"):
        # mux audio into a separate mp4 if needed
        pass
    # mux audio into mp4 sidecar always
    if audio is not None:
        muxed = out_path.with_name(out_path.stem + "_audio" + out_path.suffix)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out_path), "-i", str(audio),
             "-c:v", "copy", "-c:a", "aac", "-shortest",
             "-metadata", "title=LivLiv avatar",
             "-metadata", "comment=Characters: LivLiv (livliv.ai), AI制作",
             str(muxed)],
            capture_output=True, check=False,
        )
        if muxed.exists():
            muxed.replace(out_path)
    return out_path


def render_clip(
    character_id: str,
    audio_path: Path | None,
    out_dir: Path,
    fps: int = 30,
    width: int = 720,
    height: int = 1080,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Render audio-driven clip; returns frames count + output paths.

    Lower ``width``/``height``/``fps`` if a 30s render exceeds ~5 min.
    """
    import resource as _resource
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    if audio_path is not None:
        from .audio import analyze
        env = analyze(Path(audio_path), fps=fps)
    else:
        if duration_s is None:
            duration_s = 5.0
        n = int(duration_s * fps)
        env = [{"t": i / fps, "mouthOpen": 0.0, "vowel": 0.0} for i in range(n)]
    # trim/pad to duration
    if duration_s is not None:
        n = int(duration_s * fps)
        if len(env) > n:
            env = env[:n]
        while len(env) < n:
            env.append({"t": len(env) / fps, "mouthOpen": 0.0, "vowel": 0.0})
    render_frames(character_id, frames_dir, env, fps=fps, width=width, height=height)
    results = {}
    for ext in ("mov", "webm", "mp4"):
        p = out_dir / f"clip.{ext}"
        frames_to_video(frames_dir, p, fps=fps, audio=audio_path if ext == "mp4" else None, alpha=(ext != "mp4"))
        if p.exists():
            results[ext] = str(p)
    # also mp4 with audio (already)
    elapsed = time.time() - t0
    peak_rss_mb = _resource.getrusage(_resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0
    # compliance sidecar: character credit travels with every render
    (out_dir / "CHARACTERS_CREDIT.txt").write_text(
        "Characters: LivLiv (livliv.ai), AI制作\n"
        f"character_id: {character_id}\n",
        encoding="utf-8",
    )
    return {"frames": len(env), "outputs": results, "frames_dir": str(frames_dir),
            "elapsed_s": round(elapsed, 1), "peak_rss_mb": round(peak_rss_mb, 1)}
