"""Creator Style Kit (threeaus/creator-style-kit, MIT) support for hevi's HyperFrames line.

Integration design
------------------
* The kit itself lives OUTSIDE the hevi repo
  (``~/projects/_refs/creator-style-kit``, overridable via ``HEVI_CSK_HOME``).
  Only the generated style catalogue snapshot is kept inside hevi; the kit's
  own scripts (scaffold.py / build_style.py / compose.py) do the scene
  building.  This keeps ~180 MB of fonts, SFX WAVs and runtime assets out of
  the repo (hevi's working tree is deliberately kept small).
* Renders are deterministic and seek-based: the kit's timelines are seek-safe
  (GSAP ``tl.set``/``tl.to``, seeded PRNG), so we load the scaffolded project
  in headless Chromium (Playwright), mount each hosted composition the way
  the HyperFrames runtime does (template -> host div -> eval its script) and
  seek its registered GSAP timeline per frame.  hevi's existing ``hyperframes_service`` is deliberately NOT
  reused for capture: it opens a fresh browser per frame with a 100 ms
  virtual-time budget, which would freeze every CSK composition on its first
  instant.  The ffmpeg encoding flags are reused verbatim
  (libx264 / yuv420p / scale / medium / crf 18).
* Fonts: bundled fonts ship in the kit (all OFL-1.1, subset per project at
  build).  MiSans / 优设标题黑 are NOT redistributable: the kit fetches them
  itself via ``scripts/fetch_fonts.py`` (sha256-checked).  Styles needing them
  raise :class:`CskError` until the fetch has run.
* Sound: each style's cue kit (Kenney/uisfx, CC0) is baked into the project
  by the kit's build_style.py. The kit's own ``sound_pass.py`` (uv +
  sound-layer loudness/QA) is NOT run here: :func:`run_sound_pass` below
  re-implements only the wiring hevi needs with stdlib + ffmpeg —
  collect the scaffolded ``<audio data-peak>`` cues, peak-align each cue
  file onto the cue time, mux onto the picture, verify an audio stream
  exists with ffprobe, and measure each cue's peak-alignment error in
  the mix. A render with no cues or no cue audio files raises instead
  of silently delivering a silent MP4. Loudness / true-peak / picture
  sync QA from the kit's sound-layer (``mix.py``/``qa.py``) is NOT
  claimed: the report records ``kit_sound_pass: "not_run"``.
  This is a separate resource from hevi's
  ``audio.sfx_render`` (earshot, code-rendered) and is intentionally not
  merged — see the capability description.
"""

from __future__ import annotations

import asyncio
import array
import hashlib
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import wave

import yaml
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class CskError(RuntimeError):
    """Something is wrong with the creator-style-kit setup or a render step."""


CSK_ENV = "HEVI_CSK_HOME"
CSK_DEFAULT_HOME = Path.home() / "projects" / "_refs" / "creator-style-kit"

# Source: threeaus/creator-style-kit, MIT.  Kept here so the catalogue can be
# regenerated deterministically; the single source of truth stays in the kit.
CSK_SOURCE_URL = "https://github.com/threeaus/creator-style-kit"

REQUIRED_KIT_PATHS = ("styles", "scripts/scaffold.py", "runtime/kit.js")


def resolve_kit_home() -> Path:
    """Return the kit checkout, raising :class:`CskError` when unusable."""
    home = Path(os.environ.get(CSK_ENV, CSK_DEFAULT_HOME)).expanduser()
    missing = [p for p in REQUIRED_KIT_PATHS if not (home / p).exists()]
    if missing:
        raise CskError(
            f"creator-style-kit not usable at {home} "
            f"(missing: {', '.join(missing)}); set {CSK_ENV} or clone "
            f"{CSK_SOURCE_URL}"
        )
    return home


def load_style_specs(kit_home: Path | None = None) -> list[dict[str, Any]]:
    """Parse every ``styles/*/style.yaml`` into a sorted catalogue list."""
    home = kit_home or resolve_kit_home()
    specs = []
    for style_yaml in sorted((home / "styles").glob("*/style.yaml")):
        spec = yaml.safe_load(style_yaml.read_text(encoding="utf-8"))
        specs.append(
            {
                "id": spec.get("id"),
                "order": spec.get("order", 99),
                "name_zh": spec.get("name", {}).get("zh", ""),
                "name_en": spec.get("name", {}).get("en", ""),
                "essence": spec.get("essence", ""),
                "best_for": spec.get("best_for", []),
                "not": spec.get("not", []),
                "motion": spec.get("motion", {}),
                "colors": spec.get("colors", {}),
                "layout": spec.get("layout", {}),
                "fonts": {
                    role: {
                        "family": f.get("family"),
                        "weight": f.get("weight"),
                        "license": f.get("license"),
                        "source": f.get("source"),
                        "bundled": f.get("bundled", False),
                    }
                    for role, f in (spec.get("fonts") or {}).items()
                },
                "sound": {
                    "character": spec.get("sound", {}).get("character", ""),
                    "rules": spec.get("sound", {}).get("rules", {}),
                    "roles": list(spec.get("sound", {}).get("kit", {}).keys()),
                },
            }
        )
    specs.sort(key=lambda s: (s["order"], s["id"]))
    return specs


def style_ids(kit_home: Path | None = None) -> list[str]:
    return [s["id"] for s in load_style_specs(kit_home)]


def kit_commit(kit_home: Path | None = None) -> str:
    """Best-effort git commit of the kit checkout ("" when unknown)."""
    home = kit_home or resolve_kit_home()
    try:
        out = subprocess.run(
            ["git", "-C", str(home), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - best effort only
        return ""


def scaffold_project(
    kit_home: Path,
    style_id: str,
    content: dict[str, Any],
    project_dir: Path,
) -> float:
    """Run the kit's scaffold.py; return the planned total duration (seconds)."""
    if style_id not in style_ids(kit_home):
        raise CskError(f"unknown style '{style_id}'")
    if not isinstance(content, dict) or "name" not in content or "beats" not in content:
        raise CskError("content must be a beats JSON object with 'name' and 'beats'")
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    beats_path = project_dir / "beats.json"
    beats_path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    env = dict(os.environ)
    # build_style.py shells out to the bare `pyftsubset` console script, which
    # lives next to the interpreter when fonttools is installed in a venv.
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        [
            sys.executable,
            str(kit_home / "scripts" / "scaffold.py"),
            style_id,
            str(project_dir),
            "--content",
            str(beats_path),
            "--init",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    if proc.returncode != 0:
        raise CskError(
            f"scaffold.py failed for style '{style_id}': "
            f"{(proc.stderr or proc.stdout)[-2000:]}"
        )
    # scaffold prints: "wrote <path> (<n> beats, <total:.2f>s, style <id>)"
    match = re.search(r"\((\d+)\s+beats?,\s*([\d.]+)s,\s*style\s+\S+\)", proc.stdout)
    if not match:
        raise CskError(
            f"scaffold.py did not report a duration: {proc.stdout[-1000:]}"
        )
    return float(match.group(2))


def _serve_dir(project_dir: Path) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    """Serve a HyperFrames project dir over loopback HTTP (file:// XHR fails)."""
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(SimpleHTTPRequestHandler, directory=str(project_dir)),
    )
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, thread, f"http://127.0.0.1:{port}/index.html"


_MOUNT_SHIM = """
async () => {
  // HyperFrames runtime shim: fetch each hosted composition, mount its
  // <template> content into the host div (so its relative csk/ asset paths
  // resolve at the project root) and execute its inline script, which
  // registers window.__timelines["<comp-id>"].
  window.__timelines = window.__timelines || {};
  const hosts = [...document.querySelectorAll('[data-composition-src]')];
  const mounted = [];
  for (const host of hosts) {
    const src = host.getAttribute('data-composition-src');
    const html = await (await fetch(src)).text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const tpl = doc.querySelector('template');
    if (!tpl) continue;
    // A <script> cloned from a template executes on insertion; remove it from
    // the fragment and eval it exactly once, or the composition builds two
    // overlay sets and only the second timeline gets registered/seeked.
    const script = tpl.content.querySelector('script');
    const code = script ? script.textContent : null;
    if (script) script.remove();
    host.appendChild(document.importNode(tpl.content, true));
    if (code) window.eval(code);
    mounted.push(host.getAttribute('data-composition-id'));
  }
  return mounted;
}
"""


async def _render_project_frames(
    project_dir: Path,
    frames_dir: Path,
    *,
    fps: int,
    duration_s: float,
    width: int = 1080,
    height: int = 1920,
    capture_mode: str = "screenshot",
) -> int:
    """Seek-based deterministic capture of a HyperFrames project.

    ``capture_mode="screenshot"`` (default) polls ``page.screenshot()``
    until two captures agree. ``capture_mode="beginframe"`` drives the
    compositor with CDP ``HeadlessExperimental.beginFrame`` instead
    (``hevi/video/beginframe_capture.py``): one atomic capture per
    frame, verified by a second identical capture. In beginFrame mode
    ``page.screenshot()`` is never called (it deadlocks under manual
    BeginFrame control in this stack) and readiness waits poll with
    ``page.evaluate`` instead of ``wait_for_function`` (rAF polling
    stalls while BeginFrame control owns the compositor).
    """
    from playwright.async_api import async_playwright

    if capture_mode not in ("screenshot", "beginframe"):
        raise CskError(f"unknown capture_mode {capture_mode!r}; want screenshot|beginframe")

    frames_dir.mkdir(parents=True, exist_ok=True)
    server, _thread, url = _serve_dir(project_dir)
    total_frames = max(1, int(round(duration_s * fps)))
    try:
        async with async_playwright() as pw:
            launch_args = ["--no-sandbox", "--disable-gpu"]
            if capture_mode == "beginframe":
                from hevi.video.beginframe_capture import BEGINFRAME_CHROMIUM_ARGS

                launch_args = ["--no-sandbox", "--disable-gpu", *BEGINFRAME_CHROMIUM_ARGS]
            browser = await pw.chromium.launch(headless=True, args=launch_args)
            try:
                page = await browser.new_page(
                    viewport={"width": width, "height": height}
                )
                # The host page's own inline script writes __timelines["main"]
                # before any runtime exists; predefine it so that is not an error.
                await page.add_init_script(
                    "window.__timelines = window.__timelines || {};"
                )
                await page.goto(url)
                if capture_mode == "beginframe":
                    # Poll with evaluate + real-time waits: wait_for_function
                    # (rAF polling) stalls under BeginFrame control.
                    async def _wait_ready(expression: str, timeout_ms: int = 30000) -> None:
                        waited = 0
                        while waited < timeout_ms:
                            if await page.evaluate(expression):
                                return
                            await page.wait_for_timeout(50)
                            waited += 50
                        raise CskError(f"beginframe capture: not ready: {expression}")

                    await _wait_ready("!!(window.gsap && window.CSK)")
                else:
                    await page.wait_for_function(
                        "window.gsap && window.CSK", timeout=30000
                    )
                mounted = await page.evaluate(_MOUNT_SHIM)
                if not mounted:
                    raise CskError("no composition could be mounted from index.html")
                if capture_mode == "beginframe":
                    await _wait_ready("document.fonts.status === 'loaded'")
                else:
                    await page.wait_for_function(
                        "document.fonts.status === 'loaded'", timeout=30000
                    )
                cdp_session = None
                if capture_mode == "beginframe":
                    cdp_session = await page.context.new_cdp_session(page)
                seek_all = (
                    "Object.entries(window.__timelines || {})"
                    ".filter(([k]) => k !== 'main')"
                    ".forEach(([, tl]) => tl.pause(T))"
                )
                await page.evaluate(seek_all.replace("T", "0"))
                await page.wait_for_timeout(60)
                for idx in range(total_frames):
                    t = idx / fps
                    await page.evaluate(seek_all.replace("T", f"{t:.4f}"))
                    if capture_mode == "beginframe":
                        from hevi.video.beginframe_capture import capture_frame_settled

                        result = await capture_frame_settled(
                            cdp_session, fps=fps, image_format="png"
                        )
                        (frames_dir / f"frame_{idx:04d}.png").write_bytes(
                            result.png_or_jpeg
                        )
                        continue
                    # Settle confirmation (converged __hf discipline,
                    # hevi/video/hf_adapter.py): poll screenshots until
                    # two consecutive captures hash identically, so a
                    # blur-in transition that has not landed yet is
                    # never captured as the delivered frame. A fixed
                    # 40ms wait used to capture exactly that blur.
                    # The window.__timelines shim itself is deprecated;
                    # new renderers must speak window.__hf.
                    previous_hash = None
                    settled_png = None
                    for _attempt in range(50):
                        png = await page.screenshot()
                        digest = hashlib.sha256(png).hexdigest()
                        if previous_hash is not None and digest == previous_hash:
                            settled_png = png
                            break
                        previous_hash, settled_png = digest, png
                        await page.wait_for_timeout(20)
                    (frames_dir / f"frame_{idx:04d}.png").write_bytes(settled_png)
            finally:
                await browser.close()
    finally:
        server.shutdown()
    return total_frames


def _encode_mp4(frames_dir: Path, output: Path, *, fps: int, width: int, height: int) -> None:
    """Encode a frame sequence with the same flags as hyperframes_service."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CskError("ffmpeg not found on PATH (needed for mp4 encoding)")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "frame_%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        f"scale={width}:{height}",
        "-preset",
        "medium",
        "-crf",
        "18",
        str(output),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not output.exists():
        raise CskError(f"ffmpeg encode failed: {(proc.stderr or '')[-1000:]}")


# ---------------------------------------------------------------------------
# Sound pass (B2): scaffold cues -> peak-aligned mix -> mux -> verify.
#
# The kit's scaffold writes <audio> cues with data-peak / data-role /
# data-weight into each composition, and the host index.html carries the
# composition offset (data-start). This section re-implements only that
# wiring (collect, place, mux, measure) with stdlib + ffmpeg. It does
# NOT run the kit's sound_pass.py / sound-layer mix.py / qa.py, and it
# does NOT claim their loudness, true-peak or picture-sync checks.
# When there are no cues, or a cue's audio file is missing, or the muxed
# file has no audio stream, this raises CskError: a silent MP4 must never
# be delivered as a completed, sounded render.
# ---------------------------------------------------------------------------

_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def _tag_attrs(tag: str) -> dict[str, str]:
    return dict(_ATTR_RE.findall(tag))


def collect_sound_cues(project_dir: Path) -> list[dict[str, Any]]:
    """Collect ``<audio data-peak>`` cues from a scaffolded project.

    Returns cues sorted by absolute cue time (host data-start + the
    cue's data-peak), each with id, t, sound (absolute file path),
    role, weight, visual and volume. Cues without data-peak (hand-placed
    music/voice) are not cues and are skipped, as in the kit's own pass.
    """
    project_dir = Path(project_dir)
    index_path = project_dir / "index.html"
    if not index_path.is_file():
        return []
    index_text = index_path.read_text(encoding="utf-8")
    cues: list[dict[str, Any]] = []
    for host in re.findall(r"<div[^>]*data-composition-src=[^>]*>", index_text):
        attrs = _tag_attrs(host)
        src = attrs.get("data-composition-src")
        if not src:
            continue
        try:
            offset = float(attrs.get("data-start", "0") or 0)
        except ValueError:
            offset = 0.0
        comp_path = project_dir / src
        if not comp_path.is_file():
            continue
        comp_text = comp_path.read_text(encoding="utf-8")
        for tag in re.findall(r"<audio[^>]*>", comp_text):
            audio = _tag_attrs(tag)
            if "data-peak" not in audio or "src" not in audio:
                continue
            try:
                peak = float(audio["data-peak"])
            except ValueError:
                continue
            try:
                volume = float(audio.get("data-volume", "1") or 1)
            except ValueError:
                volume = 1.0
            cues.append(
                {
                    "id": audio.get("id", ""),
                    "t": round(offset + peak, 3),
                    "sound": str((project_dir / audio["src"]).resolve()),
                    "role": audio.get("data-role", ""),
                    "weight": audio.get("data-weight", "support"),
                    "visual": audio.get("data-visual", ""),
                    "volume": volume,
                }
            )
    cues.sort(key=lambda c: c["t"])
    return cues


def _read_wav_envelope(wav_path: Path) -> tuple[int, list[float]]:
    """Per-frame peak amplitude (0..1) of a WAV file, stdlib only.

    Handles 8/16/32-bit PCM, any channel count: a frame's value is the
    largest absolute sample across its channels.
    """
    try:
        with wave.open(str(wav_path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            rate = wf.getframerate()
            nframes = wf.getnframes()
            raw = wf.readframes(nframes)
    except Exception as exc:  # noqa: BLE001 - caller reports the file
        raise CskError(f"sound_pass: cannot read WAV {wav_path}: {exc}") from exc
    if sampwidth == 1:
        samples = array.array("B", raw)
        values = [abs(v - 128) / 128.0 for v in samples]
    elif sampwidth == 2:
        samples = array.array("h", raw)
        if sys.byteorder == "big":
            samples.byteswap()
        values = [abs(v) / 32768.0 for v in samples]
    elif sampwidth == 4:
        samples = array.array("i", raw)
        if sys.byteorder == "big":
            samples.byteswap()
        values = [abs(v) / 2147483648.0 for v in samples]
    else:
        raise CskError(
            f"sound_pass: unsupported WAV sample width {sampwidth} in {wav_path}"
        )
    envelope: list[float] = []
    for frame in range(nframes):
        base = frame * channels
        envelope.append(max(values[base : base + channels]) if channels else 0.0)
    return rate, envelope


def _peak_time_in_window(
    envelope: list[float], rate: int, start_s: float, end_s: float
) -> tuple[float | None, float]:
    """Time of the loudest frame inside [start_s, end_s]; (None, 0.0) if silent."""
    lo = max(0, int(start_s * rate))
    hi = min(len(envelope), int(end_s * rate) + 1)
    if lo >= hi or not envelope:
        return None, 0.0
    best = max(range(lo, hi), key=lambda i: envelope[i])
    return best / rate, envelope[best]


def _probe_duration(video_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise CskError("sound_pass: ffprobe not found on PATH (needed to verify audio)")
    proc = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(video_path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise CskError(f"sound_pass: ffprobe failed on {video_path}")
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise CskError(f"sound_pass: ffprobe returned no duration for {video_path}") from exc


def _probe_streams(video_path: Path) -> list[dict[str, Any]]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise CskError("sound_pass: ffprobe not found on PATH (needed to verify audio)")
    proc = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,width,height",
            "-of", "json", str(video_path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise CskError(f"sound_pass: ffprobe failed on {video_path}")
    try:
        return json.loads(proc.stdout or "{}").get("streams", [])
    except json.JSONDecodeError as exc:
        raise CskError(f"sound_pass: ffprobe output not JSON for {video_path}") from exc


def run_sound_pass(
    project_dir: Path,
    silent_mp4: Path,
    output_mp4: Path,
    *,
    fps: int,
) -> dict[str, Any]:
    """Mix scaffold cues onto a silent render and verify the result.

    Steps: collect cues (raising when there are none), verify every cue
    file exists, peak-align each cue file so its loudest sample lands on
    its cue time (ffmpeg adelay), mix, mux onto the picture (video stream
    copied), then ffprobe-verify that the output has both a video and an
    audio stream and measure each cue's alignment error from the mix
    (measured peak time minus cue time, in seconds and in frames at
    ``fps``). The report is written to ``<project>/audio/hevi_sound_pass.json``
    and returned. The kit's sound-layer loudness/QA is not run.
    """
    project_dir = Path(project_dir)
    silent_mp4 = Path(silent_mp4)
    output_mp4 = Path(output_mp4)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CskError("sound_pass: ffmpeg not found on PATH (needed for mix/mux)")
    cues = collect_sound_cues(project_dir)
    if not cues:
        raise CskError(
            "sound_pass: no audio cues found in scaffolded project "
            f"{project_dir} (compositions carry no <audio data-peak> tags); "
            "refusing to deliver a silent mp4 as a completed sounded render"
        )
    missing = [c["sound"] for c in cues if not Path(c["sound"]).is_file()]
    if missing:
        raise CskError(
            "sound_pass: cue audio file(s) missing, refusing silent delivery: "
            + ", ".join(missing)
        )
    duration_s = _probe_duration(silent_mp4)

    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    mix_wav = audio_dir / "hevi_mix.wav"

    # Peak-align: delay = cue time - source peak time (clamped at 0, recorded).
    delays_ms: list[int] = []
    source_peaks: list[float] = []
    for cue in cues:
        rate, envelope = _read_wav_envelope(Path(cue["sound"]))
        peak_t, _amp = _peak_time_in_window(envelope, rate, 0.0, len(envelope) / rate)
        source_peak = peak_t if peak_t is not None else 0.0
        source_peaks.append(round(source_peak, 3))
        delays_ms.append(max(0, round((cue["t"] - source_peak) * 1000)))

    filter_parts: list[str] = []
    for i, delay in enumerate(delays_ms):
        filter_parts.append(
            f"[{i}:a]adelay={delay}|{delay},aresample=48000[a{i}];"
        )
    inputs = "".join(f"[a{i}]" for i in range(len(cues)))
    filter_parts.append(
        f"{inputs}amix=inputs={len(cues)}:duration=longest:normalize=0,"
        f"apad=pad_dur={duration_s:.3f},aresample=48000[aout]"
    )
    cmd = [ffmpeg, "-y"]
    for cue in cues:
        cmd += ["-i", cue["sound"]]
    cmd += [
        "-filter_complex", "".join(filter_parts),
        "-map", "[aout]", "-t", f"{duration_s:.3f}",
        "-c:a", "pcm_s16le", str(mix_wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not mix_wav.is_file():
        raise CskError(f"sound_pass: cue mix failed: {(proc.stderr or '')[-1000:]}")

    # Alignment measurement on the mix itself: loudest frame near each cue.
    mix_rate, mix_envelope = _read_wav_envelope(mix_wav)
    cue_reports: list[dict[str, Any]] = []
    for cue, delay, source_peak in zip(cues, delays_ms, source_peaks):
        measured, _amp = _peak_time_in_window(
            mix_envelope, mix_rate, max(0.0, cue["t"] - 0.35), cue["t"] + 0.35
        )
        if measured is None:
            error_s: float | None = None
            error_frames: float | None = None
        else:
            error_s = round(measured - cue["t"], 3)
            error_frames = round(error_s * fps, 1)
        cue_reports.append(
            {
                **cue,
                "source_peak_s": source_peak,
                "delay_ms": delay,
                "delay_clamped": delay == 0 and source_peak > cue["t"],
                "measured_peak_s": measured,
                "alignment_error_s": error_s,
                "alignment_error_frames": error_frames,
            }
        )
    errors = [c["alignment_error_s"] for c in cue_reports if c["alignment_error_s"] is not None]
    max_abs_error = round(max((abs(e) for e in errors), default=0.0), 3)

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    mux = subprocess.run(
        [
            ffmpeg, "-y",
            "-i", str(silent_mp4), "-i", str(mix_wav),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{duration_s:.3f}", str(output_mp4),
        ],
        capture_output=True, text=True, timeout=600,
    )
    if mux.returncode != 0 or not output_mp4.is_file():
        raise CskError(f"sound_pass: mux failed: {(mux.stderr or '')[-1000:]}")
    streams = _probe_streams(output_mp4)
    has_video = any(s.get("codec_type") == "video" for s in streams)
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not has_video or not audio_streams:
        raise CskError(
            "sound_pass: muxed output failed stream verification "
            f"(video={has_video}, audio={len(audio_streams)}); "
            "refusing to deliver it as a sounded render"
        )
    report: dict[str, Any] = {
        "mixer": "hevi_ffmpeg_peak_aligned",
        "kit_sound_pass": "not_run",
        "kit_sound_pass_note": (
            "The kit's sound_pass.py / sound-layer mix.py / qa.py (uv, "
            "loudness, true-peak, picture-sync QA) were not run; only "
            "cue placement, mux and peak-alignment measurement are covered."
        ),
        "status": "mixed",
        "cue_count": len(cues),
        "duration_s": round(duration_s, 3),
        "fps": fps,
        "max_abs_alignment_error_s": max_abs_error,
        "max_abs_alignment_error_frames": round(max_abs_error * fps, 1),
        "cues": cue_reports,
        "audio_stream": audio_streams[0],
        "streams": streams,
        "mix_wav": str(mix_wav),
    }
    report_path = audio_dir / "hevi_sound_pass.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report["report_json"] = str(report_path)
    return report


def render_project_mp4(
    project_dir: Path,
    output: Path,
    *,
    fps: int = 24,
    duration_s: float,
    width: int = 1080,
    height: int = 1920,
    sound: bool = True,
    capture_mode: str = "screenshot",
    keep_frames: bool = False,
) -> Path:
    """Scaffolded HyperFrames project -> deterministic MP4 (sync wrapper).

    With ``sound=True`` (default) the silent picture render goes through
    :func:`run_sound_pass`, so the delivered MP4 carries the style's cue
    audio and an audio stream verified by ffprobe. With ``sound=False``
    the caller gets the silent picture only and must label it a pending
    draft: it is not a completed sounded delivery. A failed sound pass
    raises :class:`CskError` instead of returning a silent file.

    ``capture_mode="beginframe"`` captures each frame atomically with
    CDP ``HeadlessExperimental.beginFrame`` (see
    ``hevi/video/beginframe_capture.py``); the default ``"screenshot"``
    mode polls ``page.screenshot()`` until settled. ``keep_frames=True``
    keeps the PNG frame directory next to the project (verification
    use); by default it is deleted after encoding.
    """
    project_dir = Path(project_dir)
    if not (project_dir / "index.html").exists():
        raise CskError(f"not a scaffolded project (index.html missing): {project_dir}")
    frames_dir = project_dir.parent / (project_dir.name + "_frames")
    if frames_dir.exists():
        shutil.rmtree(frames_dir)

    async def _go() -> int:
        return await _render_project_frames(
            project_dir, frames_dir, fps=fps, duration_s=duration_s,
            width=width, height=height, capture_mode=capture_mode,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_go())
    else:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, _go()).result()
    try:
        if sound:
            silent_path = project_dir.parent / (project_dir.name + "_silent.mp4")
            try:
                _encode_mp4(frames_dir, silent_path, fps=fps, width=width, height=height)
                run_sound_pass(project_dir, silent_path, Path(output), fps=fps)
            finally:
                if silent_path.exists():
                    silent_path.unlink()
        else:
            _encode_mp4(frames_dir, output, fps=fps, width=width, height=height)
    finally:
        if not keep_frames:
            shutil.rmtree(frames_dir, ignore_errors=True)
    return Path(output)
