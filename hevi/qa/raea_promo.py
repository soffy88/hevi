"""Internal raea template for the kinetic_promo A/B (never user-authored).

The template is generated here, from an order's own topic and script lines.
Users never submit TSX/HTML: ``HEVI_KINETIC_ENGINE=raea`` is a server-side
switch, and the raea CLI is read from ``HEVI_RAEA_BIN`` (or
``/opt/raea/bin/raea``); a missing binary is a blocked render, not a fallback.

Output contract matches the other zero-cost lines: 720x1280, 30 s, h264 with
an optional locally voiced/BGM track.  Subtitles are rendered as motion
graphics inside the raea composition (Chinese, animated per line).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hevi.qa.raea_check import raea_binary

WIDTH = 720
HEIGHT = 1280
FPS = 30
FRAMES = 900
_RENDER_TIMEOUT_S = 300.0

_TSX_TEMPLATE = r"""import {{ AbsoluteFill, Composition, interpolate, registerRoot, useCurrentFrame }} from "raea";

const TITLE = {title};
const LINES = {lines};
const ACCENT = {accent};
const SECONDARY = {secondary};
const SEGMENT = {segment};

function clamp(x: number, lo: number, hi: number) {{
  return Math.max(lo, Math.min(hi, x));
}}

function Kinetic() {{
  const f = useCurrentFrame();
  const t = f / {fps};
  const total = {frames} / {fps};
  const index = Math.min(LINES.length - 1, Math.floor(t / SEGMENT));
  const local = t - index * SEGMENT;
  const enter = clamp(local / 0.45, 0, 1);
  const exit = clamp((SEGMENT - local) / 0.45, 0, 1);
  const visible = Math.min(enter, exit);
  const slide = (1 - visible) * 46;
  const scale = 0.94 + 0.06 * visible;
  const hue = (t * 12) % 360;
  const sweep = (t / total) * 100;
  const pulse = 1 + 0.012 * Math.sin(t * 4.2);
  return (
    <AbsoluteFill style={{{{ background: `linear-gradient(155deg, hsl(${{hue}} 68% 17%), hsl(${{(hue + 58) % 360}} 72% 7%))` }}}}>
      <AbsoluteFill style={{{{ opacity: 0.22, background: `radial-gradient(circle at ${{20 + ((t * 9) % 60)}}% 30%, ${{ACCENT}} 0%, transparent 46%)` }}}} />
      <div style={{{{ position: "absolute", top: 132, left: 56, right: 56, color: "#fff", fontSize: 30, letterSpacing: 8, opacity: 0.78 }}}}>
        {{TITLE}}
      </div>
      <AbsoluteFill style={{{{ justifyContent: "center", alignItems: "center", padding: "0 64px" }}}}>
        <div style={{{{ color: "#fff", fontSize: 72, fontWeight: 800, lineHeight: 1.18, textAlign: "center",
          transform: `translateY(${{slide}}px) scale(${{scale * pulse}})`, opacity: visible,
          textShadow: `0 8px 34px rgba(0,0,0,0.55)` }}}}>
          {{LINES[index]}}
        </div>
      </AbsoluteFill>
      <div style={{{{ position: "absolute", left: 56, right: 56, bottom: 360 }}}}>
        <div style={{{{ color: SECONDARY, fontSize: 26, letterSpacing: 6, marginBottom: 14, opacity: 0.9 }}}}>MOTION TYPE</div>
        <div style={{{{ height: 6, borderRadius: 3, background: "rgba(255,255,255,0.16)" }}}}>
          <div style={{{{ height: 6, borderRadius: 3, width: `${{sweep}}%`, background: ACCENT }}}} />
        </div>
        <div style={{{{ marginTop: 22, display: "flex", justifyContent: "space-between", color: "#fff", fontSize: 28, opacity: 0.82 }}}}>
          <span>KINETIC PROMO</span>
          <span>{{`${{String(Math.floor(t)).padStart(2, "0")}} / 30`}}</span>
        </div>
      </div>
    </AbsoluteFill>
  );
}}

registerRoot(() => <Composition id="kinetic-promo" component={{Kinetic}} width={{{width}}} height={{{height}}} fps={{{fps}}} durationInFrames={{{frames}}} />);
"""


def _tsx_source(*, title: str, lines: list[str], accent: str, secondary: str) -> str:
    return _TSX_TEMPLATE.format(
        title=json.dumps(title, ensure_ascii=False),
        lines=json.dumps(lines, ensure_ascii=False),
        accent=json.dumps(accent),
        secondary=json.dumps(secondary),
        segment=round(30.0 / max(1, len(lines)), 4),
        width=WIDTH,
        height=HEIGHT,
        fps=FPS,
        frames=FRAMES,
    )


def _render_video(*, source: Path, output: Path) -> dict[str, Any]:
    binary = raea_binary()
    if binary is None:
        raise RuntimeError("raea binary not found (HEVI_RAEA_BIN / /opt/raea/bin/raea)")
    env = dict(os.environ)
    env.setdefault("RAEA_OFFLINE", "1")
    env.setdefault("WGPU_BACKEND", "vulkan")
    icd = Path("/usr/share/vulkan/icd.d/lvp_icd.json")
    if icd.is_file():
        env.setdefault("VK_ICD_FILENAMES", str(icd))
    cmd = [
        binary,
        "render",
        str(source),
        "-o",
        str(output),
        "--w",
        str(WIDTH),
        "--h",
        str(HEIGHT),
        "--fps",
        str(FPS),
        "--frames",
        str(FRAMES),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_RENDER_TIMEOUT_S, check=False, env=env
    )
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-1200:]
        raise RuntimeError(f"raea render failed rc={proc.returncode}: {tail}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "binary": binary,
        "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        "template_sha256": digest,
        "render_log_tail": ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-1500:],
    }


def _mux_audio(video: Path, lines: list[str], work: Path, final: Path) -> dict[str, Any]:
    """Piper voice + procedural BGM over the raea picture; -14 LUFS master."""
    try:
        from hevi.layer4_legacy.zerolines.omodul_impl._media import (
            dur,
            finish,
            mix,
            tts_lines,
            write_bgm,
        )

        vo, cues = tts_lines(list(lines), work / "vo", lang="zh", speed=1.05)
        total = max(30.0, float(dur(vo)) + 1.5)
        bgm = write_bgm(work / "bgm.wav", total + 1, "bright")
        mixed = mix(vo, bgm, work / "mix.wav", total, -14)
        finish(video, mixed, final)
        return {"audio": "piper+bgm", "vo_duration_s": round(float(dur(vo)), 3), "cue_count": len(cues)}
    except Exception as exc:  # audio is an enhancement; picture still ships
        shutil.copyfile(video, final)
        return {"audio": "none", "audio_error": f"{type(exc).__name__}: {exc}"}


async def render_raea_promo(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Render the internal raea kinetic promo template for one order."""
    from hevi.layer4_legacy.zerolines.oprim_impl.specs import generate_script_lines

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    topic = str(order.get("topic") or "").strip()
    texts = [str(item).strip() for item in (order.get("script_lines") or []) if str(item).strip()]
    if not texts:
        texts = list(generate_script_lines(topic, line_id="kinetic_promo", n=7))
    if not texts:
        return {
            "status": "blocked",
            "target": "kinetic_promo",
            "line_id": "kinetic_promo",
            "reason": "kinetic_promo raea 渲染需要 topic 或 script_lines",
        }
    title = str(order.get("title") or topic or "HEVI").strip()[:24]
    accent = str((order.get("extras") or {}).get("accent") or "#ff5a3c")
    secondary = str((order.get("extras") or {}).get("secondary") or "#ffd9a8")

    raw_video = output_dir / ".raea_kinetic_raw.mp4"
    final = output_dir / "kinetic_promo.mp4"
    with tempfile.TemporaryDirectory(prefix="raea-promo-", dir=output_dir) as tmp:
        work = Path(tmp)
        source = work / "edit.tsx"
        source.write_text(
            _tsx_source(title=title, lines=texts[:7], accent=accent, secondary=secondary),
            encoding="utf-8",
        )
        try:
            render = await asyncio.to_thread(_render_video, source=source, output=raw_video)
        except Exception as exc:
            return {
                "status": "blocked",
                "target": "kinetic_promo",
                "line_id": "kinetic_promo",
                "reason": str(exc),
                "render_runtime": "raea",
            }
        audio = await asyncio.to_thread(_mux_audio, raw_video, texts[:7], work, final)
        # keep the generated (internal) template beside the film for provenance
        (output_dir / "raea_kinetic.tsx").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    raw_video.unlink(missing_ok=True)

    from hevi.studio.fulfill import _verified_video_manifest

    manifest, quality = await _verified_video_manifest(
        [(final, True, "kinetic_promo")], require_audio=False
    )
    return {
        "status": "completed",
        "target": "kinetic_promo",
        "line_id": "kinetic_promo",
        "result_video_path": str(manifest.primary_path() or final),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": "raea",
        "raea": {**render, "audio": audio.get("audio"), "cue_count": audio.get("cue_count")},
        "provider_trace": [{"resolved_provider": "raea", "fallback_used": False}],
    }


__all__ = ["render_raea_promo"]
