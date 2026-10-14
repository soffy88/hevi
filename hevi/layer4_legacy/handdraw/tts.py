"""Hevi Handdraw Line: TTS and narration master alignment.

Uses CosyVoice (127.0.0.1:17600) with local piper CPU fallback.
Generates a locked continuous 48kHz master WAV and exact beat/cue timestamps
conforming to the continuous_narration contract. Zero paid APIs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import urllib.request
import wave
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

COSYVOICE_URL = os.environ.get("COSYVOICE_URL", "http://127.0.0.1:17600/api/ai/cosyvoice")
PIPER_BIN = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
PIPER_MODEL = "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx"
FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"
SAMPLE_RATE = 48000


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _synth_cosyvoice(text: str, out_wav: Path, timeout: float = 20.0) -> bool:
    """Attempt CosyVoice synthesis with a modest timeout."""
    payload = {
        "script": [{"text": text, "voice_ref": "builtin:zh_default"}],
        "config": {},
    }
    try:
        req = urllib.request.Request(
            COSYVOICE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if len(data) > 1024:
                out_wav.write_bytes(data)
                return True
    except Exception as exc:
        logger.info("CosyVoice unavailable or timed out (%s), falling back to piper", exc)
    return False


def _synth_piper(text: str, out_wav: Path, speed: float = 1.05) -> None:
    """Synthesise text with local CPU piper."""
    raw = out_wav.with_suffix(".raw.wav")
    proc = subprocess.run(
        [
            PIPER_BIN,
            "-m",
            PIPER_MODEL,
            "-f",
            str(raw),
            "--length_scale",
            str(1.0 / speed),
            "--sentence_silence",
            "0.25",
        ],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr[-400:]}")

    # Standardize to 48kHz mono 16-bit
    cmd = [
        FFMPEG,
        "-y",
        "-v",
        "error",
        "-i",
        str(raw),
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True)
    raw.unlink(missing_ok=True)


def read_wav_samples(path: Path) -> np.ndarray:
    """Read mono int16 PCM samples from a WAV file."""
    with wave.open(str(path), "rb") as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")


def synth_line(text: str, out_wav: Path, *, prefer_cosy: bool = True) -> float:
    """Synthesise one line; returns duration in seconds measured from PCM samples."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    success = False
    if prefer_cosy:
        success = _synth_cosyvoice(text, out_wav)
    if not success:
        _synth_piper(text, out_wav)

    # Normalize to 48kHz mono 16-bit PCM if not already
    normalized = out_wav.with_name(out_wav.stem + "_norm.wav")
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-i",
            str(out_wav),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-af",
            "apad=pad_dur=0.25",
            str(normalized),
        ],
        check=True,
    )
    normalized.replace(out_wav)

    # Duration from the actual PCM sample count: the alignment and the
    # compiled master must agree exactly, so never trust container metadata.
    samples = read_wav_samples(out_wav)
    return len(samples) / SAMPLE_RATE


def split_text_into_cues(text: str, max_chars: int = 15) -> list[str]:
    """Split a sentence into readable chunks without breaking mid-word."""
    if len(text) <= max_chars:
        return [text]

    # Split on natural Chinese punctuation first
    clauses = re.split(r"([，、；：,;:])", text)
    rebuilt = []
    buf = ""
    for token in clauses:
        if token in "，、；：,;:":
            buf += token
            rebuilt.append(buf)
            buf = ""
        else:
            if buf:
                rebuilt.append(buf)
            buf = token
    if buf:
        rebuilt.append(buf)

    cues = []
    current = ""
    for clause in rebuilt:
        if len(current) + len(clause) <= max_chars:
            current += clause
        else:
            if current:
                cues.append(current)
            current = clause
    if current:
        cues.append(current)

    # Ensure complete characters preserved
    if "".join(cues) != text:
        # Fallback to character chunks if punctuation split failed
        cues = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    return cues


def build_narration_master(
    beats: list[dict[str, Any]],
    output_dir: Path,
    *,
    pause_gap: float = 0.22,
    prefer_cosy: bool = True,
) -> tuple[Path, Path, float]:
    """Synthesises all beats, concatenates into a locked master WAV, and outputs alignment.json.

    Returns: (master_wav_path, alignment_json_path, total_duration)
    """
    output_dir = output_dir.resolve()
    temp_audio_dir = output_dir / "temp_audio"
    temp_audio_dir.mkdir(parents=True, exist_ok=True)

    beat_wavs = []
    beat_samples_list = []
    beat_durations = []
    for i, beat in enumerate(beats):
        b_id = beat.get("id", f"b{i:02d}")
        wpath = temp_audio_dir / f"{b_id}.wav"
        synth_line(beat["text"], wpath, prefer_cosy=prefer_cosy)
        # Read the exact PCM we will concatenate so timestamps cannot drift.
        samples = read_wav_samples(wpath)
        beat_wavs.append(wpath)
        beat_samples_list.append(samples)
        beat_durations.append(len(samples) / SAMPLE_RATE)

    # Build continuous waveform with exact pause gaps
    pcm_pieces = []
    gap_samples = np.zeros(round(pause_gap * SAMPLE_RATE), dtype=np.int16)

    aligned_beats = []
    cursor = 0.0

    for i, (beat, wpath, dur) in enumerate(zip(beats, beat_wavs, beat_durations)):
        b_id = beat.get("id", f"b{i:02d}")
        samples = beat_samples_list[i]
        pcm_pieces.append(samples)

        b_start = cursor
        b_end = cursor + dur

        # Calculate caption cues (relative to beat start)
        cue_texts = split_text_into_cues(beat["text"])
        caption_cues = []
        total_len = max(1, len(beat["text"]))
        cue_cursor = 0.0
        for ctxt in cue_texts:
            c_fraction = len(ctxt) / total_len
            c_dur = dur * c_fraction
            caption_cues.append({
                "text": ctxt,
                "start": round(cue_cursor, 4),
                "end": round(min(dur, cue_cursor + c_dur), 4),
            })
            cue_cursor += c_dur
        # Clamp last cue to exactly beat duration
        if caption_cues:
            caption_cues[-1]["end"] = round(dur, 4)

        aligned_beats.append({
            "id": b_id,
            "text": beat["text"],
            "start": round(b_start, 4),
            "end": round(b_end, 4),
            "caption_cues": caption_cues,
        })

        cursor = b_end
        if i < len(beats) - 1:
            pcm_pieces.append(gap_samples)
            cursor += pause_gap

    master_pcm = np.concatenate(pcm_pieces)
    master_wav = output_dir / "master.wav"
    with wave.open(str(master_wav), "wb") as wf:
        wf.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        wf.writeframes(master_pcm.tobytes())

    total_duration = len(master_pcm) / SAMPLE_RATE

    full_script_text = "".join(b["text"] for b in beats)
    alignment_data = {
        "version": 1,
        "source_sha256": sha256_file(master_wav),
        "script_sha256": hashlib.sha256(full_script_text.encode("utf-8")).hexdigest(),
        "total_duration": total_duration,
        "beats": aligned_beats,
    }

    alignment_json = output_dir / "alignment.json"
    alignment_json.write_text(json.dumps(alignment_data, ensure_ascii=False, indent=2))

    return master_wav, alignment_json, total_duration
