#!/usr/bin/env python3
"""OMRENDER end-to-end acceptance: real HyperFrames / SVG / Blender renders.

Everything here is measured from the produced files — no mock, no placeholder:

* nine (or a chosen subset of) lanshu HyperFrames styles rendered from the
  locally voiced KV-cache story (piper narration + faster-whisper word times),
* one SVG skeletal character animation driven by CMU motion capture,
* one animated, lit Cycles-CPU Blender shot with a moving camera,
* a contact sheet, an ffprobe report, a sha256 and a motion ratio per film.

Run:  PYTHONPATH=. .venv/bin/python scripts/om_render_e2e.py [--styles a,b,c]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hevi.creative.layer4.blender_workflow import blender_render_animated_scene  # noqa: E402
from hevi.providers.hyperframes import styled  # noqa: E402
from hevi.studio.svg_character import Segment, build_character_animation, synth_line  # noqa: E402

FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"
OUT = REPO / "output" / "om_render_e2e"
STORY = REPO / "third_party" / "lanshu_explainer" / "stories" / "kv-cache"

DEFAULT_STYLES = ["v4-paper", "v6-cinematic", "v8-chalkboard", "v9-clay"]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    env["PATH"] = f"/home/soffy/.local/bin:/home/soffy/.nvm/versions/node/v26.4.0/bin:{env.get('PATH', '')}"
    return env


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    raw = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    ).decode()
    data = json.loads(raw)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {
        "duration": round(float(data["format"].get("duration", 0.0)), 3),
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "fps": video.get("r_frame_rate"),
        "nb_frames": int(video.get("nb_frames") or 0),
        "has_audio": audio is not None,
        "audio_codec": (audio or {}).get("codec_name"),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def contact_sheet(mp4: Path, *, tile: str = "4x3") -> Path:
    sheet = mp4.with_suffix(mp4.suffix + ".jpg")
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(mp4), "-vf", f"fps=1,scale=480:-1,tile={tile}", "-frames:v", "1", str(sheet)],
        env=_env(),
        check=False,
    )
    return sheet


def motion_ratio(mp4: Path, *, samples: int = 8) -> float:
    """Mean absolute pixel difference between consecutive sampled frames (0..1)."""
    import numpy as np

    tmp = mp4.parent / f".{mp4.stem}_motion"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    duration = float(
        subprocess.check_output([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)]).decode()
    )
    fps = max(samples / max(duration, 0.1), 0.2)
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(mp4), "-vf", f"fps={fps:.4f},scale=160:90,format=gray", str(tmp / "%03d.png")],
        check=True,
    )
    frames = sorted(tmp.glob("*.png"))
    ratios: list[float] = []
    prev = None
    for frame in frames[: samples + 2]:
        raw = subprocess.check_output([FFMPEG, "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 255.0
        if prev is not None:
            ratios.append(float(np.abs(arr - prev).mean()))
        prev = arr
    shutil.rmtree(tmp, ignore_errors=True)
    return round(sum(ratios) / len(ratios), 5) if ratios else 0.0


def _mux_audio(video: Path, narration: Path, music: Path | None, out: Path) -> Path:
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", str(video), "-i", str(narration)]
    if music is not None:
        cmd += ["-i", str(music), "-filter_complex", "[1:a]volume=1.0[n];[2:a]volume=0.28[m];[n][m]amix=inputs=2:duration=longest[a]"]
    else:
        cmd += ["-filter_complex", "[1:a]volume=1.0[a]"]
    cmd += ["-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)]
    subprocess.run(cmd, env=_env(), check=True)
    return out


def _music_bed(path: Path, seconds: float) -> Path:
    """A small licence-free procedural pad, so the Blender shot carries music."""
    import numpy as np

    sr = 44100
    t = np.arange(int(seconds * sr)) / sr
    chord = sum(np.sin(2 * np.pi * f * t) * a for f, a in [(110, 0.5), (164.8, 0.4), (220, 0.35), (277.2, 0.25)])
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 0.12 * t)
    wave = (chord * (0.6 + 0.4 * lfo)) * 0.22
    wave[-int(0.8 * sr):] *= np.linspace(1, 0, int(0.8 * sr))
    pcm = (np.clip(wave, -1, 1) * 32767).astype("<i2")
    import wave as wavemod

    with wavemod.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())
    return path


async def render_styles(styles: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for style in styles:
        out = OUT / f"hf_{style}.mp4"
        print(f"[hyperframes] {style} …", flush=True)
        try:
            await styled.render_styled_film(style=style, output_path=out, story_dir=STORY)
            contact_sheet(out)
            info = probe(out)
            info["motion_ratio"] = motion_ratio(out)
            results[f"hf_{style}"] = info
            print(f"[hyperframes] {style} -> {info}", flush=True)
        except Exception as exc:  # keep going: one bad style must not hide the rest
            results[f"hf_{style}"] = {"error": str(exc)[-600:]}
            print(f"[hyperframes] {style} FAILED: {exc}", flush=True)
    return results


def render_character() -> dict:
    out = OUT / "character_animation.mp4"
    print("[character] building + rendering …", flush=True)
    lines = [
        "这是一段由动作捕捉数据驱动的角色动画。",
        "画面里的小人，每一根骨头都在动。",
        "它先走几步。",
        "然后原地踏步，活动一下。",
        "接着跑起来。",
        "它挥挥手，打个招呼。",
        "再转个圈，跳起舞来。",
        "最后跳一下，稳稳落地。",
        "所有动作都来自卡内基梅隆大学的公开动作捕捉数据库。",
    ]
    clips = ["walk", "march", "run", "wave", "dance_spin", "dance_glide", "jump", "sit", "twist"]
    captions = ["走两步", "原地踏步", "跑起来", "挥挥手", "转个圈", "跳起舞", "跳一下", "坐下来", "扭一扭"]
    program = [Segment(clip=clips[i], duration=2.6, caption=captions[i]) for i in range(len(clips))]
    build_character_animation(output_path=out, segments=program, narration_lines=lines)
    contact_sheet(out, tile="5x2")
    info = probe(out)
    info["motion_ratio"] = motion_ratio(out)
    print(f"[character] -> {info}", flush=True)
    return info


def render_blender() -> dict:
    out = OUT / "blender_shot.mp4"
    silent = OUT / ".blender_shot_silent.mp4"
    print("[blender] rendering animated scene …", flush=True)
    result = blender_render_animated_scene(
        shot_spec={
            "width": 1280,
            "height": 720,
            "fps": 24,
            "frame_start": 1,
            "frame_end": 144,
            "samples": 12,
            "denoise": True,
            "output_path": str(silent),
        },
        timeout_s=1800,
    )
    if not result.success:
        raise RuntimeError(f"blender render failed: {result.error_message}\n{(result.execution_metadata or {}).get('stderr','')[-800:]}")
    narration_text = "用 Blender 在 CPU 上渲染的三维场景，相机在几何体之间平滑环绕。"
    narration = OUT / ".blender_narration.wav"
    synth_line(narration_text, narration)
    music = _music_bed(OUT / ".blender_music.wav", 6.5)
    _mux_audio(silent, narration, music, out)
    silent.unlink(missing_ok=True)
    contact_sheet(out, tile="4x2")
    info = probe(out)
    info["motion_ratio"] = motion_ratio(out)
    info["script_sha256"] = result.script_sha256
    print(f"[blender] -> {info}", flush=True)
    return info


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--styles", default=",".join(DEFAULT_STYLES), help="comma-separated style ids, or 'all'")
    parser.add_argument("--skip-styles", action="store_true")
    parser.add_argument("--skip-character", action="store_true")
    parser.add_argument("--skip-blender", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    styles = list(styled.STYLES) if args.styles == "all" else [s.strip() for s in args.styles.split(",") if s.strip()]

    report: dict[str, dict] = {}
    if not args.skip_styles:
        report.update(await render_styles(styles))
    if not args.skip_character:
        try:
            report["character_animation"] = render_character()
        except Exception as exc:
            report["character_animation"] = {"error": str(exc)[-600:]}
            print(f"[character] FAILED: {exc}", flush=True)
    if not args.skip_blender:
        try:
            report["blender_shot"] = render_blender()
        except Exception as exc:
            report["blender_shot"] = {"error": str(exc)[-600:]}
            print(f"[blender] FAILED: {exc}", flush=True)

    report_path = OUT / "om_render_e2e_report.json"
    existing: dict[str, dict] = {}
    if report_path.is_file():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing.update(report)
    report_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    report = existing
    print("\n=== OMRENDER E2E report ===")
    for name, info in report.items():
        if info.get("error"):
            print(f"{name:28s} FAILED: {str(info['error'])[:140]}")
            continue
        audio = "audio" if info.get("has_audio") else "NO-AUDIO"
        print(
            f"{name:28s} {info.get('duration'):>7}s {info.get('width')}x{info.get('height')} "
            f"{info.get('video_codec')} {audio} motion={info.get('motion_ratio')} sha={str(info.get('sha256'))[:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
