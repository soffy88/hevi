"""VIBE3D-R1 sample films: two preschool 3D shorts, 1080p, CPU-only, one at a time.

Produces, under ``audit/vibe3d/samples/``:

* ``planet_walk_16x9``  — 16:9, ~14 s, a warm little planet + a walking rigged
  character, CosyVoice Chinese narration + burned-in subtitles.
* ``town_walk_9x16``    — 9:16, ~14 s, the town street with the walker crossing.

Both are rendered single-process (CPU / SwiftShader), deterministically, and the
character's skeletal motion is measured from real bone world positions (the
"抽帧可见肢体位移" requirement).  A comparison strip against the existing R1D
star-sea / fox samples is written alongside.

Narration is generated locally with CosyVoice (the /data/soffy/cosyvoice CPU
venv) when available; if it is missing the script fails loudly rather than
shipping a silent film that claims to have narration.

Usage:
    python scripts/vibe3d_samples.py [--tts|--no-tts] [--only planet|town]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "audit" / "vibe3d"
SAMPLES = AUDIT / "samples"
TMP = ROOT / ".tmp" / "vibe3d_samples"
COSY_VENV = Path("/data/soffy/cosyvoice/venv/bin/python")

# Two warm preschool shorts.  Text is short and gentle (2–6 year old pacing).
CLIPS: list[dict[str, Any]] = [
    {
        "id": "planet_walk_16x9",
        "template": "little_planet",
        "camera_preset": "orbit",
        "aspect": "16:9",
        "duration_s": 14.0,
        "seed": 20241015,
        "narration": [
            (0.6, "小小的星球，慢慢转呀转。"),
            (5.2, "小人儿在草地上，一步一步地走。"),
            (9.8, "天上的白云，也跟着一起走。"),
        ],
        "voice": "zh_default",
    },
    {
        "id": "town_walk_9x16",
        "template": "town_street",
        "camera_preset": "follow",
        "aspect": "9:16",
        "duration_s": 14.0,
        "seed": 20241015,
        "narration": [
            (0.6, "小镇的街道上，太阳暖暖的。"),
            (5.2, "叔叔提着包，慢慢地往前走。"),
            (9.8, "大树和小鸟，都跟他打招呼。"),
        ],
        "voice": "zh_default",
    },
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(path: Path) -> dict[str, Any]:
    from hevi.layer4_legacy.scene3d.renderer import ffprobe as _fp

    return _fp(path)


def ffprobe_frames(path: Path) -> dict[str, Any]:
    from hevi.layer4_legacy.scene3d.renderer import ffprobe_frames as _fpf

    return _fpf(path)


# --------------------------------------------------------------------------- #
# Narration (CosyVoice, CPU)
# --------------------------------------------------------------------------- #
def synthesize_narration_batch(texts: list[str], out_wavs: list[Path]) -> None:
    """Synthesize several narration lines in one CosyVoice process.

    Uses the CosyVoice-300M-SFT checkpoint with the built-in ``中文女`` speaker:
    the zero-shot/CrossLingual path needs a reference wav and its text frontend
    tries to reach ModelScope, which is blocked here, whereas the SFT path is
    fully offline (frontend bundled).  One process loads the model once and
    synthesizes every line, which matters because the CPU model load dominates.
    """
    if not COSY_VENV.is_file():
        raise RuntimeError(
            f"CosyVoice venv missing at {COSY_VENV}; cannot produce narration"
        )
    for out in out_wavs:
        out.parent.mkdir(parents=True, exist_ok=True)
    script = f'''
import sys, os, time
os.chdir("/data/soffy/cosyvoice/CosyVoice"); sys.path += [".", "third_party/Matcha-TTS"]
import torch, torchaudio
torch.set_num_threads(16)
from cosyvoice.cli.cosyvoice import AutoModel
m = AutoModel(model_dir="/data/soffy/cosyvoice/models/CosyVoice-300M-SFT")
texts = {texts!r}
outs = {[str(p) for p in out_wavs]!r}
for text, out in zip(texts, outs):
    t0 = time.time()
    w = torch.cat([j["tts_speech"] for j in m.inference_sft(text, "中文女", stream=False)], 1)
    torchaudio.save(out, w, m.sample_rate)
    print("TTS_OK", out, round(w.shape[1]/m.sample_rate, 2), "in", round(time.time()-t0,1), flush=True)
'''
    proc = subprocess.run(
        [str(COSY_VENV), "-c", script], capture_output=True, text=True, timeout=3600
    )
    if proc.returncode != 0:
        raise RuntimeError(f"CosyVoice failed: {proc.stderr[-1500:]}")
    missing = [p for p in out_wavs if not p.is_file()]
    if missing:
        raise RuntimeError(f"CosyVoice produced no wav for {missing}: {proc.stderr[-800:]}")
    for line in proc.stdout.strip().splitlines():
        if line.startswith("TTS_OK"):
            print("   ", line)


def wav_duration(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    return float(probe.stdout.strip() or 0.0)


# --------------------------------------------------------------------------- #
# Subtitles
# --------------------------------------------------------------------------- #
def srt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> Path:
    lines: list[str] = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{srt_timestamp(start)} --> {srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Render + mux
# --------------------------------------------------------------------------- #
def render_clip(clip: dict[str, Any], tts: bool) -> dict[str, Any]:
    from hevi.layer4_legacy.scene3d.renderer import SceneRenderer, FFMPEG
    from hevi.layer4_legacy.scene3d.templates import build_template

    out_dir = SAMPLES / clip["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = build_template(
        clip["template"],
        aspect=clip["aspect"],
        duration=clip["duration_s"],
        seed=clip["seed"],
        camera_preset=clip["camera_preset"],
        resolution=1080,
    )
    spec.fps = 30
    renderer = SceneRenderer(spec, out_dir)

    # 1) Measure real skeletal motion before rendering (fails loudly if static).
    times = [clip["duration_s"] * f for f in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]
    stats = renderer.probe_character_stats(times)
    motion = _limb_displacement(stats)
    if motion["max_limb_displacement"] < 0.05:
        raise RuntimeError(f"{clip['id']}: character does not move ({motion})")
    boxes = renderer.probe_subject_bboxes(times)

    # 2) Render frames + encode the silent master.
    t0 = time.perf_counter()
    metrics = renderer.render()
    render_s = time.perf_counter() - t0
    silent = Path(metrics["video"])

    # 3) Narration.
    narration_meta: dict[str, Any] = {"enabled": tts, "lines": []}
    voice_wav = out_dir / "narration.wav"
    cue_starts: list[float] = []
    if tts:
        parts: list[Path] = []
        for i in range(len(clip["narration"])):
            parts.append(TMP / f"{clip['id']}_line{i}.wav")
        synthesize_narration_batch([t for _, t in clip["narration"]], parts)
        # Place lines at their intended cue start, but push later lines out if an
        # earlier line overruns so narration never overlaps.
        prev_end = -1.0
        for i, (start, text) in enumerate(clip["narration"]):
            dur = wav_duration(parts[i])
            placed = max(float(start), prev_end + 0.3)
            cue_starts.append(placed)
            prev_end = placed + dur
            narration_meta["lines"].append(
                {"start_s": round(placed, 3), "intended_start_s": start, "text": text,
                 "wav": parts[i].name, "duration_s": round(dur, 3)}
            )
        inputs: list[str] = ["-f", "lavfi", "-t", str(clip["duration_s"]),
                             "-i", "anullsrc=r=24000:cl=mono"]
        for part in parts:
            inputs += ["-i", str(part)]
        filters = []
        mix_labels = ["[0:a]"]
        for idx, start in enumerate(cue_starts, start=1):
            delay_ms = int(round(start * 1000))
            filters.append(
                f"[{idx}:a]aresample=24000,adelay={delay_ms}|{delay_ms}[a{idx}]"
            )
            mix_labels.append(f"[a{idx}]")
        filters.append(
            "".join(mix_labels) + f"amix=inputs={len(mix_labels)}:duration=first:normalize=0[aout]"
        )
        cmd = [FFMPEG, "-y", *inputs, "-filter_complex", ";".join(filters),
               "-map", "[aout]", "-c:a", "pcm_s16le", str(voice_wav)]
        subprocess.run(cmd, check=True, capture_output=True)

    # 4) Subtitles.
    cues = []
    for i, (start, text) in enumerate(clip["narration"]):
        cue_start = cue_starts[i] if tts else float(start)
        dur = narration_meta["lines"][i]["duration_s"] if tts else 3.2
        end = min(clip["duration_s"] - 0.05, cue_start + max(1.6, dur + 0.4))
        cues.append((cue_start, end, text))
    srt = write_srt(cues, out_dir / "subtitles.srt")

    # 5) Mux: burn subtitles, add narration if present.
    final = out_dir / f"{clip['id']}.mp4"
    sub_style = (
        "FontName=Noto Sans CJK SC,FontSize=15,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=42"
    )
    vf = f"subtitles={srt}:force_style='{sub_style}'"
    if tts:
        cmd = [FFMPEG, "-y", "-i", str(silent), "-i", str(voice_wav),
               "-vf", vf, "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
               "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(final)]
    else:
        cmd = [FFMPEG, "-y", "-i", str(silent), "-vf", vf,
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
               "-movflags", "+faststart", str(final)]
    subprocess.run(cmd, check=True, capture_output=True)

    probe = ffprobe(final)
    counted = ffprobe_frames(final)
    result = {
        "id": clip["id"],
        "template": clip["template"],
        "camera_preset": clip["camera_preset"],
        "aspect": clip["aspect"],
        "resolution": [spec.width, spec.height],
        "duration_s": clip["duration_s"],
        "fps": spec.fps,
        "seed": spec.seed,
        "frame_count": metrics["frame_count"],
        "nb_read_frames": counted["nb_read_frames"],
        "per_frame_s": metrics["per_frame_s"],
        "total_render_s": round(render_s, 3),
        "encode_s": metrics["encode_s"],
        "sha256": sha256(final),
        "silent_sha256": sha256(silent),
        "probe": probe,
        "character_motion": motion,
        "layout_boxes": boxes,
        "narration": narration_meta,
        "subtitles": str(srt.relative_to(ROOT)),
        "video": str(final.relative_to(ROOT)),
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def _limb_displacement(stats: list[dict[str, Any]]) -> dict[str, Any]:
    bone_names: set[str] = set()
    for row in stats:
        for c in row["characters"]:
            bone_names |= set(c["bones"].keys())
    peak = 0.0
    per_bone: dict[str, float] = {}
    for bone in sorted(bone_names):
        pts = []
        for row in stats:
            for c in row["characters"]:
                if bone in c["bones"]:
                    pts.append(c["bones"][bone])
        if len(pts) < 2:
            continue
        d = max(math.dist(pts[0], p) for p in pts[1:])
        per_bone[bone] = round(d, 4)
        peak = max(peak, d)
    return {
        "max_limb_displacement": round(peak, 4),
        "samples": len(stats),
        "per_bone": per_bone,
    }


def make_comparison_strip(results: list[dict[str, Any]]) -> Path | None:
    """6-frame strips of each new sample next to the existing R1D samples."""
    from PIL import Image, ImageDraw

    new_frames: list[tuple[str, list[Path]]] = []
    for r in results:
        d = SAMPLES / r["id"] / "frames"
        frames = sorted(d.glob("frame_*.png"))
        if not frames:
            continue
        idx = [round(i * (len(frames) - 1) / 5) for i in range(6)]
        new_frames.append((r["id"], [frames[i] for i in idx]))
    r1d = ROOT / "output" / "scene3d_r1d"
    refs: list[tuple[str, Path]] = []
    for name, sub in (("star_sea (R1D)", "star_sea_16x9"), ("fox_wheat (R1D)", "fox_wheat_9x16")):
        cands = sorted((r1d / sub / "frames").glob("frame_*.png")) if (r1d / sub / "frames").is_dir() else []
        if cands:
            refs.append((name, cands[len(cands) // 2]))
    if not new_frames:
        return None
    cols = 6
    thumb = (260, 146)
    rows = len(new_frames) + (1 if refs else 0)
    sheet = Image.new("RGB", (cols * thumb[0], rows * (thumb[1] + 22)), (18, 20, 34))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for label, frames in new_frames:
        draw.text((6, y + 4), f"VIBE3D {label}", fill=(255, 255, 255))
        for c, fr in enumerate(frames):
            im = Image.open(fr).convert("RGB")
            im.thumbnail(thumb, Image.Resampling.LANCZOS)
            sheet.paste(im, (c * thumb[0], y + 22))
        y += thumb[1] + 22
    if refs:
        draw.text((6, y + 4), "reference (existing scene3d R1D)", fill=(255, 220, 160))
        for c, (label, fr) in enumerate(refs):
            im = Image.open(fr).convert("RGB")
            im.thumbnail(thumb, Image.Resampling.LANCZOS)
            sheet.paste(im, (c * thumb[0], y + 22))
    out = AUDIT / "sample_comparison.png"
    sheet.save(out, quality=92)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tts", dest="tts", action="store_true", default=True)
    ap.add_argument("--no-tts", dest="tts", action="store_false")
    ap.add_argument("--only", choices=["planet", "town"], default=None)
    args = ap.parse_args(argv)

    SAMPLES.mkdir(parents=True, exist_ok=True)
    clips = CLIPS
    if args.only == "planet":
        clips = [c for c in CLIPS if c["template"] == "little_planet"]
    elif args.only == "town":
        clips = [c for c in CLIPS if c["template"] == "town_street"]

    results = []
    for clip in clips:
        print(f"[{clip['id']}] rendering {clip['template']} {clip['aspect']} ...", flush=True)
        results.append(render_clip(clip, args.tts))
        print(f"[{clip['id']}] done: {results[-1]['per_frame_s']}s/frame, "
              f"{results[-1]['nb_read_frames']} frames", flush=True)

    strip = make_comparison_strip(results)
    summary = {
        "clips": results,
        "comparison_strip": str(strip.relative_to(ROOT)) if strip else None,
    }
    (AUDIT / "samples_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
