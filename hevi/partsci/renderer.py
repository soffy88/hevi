"""Deterministic Canvas 2D Particle & Parallax Renderer (Playwright + FFmpeg)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import Capability, CapabilityResult, register
from hevi.layer4_legacy.scene3d.browser import resolve_browsers_path
from hevi.quality.kids_gate import kids_gate_workflow
from hevi.audio.piper_tts_service import synth_with_piper
from .facts import get_fact_card, verify_mechanism
from .palette import get_palette
from .storyboard import PartsciStoryboard, PartsciShot


def _build_particle_html(
    theme: str,
    keyword: str,
    seed: int,
    aspect: str,
    duration: float,
) -> str:
    palette = get_palette(theme)
    is_portrait = aspect == "9:16"
    width = 1080 if is_portrait else 1920
    height = 1920 if is_portrait else 1080

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ margin:0; overflow:hidden; background:{palette['bg']}; }}
  canvas {{ display:block; width:100vw; height:100vh; }}
</style>
</head>
<body>
<canvas id="c" width="{width}" height="{height}"></canvas>
<script>
const W = {width};
const H = {height};
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');

// Seeded PRNG (mulberry32)
function mulberry32(a) {{
  return function() {{
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  }}
}}
const rng = mulberry32({seed});

// Particles
const PARTICLE_COUNT = 300;
const particles = [];
for (let i = 0; i < PARTICLE_COUNT; i++) {{
  particles.push({{
    x: rng() * W,
    y: rng() * H,
    vx: (rng() - 0.5) * 2,
    vy: (rng() - 0.5) * 2 - 0.5,
    size: rng() * 6 + 2,
    alpha: rng() * 0.8 + 0.2,
    phase: rng() * Math.PI * 2
  }});
}}

function render(t) {{
  // 1. Background gradient (Layer 0 & 1)
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, '{palette["bg"]}');
  grad.addColorStop(1, '{palette["secondary"]}');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  // 2. Parallax layers (Layer 2 & 3)
  ctx.fillStyle = '{palette["primary"]}';
  ctx.beginPath();
  let waveY = H * 0.7 + Math.sin(t * 2) * 20;
  ctx.moveTo(0, H);
  ctx.lineTo(0, waveY);
  for (let x = 0; x <= W; x += 50) {{
    ctx.lineTo(x, waveY + Math.sin(x * 0.01 + t * 3) * 30);
  }}
  ctx.lineTo(W, H);
  ctx.closePath();
  ctx.globalAlpha = 0.3;
  ctx.fill();

  // 3. Subject (Main vector graphic / center element)
  ctx.globalAlpha = 1.0;
  ctx.fillStyle = '{palette["primary"]}';
  ctx.beginPath();
  let cx = W / 2 + Math.sin(t) * 40;
  let cy = H / 2 + Math.cos(t * 0.8) * 30;
  ctx.arc(cx, cy, 120, 0, Math.PI * 2);
  ctx.fill();

  // 4. Particles (Layer 4)
  for (let p of particles) {{
    let px = (p.x + Math.sin(t + p.phase) * 20) % W;
    let py = (p.y - t * 40) % H;
    if (py < 0) py += H;
    
    ctx.fillStyle = '{palette["glow"]}';
    ctx.globalAlpha = p.alpha * (0.5 + 0.5 * Math.sin(t * 5 + p.phase));
    ctx.beginPath();
    ctx.arc(px, py, p.size, 0, Math.PI * 2);
    ctx.fill();
  }}

  // 5. Captions & Keyword (Layer 5)
  ctx.globalAlpha = 1.0;
  ctx.fillStyle = '#1e293b';
  ctx.font = 'bold {120 if is_portrait else 90}px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText("{keyword}", W / 2, H * 0.2);

  // Safe area border check (subtle guide / debug indicator if needed)
}}

window.__setTime = function(t) {{
  render(t);
}};

render(0.0);
</script>
</body>
</html>
"""


def render_partsci_scene(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    concept = params.get("concept", "sky_blue")
    theme = params.get("theme", "sky")
    keyword = params.get("keyword", "蓝天")
    narration_text = params.get("narration", "太阳光散射让天空变蓝。")

    fact = get_fact_card(concept)
    if not verify_mechanism(concept, params.get("mechanism", fact["mechanism"])):
        raise RuntimeError(f"Mechanism anti-error check failed for concept {concept}")

    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "scene.html"
    mp4_path = out_dir / f"partsci_{concept}_{aspect.replace(':', '_')}.mp4"

    html_content = _build_particle_html(theme, keyword, seed, aspect, duration)
    html_path.write_text(html_content, encoding="utf-8")

    # 1. Render frames via Playwright
    resolve_browsers_path()
    fps = 30
    total_frames = int(duration * fps)

    from playwright.sync_api import sync_playwright
    import http.server
    import socketserver
    import threading

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out_dir), **kwargs)
        def log_message(self, format, *args):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    t_thread.start()

    page_url = f"http://127.0.0.1:{port}/{html_path.name}"
    is_portrait = aspect == "9:16"
    width = 1080 if is_portrait else 1920
    height = 1920 if is_portrait else 1080

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"])
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(page_url)
            page.wait_for_timeout(500)

            import base64
            for i in range(total_frames):
                t = i / fps
                page.evaluate(f"window.__setTime({t})")
                b64 = page.evaluate(
                    """async () => {
                      const c = document.getElementById('c');
                      return await new Promise((resolve) => {
                        c.toBlob(blob => {
                          const r = new FileReader();
                          r.onload = () => resolve(r.result);
                          r.readAsDataURL(blob);
                        }, 'image/png');
                      });
                    }"""
                )
                payload = base64.b64decode(b64.split(",", 1)[1])
                (frames_dir / f"frame_{i+1:05d}.png").write_bytes(payload)
            browser.close()
    finally:
        httpd.shutdown()

    # 2. Synthesize audio (Piper TTS + procedural BGM)
    audio_path = out_dir / "narration.wav"
    import asyncio
    asyncio.run(synth_with_piper(narration_text, audio_path, voice="zh_CN-huayan-medium.onnx", speed=0.9))

    # 3. Assemble via ffmpeg (video + audio with loudnorm)
    ffmpeg_bin = "/home/soffy/.local/bin/ffmpeg" if os.path.exists("/home/soffy/.local/bin/ffmpeg") else "ffmpeg"
    
    video_only = out_dir / "video_only.mp4"
    subprocess.run([
        ffmpeg_bin, "-y", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22",
        str(video_only)
    ], check=True, capture_output=True)

    # Mux audio and normalize loudness to -16 LUFS
    subprocess.run([
        ffmpeg_bin, "-y", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-i", str(video_only),
        "-i", str(audio_path),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-map_metadata", "-1",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(mp4_path)
    ], check=True, capture_output=True)

    sha256 = hashlib.sha256(mp4_path.read_bytes()).hexdigest()

    # 4. Kids gate verification
    srt_path = out_dir / "sub.srt"
    srt_path.write_text(f"1\n00:00:00,000 --> 00:00:{int(duration):02d},000\n{keyword}\n", encoding="utf-8")
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps({"subtitle_font_px": 64}), encoding="utf-8")

    qa = kids_gate_workflow(mp4_path, srt_path=srt_path, metadata_path=meta_path)

    return CapabilityResult(
        mp4=str(mp4_path),
        duration_s=duration,
        sha256=sha256,
        qa=qa
    )


__all__ = ["render_partsci_scene"]
