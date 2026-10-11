"""TTS synthesis and Whisper ASR alignment for whiteboard (omodul layer)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel

PIPER = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
VOICE = "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx"
WHISPER_PATH = "/home/soffy/models/faster-whisper-large-v3-turbo"
FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"


def norm_text(s: str) -> str:
    return "".join(c for c in s if c.isalnum())


def align_words_to_segments(segments: list[str], words: list[dict], duration: float) -> list[float]:
    """Map segment start character offsets to speech timestamps."""
    char_times: list[float] = []
    for w in words:
        w_norm = norm_text(str(w.get("w", "")))
        w_len = len(w_norm)
        if w_len == 0:
            continue
        w_s = float(w.get("s", 0.0))
        w_e = float(w.get("e", w_s))
        span = max(w_e - w_s, 0.01)
        for i in range(w_len):
            char_times.append(round(w_s + span * (i / w_len), 3))

    seg_starts: list[float] = [0.0]
    curr_char_idx = 0
    for seg in segments[:-1]:
        curr_char_idx += len(norm_text(seg))
        if curr_char_idx < len(char_times):
            seg_starts.append(char_times[curr_char_idx])
        elif char_times:
            seg_starts.append(char_times[-1])
        else:
            seg_starts.append(0.0)

    # Ensure monotonic non-decreasing
    for k in range(1, len(seg_starts)):
        if seg_starts[k] < seg_starts[k - 1]:
            seg_starts[k] = seg_starts[k - 1]

    return seg_starts


def tts_and_align(
    *,
    project_dir: Path,
    audio_dir: Path,
    speed: float = 1.2,
) -> None:
    """Run local Piper TTS and Whisper ASR to generate word-aligned timings."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    script_path = project_dir / "scenes" / "script.json"
    if not script_path.exists():
        subprocess.run(["node", str(project_dir / "scenes.js")], cwd=project_dir, check=True)

    with open(script_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)

    model = WhisperModel(WHISPER_PATH, device="cpu", compute_type="int8")

    for sc in scenes:
        scene_name = sc["name"]
        full_text = "".join(sc["segments"])
        wav_path = audio_dir / f"{scene_name}.wav"
        raw_path = audio_dir / f"{scene_name}.raw.wav"
        json_path = audio_dir / f"{scene_name}.json"

        # Check if already synthesized
        if not wav_path.exists():
            # Local Piper TTS
            r = subprocess.run(
                [
                    PIPER,
                    "-m", VOICE,
                    "-f", str(raw_path),
                    "--length_scale", str(1.0 / speed),
                    "--sentence_silence", "0.25",
                ],
                input=full_text,
                text=True,
                stderr=subprocess.PIPE,
            )
            if r.returncode:
                raise RuntimeError(f"Piper TTS synthesis failed: {r.stderr}")

            # Resample to 48kHz stereo PCM WAV
            subprocess.run(
                [
                    FFMPEG,
                    "-y",
                    "-loglevel", "error",
                    "-i", str(raw_path),
                    "-ar", "48000",
                    "-ac", "2",
                    str(wav_path),
                ],
                check=True,
            )
            if raw_path.exists():
                raw_path.unlink()

        # Whisper ASR transcription for word-level timestamps
        segments, _ = model.transcribe(str(wav_path), word_timestamps=True, language="zh")
        words: list[dict] = []
        for segment in segments:
            if segment.words:
                for word in segment.words:
                    words.append({
                        "w": word.word,
                        "s": round(word.start, 3),
                        "e": round(word.end, 3),
                    })

        dur_out = subprocess.check_output([
            FFPROBE,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(wav_path),
        ])
        duration = float(dur_out.decode().strip())

        seg_starts = align_words_to_segments(sc["segments"], words, duration)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "name": scene_name,
                    "duration": duration,
                    "segmentStarts": seg_starts,
                    "segments": sc["segments"],
                    "wordList": words,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
