"""Per-character voice consistency and dialogue audio.

Every character carries one fixed ``voice`` profile: a written timbre
description, one Piper voice, an optional pitch offset and an optional
reference take.  Offline mode always uses the same voice for a character;
the first clean 3-8 s take is cut out as that character's audio reference
for H3/RunningHub reference-to-video requests.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

FFMPEG = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/usr/bin/ffprobe"
PIPER = os.environ.get("HEVI_PIPER_BIN") or "/data/soffy/projects/hevi-zero/.venv/bin/piper"
VOICE_DIR = Path(os.environ.get("HEVI_PIPER_VOICES_DIR") or "/data/soffy/projects/hevi-zero/voices")
PIPER_VOICES = {
    "zh_CN-huayan-medium.onnx": VOICE_DIR / "zh_CN-huayan-medium.onnx",
    "zh_CN-huayan-x_low.onnx": VOICE_DIR / "zh_CN-huayan-x_low.onnx",
}

EFFECTS = {
    "said": None,
    "inner": "highpass=f=120,lowpass=f=3200,aecho=0.8:0.6:40:0.25",
    "vo": "highpass=f=300,lowpass=f=3400,acompressor=threshold=-18dB:ratio=3",
}


def duration(path: str | Path) -> float:
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    )
    return float(out.strip())


def _cache_key(text: str, voice: str, pitch: float, kind: str) -> str:
    h = hashlib.sha256()
    for part in (text, voice, f"{pitch:.2f}", kind, "v1"):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:24]


def _pitch_filter(semitones: float) -> str:
    if abs(semitones) < 0.01:
        return ""
    factor = 2 ** (semitones / 12.0)
    return f"asetrate=48000*{factor:.6f},aresample=48000,atempo={1 / factor:.6f}"


def synthesize_line(
    text: str,
    profile: dict[str, Any],
    out_dir: Path,
    *,
    kind: str = "said",
    length_scale: float = 1.0,
) -> dict[str, Any]:
    """Synthesize one dialogue line.  Deterministic and cached by content."""
    out_dir.mkdir(parents=True, exist_ok=True)
    voice = str(profile.get("piper_voice") or "zh_CN-huayan-medium.onnx")
    pitch = float(profile.get("pitch_semitones") or 0.0)
    key = _cache_key(text, voice, pitch, kind)
    out_wav = out_dir / f"line_{key}.wav"
    if not out_wav.is_file() or out_wav.stat().st_size == 0:
        model = PIPER_VOICES.get(voice)
        if model is None or not model.is_file():
            raise RuntimeError(f"piper 音色缺失: {voice}")
        if not Path(PIPER).is_file():
            raise RuntimeError(f"piper 可执行文件缺失: {PIPER}")
        raw = out_dir / f"line_{key}.raw.wav"
        proc = subprocess.run(
            [PIPER, "-m", str(model), "-f", str(raw), "--length_scale", str(length_scale)],
            input=text,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0 or not raw.is_file():
            raise RuntimeError(f"piper 失败: {proc.stderr[-500:]}")
        filters = ["silenceremove=start_periods=1:start_threshold=-50dB",
                   "areverse", "silenceremove=start_periods=1:start_threshold=-50dB",
                   "areverse", "highpass=f=70"]
        pitch_f = _pitch_filter(pitch)
        if pitch_f:
            filters.append(pitch_f)
        effect = EFFECTS.get(kind)
        if effect:
            filters.append(effect)
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-i", str(raw), "-af", ",".join(filters),
             "-ar", "48000", "-ac", "2", str(out_wav)],
            check=True,
        )
        raw.unlink(missing_ok=True)
    return {"text": text, "kind": kind, "path": str(out_wav), "duration_s": round(duration(out_wav), 3)}


def make_silence(seconds: float, out_wav: Path) -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
         f"anullsrc=r=48000:cl=stereo:d={max(0.05, seconds):.3f}", "-ar", "48000", str(out_wav)],
        check=True,
    )
    return out_wav


def concat_audio(paths: list[Path], out_wav: Path, *, gap_s: float = 0.18) -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if not paths:
        return make_silence(0.1, out_wav)
    parts: list[Path] = []
    gap = out_wav.parent / "_gap.wav"
    make_silence(gap_s, gap)
    for i, path in enumerate(paths):
        parts.append(path)
        if i < len(paths) - 1:
            parts.append(gap)
    lst = out_wav.parent / "_concat_audio.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c:a", "pcm_s16le", str(out_wav)],
        check=True,
    )
    return out_wav


def pad_to(path: Path, seconds: float, out_wav: Path) -> Path:
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", str(path), "-af", "apad", "-t", f"{seconds:.3f}",
         "-c:a", "pcm_s16le", str(out_wav)],
        check=True,
    )
    return out_wav


def extract_voice_reference(source_wav: Path, out_wav: Path, *, min_s: float = 3.0, max_s: float = 8.0) -> dict[str, Any]:
    """Cut the first clean 3-8 s window from a take as an audio reference."""
    total = duration(source_wav)
    if total <= 0:
        raise RuntimeError("参考音频为空")
    length = min(max_s, max(min_s, min(total, 6.0)))
    start = 0.0
    if total > length:
        # Skip obvious leading silence with silencedetect, bounded by the file.
        proc = subprocess.run(
            [FFMPEG, "-v", "info", "-i", str(source_wav), "-af", "silencedetect=n=-45dB:d=0.3", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        for line in proc.stderr.splitlines():
            if "silence_end:" in line:
                try:
                    start = max(0.0, float(line.split("silence_end:")[1].split()[0]))
                except (ValueError, IndexError):
                    start = 0.0
                break
        start = min(start, max(0.0, total - length))
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(source_wav), "-t", f"{length:.3f}",
         "-af", "afade=t=in:st=0:d=0.05,afade=t=out:st=" + f"{max(0.0, length - 0.08):.3f}" + ":d=0.08",
         "-ar", "48000", "-ac", "1", str(out_wav)],
        check=True,
    )
    return {"path": str(out_wav), "start_s": round(start, 3), "duration_s": round(length, 3)}


def build_voice_plan(script: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Synthesize every script line; return a plan keyed by scene/beat/line."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lines_dir = out_dir / "lines"
    plan: dict[str, Any] = {"characters": {}, "lines": {}, "by_shot_key": {}}
    profiles = {str(c["id"]): c.get("voice") or {} for c in script.get("characters") or [] if c.get("id")}
    for cid, profile in profiles.items():
        plan["characters"][cid] = {
            "description": profile.get("description", ""),
            "piper_voice": profile.get("piper_voice", ""),
            "pitch_semitones": float(profile.get("pitch_semitones") or 0.0),
            "reference": profile.get("reference"),
        }
    for scene in script.get("scenes") or []:
        for beat in scene.get("beats") or []:
            for i, line in enumerate(beat.get("dialogue") or []):
                speaker = str(line.get("speaker"))
                profile = profiles.get(speaker) or {}
                result = synthesize_line(
                    str(line.get("text") or ""),
                    profile,
                    lines_dir,
                    kind=str(line.get("kind") or "said"),
                )
                key = f"{beat.get('beat_id')}:{i}"
                result.update({"speaker": speaker, "beat_id": beat.get("beat_id"), "key": key})
                plan["lines"][key] = result
                plan["by_shot_key"].setdefault(str(beat.get("beat_id")), []).append(key)
    (out_dir / "voice_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def attach_references(plan: dict[str, Any], ref_dir: Path) -> dict[str, Any]:
    """Cut a 3-8 s reference from each character's first synthesized line."""
    ref_dir.mkdir(parents=True, exist_ok=True)
    first: dict[str, dict[str, Any]] = {}
    for line in (plan.get("lines") or {}).values():
        speaker = str(line.get("speaker"))
        if speaker not in first or float(line.get("duration_s") or 0) > float(first[speaker].get("duration_s") or 0):
            first[speaker] = line
    for cid, line in first.items():
        out = ref_dir / f"voice_ref_{cid}.wav"
        info = extract_voice_reference(Path(line["path"]), out)
        plan["characters"].setdefault(cid, {})["reference"] = info
    return plan
