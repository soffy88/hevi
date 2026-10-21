"""Music analysis data pipeline as a first-class capability (``audio.music_analyze``).

Wraps ``hevi.audio.music_analyze`` (librosa, local/offline/CPU) in the
pdoom-video ``analysis/`` paradigm: one structured JSON report per
audio file with duration, BPM (decimal precision, least-squares
refined over beat times), beats, downbeats, onsets, structural
sections and a downsampled loudness (RMS/dB) envelope.

Honesty rules, same as the rest of the registry:

* Missing / undecodable audio -> ``CapabilityError`` (never a fake
  success or an invented report).
* Optional ``lyrics`` text attaches per-word timings from the existing
  whisper_local alignment path (single path; the report states
  plainly that no CTC cross-check exists in this CPU environment).
  Alignment failure is recorded in the report as
  ``lyrics_alignment_error`` with ``lyrics_alignment=None`` — the
  music analysis itself is real, the missing timings are not faked.
* ``include_stems=True`` (Demucs separation) -> ``CapabilityError``:
  demucs is deliberately NOT shipped.  Probe 2026-10-21 on ubuntu26
  (20 cores, CPU only): installing demucs 4.1.0 pulled a separate
  5.3 GB torch stack next to hevi's pinned torch, and it never
  produced stems — one separation attempt on an 8-second clip was
  still running at a 600 s timeout (killed), a second died after
  443 s when its torch build failed to load the model checkpoint.
  Stem separation is downgraded / out of scope until a GPU or a
  pinned, shared-stack demucs exists.

The render writes ``music_analysis.json`` into ``out_dir`` and points
``wav`` at the source audio (same convention as
``assembly.beat_align`` / ``audio.earshot_gate``: analysis
capabilities report on the input artefact, they do not re-render it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}


def _render_music_analyze(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.audio.music_analyze import MusicAnalyzeError, analyze_music

    audio_path = Path(params["audio_path"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not audio_path.is_file():
        raise CapabilityError(f"audio.music_analyze: audio file not found: {audio_path}")

    try:
        report = analyze_music(
            audio_path,
            lyrics=params.get("lyrics") or None,
            language=str(params.get("language", "zh")),
            beats_per_bar=int(params.get("beats_per_bar", 4)),
            include_stems=bool(params.get("include_stems", False)),
            loudness_max_points=int(params.get("loudness_max_points", 500)),
        )
    except MusicAnalyzeError as exc:
        raise CapabilityError(f"audio.music_analyze: {exc}") from exc

    report_path = out_dir / "music_analysis.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    lyrics_alignment = report.get("lyrics_alignment")
    is_audio = audio_path.suffix.lower() in _AUDIO_SUFFIXES
    return CapabilityResult(
        wav=str(audio_path) if is_audio else None,
        mp4=None if is_audio else str(audio_path),
        duration_s=float(report["duration_s"]),
        sha256=compute_sha256(audio_path),
        qa={
            "report": str(report_path),
            "bpm": report["bpm"],
            "tempo_raw": report["tempo_raw"],
            "duration_s": report["duration_s"],
            "beat_count": report["beat_count"],
            "downbeat_count": report["downbeat_count"],
            "onset_count": report["onset_count"],
            "section_count": report["section_count"],
            "section_method": report["section_method"],
            "peak_db": report["peak_db"],
            "has_lyrics_alignment": lyrics_alignment is not None,
            "lyrics_word_count": (
                int(lyrics_alignment["word_count"]) if lyrics_alignment else 0
            ),
            "lyrics_alignment_error": report.get("lyrics_alignment_error"),
            "stems": "unavailable_demucs_downgraded",
        },
    )


def register_music_analyze_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    register(
        Capability(
            name="audio.music_analyze",
            kind="audio",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "audio_path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Local audio file to analyse (wav/mp3/flac/ogg/m4a)",
                    },
                    "lyrics": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Optional known lyrics/transcript text; "
                        "when given, per-word timings from the whisper_local "
                        "alignment path are attached as lyrics_alignment",
                    },
                    "language": {
                        "type": "string",
                        "minLength": 1,
                        "default": "zh",
                        "description": "Language hint for whisper lyrics alignment",
                    },
                    "beats_per_bar": {
                        "type": "integer",
                        "minimum": 2,
                        "maximum": 6,
                        "default": 4,
                        "description": "Bar size for downbeat phase estimation (4 = 4/4)",
                    },
                    "include_stems": {
                        "type": "boolean",
                        "default": False,
                        "description": "Demucs stem separation: NOT available "
                        "(downgraded after CPU probe); true raises CapabilityError",
                    },
                    "loudness_max_points": {
                        "type": "integer",
                        "minimum": 10,
                        "maximum": 2000,
                        "default": 500,
                        "description": "Max points in the downsampled loudness envelope",
                    },
                },
                "required": ["audio_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.5,
            render=_render_music_analyze,
            description=(
                "Music analysis pipeline (librosa, local/offline/CPU): "
                "duration, BPM with decimal precision (beat-track + "
                "least-squares interval refinement), beats, downbeats "
                "(bar-phase voted by onset strength), onsets, structural "
                "sections (chroma agglomerative) and a downsampled RMS/dB "
                "loudness envelope, written to music_analysis.json. "
                "Optional lyrics attach whisper_local per-word timings "
                "(single path only: no CTC cross-check exists in this "
                "CPU environment and none is claimed). Demucs stem "
                "separation is downgraded out: a 2026-10-21 CPU probe "
                "(demucs 4.1.0, own 5.3 GB torch stack) never produced "
                "stems — an 8 s clip attempt hit a 600 s timeout and a "
                "retry crashed in torch checkpoint loading — so "
                "include_stems=true raises instead of faking stems."
            ),
            line="audio",
        )
    )
    return ["audio.music_analyze"]
