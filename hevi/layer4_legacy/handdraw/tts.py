"""Hevi Handdraw Line: TTS, narration master and ASR-forced caption alignment.

Engine policy (F2):
  * The whole script is synthesised by **one** engine.  CosyVoice is requested
    in a single batched call (``timeout >= 300s``); if that call fails the whole
    narration falls back to local CPU piper.  Engines are never mixed inside one
    film, and the engine actually used per beat is written into ``alignment.json``.
  * piper is pinned to ``--noise-scale 0 --noise-w-scale 0`` so the same script
    yields a byte-identical master (F3 reproducibility).

Timing policy (F1):
  * Beat and cue ranges are computed from **integer sample counts**, never by
    rounding seconds up, so a range can never exceed the master length.
  * Caption cue boundaries come from local CPU ASR word timestamps (F5); if ASR
    is unavailable the fallback is recorded honestly as ``proportional``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import urllib.request
import wave
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

COSYVOICE_URL = os.environ.get("COSYVOICE_URL", "http://127.0.0.1:17600/api/ai/cosyvoice")
COSY_TIMEOUT = float(os.environ.get("HANDDRAW_COSY_TIMEOUT", "360"))
PIPER_BIN = os.environ.get("HANDDRAW_PIPER_BIN", "/data/soffy/projects/hevi-zero/.venv/bin/piper")
PIPER_MODEL = os.environ.get(
    "HANDDRAW_PIPER_MODEL", "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx"
)
FFMPEG = os.environ.get("HANDDRAW_FFMPEG", shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg")
SAMPLE_RATE = 48000
CUE_MAX_CHARS = 12
CUE_TARGET_CHARS = 10
# KIDS_ANIME_DIRECTION: narration pace must stay at or below 3.5 characters/second.
MAX_CHARS_PER_SECOND = 3.5
DEFAULT_LENGTH_SCALE = 3.0


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


def _synth_cosyvoice_batch(texts: list[str], out_dir: Path) -> list[Path] | None:
    """One batched CosyVoice request for the whole script.

    Returns the written wav paths, or ``None`` when the engine is unreachable /
    errored.  A single request means the model is loaded once instead of once
    per sentence (the R1 bug: per-sentence 20s timeouts against a cold worker).
    """
    payload = {
        "script": [{"text": text, "voice_ref": "builtin:zh_default"} for text in texts],
        "config": {},
    }
    try:
        req = urllib.request.Request(
            COSYVOICE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=COSY_TIMEOUT) as resp:
            body = resp.read()
    except Exception as exc:
        logger.info("CosyVoice batch request failed (%s); narration will use piper", exc)
        return None
    if len(body) < 1024:
        logger.info("CosyVoice returned a suspiciously small body (%d bytes)", len(body))
        return None
    # The engine may answer with a single concatenated wav or a zip/tar archive.
    blob = out_dir / "_cosy_blob.bin"
    blob.write_bytes(body)
    try:
        if body[:4] == b"RIFF":
            # A single concatenated WAV is not a per-beat response. Do not reuse
            # the entire film narration for every beat; that duplicates speech and
            # invalidates the cue timings. Use the consistent Piper engine unless
            # the endpoint returns one WAV per beat or a structured ZIP.
            if len(texts) != 1:
                logger.warning(
                    "CosyVoice returned one concatenated WAV for %d beats; "
                    "cannot prove beat boundaries, switching the whole script to Piper",
                    len(texts),
                )
                return None
            single = out_dir / "_cosy_single.wav"
            single.write_bytes(body)
            return [single]
        if body[:2] == b"PK":
            import zipfile

            with zipfile.ZipFile(blob) as archive:
                members = sorted(n for n in archive.namelist() if n.lower().endswith(".wav"))
                if not members:
                    return None
                paths = []
                for index, name in enumerate(members):
                    target = out_dir / f"_cosy_{index:04d}.wav"
                    target.write_bytes(archive.read(name))
                    paths.append(target)
                return paths if len(paths) == len(texts) else None
        logger.info("CosyVoice response format not understood; using piper")
        return None
    except Exception as exc:
        logger.info("CosyVoice response could not be unpacked (%s); using piper", exc)
        return None
    finally:
        blob.unlink(missing_ok=True)


def _synth_piper(text: str, out_wav: Path, length_scale: float = DEFAULT_LENGTH_SCALE) -> None:
    """Deterministic local CPU piper (noise disabled -> byte-stable output)."""
    raw = out_wav.with_suffix(".raw.wav")
    proc = subprocess.run(
        [
            PIPER_BIN,
            "-m",
            PIPER_MODEL,
            "-f",
            str(raw),
            "--length_scale",
            str(length_scale),
            "--noise-scale",
            "0.0",
            "--noise-w-scale",
            "0.0",
            "--sentence_silence",
            "0.25",
        ],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not raw.is_file() or raw.stat().st_size == 0:
        raise RuntimeError(f"piper failed: {(proc.stderr or '')[-400:]}")
    _to_master_format(raw, out_wav, pad=True)
    raw.unlink(missing_ok=True)


def _to_master_format(src: Path, dst: Path, *, pad: bool) -> None:
    """Normalise any audio to 48kHz mono s16le; optionally pad a short tail."""
    cmd = [
        FFMPEG,
        "-y",
        "-v",
        "error",
        "-i",
        str(src),
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
    ]
    if pad:
        cmd += ["-af", "apad=pad_dur=0.25"]
    cmd.append(str(dst))
    subprocess.run(cmd, check=True)


def read_wav_samples(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")


def _cache_key(text: str, engine: str, length_scale: float) -> str:
    return hashlib.sha256(f"{engine}\x00{length_scale:.4f}\x00{text}".encode()).hexdigest()[:24]


def _synth_with_cache(
    text: str,
    out_wav: Path,
    cache_dir: Path,
    *,
    engine: str,
    length_scale: float,
    cosy_wav: Path | None,
) -> None:
    """Synthesise one beat, reusing a content-addressed cache when possible."""
    key = _cache_key(text, engine, length_scale)
    cached = cache_dir / f"{key}.wav"
    if cached.is_file() and cached.stat().st_size > 44:
        shutil.copyfile(cached, out_wav)
        return
    if engine == "cosyvoice" and cosy_wav is not None and cosy_wav.is_file():
        _to_master_format(cosy_wav, out_wav, pad=True)
    else:
        _synth_piper(text, out_wav, length_scale=length_scale)
    cached.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_wav, cached)


# ---------------------------------------------------------------------------
# Caption cues
# ---------------------------------------------------------------------------


def _is_punctuation(char: str) -> bool:
    return bool(char) and char in "，。！？；：、,.!?;:…—·「」『』（）()《》<>\"'“”‘’ "


def _align_chars_to_words(text: str, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map every character of ``text`` onto an ASR word timestamp.

    Whisper output for Chinese is roughly one token per character but may differ
    (traditional forms, dropped particles).  ``difflib`` matches what it can and
    unmatched characters are interpolated between their neighbours, so the
    returned timings are monotonic and cover the whole original text.
    """
    import difflib

    asr_chars: list[str] = []
    asr_times: list[tuple[float, float]] = []
    for word in words:
        for char in str(word["text"]):
            if char.strip():
                asr_chars.append(char)
                asr_times.append((float(word["start"]), float(word["end"])))

    chars = list(text)
    result: list[dict[str, Any] | None] = [None] * len(chars)

    if not asr_chars:
        return []

    matcher = difflib.SequenceMatcher(a=chars, b=asr_chars, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                result[i1 + offset] = {
                    "char": chars[i1 + offset],
                    "start": asr_times[j1 + offset][0],
                    "end": asr_times[j1 + offset][1],
                }
        elif tag in ("replace", "delete"):
            # Spread the matched window's time span across the unmatched chars.
            span_start = asr_times[j1][0] if j1 < len(asr_times) else (
                asr_times[j1 - 1][1] if j1 > 0 else 0.0
            )
            span_end = asr_times[j2 - 1][1] if j2 > j1 else span_start
            count = max(1, i2 - i1)
            step = (span_end - span_start) / count
            for offset in range(i2 - i1):
                result[i1 + offset] = {
                    "char": chars[i1 + offset],
                    "start": span_start + offset * step,
                    "end": span_start + (offset + 1) * step,
                }
    # Fill any remaining holes (pure inserts leave originals untouched, but be safe).
    last_end = 0.0
    for index, item in enumerate(result):
        if item is None:
            nxt = next((r for r in result[index:] if r is not None), None)
            end = nxt["start"] if nxt else last_end
            result[index] = {"char": chars[index], "start": last_end, "end": max(last_end, end)}
        last_end = max(last_end, result[index]["end"])  # type: ignore[index]
    return [r for r in result if r is not None]  # type: ignore[misc]


def _group_chars_into_cues(char_times: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """Greedy word-boundary grouping, never leaving punctuation alone."""
    if not char_times:
        return []
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for item in char_times:
        char = item["char"]
        if current and len(current) >= max_chars and not _is_punctuation(char):
            groups.append(current)
            current = []
        current.append(item)
        # Prefer to break right after sentence punctuation once the cue is long enough.
        if char in "。！？!?" and len(current) >= max(6, max_chars // 2):
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    # Pull orphan punctuation groups back into the previous cue.
    merged: list[list[dict[str, Any]]] = []
    for group in groups:
        if merged and all(_is_punctuation(item["char"]) for item in group):
            merged[-1].extend(group)
        else:
            merged.append(group)
    # An over-long tail (punctuation push) is split again on character boundaries.
    final: list[list[dict[str, Any]]] = []
    for group in merged:
        while len(group) > max_chars + 2:
            final.append(group[:max_chars])
            group = group[max_chars:]
        if group:
            final.append(group)
    return [
        {
            "text": "".join(item["char"] for item in group),
            "start": group[0]["start"],
            "end": group[-1]["end"],
        }
        for group in final
    ]


def split_text_into_cues(text: str, max_chars: int = CUE_MAX_CHARS) -> list[str]:
    """Fallback text-only splitter (no timing) that never orphans punctuation."""
    if len(text) <= max_chars:
        return [text] if text else []
    cues: list[str] = []
    current = ""
    for char in text:
        if current and len(current) >= max_chars and not _is_punctuation(char):
            cues.append(current)
            current = ""
        current += char
        if char in "。！？!?" and len(current) >= max(6, max_chars // 2):
            cues.append(current)
            current = ""
    if current:
        if cues and all(_is_punctuation(c) for c in current):
            cues[-1] += current
        else:
            cues.append(current)
    return cues


def _proportional_cues(text: str, duration: float) -> list[dict[str, Any]]:
    texts = split_text_into_cues(text)
    total = max(1, len(text))
    cues = []
    cursor = 0.0
    for ctxt in texts:
        span = duration * len(ctxt) / total
        cues.append({"text": ctxt, "start": cursor, "end": cursor + span})
        cursor += span
    if cues:
        cues[-1]["end"] = duration
    return cues


def build_caption_cues(
    text: str,
    duration: float,
    words: list[dict[str, Any]] | None,
    *,
    max_chars: int = CUE_MAX_CHARS,
) -> tuple[list[dict[str, Any]], str]:
    """Return (cues relative to the beat start, method)."""
    method = "proportional"
    cues: list[dict[str, Any]] = []
    if words:
        char_times = _align_chars_to_words(text, words)
        if char_times:
            cues = _group_chars_into_cues(char_times, max_chars)
            method = "asr"
    if not cues:
        cues = _proportional_cues(text, duration)
        method = "proportional"
    # Clamp into the measured beat and guarantee strict ordering.
    clamped = []
    previous = 0.0
    for index, cue in enumerate(cues):
        start = min(max(0.0, float(cue["start"])), duration)
        end = min(max(start, float(cue["end"])), duration)
        if index == len(cues) - 1:
            end = duration
        if end <= start:
            end = min(duration, start + 1e-3)
        start = max(start, previous)
        if end <= start:
            end = start + 1e-3
        clamped.append({"text": cue["text"], "start": start, "end": end})
        previous = end
    return clamped, method


# ---------------------------------------------------------------------------
# Master assembly
# ---------------------------------------------------------------------------


def _resolve_engine(prefer_cosy: bool, beats: list[dict[str, Any]], scratch: Path) -> tuple[str, list[Path] | None]:
    if not prefer_cosy:
        return "piper", None
    cosy = _synth_cosyvoice_batch([b["text"] for b in beats], scratch)
    if cosy:
        return "cosyvoice", cosy
    return "piper", None


def build_narration_master(
    beats: list[dict[str, Any]],
    output_dir: Path,
    *,
    pause_gap: float = 0.22,
    prefer_cosy: bool = True,
    length_scale: float = DEFAULT_LENGTH_SCALE,
    use_asr: bool = True,
) -> tuple[Path, Path, float]:
    """Synthesise all beats, concatenate a locked master, emit alignment.json.

    Returns ``(master_wav, alignment_json, total_duration)``.
    """
    output_dir = Path(output_dir).resolve()
    scratch = output_dir / "_synth"
    scratch.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / "_synth_cache"

    engine, cosy_wavs = _resolve_engine(prefer_cosy, beats, scratch)

    beat_samples: list[np.ndarray] = []
    for index, beat in enumerate(beats):
        wav = scratch / f"{index:04d}.wav"
        cosy_wav = None
        if cosy_wavs:
            cosy_wav = cosy_wavs[0] if len(cosy_wavs) == 1 else cosy_wavs[index]
        _synth_with_cache(
            beat["text"], wav, cache_dir, engine=engine, length_scale=length_scale, cosy_wav=cosy_wav
        )
        beat_samples.append(read_wav_samples(wav))

    # ASR is run on each beat wav: word timings are then relative to that beat,
    # which is exactly what the cue builder needs.
    asr_words: list[list[dict[str, Any]] | None] = [None] * len(beats)
    asr_used = False
    if use_asr:
        try:
            from hevi.layer4_legacy.handdraw.asr import transcribe_words

            for index in range(len(beats)):
                asr_words[index] = transcribe_words(scratch / f"{index:04d}.wav")
            asr_used = any(words for words in asr_words)
        except Exception as exc:
            logger.info("ASR alignment unavailable, using proportional cues: %s", exc)
            asr_words = [None] * len(beats)

    gap = np.zeros(round(pause_gap * SAMPLE_RATE), dtype=np.int16)
    pieces: list[np.ndarray] = []
    aligned_beats: list[dict[str, Any]] = []
    cursor_samples = 0

    for index, beat in enumerate(beats):
        samples = beat_samples[index]
        start_samples = cursor_samples
        end_samples = cursor_samples + len(samples)
        duration = len(samples) / SAMPLE_RATE
        cues, method = build_caption_cues(
            beat["text"], duration, asr_words[index] if asr_used else None
        )
        aligned_beats.append(
            {
                "id": beat.get("id", f"b{index:02d}"),
                "text": beat["text"],
                "start": start_samples / SAMPLE_RATE,
                "end": end_samples / SAMPLE_RATE,
                "start_samples": start_samples,
                "end_samples": end_samples,
                "engine": engine,
                "caption_method": method,
                "caption_cues": cues,
            }
        )
        pieces.append(samples)
        cursor_samples = end_samples
        if index < len(beats) - 1:
            pieces.append(gap)
            cursor_samples += len(gap)

    master_pcm = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.int16)
    master_wav = output_dir / "master.wav"
    with wave.open(str(master_wav), "wb") as wf:
        wf.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        wf.writeframes(master_pcm.tobytes())

    total_duration = len(master_pcm) / SAMPLE_RATE
    engines = sorted({b["engine"] for b in aligned_beats})
    methods = sorted({b["caption_method"] for b in aligned_beats})
    full_script_text = "".join(b["text"] for b in beats)
    total_chars = sum(len(b["text"]) for b in beats)
    # Spoken pace excludes the inter-beat pauses: it is the honest measure the
    # kids gate checks ("旁白语速 ≤ 3.5 字/秒").
    spoken_samples = sum(int(b["end_samples"]) - int(b["start_samples"]) for b in aligned_beats)
    spoken_seconds = spoken_samples / SAMPLE_RATE
    characters_per_second = (total_chars / spoken_seconds) if spoken_seconds else 0.0
    alignment_data = {
        "version": 1,
        "source_sha256": sha256_file(master_wav),
        "script_sha256": hashlib.sha256(full_script_text.encode("utf-8")).hexdigest(),
        "total_duration": total_duration,
        "total_samples": len(master_pcm),
        "sample_rate": SAMPLE_RATE,
        "engine": engines[0] if len(engines) == 1 else "mixed",
        "engines_used": engines,
        "caption_method": methods[0] if len(methods) == 1 else "mixed",
        "caption_methods_used": methods,
        "cosyvoice_available": engine == "cosyvoice",
        "length_scale": length_scale,
        "characters_per_second": characters_per_second,
        "beats": aligned_beats,
    }
    alignment_json = output_dir / "alignment.json"
    alignment_json.write_text(json.dumps(alignment_data, ensure_ascii=False, indent=2))

    # Preserve intermediates as forensic evidence; all scratch files stay inside
    # the selected job directory and are not cleaned as part of production.
    return master_wav, alignment_json, total_duration
