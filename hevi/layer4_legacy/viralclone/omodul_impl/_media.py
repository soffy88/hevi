"""Media side-effects for ViralClone (internal omodul helpers): ffmpeg, Whisper, Piper TTS. CPU only."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

FFMPEG = os.environ.get("HEVI_FFMPEG") or shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
FFPROBE = os.environ.get("HEVI_FFPROBE") or shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"
PIPER = os.environ.get("HEVI_TALKCRAFT_PIPER", "/data/soffy/projects/hevi-zero/.venv/bin/piper")
VOICE_DIR = os.environ.get("HEVI_TALKCRAFT_VOICES", "/data/soffy/projects/hevi-zero/voices")
VOICES = {"zh": "zh_CN-huayan-medium.onnx", "en": "en_US-ryan-medium.onnx"}
WHISPER_MODEL = os.environ.get("HEVI_WHISPER_MODEL", "/home/soffy/models/faster-whisper-large-v3-turbo")


def _sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _probe_video(path: str | Path) -> dict[str, Any]:
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    out = subprocess.check_output(cmd, text=True)
    payload = json.loads(out)
    v_stream = next((s for s in payload.get("streams", []) if s.get("codec_type") == "video"), {})
    a_stream = next((s for s in payload.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = payload.get("format", {})

    fps = 25.0
    r_fps = v_stream.get("r_frame_rate", "25/1")
    if "/" in r_fps:
        num, den = r_fps.split("/")
        fps = float(num) / max(1.0, float(den))
    elif r_fps:
        fps = float(r_fps)

    return {
        "width": int(v_stream.get("width") or 0),
        "height": int(v_stream.get("height") or 0),
        "fps": round(fps, 2),
        "duration_s": float(fmt.get("duration") or 0.0),
        "has_audio": bool(a_stream),
        "video_codec": str(v_stream.get("codec_name") or ""),
        "audio_codec": str(a_stream.get("codec_name") or ""),
        "size_bytes": int(fmt.get("size") or 0),
    }


def _detect_silences(path: str | Path, *, noise_db: int = -30, min_dur_s: float = 0.3) -> list[dict[str, float]]:
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_dur_s}",
        "-f",
        "null",
        "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    silences: list[dict[str, float]] = []
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", r.stderr)]
    ends_durs = re.findall(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)", r.stderr)

    for start, (end_s, dur_s) in zip(starts, ends_durs, strict=False):
        silences.append(
            {
                "start_s": round(start, 3),
                "end_s": round(float(end_s), 3),
                "duration_s": round(float(dur_s), 3),
            }
        )
    return silences


def _extract_frames(path: str | Path, out_dir: str | Path, *, fps: float = 1.0, max_frames: int = 30) -> list[Path]:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    pattern = str(d / "frame_%04d.jpg")
    cmd = [
        FFMPEG,
        "-y",
        "-v",
        "error",
        "-i",
        str(path),
        "-vf",
        f"fps={fps}",
        "-vframes",
        str(max_frames),
        "-q:v",
        "3",
        pattern,
    ]
    subprocess.run(cmd, check=True)
    return sorted(d.glob("frame_*.jpg"))


def _transcribe_audio_with_whisper(
    media_path: str | Path,
    *,
    model_dir: str | Path = WHISPER_MODEL,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Transcribe audio returning (words, sentences) with precise timestamps."""
    import faster_whisper

    model = faster_whisper.WhisperModel(str(model_dir), device="cpu", compute_type="int8")
    segments_gen, _ = model.transcribe(str(media_path), word_timestamps=True)

    words_out: list[dict[str, Any]] = []
    sentences_out: list[dict[str, Any]] = []

    for s_idx, seg in enumerate(segments_gen):
        text = seg.text.strip()
        sentences_out.append(
            {
                "index": s_idx,
                "text": text,
                "start_s": round(seg.start, 3),
                "end_s": round(seg.end, 3),
            }
        )
        if seg.words:
            for w in seg.words:
                clean_w = w.word.strip()
                if clean_w:
                    words_out.append(
                        {
                            "word": clean_w,
                            "start_s": round(w.start, 3),
                            "end_s": round(w.end, 3),
                            "score": round(float(w.probability), 3),
                        }
                    )

    return words_out, sentences_out


def _tts_piper_sentence(text: str, out_wav: Path, *, lang: str = "zh", speed: float = 1.0) -> float:
    """Render single text line with Piper TTS."""
    voice_file = Path(VOICE_DIR) / VOICES.get(lang, VOICES["zh"])
    if not voice_file.is_file():
        raise FileNotFoundError(f"Missing Piper voice model: {voice_file}")

    raw_wav = out_wav.with_suffix(".raw.wav")
    length_scale = round(1.0 / max(0.2, speed), 2)
    cmd_piper = [
        PIPER,
        "-m",
        str(voice_file),
        "-f",
        str(raw_wav),
        "--length_scale",
        str(length_scale),
    ]
    p = subprocess.run(cmd_piper, input=text, text=True, capture_output=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"Piper TTS failed: {p.stderr[-400:]}")

    # Normalize audio
    cmd_norm = [
        FFMPEG,
        "-y",
        "-v",
        "error",
        "-i",
        str(raw_wav),
        "-af",
        "highpass=f=70,loudnorm=I=-16:TP=-1.5",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(out_wav),
    ]
    subprocess.run(cmd_norm, check=True)
    raw_wav.unlink(missing_ok=True)

    probe = _probe_video(out_wav)
    return probe["duration_s"]


def _synthesize_voiceover_script(
    sentences: list[str],
    work_dir: Path,
    *,
    lang: str = "zh",
    gap_s: float = 0.25,
) -> tuple[Path, list[dict[str, Any]]]:
    """Synthesize full script with Piper; return (full_wav, sentence_cues)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    cues: list[dict[str, Any]] = []
    wav_parts: list[Path] = []
    cursor = 0.0

    sil_gap = work_dir / "sil_gap.wav"
    cmd_sil = [
        FFMPEG,
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        f"{gap_s:.3f}",
        str(sil_gap),
    ]
    subprocess.run(cmd_sil, check=True)

    for idx, sent in enumerate(sentences):
        clean = sent.strip()
        if not clean:
            continue
        p = work_dir / f"sent_{idx:03d}.wav"
        dur = _tts_piper_sentence(clean, p, lang=lang)
        cues.append(
            {
                "index": idx,
                "text": clean,
                "start_s": round(cursor, 3),
                "end_s": round(cursor + dur, 3),
            }
        )
        wav_parts.append(p)
        cursor += dur
        if idx < len(sentences) - 1:
            wav_parts.append(sil_gap)
            cursor += gap_s

    # Concat
    concat_list = work_dir / "concat_audio.txt"
    concat_list.write_text("".join(f"file '{f.resolve()}'\n" for f in wav_parts), encoding="utf-8")
    out_wav = work_dir / "full_narration.wav"
    cmd_cat = [
        FFMPEG,
        "-y",
        "-v",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd_cat, check=True)
    return out_wav, cues


def _build_vf(
    width: int,
    height: int,
    fps: int,
    dur: float,
    *,
    color_grade: str = "",
    transition: str = "",
) -> str:
    """Compose the per-clip ffmpeg filter chain (fit + optional grade/transition)."""
    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        f"fps={fps}",
        "setsar=1",
    ]
    grade = {
        "warm": "colorbalance=rs=0.12:gs=0.02:bs=-0.12,eq=saturation=1.15:contrast=1.05",
        "cool": "colorbalance=rs=-0.12:gs=0.0:bs=0.12,eq=saturation=1.15:contrast=1.05",
        "vivid": "eq=saturation=1.35:contrast=1.12",
        "mono": "hue=s=0,eq=contrast=1.1",
    }.get(color_grade, "")
    if grade:
        filters.append(grade)
    if transition == "fade":
        filters.append("fade=t=in:st=0:d=0.3")
    elif transition == "fade_slow":
        filters.append("fade=t=in:st=0:d=0.6")
    elif transition == "dip":
        out_st = max(0.0, dur - 0.25)
        filters.append("fade=t=in:st=0:d=0.25")
        filters.append(f"fade=t=out:st={out_st:.3f}:d=0.25")
    return ",".join(filters)


def _render_video_clips_concat(
    clips: list[dict[str, Any]] | None = None,
    total_duration_s: float = 0.0,
    width: int = 720,
    height: int = 1280,
    output_mp4: Path = Path("out.mp4"),
    *,
    fps: int = 25,
    cuts: list[dict[str, Any]] | None = None,
    color_grade: str = "",
    transition: str = "",
) -> Path:
    """Render cut sequence into visual video stream scaled and padded to target dimensions.

    Short sources (e.g. a 2.5s product card used for a longer narration beat) are
    looped so the visual track always fills the audio duration.
    """
    clips = clips or cuts or []
    work = output_mp4.parent / "cuts_tmp"
    work.mkdir(parents=True, exist_ok=True)
    rendered_parts: list[Path] = []

    for idx, c in enumerate(clips):
        src = Path(c["source"])
        dur = max(0.5, float(c["duration_s"]))
        target_clip = work / f"part_{idx:03d}.mp4"
        vf = _build_vf(width, height, fps, dur, color_grade=color_grade, transition=transition)

        if src.suffix.lower() in (".jpg", ".jpeg", ".png"):
            # Image input: loop for dur
            cmd = [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-loop",
                "1",
                "-i",
                str(src),
                "-t",
                f"{dur:.3f}",
                "-vf",
                vf,
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                str(target_clip),
            ]
        elif src.is_file():
            # Video input: loop the source so short clips still fill ``dur``.
            cmd = [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-stream_loop",
                "-1",
                "-ss",
                f"{c.get('source_in_s', 0.0):.3f}",
                "-i",
                str(src),
                "-t",
                f"{dur:.3f}",
                "-vf",
                vf,
                "-an",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                str(target_clip),
            ]
        else:
            # Fallback color background
            cmd = [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x181824:s={width}x{height}:r={fps}",
                "-t",
                f"{dur:.3f}",
                "-vf",
                vf,
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                str(target_clip),
            ]

        subprocess.run(cmd, check=True)
        rendered_parts.append(target_clip)

    cat_txt = work / "cat_video.txt"
    cat_txt.write_text("".join(f"file '{p.resolve()}'\n" for p in rendered_parts), encoding="utf-8")
    cmd_cat = [
        FFMPEG,
        "-y",
        "-v",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(cat_txt),
        "-c",
        "copy",
        str(output_mp4),
    ]
    subprocess.run(cmd_cat, check=True)
    return output_mp4


def _mux_final_video_with_subtitles(
    video_path: Path,
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
    *,
    metadata_comment: str = "",
) -> Path:
    """Burn in ASS subtitles, mux audio, inject AIGC metadata, and finish output."""
    cmd = [
        FFMPEG,
        "-y",
        "-v",
        "error",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-vf",
        f"subtitles={ass_path.resolve()}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
    ]
    if metadata_comment:
        cmd.extend(
            [
                "-metadata",
                f"comment={metadata_comment}",
                "-metadata",
                f"AIGC={metadata_comment}",
                "-metadata",
                f"description={metadata_comment}",
                "-movflags",
                "+use_metadata_tags",
            ]
        )
    cmd.append(str(output_path))
    subprocess.run(cmd, check=True)
    return output_path
