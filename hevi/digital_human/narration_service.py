"""Layer 4 presenter narration transaction.

This operation owns PresenterJob mutation and artifact placement.  It is kept
outside the 3O namespaces; the old ``digital_human.oprim`` entry point only
delegates here for compatibility during the migration.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from hevi.digital_human.schemas import JobStatus, PresenterJob


def generate_narration(
    job: PresenterJob,
    *,
    voice_id: str | None = None,
    rate: float | None = None,
) -> PresenterJob:
    """Generate narration and persist the resulting presenter artifact."""
    if voice_id:
        job.voice_id = voice_id
    if rate is not None:
        job.rate = rate
    if job.final_audio and Path(job.final_audio).is_file():
        job.status = JobStatus.AUDIO_LOCKED
        job.updated_at = datetime.utcnow()
        return job
    if not job.script.strip():
        raise ValueError("cannot generate narration before content is locked")

    from hevi.voicepro.oskill import synthesize_native_voice_sync

    output_root = Path(os.getenv("HEVI_DIGITAL_HUMAN_OUTPUT_DIR", "data/digital_human")).expanduser()
    output_path = output_root / job.job_id / "audio" / "narration.wav"
    synthesize_native_voice_sync(
        job.script,
        output_path,
        voice=job.voice_id,
        language=job.language,
        reference_audio=job.voice_sample or None,
        speed=job.rate,
    )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("native narration renderer produced no audio artifact")
    job.status = JobStatus.AUDIO_LOCKED
    job.updated_at = datetime.utcnow()
    job.final_audio = str(output_path)
    return job
