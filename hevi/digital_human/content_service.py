"""Layer 4 content transaction for the digital-human runtime.

Content locking owns PresenterJob mutation; the lower 3O layers receive and
return data and never hold business state.
"""
from __future__ import annotations

from hevi.digital_human.oprim import generate_narration
from hevi.digital_human.oprim.narration import topic_to_script
from hevi.digital_human.schemas import JobStatus, PresenterJob


def lock_content(job: PresenterJob) -> PresenterJob:
    """Apply the content-lock transaction to the HEVI business object."""
    job.status = JobStatus.CONTENT_LOCKED
    job.script = topic_to_script(job.topic, job.duration_target_s)
    job.beat_sheet = "hook → promise → 2–4 useful beats → synthesis → close"
    return job


def content_lock(
    job: PresenterJob,
    *,
    voice_id: str | None = None,
    rate: float | None = None,
) -> PresenterJob:
    """Run the content-lock transaction and apply its business state."""
    locked = lock_content(job)
    return generate_narration(locked, voice_id=voice_id, rate=rate)
