"""Layer 4 content transaction for the digital-human runtime.

Content locking owns PresenterJob mutation; the lower 3O layers receive and
return data and never hold business state.
"""
from __future__ import annotations

from hevi.digital_human.oprim import build_timeline, generate_narration
from hevi.digital_human.oprim.caption import build_caption_plan as build_caption_plan_atom
from hevi.digital_human.oprim.narration import topic_to_script
from hevi.digital_human.schemas import CaptionPlan, JobStatus, PresenterJob, TimelinePlan


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


def visual_plan(job: PresenterJob, narration_duration_s: float, *, opening_target_s: float = 4.0, closing_target_s: float = 5.0) -> TimelinePlan:
    """Create a timeline and apply its business status in Layer 4."""
    timeline = build_timeline(job, narration_duration_s, opening_target_s, closing_target_s)
    job.status = JobStatus.VISUAL_PLAN_LOCKED
    return timeline


def caption_plan(job: PresenterJob, audio_duration_s: float, *, keyword_anchors: list[tuple[float, str]] | None = None) -> CaptionPlan:
    """Create captions and apply the canonical job projection in Layer 4."""
    plan = build_caption_plan_atom(audio_duration_s=audio_duration_s, script_text=job.script, keyword_anchors=keyword_anchors)
    job.caption_json = plan.model_dump_json()
    return plan
