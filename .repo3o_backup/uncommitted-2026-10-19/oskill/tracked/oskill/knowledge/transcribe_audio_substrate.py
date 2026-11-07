"""Transcribe an audio substrate via whisper.cpp."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from oprim._logging import log
from oprim.external.clients.whisper_client import WhisperClient
from oprim.external.gpu_lock import GpuLock
from oprim.meta_db import open_meta_db

from oskill.knowledge._context import meta_db_path


@dataclass
class TranscriptionResult:
    substrate_id: str
    transcription_job_id: str
    text: str
    language: str
    segments: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0


async def transcribe_audio_substrate(
    substrate_id: str,
    language: str = "auto",
) -> TranscriptionResult:
    """Transcribe an audio substrate using whisper.cpp large-v3 Q5.

    Acquires GpuLock; whisper needs ~1–2GB VRAM.
    Creates a transcription_job row and a 'transcription' derivative.

    Args:
        substrate_id: Audio substrate ULID (medium='audio' or 'screenpipe').
        language: ISO 639-1 language code or "auto" for detection.

    Returns:
        TranscriptionResult with full text and timestamped segments.
    """
    audio_path = _fetch_audio_path(substrate_id)
    if not audio_path:
        raise ValueError(f"substrate {substrate_id} has no audio source_path")
    if not audio_path.exists():
        raise FileNotFoundError(f"audio file not found: {audio_path}")

    from python_ulid import ULID

    job_id = str(ULID())
    _create_transcription_job(job_id, substrate_id, language)

    log.info(
        "transcribe_audio_substrate.start",
        substrate_id=substrate_id,
        job_id=job_id,
        language=language,
    )

    gpu_lock = GpuLock()
    whisper = WhisperClient()
    try:
        async with gpu_lock.acquire(requester=f"transcribe:{substrate_id}"):
            result = await whisper.transcribe(audio_path, language=language)
    except Exception as exc:
        _update_transcription_job(job_id, status="failed", error=str(exc))
        raise
    finally:
        await whisper.close()
        await gpu_lock.close()

    segments_dicts = [{"start": s.start, "end": s.end, "text": s.text} for s in result.segments]

    _update_transcription_job(
        job_id,
        status="done",
        text=result.text,
        segments=segments_dicts,
        language=result.language,
    )
    _save_transcription_derivative(substrate_id, job_id, result.text, segments_dicts)

    log.info(
        "transcribe_audio_substrate.done",
        substrate_id=substrate_id,
        job_id=job_id,
        language=result.language,
        text_len=len(result.text),
        segments=len(segments_dicts),
    )
    return TranscriptionResult(
        substrate_id=substrate_id,
        transcription_job_id=job_id,
        text=result.text,
        language=result.language,
        segments=segments_dicts,
        cost_usd=0.0,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fetch_audio_path(substrate_id: str) -> Path | None:
    db_path = meta_db_path()
    if not db_path.exists():
        return None
    try:
        db = open_meta_db(db_path)
        rows = db.fetchall(
            "SELECT source_path FROM substrates WHERE id = ?",
            [substrate_id],
        )
        db.close()
        if rows and rows[0][0]:
            return Path(rows[0][0])
    except Exception as exc:
        log.warning("transcribe_audio_substrate.fetch_path_failed", error=str(exc))
    return None


def _create_transcription_job(job_id: str, substrate_id: str, language: str) -> None:
    db_path = meta_db_path()
    if not db_path.exists():
        return
    try:
        db = open_meta_db(db_path)
        db.execute(
            """
            INSERT INTO transcription_jobs
                (id, substrate_id, status, language, started_at)
            VALUES (?, ?, 'running', ?, CURRENT_TIMESTAMP)
            """,
            [job_id, substrate_id, language],
        )
        db.close()
    except Exception as exc:
        log.warning("transcribe_audio_substrate.create_job_failed", error=str(exc))


def _update_transcription_job(
    job_id: str,
    status: str,
    text: str = "",
    segments: list[dict] | None = None,
    language: str = "",
    error: str = "",
) -> None:
    db_path = meta_db_path()
    if not db_path.exists():
        return
    try:
        db = open_meta_db(db_path)
        db.execute(
            """
            UPDATE transcription_jobs
            SET status = ?, text = ?, segments = ?, language = COALESCE(NULLIF(?, ''), language),
                completed_at = CURRENT_TIMESTAMP, error_message = ?
            WHERE id = ?
            """,
            [
                status,
                text or None,
                json.dumps(segments) if segments else None,
                language,
                error or None,
                job_id,
            ],
        )
        db.close()
    except Exception as exc:
        log.warning("transcribe_audio_substrate.update_job_failed", error=str(exc))


def _save_transcription_derivative(
    substrate_id: str,
    job_id: str,
    text: str,
    segments: list[dict],
) -> None:
    from python_ulid import ULID

    db_path = meta_db_path()
    if not db_path.exists():
        return
    try:
        db = open_meta_db(db_path)
        deriv_id = str(ULID())
        meta = json.dumps({"job_id": job_id, "segments": segments})
        db.execute(
            """
            INSERT INTO derivative (id, substrate_id, kind, content, meta_json)
            VALUES (?, ?, 'transcription', ?, ?)
            """,
            [deriv_id, substrate_id, text, meta],
        )
        db.close()
    except Exception as exc:
        log.warning("transcribe_audio_substrate.save_derivative_failed", error=str(exc))
