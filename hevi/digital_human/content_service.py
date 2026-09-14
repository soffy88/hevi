"""Layer 4 content transaction for the digital-human runtime.

Content locking owns PresenterJob mutation; the lower 3O layers receive and
return data and never hold business state.
"""
from __future__ import annotations

from hevi.digital_human.layer4.atoms import (
    build_timeline,
    generate_narration,
    run_preflight_check,
    run_qa_gate,
)
from hevi.digital_human.layer4.atoms_caption import build_caption_plan as build_caption_plan_atom
from hevi.digital_human.layer4.atoms_narration import topic_to_script
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


def preflight_check(job: PresenterJob):
    """Run the HEVI preflight transaction at the Layer 4 boundary."""
    return run_preflight_check(job)


def qa_gate(job: PresenterJob, *, identity_coherent: bool = True, mouth_sync: bool = True, no_black_frames: bool = True, no_overlay: bool = True, captions_readable: bool = True, safe_zones_ok: bool = True):
    """Run the HEVI acceptance transaction at the Layer 4 boundary."""
    return run_qa_gate(
        job,
        identity_coherent=identity_coherent,
        mouth_sync=mouth_sync,
        no_black_frames=no_black_frames,
        no_overlay=no_overlay,
        captions_readable=captions_readable,
        safe_zones_ok=safe_zones_ok,
    )
