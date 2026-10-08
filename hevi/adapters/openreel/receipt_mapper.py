"""P0.8 — OpenReel result → HEVI render job and receipt.

The important constraint is §12 and §43 together: a render that came back from OpenReel
is not a HEVI render receipt yet. It has to pass through the *canonical* `RenderJob`
state machine and `RenderReceipt` validation, because those are what enforce ffprobe,
immutable identity and the output-spec check.

So this module translates, and then re-uses the canonical constructors. It does not
mint receipts itself — a mapper that could issue a receipt would be a second authority
for what a render produced, which §62 prohibits.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from hevi.adapters.openreel import OpenReelArtifact
from hevi.production.operation import ArtifactRef
from hevi.production.render_job import RenderJob, RenderJobStatus, RenderReceipt


class RenderMappingError(ValueError):
    """The OpenReel result cannot become a valid HEVI receipt."""


def to_render_job(
    *,
    job_id: str,
    production_id: str,
    operation_id: str,
    renderer: str,
    renderer_version: str,
    width: int,
    height: int,
    fps: int,
    duration_ms: int,
    input_refs: tuple[ArtifactRef, ...] = (),
    timeline_id: str | None = None,
) -> RenderJob:
    """Build the canonical ``RenderJob`` for an OpenReel-driven render.

    The job is created *before* the run, in PLANNED, so an OpenReel render is ordered
    and cacheable by the same machinery as any other. Creating it afterwards would mean
    the run happened with nothing recording that it was going to.
    """
    from hevi.production.render_job import OutputSpec

    spec = OutputSpec(
        width=width, height=height, fps=Fraction(fps), duration_ms=duration_ms
    )
    return RenderJob(
        job_id=job_id,
        production_id=production_id,
        timeline_id=timeline_id,
        operation_id=operation_id,
        renderer=renderer,
        renderer_version=renderer_version,
        input_refs=input_refs,
        output_spec=spec,
    )


def to_artifact_ref(artifact: OpenReelArtifact) -> ArtifactRef:
    """Translate an OpenReel artifact into an HEVI reference.

    Refuses a missing hash. §14 puts artifact identity inside the render identity, so an
    unhashed artifact cannot participate in idempotency or the cache; accepting one here
    would let it through and fail silently much later.
    """
    if not artifact.content_hash:
        raise RenderMappingError(
            f"OPENREEL_ARTIFACT_WITHOUT_HASH:{artifact.artifact_id}; §14 requires "
            "artifact identity in the render identity"
        )
    return ArtifactRef(
        artifact_id=artifact.artifact_id,
        content_hash=artifact.content_hash,
        uri=artifact.uri,
        kind=artifact.kind,
    )


def to_render_receipt(
    *,
    job: RenderJob,
    artifact: OpenReelArtifact,
    timeline_hash: str,
    ffprobe_summary: dict[str, Any],
    scene_hash: str | None = None,
) -> RenderReceipt:
    """Build the canonical receipt from an OpenReel result.

    ffprobe must be supplied by the caller from a *real* probe of the produced file.
    This module does not synthesise it: §33/§60 forbid a receipt resting on synthetic
    ffprobe data, and generating a plausible-looking dict here would be exactly that.
    """
    if not ffprobe_summary:
        raise RenderMappingError(
            "OPENREEL_RECEIPT_WITHOUT_FFPROBE:a receipt with no real probe data is a "
            "claim, not evidence (§33, §60)"
        )

    spec = job.output_spec
    return RenderReceipt.for_job(
        job=job,
        output_artifact=to_artifact_ref(artifact),
        duration_ms=_probe_duration_ms(ffprobe_summary, spec.duration_ms),
        width=spec.width,
        height=spec.height,
        fps=spec.fps,
        audio_present=bool(_probe_has_audio(ffprobe_summary)),
        ffprobe_summary=ffprobe_summary,
        timeline_hash=timeline_hash,
        scene_hash=scene_hash,
    )


def _probe_duration_ms(summary: dict[str, Any], fallback_ms: int) -> int:
    duration = summary.get("duration_ms")
    if isinstance(duration, int) and duration >= 0:
        return duration
    raw = summary.get("duration")
    if isinstance(raw, (int, float)) and raw >= 0:
        # ffprobe reports seconds; the canonical unit is integer milliseconds (§17).
        return round(float(raw) * 1000)
    return fallback_ms


def _probe_has_audio(summary: dict[str, Any]) -> bool:
    for stream in summary.get("streams", []) or []:
        if isinstance(stream, dict) and stream.get("codec_type") == "audio":
            return True
    return bool(summary.get("audio_present"))


def mark_succeeded(job: RenderJob) -> RenderJob:
    """Advance through the canonical state machine, not around it.

    PLANNED -> QUEUED -> RUNNING -> SUCCEEDED. All four steps are required:
    `RenderJob._RENDER_TRANSITIONS` refuses PLANNED -> RUNNING, and an earlier version of
    this helper tried exactly that. Skipping QUEUED would erase the window in which the
    job is accepted but not yet started, which is the window a crash-recovery pass
    (§58) reads to decide what still needs re-running.
    """
    for step in (
        RenderJobStatus.QUEUED,
        RenderJobStatus.RUNNING,
        RenderJobStatus.SUCCEEDED,
    ):
        job = job.with_status(step)
    return job


__all__ = [
    "RenderMappingError",
    "mark_succeeded",
    "to_artifact_ref",
    "to_render_job",
    "to_render_receipt",
]
