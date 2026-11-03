"""Three measured delivery gates for talking-head films.

1. **Whisper verification** — the delivered audio track is transcribed
   locally with faster-whisper (reusing
   ``hevi.audio.whisper_alignment._transcribe_words`` and its model
   resolution: local ``/home/soffy/models/faster-whisper-large-v3-turbo``
   first) and compared to the original script with a punctuation/space-
   normalised similarity (:func:`text_similarity`, normalisation reuses
   ``hevi...oprim_impl.sync.norm_chars``).  Output carries the transcript
   and the score — not just a boolean.
2. **earshot audio gate** — reuses ``hevi.audio.earshot_client.measure``
   for the measurements and ``hevi.capabilities.earshot_gate._gate_checks``
   for the verdict logic (LUFS vs target, true-peak ceiling, hard
   clipping), so this gate can never drift from the capability gate.
3. **Visual gate** — frames are sampled from the delivered MP4
   (``_avatar._grab_frame``), each frame's mean luma decides black-frame
   (:func:`is_black_luma`) and yoloface (``_avatar._detect_face``, shared
   session like ``measure_host_face``) decides the face-detection rate;
   plus the video-vs-audio duration difference from ffprobe
   (``_media.probe``).

A gate that cannot run (model missing, earshot missing, undecodable
media) returns ``pass=False`` with an ``error`` field.  It never raises
into the pipeline and never reports a pass it did not measure.

Pure helpers (:func:`normalize_for_compare`, :func:`text_similarity`,
:func:`is_black_luma`, :func:`summarize_frames`) carry no I/O so the
verdict logic is unit-testable without any model.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

__all__ = [
    "earshot_gate",
    "is_black_luma",
    "normalize_for_compare",
    "run_all_gates",
    "summarize_frames",
    "text_similarity",
    "visual_gate",
    "whisper_gate",
]

_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
BLACK_LUMA_THRESHOLD = 12.0  # mean luma (0..255) below this = black frame


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------
def normalize_for_compare(text: str) -> str:
    """Normalised comparison form: no whitespace/punctuation, lower-case.

    Delegates to talkcraft's ``norm_chars`` (the form script/ASR matching
    already uses in hevi) with an identical local fallback.
    """
    try:
        from hevi.layer4_legacy.talkcraft.oprim_impl.sync import norm_chars

        return norm_chars(text or "")
    except Exception:
        return "".join(ch.lower() for ch in (text or "") if not ch.isspace() and ch.isalnum())


def text_similarity(expected: str, actual: str) -> float:
    """Normalised similarity in [0, 1] between script and transcript (pure)."""
    ref = normalize_for_compare(expected)
    hyp = normalize_for_compare(actual)
    if not ref and not hyp:
        return 1.0
    if not ref or not hyp:
        return 0.0
    return round(SequenceMatcher(None, ref, hyp, autojunk=False).ratio(), 4)


def is_black_luma(mean_luma: float, *, threshold: float = BLACK_LUMA_THRESHOLD) -> bool:
    """True when a frame's mean luma is at/below the black threshold (pure)."""
    return float(mean_luma) <= float(threshold)


def summarize_frames(
    frame_lumas: list[float],
    face_flags: list[bool],
    *,
    black_threshold: float = BLACK_LUMA_THRESHOLD,
    min_face_rate: float = 0.8,
    max_black_share: float = 0.1,
) -> dict[str, Any]:
    """Aggregate per-frame measurements into the visual verdict (pure)."""
    total = len(frame_lumas)
    if total == 0:
        return {
            "pass": False,
            "frames_sampled": 0,
            "face_detected": 0,
            "face_rate": 0.0,
            "black_frames": 0,
            "black_share": 1.0,
            "checks": [
                {"name": "frames_sampled", "ok": False, "value": 0, "threshold": ">= 1 frame"}
            ],
        }
    face_detected = sum(1 for flag in face_flags[:total] if flag)
    face_rate = round(face_detected / total, 4)
    black_frames = sum(1 for luma in frame_lumas if is_black_luma(luma, threshold=black_threshold))
    black_share = round(black_frames / total, 4)
    checks = [
        {
            "name": "face_rate",
            "ok": face_rate >= min_face_rate,
            "value": face_rate,
            "threshold": f">= {min_face_rate}",
        },
        {
            "name": "black_share",
            "ok": black_share <= max_black_share,
            "value": black_share,
            "threshold": f"<= {max_black_share}",
        },
    ]
    return {
        "pass": all(c["ok"] for c in checks),
        "frames_sampled": total,
        "face_detected": face_detected,
        "face_rate": face_rate,
        "black_frames": black_frames,
        "black_share": black_share,
        "mean_luma": round(sum(frame_lumas) / total, 2),
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# gate 1: whisper verification
# ---------------------------------------------------------------------------
def _default_transcriber(media_path: Path, *, language: str) -> str:
    """Transcribe a media file's audio with local faster-whisper (reused).

    Video inputs get their audio extracted to a temp WAV with ffmpeg
    first.  Word texts from ``_transcribe_words`` are joined verbatim
    (faster-whisper word strings keep their leading spaces for latin
    scripts), giving the raw transcript for the record.
    """
    from hevi.audio.whisper_alignment import _transcribe_words
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG

    audio_path = Path(media_path)
    temp_wav: Path | None = None
    try:
        if audio_path.suffix.lower() in _VIDEO_SUFFIXES:
            import os

            fd, tmp_name = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            temp_wav = Path(tmp_name)
            proc = subprocess.run(
                [FFMPEG, "-y", "-v", "error", "-i", str(audio_path),
                 "-vn", "-ac", "1", "-ar", "16000", str(temp_wav)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg audio extract failed: {proc.stderr[-500:]}")
            audio_path = temp_wav
        words = _transcribe_words(audio_path, language=language)
        return "".join(word_text for word_text, _start, _end in words).strip()
    finally:
        if temp_wav is not None:
            temp_wav.unlink(missing_ok=True)


def whisper_gate(
    media_path: str | Path,
    script_text: str,
    *,
    threshold: float = 0.85,
    language: str = "zh",
    transcriber: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Gate 1: ASR transcript of the delivered audio vs the script."""
    path = Path(media_path)
    base: dict[str, Any] = {"name": "whisper_verify", "threshold": threshold}
    if not path.is_file():
        return {**base, "pass": False, "score": 0.0, "transcript": "",
                "error": f"media not found: {path}"}
    if not (script_text or "").strip():
        return {**base, "pass": False, "score": 0.0, "transcript": "",
                "error": "script text is empty; nothing to verify against"}
    try:
        run = transcriber or (lambda p: _default_transcriber(Path(p), language=language))
        transcript = str(run(path))
    except Exception as exc:
        return {**base, "pass": False, "score": 0.0, "transcript": "",
                "error": f"{type(exc).__name__}: {exc}"}
    score = text_similarity(script_text, transcript)
    return {
        **base,
        "pass": score >= threshold,
        "score": score,
        "transcript": transcript,
        "normalized_expected": normalize_for_compare(script_text),
        "normalized_transcript": normalize_for_compare(transcript),
        "error": None,
    }


# ---------------------------------------------------------------------------
# gate 2: earshot audio hygiene
# ---------------------------------------------------------------------------
def earshot_gate(
    media_path: str | Path,
    *,
    lufs_target: float = -14.0,
    lufs_tolerance: float = 2.0,
    true_peak_ceiling: float = -1.0,
    measurer: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Gate 2: LUFS / true peak / clipping via earshot (reused checks)."""
    path = Path(media_path)
    base: dict[str, Any] = {
        "name": "earshot_audio",
        "thresholds": {
            "lufs_target": lufs_target,
            "lufs_tolerance": lufs_tolerance,
            "true_peak_ceiling_dbtp": true_peak_ceiling,
        },
    }
    if not path.is_file():
        return {**base, "pass": False, "checks": [], "measurements": {},
                "error": f"media not found: {path}"}
    try:
        if measurer is None:
            from hevi.audio import earshot_client

            measurer = earshot_client.measure
        measurements = measurer(path)
        from hevi.capabilities.earshot_gate import _gate_checks

        checks = _gate_checks(
            measurements,
            lufs_target=lufs_target,
            lufs_tolerance=lufs_tolerance,
            true_peak_ceiling=true_peak_ceiling,
        )
    except Exception as exc:
        return {**base, "pass": False, "checks": [], "measurements": {},
                "error": f"{type(exc).__name__}: {exc}"}
    return {
        **base,
        "pass": all(c["ok"] for c in checks),
        "checks": checks,
        "measurements": measurements,
        "failed_checks": [c["name"] for c in checks if not c["ok"]],
        "error": None,
    }


# ---------------------------------------------------------------------------
# gate 3: visual (face presence / black frames / AV duration)
# ---------------------------------------------------------------------------
def _probe_durations(path: Path) -> dict[str, Any]:
    """Video + audio stream durations from ffprobe (talkcraft ``probe``)."""
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import probe

    info = probe(path)
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    def _dur(stream: dict[str, Any] | None) -> float | None:
        if stream is None:
            return None
        try:
            return float(stream.get("duration"))
        except (TypeError, ValueError):
            return None

    format_duration = None
    try:
        format_duration = float((info.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        format_duration = None
    return {
        "video_duration_s": _dur(video) or format_duration,
        "audio_duration_s": _dur(audio) or format_duration,
        "format_duration_s": format_duration,
        "has_audio": audio is not None,
        "width": int(video["width"]) if video and video.get("width") else None,
        "height": int(video["height"]) if video and video.get("height") else None,
    }


def _default_frame_sampler(
    video_path: Path, *, sample_count: int
) -> dict[str, Any]:
    """Sample frames: mean luma per frame + yoloface face flag per frame.

    Mirrors ``_avatar.measure_host_face``: evenly spaced timestamps,
    ``_grab_frame`` for decoding, one shared yoloface session for all
    ``_detect_face`` calls.
    """
    import numpy as np

    from hevi.layer4_legacy.talkcraft.omodul_impl._avatar import (
        _detect_face,
        _grab_frame,
        _session,
    )

    durations = _probe_durations(video_path)
    total = float(durations["video_duration_s"] or 0.0)
    if total <= 0:
        raise RuntimeError(f"could not probe video duration for {video_path}")
    sess = _session("yoloface_8n.onnx")
    lumas: list[float] = []
    face_flags: list[bool] = []
    for k in range(sample_count):
        t = total * (k + 0.5) / sample_count
        frame = _grab_frame(video_path, t)
        if frame is None:
            lumas.append(0.0)
            face_flags.append(False)
            continue
        gray = np.asarray(frame.convert("L"), dtype=np.float32)
        lumas.append(float(gray.mean()))
        face = _detect_face(frame, sess=sess, required=False)
        face_flags.append(face is not None and float(face[4]) >= 0.5)
    return {"lumas": lumas, "face_flags": face_flags, "durations": durations}


def visual_gate(
    video_path: str | Path,
    *,
    audio_duration_s: float | None = None,
    max_av_diff_s: float = 0.5,
    min_face_rate: float = 0.8,
    max_black_share: float = 0.1,
    black_luma_threshold: float = BLACK_LUMA_THRESHOLD,
    sample_count: int = 12,
    frame_sampler: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Gate 3: face presence, black frames, video/audio duration delta."""
    path = Path(video_path)
    base: dict[str, Any] = {
        "name": "visual",
        "thresholds": {
            "min_face_rate": min_face_rate,
            "max_black_share": max_black_share,
            "black_luma_threshold": black_luma_threshold,
            "max_av_diff_s": max_av_diff_s,
        },
    }
    if not path.is_file():
        return {**base, "pass": False, "error": f"media not found: {path}"}
    try:
        sampler = frame_sampler or (
            lambda p: _default_frame_sampler(Path(p), sample_count=sample_count)
        )
        sampled = sampler(path)
        durations = sampled.get("durations") or _probe_durations(path)
    except Exception as exc:
        return {**base, "pass": False, "error": f"{type(exc).__name__}: {exc}"}

    summary = summarize_frames(
        [float(v) for v in sampled.get("lumas") or []],
        [bool(v) for v in sampled.get("face_flags") or []],
        black_threshold=black_luma_threshold,
        min_face_rate=min_face_rate,
        max_black_share=max_black_share,
    )
    video_dur = durations.get("video_duration_s")
    reference_audio = audio_duration_s if audio_duration_s is not None else durations.get("audio_duration_s")
    if video_dur is None or reference_audio is None:
        av_diff = None
        av_ok = False
        av_detail = "missing video or audio duration"
    else:
        av_diff = round(abs(float(video_dur) - float(reference_audio)), 3)
        av_ok = av_diff <= max_av_diff_s
        av_detail = f"{video_dur:.3f}s video vs {float(reference_audio):.3f}s audio"
    checks = list(summary.get("checks") or [])
    checks.append(
        {"name": "av_duration_diff", "ok": av_ok, "value": av_diff,
         "threshold": f"<= {max_av_diff_s} s", "detail": av_detail}
    )
    if not durations.get("has_audio", True) and audio_duration_s is None:
        checks.append(
            {"name": "has_audio_stream", "ok": False, "value": False, "threshold": "audio stream present"}
        )
    # summarize_frames already folds face/black into its own pass; the AV
    # checks above are additional, so the gate passes only if both agree.
    passed = bool(summary.get("pass")) and av_ok and not any(
        c["name"] == "has_audio_stream" and not c["ok"] for c in checks
    )
    return {
        **base,
        "pass": passed,
        "frames_sampled": summary.get("frames_sampled", 0),
        "face_detected": summary.get("face_detected", 0),
        "face_rate": summary.get("face_rate", 0.0),
        "black_frames": summary.get("black_frames", 0),
        "black_share": summary.get("black_share", 1.0),
        "mean_luma": summary.get("mean_luma"),
        "video_duration_s": video_dur,
        "audio_duration_s": reference_audio,
        "av_duration_diff_s": av_diff,
        "checks": checks,
        "error": None,
    }


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------
def run_all_gates(
    video_path: str | Path,
    *,
    script_text: str,
    audio_duration_s: float | None = None,
    whisper_threshold: float = 0.85,
    language: str = "zh",
    lufs_target: float = -14.0,
    lufs_tolerance: float = 2.0,
    true_peak_ceiling: float = -1.0,
    min_face_rate: float = 0.8,
    max_black_share: float = 0.1,
    max_av_diff_s: float = 0.5,
    transcriber: Callable[..., str] | None = None,
    measurer: Callable[[Path], dict[str, Any]] | None = None,
    frame_sampler: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run all three gates; a gate exception becomes a failed gate record."""
    gates: dict[str, Any] = {}
    gates["whisper_verify"] = whisper_gate(
        video_path, script_text, threshold=whisper_threshold, language=language,
        transcriber=transcriber,
    )
    gates["earshot_audio"] = earshot_gate(
        video_path, lufs_target=lufs_target, lufs_tolerance=lufs_tolerance,
        true_peak_ceiling=true_peak_ceiling, measurer=measurer,
    )
    gates["visual"] = visual_gate(
        video_path, audio_duration_s=audio_duration_s, max_av_diff_s=max_av_diff_s,
        min_face_rate=min_face_rate, max_black_share=max_black_share,
        frame_sampler=frame_sampler,
    )
    failed = [name for name, gate in gates.items() if gate.get("pass") is not True]
    return {"pass": not failed, "gates": gates, "failed": failed}
