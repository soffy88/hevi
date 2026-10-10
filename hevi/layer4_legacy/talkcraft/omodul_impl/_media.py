"""Local media side effects for talkcraft (omodul-side helpers): Piper TTS,
ffmpeg/ffprobe wrappers.  CPU only, no network, no paid provider."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

FFMPEG = os.environ.get("HEVI_FFMPEG") or shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
FFPROBE = os.environ.get("HEVI_FFPROBE") or shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"
PIPER = os.environ.get("HEVI_TALKCRAFT_PIPER", "/data/soffy/projects/hevi-zero/.venv/bin/piper")
VOICE_DIR = os.environ.get("HEVI_TALKCRAFT_VOICES", "/data/soffy/projects/hevi-zero/voices")
VOICES = {"zh": "zh_CN-huayan-medium.onnx", "en": "en_US-ryan-medium.onnx"}


class MediaError(RuntimeError):
    pass


def run(cmd: list[str], *, stdin: str | None = None) -> str:
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if r.returncode:
        raise MediaError(f"{Path(cmd[0]).name} failed ({r.returncode}): {r.stderr[-1200:]}")
    return r.stdout + r.stderr


def duration(path: str | Path) -> float:
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    )
    return float(out.strip())


def probe(path: str | Path) -> dict:
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], text=True
    )
    return json.loads(out)


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def piper_tts(*, text: str, out_wav: Path, lang: str = "zh", length_scale: float = 1.0) -> float:
    """One sentence -> 48 kHz stereo wav (edge silence trimmed). Returns seconds."""
    if not Path(PIPER).is_file():
        raise MediaError(f"piper binary missing: {PIPER}")
    voice = Path(VOICE_DIR) / VOICES[lang]
    if not voice.is_file():
        raise MediaError(f"piper voice missing: {voice}")
    raw = out_wav.with_suffix(".raw.wav")
    run([PIPER, "-m", str(voice), "-f", str(raw), "--length_scale", str(length_scale)], stdin=text)
    run(
        [
            FFMPEG, "-y", "-v", "error", "-i", str(raw),
            "-af", "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
            "silenceremove=start_periods=1:start_threshold=-50dB,areverse,highpass=f=70",
            "-ar", "48000", "-ac", "2", str(out_wav),
        ]
    )
    raw.unlink(missing_ok=True)
    return duration(out_wav)


def concat_with_gaps(*, parts: list[Path], gap_s: float, lead_s: float, out_wav: Path) -> list[float]:
    """Concatenate sentence wavs with fixed gaps; return each part's start (s)."""
    work = out_wav.parent
    sil = work / "_gap.wav"
    lead = work / "_lead.wav"
    run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{gap_s:.3f}", str(sil)])
    run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{lead_s:.3f}", str(lead)])
    starts: list[float] = []
    seq: list[Path] = [lead]
    t = duration(lead)
    for i, p in enumerate(parts):
        starts.append(t)
        seq.append(p)
        t += duration(p)
        if i < len(parts) - 1:
            seq.append(sil)
            t += duration(sil)
    lst = work / "_concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in seq))
    run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "pcm_s16le", str(out_wav)])
    return starts
