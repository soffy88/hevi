"""SVG skeletal character animation driven by CMU motion capture.

Clean-room replacement for the removed OpenMontage ink-puppet path.  A flat
skeletal puppet is drawn in SVG; every joint is posed each frame from a CMU
mocap clip (``hevi.studio.cmumocap``); a seek-driven renderer plays the
choreography so HyperFrames can capture it deterministically.

The renderer is driven by HyperFrames' ``hf-seek`` event rather than a GSAP
timeline: the page builds the puppet, then poses it from the mocap data at the
exact requested time, which keeps every captured frame reproducible.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.studio import cmumocap

logger = logging.getLogger(__name__)

PIPER = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
PIPER_VOICE = "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx"
FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"

#: the bones drawn between kept joints
BONES: tuple[tuple[str, str], ...] = (
    ("hips", "chest"),
    ("chest", "neck"),
    ("neck", "head"),
    ("chest", "shR"),
    ("shR", "elR"),
    ("elR", "haR"),
    ("chest", "shL"),
    ("shL", "elL"),
    ("elL", "haL"),
    ("hips", "hipR"),
    ("hipR", "knR"),
    ("knR", "ftR"),
    ("hips", "hipL"),
    ("hipL", "knL"),
    ("knL", "ftL"),
)


@dataclass
class Segment:
    """One performance beat: a mocap clip held on screen for ``duration`` seconds."""

    clip: str
    duration: float
    caption: str = ""
    loop: bool = True
    drift: float = 0.0


@dataclass
class CharacterFilm:
    segments: list[Segment]
    narration_lines: list[str] = field(default_factory=list)
    title: str = ""


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def synth_line(text: str, out_wav: Path, *, speed: float = 1.0) -> float:
    """Synthesise one Chinese narration line with the local piper voice."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    raw = out_wav.with_suffix(".raw.wav")
    proc = subprocess.run(
        [PIPER, "-m", PIPER_VOICE, "-f", str(raw), "--length_scale", str(1 / speed), "--sentence_silence", "0.25"],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr[-400:]}")
    proc = _run([FFMPEG, "-y", "-loglevel", "error", "-i", str(raw), "-af", "highpass=f=70,loudnorm=I=-16:TP=-1.5", "-ar", "44100", "-ac", "1", str(out_wav)])
    raw.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg loudnorm failed: {proc.stderr[-400:]}")
    return float(_run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_wav)]).stdout.strip())


def build_narration(lines: list[str], audio_dir: Path, *, gap: float = 0.35) -> tuple[Path, list[tuple[float, float]]]:
    """Voice each line, concatenate with gaps; return the wav and per-line (start, end)."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    cues: list[tuple[float, float]] = []
    t = 0.0
    for i, line in enumerate(lines):
        wav = audio_dir / f"vo_{i:02d}.wav"
        dur = synth_line(line, wav)
        cues.append((t, t + dur))
        parts.append(wav)
        t += dur + gap
    # concat via the concat demuxer
    listfile = audio_dir / "vo.txt"
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    out = audio_dir / "narration.wav"
    proc = _run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(out)])
    if proc.returncode != 0:
        raise RuntimeError(f"narration concat failed: {proc.stderr[-400:]}")
    return out, cues


def _mocap_js(clip_names: list[str]) -> str:
    data = {}
    for name in dict.fromkeys(clip_names):
        clip = cmumocap.load_clip(name)
        data[name] = {"fps": clip["fps"], "frameCount": clip["frameCount"], "frames": clip["frames"]}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


_HTML = """<!doctype html>
<html lang="zh-CN" data-resolution="landscape">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <title>__TITLE__</title>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1920px; height: 1080px; overflow: hidden; background: #f4efe6; }
      #root { position: relative; width: 1920px; height: 1080px; overflow: hidden;
              background: radial-gradient(120% 90% at 50% 12%, #fbf8f2 0%, #efe7d8 62%, #e4d9c5 100%); }
      svg { position: absolute; inset: 0; width: 1920px; height: 1080px; }
      .bone { stroke: #2f2a24; stroke-width: 15; stroke-linecap: round; fill: none; }
      .torso { fill: #d9773f; stroke: #2f2a24; stroke-width: 8; }
      .head { fill: #f7e2c8; stroke: #2f2a24; stroke-width: 8; }
      .joint { fill: #2f2a24; }
      .limb { stroke: #3d4a6b; }
      .arm { stroke: #d9773f; }
      .shadow { fill: rgba(60,50,35,0.16); }
      #caption { position: absolute; left: 0; width: 1920px; top: 120px; text-align: center;
                 font-family: "Noto Sans CJK SC", "PingFang SC", sans-serif; font-size: 74px;
                 font-weight: 700; color: #2f2a24; letter-spacing: 2px; }
      #title { position: absolute; left: 0; width: 1920px; top: 60px; text-align: center;
               font-family: "Noto Sans CJK SC", sans-serif; font-size: 34px; font-weight: 500;
               color: #8a7c66; letter-spacing: 8px; }
      #credit { position: absolute; left: 0; width: 1920px; bottom: 54px; text-align: center;
                font-family: "Noto Sans CJK SC", sans-serif; font-size: 26px; color: #9a8b73; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-no-timeline data-start="0" data-duration="__DUR__" data-width="1920" data-height="1080">
      <div id="stage" class="clip" data-start="0" data-duration="__DUR__" data-track-index="1">
        <svg viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg">
          <ellipse id="shadow" class="shadow" cx="960" cy="940" rx="150" ry="22"></ellipse>
          <path id="ground" d="M 220 940 H 1700" stroke="#cbbfa8" stroke-width="4" stroke-dasharray="26 20" fill="none"></path>
          <g id="figure" opacity="0">
            <line id="b_hips_chest" class="bone" data-a="hips" data-b="chest"></line>
            <line id="b_chest_neck" class="bone" data-a="chest" data-b="neck"></line>
            <line id="b_neck_head" class="bone" data-a="neck" data-b="head"></line>
            <line id="b_chest_shR" class="bone arm" data-a="chest" data-b="shR"></line>
            <line id="b_shR_elR" class="bone arm" data-a="shR" data-b="elR"></line>
            <line id="b_elR_haR" class="bone arm" data-a="elR" data-b="haR"></line>
            <line id="b_chest_shL" class="bone arm" data-a="chest" data-b="shL"></line>
            <line id="b_shL_elL" class="bone arm" data-a="shL" data-b="elL"></line>
            <line id="b_elL_haL" class="bone arm" data-a="elL" data-b="haL"></line>
            <line id="b_hips_hipR" class="bone limb" data-a="hips" data-b="hipR"></line>
            <line id="b_hipR_knR" class="bone limb" data-a="hipR" data-b="knR"></line>
            <line id="b_knR_ftR" class="bone limb" data-a="knR" data-b="ftR"></line>
            <line id="b_hips_hipL" class="bone limb" data-a="hips" data-b="hipL"></line>
            <line id="b_hipL_knL" class="bone limb" data-a="hipL" data-b="knL"></line>
            <line id="b_knL_ftL" class="bone limb" data-a="knL" data-b="ftL"></line>
            <circle id="head" class="head" r="62"></circle>
            <circle id="joint_hips" class="joint" r="9"></circle>
            <circle id="joint_chest" class="joint" r="9"></circle>
          </g>
        </svg>
        <div id="title">__TITLE__</div>
        <div id="caption"></div>
        <div id="credit">CMU Motion Capture Database · SVG skeleton · 本地合成</div>
      </div>
      <audio id="narration" src="assets/audio/narration.wav" data-start="0" data-duration="__NARR__" data-track-index="10"></audio>
    </div>
    <script>
      window.MOCAP = __MOCAP__;
      window.SEGMENTS = __SEGMENTS__;
      (function () {
        var CX = 960, GROUND = 940, SCALE = 690;
        var figure = document.getElementById("figure");
        var bones = Array.prototype.slice.call(document.querySelectorAll("line[data-a]"));
        var head = document.getElementById("head");
        var jHips = document.getElementById("joint_hips");
        var jChest = document.getElementById("joint_chest");
        var caption = document.getElementById("caption");
        var shadow = document.getElementById("shadow");
        var ground = document.getElementById("ground");

        function toPx(j) { return [CX + j[0] * SCALE, GROUND - j[1] * SCALE]; }

        function poseAt(t) {
          var segs = window.SEGMENTS, acc = 0;
          for (var i = 0; i < segs.length; i++) {
            var s = segs[i];
            if (t < acc + s.duration || i === segs.length - 1) {
              var local = Math.max(0, t - acc);
              var clip = window.MOCAP[s.clip];
              var f = Math.floor(local * clip.fps);
              if (s.loop) { f = ((f % clip.frameCount) + clip.frameCount) % clip.frameCount; }
              f = Math.max(0, Math.min(clip.frameCount - 1, f));
              return { frame: clip.frames[f], seg: s, index: i, local: local };
            }
            acc += s.duration;
          }
          var last = segs[segs.length - 1];
          return { frame: window.MOCAP[last.clip].frames[0], seg: last, index: segs.length - 1, local: 0 };
        }

        var lastCaption = null;
        function renderAt(t) {
          var p = poseAt(t), frame = p.frame;
          var drift = 0, acc = 0;
          for (var i = 0; i < p.index; i++) { acc += window.SEGMENTS[i].duration; drift += window.SEGMENTS[i].drift * window.SEGMENTS[i].duration; }
          drift += p.seg.drift * Math.max(0, t - acc);
          bones.forEach(function (b) {
            var a = toPx(frame[b.dataset.a]), c = toPx(frame[b.dataset.b]);
            b.setAttribute("x1", (a[0] + drift).toFixed(2)); b.setAttribute("y1", a[1].toFixed(2));
            b.setAttribute("x2", (c[0] + drift).toFixed(2)); b.setAttribute("y2", c[1].toFixed(2));
          });
          var hp = toPx(frame.head);
          head.setAttribute("cx", (hp[0] + drift).toFixed(2));
          head.setAttribute("cy", (hp[1] - 34).toFixed(2));
          var jh = toPx(frame.hips), jc = toPx(frame.chest);
          jHips.setAttribute("cx", (jh[0] + drift).toFixed(2)); jHips.setAttribute("cy", jh[1].toFixed(2));
          jChest.setAttribute("cx", (jc[0] + drift).toFixed(2)); jChest.setAttribute("cy", jc[1].toFixed(2));
          shadow.setAttribute("cx", (jh[0] + drift).toFixed(2));
          var feet = [frame.ftR[1], frame.ftL[1]];
          var low = Math.min(feet[0], feet[1]);
          shadow.setAttribute("rx", (150 - low * 120).toFixed(1));
          shadow.setAttribute("ry", (22 - low * 16).toFixed(1));
          if (p.seg.caption !== lastCaption) { caption.textContent = p.seg.caption || ""; lastCaption = p.seg.caption; }
          figure.setAttribute("opacity", t < 0.6 ? (t / 0.6).toFixed(3) : "1");
        }

        window.__hf = window.__hf || {};
        window.__hf.buildReady = window.__hf.buildReady || {};
        window.__hf.buildReady["character-svg"] = (async function () {
          if (document.fonts && document.fonts.ready) { try { await document.fonts.ready; } catch (e) {} }
          renderAt(0);
        })();
        window.addEventListener("hf-seek", function (e) { renderAt(e.detail.time); });
      })();
    </script>
  </body>
</html>
"""


def write_project(
    *,
    project_dir: Path,
    film: CharacterFilm,
    narration_wav: Path,
    narration_duration: float,
    duration: float,
) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "assets" / "audio").mkdir(parents=True, exist_ok=True)
    shutil.copy2(narration_wav, project_dir / "assets" / "audio" / "narration.wav")

    clip_names = [s.clip for s in film.segments]
    segments_js = [
        {"clip": s.clip, "duration": round(s.duration, 3), "caption": s.caption, "loop": bool(s.loop), "drift": float(s.drift)}
        for s in film.segments
    ]
    html = (
        _HTML.replace("__TITLE__", film.title or "SVG 角色动画")
        .replace("__DUR__", f"{duration:g}")
        .replace("__NARR__", f"{narration_duration:g}")
        .replace("__MOCAP__", _mocap_js(clip_names))
        .replace("__SEGMENTS__", json.dumps(segments_js, ensure_ascii=False))
    )
    (project_dir / "index.html").write_text(html, encoding="utf-8")
    (project_dir / "hyperframes.json").write_text(
        json.dumps({"media": {"autoProxy": True}}, indent=2), encoding="utf-8"
    )
    return project_dir / "index.html"


def _render_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    env["PATH"] = f"/home/soffy/.local/bin:/home/soffy/.nvm/versions/node/v26.4.0/bin:{env.get('PATH', '')}"
    env["HYPERFRAMES_RENDER_DETACHED"] = "1"
    return env


def render_project(*, project_dir: Path, output_path: Path, fps: int = 30, quality: str = "looks", timeout_s: float = 1800.0) -> Path:
    binary = shutil.which("hyperframes")
    if not binary:
        raise RuntimeError("hyperframes CLI not found on PATH")
    project_dir = project_dir.resolve()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [binary, "render", str(project_dir), "-o", str(output_path), "-f", str(fps), "-q", quality, "--no-best-effort", "--quiet"]
    proc = subprocess.run(cmd, cwd=str(project_dir), env=_render_env(), capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise RuntimeError(f"hyperframes render failed ({proc.returncode}):\n{(proc.stdout or '')[-800:]}{(proc.stderr or '')[-800:]}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"hyperframes wrote nothing: {output_path}")
    return output_path


def build_character_animation(
    *,
    output_path: Path,
    segments: list[Segment],
    narration_lines: list[str],
    title: str = "SVG 角色动画 · CMU 动作捕捉",
    fps: int = 30,
    quality: str = "looks",
    tail: float = 1.6,
) -> Path:
    """Voice the narration, lay out the performance, render the film."""
    output_path = output_path.resolve()
    project_dir = output_path.parent / f".{output_path.stem}_hf"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    narration_wav, cues = build_narration(narration_lines, project_dir / "audio")
    narration_duration = float(_run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(narration_wav)]).stdout.strip())

    # stretch/shrink each segment so the performance follows the spoken line
    timed: list[Segment] = []
    for i, seg in enumerate(segments):
        target = max(cues[i][1] - cues[i][0], 1.0) if i < len(cues) else seg.duration
        timed.append(Segment(clip=seg.clip, duration=round(target, 3), caption=seg.caption, loop=seg.loop, drift=seg.drift))

    duration = max(narration_duration + tail, sum(s.duration for s in timed))
    film = CharacterFilm(segments=timed, narration_lines=narration_lines, title=title)
    write_project(
        project_dir=project_dir,
        film=film,
        narration_wav=narration_wav,
        narration_duration=narration_duration,
        duration=duration,
    )
    return render_project(project_dir=project_dir, output_path=output_path, fps=fps, quality=quality)


__all__ = [
    "BONES",
    "CharacterFilm",
    "Segment",
    "build_character_animation",
    "build_narration",
    "render_project",
    "synth_line",
    "write_project",
]
