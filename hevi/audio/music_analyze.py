"""Music analysis pipeline (pdoom-video ``analysis/`` paradigm, local/CPU).

One structured pass over an audio file producing everything downstream
picture-editing needs to know about the music:

* ``duration_s`` / ``sample_rate``
* ``bpm`` — tempo with decimal precision: librosa's aggregate tempo is
  refined by a least-squares fit over the detected beat times (frame
  quantisation makes any single inter-beat interval jitter by a full
  hop, the fit averages that out).  ``tempo_raw`` keeps the unrefined
  librosa estimate for comparison.
* ``beats`` / ``downbeats`` — beat times (s); downbeats are the beats
  phase-aligned onto bars of ``beats_per_bar`` (default 4/4), the phase
  chosen to maximise summed onset strength on downbeat positions.
* ``onsets`` — onset times (s) from the onset envelope.
* ``sections`` — structural segmentation via chroma agglomerative
  clustering (``librosa.segment.agglomerative``); falls back to a
  single whole-file section, explicitly labelled, when clustering is
  unavailable — never an invented boundary.
* ``loudness_envelope`` — per-frame RMS downsampled to at most
  ``loudness_max_points`` points (block-averaged in the linear domain),
  with ``times_s`` / ``rms`` / ``db`` arrays, plus peak / mean stats.

Lyrics (optional): when ``lyrics`` text is supplied, word timings are
attached as ``lyrics_alignment`` reusing the warehouse whisper_local
path (``hevi.audio.whisper_alignment.whisper_align_words``, faster-
whisper ASR measured, ``alignment_source="whisper_asr_local"``).
This is a *single* alignment path on purpose: the pdoom-style CTC +
Whisper cross-check is NOT wired because no CTC model / torchaudio
stack exists in this CPU environment (verified 2026-10-21: torchaudio
not installed, no wav2vec2 CTC weights on disk) — shipping a second
path that cannot run would be a fake cross-check.  If alignment fails
the report carries ``lyrics_alignment=None`` plus the explicit
``lyrics_alignment_error`` instead of invented timings.

Stem separation (Demucs): NOT included.  A 2026-10-21 CPU probe
installed demucs 4.1.0 in a throwaway venv (5.3 GB of its own torch
stack, conflicting with hevi's pinned torch) and never produced a
single stem: the first separation attempt on an 8-second clip was
still running at a 600 s timeout (killed, exit 124), and a second
attempt died after 443 s when that venv's torch build failed to
load the model checkpoint (ModuleNotFoundError:
torch.utils.serialization).  That stack is neither fast nor
working on this box, so separation is downgraded (see the
capability description).  ``include_stems=
True`` therefore raises :class:`MusicAnalyzeError` rather than
pretending; revisit when a GPU or a pinned demucs stack exists.

librosa is already importable in the hevi venv (0.11.0, transitive
via vibevoice, same basis ``hevi.assembly.beat_align`` relies on) and
is now also declared directly in ``pyproject.toml`` so the analysis
line does not depend on a transitive accident.
"""

from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MusicAnalyzeError(RuntimeError):
    """Analysis cannot be produced honestly (missing file / decode / stems)."""


def refine_bpm(beats: list[float], fallback_tempo: float) -> float:
    """Refine a tempo estimate from beat times.

    With >= 3 beats, fit ``time = offset + interval * index`` by least
    squares and return ``60 / interval`` — this averages out the
    per-interval hop quantisation that makes a single median interval
    read several BPM off.  With 2 beats use their interval; otherwise
    fall back to librosa's aggregate tempo.  Rounded to 3 decimals
    (sub-milliBPM precision is not real).
    """
    clean = sorted(float(b) for b in beats)
    if len(clean) >= 3:
        n = len(clean)
        mean_i = (n - 1) / 2.0
        mean_t = sum(clean) / n
        num = sum((i - mean_i) * (t - mean_t) for i, t in enumerate(clean))
        den = sum((i - mean_i) ** 2 for i in range(n))
        if den > 0:
            interval = num / den
            if interval > 0:
                return round(60.0 / interval, 3)
    if len(clean) == 2 and clean[1] > clean[0]:
        return round(60.0 / (clean[1] - clean[0]), 3)
    return round(float(fallback_tempo), 3)


def estimate_downbeats(
    beats: list[float],
    beat_strengths: list[float] | None = None,
    *,
    beats_per_bar: int = 4,
) -> list[float]:
    """Pick the bar phase and return every ``beats_per_bar``-th beat.

    Phase = the offset (0..beats_per_bar-1) whose downbeat positions
    carry the highest total onset strength; ties / no strengths ->
    phase 0 (first detected beat is the bar start).
    """
    if not beats or beats_per_bar < 1:
        return []
    phase = 0
    if beat_strengths and len(beat_strengths) == len(beats):
        best = -1.0
        for cand in range(beats_per_bar):
            total = sum(
                float(beat_strengths[i])
                for i in range(cand, len(beats), beats_per_bar)
            )
            if total > best:
                best = total
                phase = cand
    return [float(b) for b in beats[phase::beats_per_bar]]


def build_sections(
    boundary_times: list[float], duration_s: float
) -> list[dict[str, Any]]:
    """Turn sorted boundary times into contiguous section dicts.

    Boundaries at/after the edges are dropped, duplicates collapsed;
    the result always tiles ``[0, duration_s]`` exactly (last section
    ends at ``duration_s``), even when ``boundary_times`` is empty
    (single whole-file section).
    """
    if duration_s <= 0:
        raise MusicAnalyzeError("build_sections requires a positive duration")
    cuts = sorted(
        {round(float(b), 4) for b in boundary_times if 0.0 < float(b) < duration_s}
    )
    points = [0.0, *cuts, float(duration_s)]
    sections: list[dict[str, Any]] = []
    for idx in range(len(points) - 1):
        start, end = points[idx], points[idx + 1]
        sections.append(
            {
                "index": idx,
                "start_s": round(start, 4),
                "end_s": round(end, 4),
                "duration_s": round(end - start, 4),
            }
        )
    return sections


def downsample_envelope(
    times: list[float], rms_values: list[float], *, max_points: int = 500
) -> dict[str, Any]:
    """Block-average an RMS envelope to at most ``max_points`` points.

    Averaging happens in the linear RMS domain; ``db`` is derived per
    output point (``20*log10(rms)``, floored at -80 dB).  ``hop_s`` is
    the median spacing of the *output* times (0.0 for < 2 points).
    """
    if max_points < 1:
        raise MusicAnalyzeError("loudness_max_points must be >= 1")
    pairs = [(float(t), float(r)) for t, r in zip(times, rms_values, strict=False)]
    if not pairs:
        return {"hop_s": 0.0, "times_s": [], "rms": [], "db": []}
    if len(pairs) > max_points:
        block = math.ceil(len(pairs) / max_points)
        pairs = [
            (
                sum(p[0] for p in pairs[i : i + block]) / len(pairs[i : i + block]),
                sum(p[1] for p in pairs[i : i + block]) / len(pairs[i : i + block]),
            )
            for i in range(0, len(pairs), block)
        ]
    out_times = [round(t, 4) for t, _ in pairs]
    out_rms = [round(r, 6) for _, r in pairs]
    out_db = [
        round(20.0 * math.log10(max(r, 1e-4)), 2) if r > 0 else -80.0 for r in out_rms
    ]
    hop = 0.0
    if len(out_times) >= 2:
        from itertools import pairwise

        diffs = sorted(b - a for a, b in pairwise(out_times))
        hop = round(diffs[len(diffs) // 2], 4)
    return {"hop_s": hop, "times_s": out_times, "rms": out_rms, "db": out_db}


def _align_lyrics_sync(
    audio_path: Path, lyrics: str, language: str
) -> list[dict[str, Any]]:
    """Run the whisper_local alignment path synchronously.

    Reuses ``whisper_align_words`` verbatim (ASR-measured word times
    projected onto the known lyrics).  Kept as its own function so
    tests can substitute it without a model download.
    """
    from hevi.audio.whisper_alignment import whisper_align_words

    async def _run() -> Any:
        return await whisper_align_words(
            audio_path=audio_path, text=lyrics, language=language
        )

    try:
        words, _cost = asyncio.run(_run())
    except RuntimeError:
        # Already inside a running loop (rare for capability renders):
        # drive the coroutine on a private loop in a worker thread.
        import threading

        holder: dict[str, Any] = {}

        def _thread_main() -> None:
            try:
                holder["value"] = asyncio.run(_run())
            except Exception as exc:  # surfaced below
                holder["error"] = exc

        thread = threading.Thread(target=_thread_main, daemon=True)
        thread.start()
        thread.join()
        if "error" in holder:
            raise holder["error"] from None
        words, _cost = holder["value"]
    return [
        {
            "text": w.text,
            "start_ms": int(w.start_ms),
            "end_ms": int(w.end_ms),
            "start_s": round(w.start_ms / 1000.0, 4),
            "end_s": round(w.end_ms / 1000.0, 4),
        }
        for w in words
    ]


def separate_stems_demucs(audio_path: Path, out_dir: Path) -> dict[str, Any]:
    """Demucs stem separation — deliberately unavailable (see module docstring).

    Raises :class:`MusicAnalyzeError` unless a working demucs import
    exists; the CPU probe (2026-10-21) showed the stack is too heavy /
    slow for this environment, so this stays an explicit refusal
    rather than a silently skipped step.
    """
    try:
        import demucs  # noqa: F401
    except Exception as exc:
        raise MusicAnalyzeError(
            "stem separation unavailable: demucs is not installed in the "
            "hevi environment (CPU probe 2026-10-21: separate 5.3 GB "
            "torch stack; an 8 s clip separation attempt exceeded a "
            "600 s timeout and a retry crashed in torch checkpoint "
            "loading). Re-run without include_stems."
        ) from exc
    raise MusicAnalyzeError(
        "stem separation is not wired in this capability even though "
        "demucs imports; refusing to fake stems."
    )


def analyze_music(
    audio_path: Path | str,
    *,
    lyrics: str | None = None,
    language: str = "zh",
    beats_per_bar: int = 4,
    include_stems: bool = False,
    loudness_max_points: int = 500,
    target_sr: int = 22050,
) -> dict[str, Any]:
    """Full music analysis of one audio file -> structured report dict.

    Raises :class:`MusicAnalyzeError` on a missing / undecodable /
    empty file and on an explicit ``include_stems`` request (demucs
    downgrade, see module docstring).  Beat/onset emptiness on
    near-silent audio is reported honestly (empty lists, bpm from the
    aggregate estimator or 0.0), not raised.
    """
    path = Path(audio_path)
    if not path.is_file():
        raise MusicAnalyzeError(f"music analysis audio file not found: {path}")
    if include_stems:
        # Fail fast before paying for the whole analysis pass.
        separate_stems_demucs(path, path.parent)
    try:
        import librosa
        import numpy as np
    except Exception as exc:
        raise MusicAnalyzeError(f"librosa unavailable: {exc}") from exc

    try:
        y, sr = librosa.load(str(path), sr=int(target_sr), mono=True)
    except Exception as exc:
        raise MusicAnalyzeError(f"cannot decode audio {path}: {exc}") from exc
    if y is None or len(y) == 0:
        raise MusicAnalyzeError(f"audio file decoded to zero samples: {path}")
    duration_s = round(float(len(y)) / float(sr), 4)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo_raw_arr, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, units="frames"
    )
    tempo_raw = float(np.atleast_1d(tempo_raw_arr)[0]) if np.size(tempo_raw_arr) else 0.0
    beats = [
        round(float(t), 4) for t in librosa.frames_to_time(beat_frames, sr=sr)
    ]
    bpm = refine_bpm(beats, tempo_raw)

    # Onset strength sampled at beat frames -> downbeat phase vote.
    beat_strengths: list[float] | None = None
    if len(beat_frames) and len(onset_env):
        beat_strengths = [
            float(onset_env[min(int(f), len(onset_env) - 1)]) for f in beat_frames
        ]
    downbeats = estimate_downbeats(
        beats, beat_strengths, beats_per_bar=int(beats_per_bar)
    )

    onsets = [
        round(float(t), 4)
        for t in librosa.onset.onset_detect(
            onset_envelope=onset_env, sr=sr, units="time"
        )
    ]

    sections: list[dict[str, Any]]
    section_method = "chroma_agglomerative"
    try:
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        n_sections = max(2, min(8, int(duration_s // 8) + 1))
        bound_frames = librosa.segment.agglomerative(chroma, n_sections)
        bound_times = [
            float(t) for t in librosa.frames_to_time(bound_frames, sr=sr)
        ]
        sections = build_sections(bound_times, duration_s)
    except Exception as exc:
        logger.warning("music_analyze segmentation fell back for %s: %s", path, exc)
        section_method = "single_section_fallback"
        sections = build_sections([], duration_s)

    rms_frames = librosa.feature.rms(y=y)[0]
    frame_times = [
        float(t) for t in librosa.frames_to_time(np.arange(len(rms_frames)), sr=sr)
    ]
    envelope = downsample_envelope(
        frame_times, [float(r) for r in rms_frames], max_points=int(loudness_max_points)
    )
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    peak_db = round(20.0 * math.log10(peak), 2) if peak > 0 else -80.0
    mean_rms = float(np.sqrt(np.mean(np.square(y)))) if len(y) else 0.0
    mean_db = round(20.0 * math.log10(max(mean_rms, 1e-4)), 2) if mean_rms > 0 else -80.0

    report: dict[str, Any] = {
        "audio_path": str(path),
        "duration_s": duration_s,
        "sample_rate": int(sr),
        "bpm": bpm,
        "tempo_raw": round(tempo_raw, 3),
        "tempo_method": "beat_track+least_squares_beat_interval_refinement",
        "beats": beats,
        "beat_count": len(beats),
        "downbeats": [round(float(d), 4) for d in downbeats],
        "downbeat_count": len(downbeats),
        "beats_per_bar": int(beats_per_bar),
        "onsets": onsets,
        "onset_count": len(onsets),
        "sections": sections,
        "section_count": len(sections),
        "section_method": section_method,
        "loudness_envelope": envelope,
        "peak_db": peak_db,
        "mean_rms_db": mean_db,
        "is_silent": peak == 0.0,
        "lyrics_alignment": None,
        "lyrics_alignment_error": None,
        "stems": None,
    }

    if lyrics and lyrics.strip():
        try:
            words = _align_lyrics_sync(path, lyrics, language)
            report["lyrics_alignment"] = {
                "source": "whisper_asr_local",
                "cross_check": None,
                "cross_check_note": (
                    "single-path whisper_local alignment; CTC cross-check "
                    "not available in this CPU environment (no torchaudio / "
                    "CTC weights), so no second path is claimed"
                ),
                "language": language,
                "words": words,
                "word_count": len(words),
            }
        except Exception as exc:
            logger.warning("music_analyze lyrics alignment failed for %s: %s", path, exc)
            report["lyrics_alignment_error"] = str(exc)
    return report


__all__ = [
    "MusicAnalyzeError",
    "analyze_music",
    "build_sections",
    "downsample_envelope",
    "estimate_downbeats",
    "refine_bpm",
    "separate_stems_demucs",
]
