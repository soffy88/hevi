"""P0.4 — render job and render receipt.

Why RenderReceipt is not ProductionReceipt
------------------------------------------
``hevi/execution/models.py`` documents this precisely and the reasoning still holds:

    P8.3 ProductionReceipt  an artifact is proven (requires ValidationResult over
                            the same bytes -- bytes exist *and* were checked)
    RenderReceipt           a render ran, with these inputs, by this renderer version

Neither implies the other. A render receipt with no artifact validation is a claim
about a process, not proof of a deliverable; a production receipt says nothing about
which renderer produced the bytes. ``RenderReceipt`` does not replace or weaken
``ProductionReceipt`` -- a final PASS still needs the latter.

Why ffprobe is required rather than optional
--------------------------------------------
§18 permits encoder-level variation ("minor codec differences"). That is a reason to
record what the encoder produced, not a reason to leave it unrecorded. A receipt
without ffprobe data cannot answer "did the output actually have the duration and
resolution we asked for", which is the first question anyone asks about a render.

Why duration/fps are integers and rationals
--------------------------------------------
§17 requires integer milliseconds, matching ``TimelineIR``. A float duration is how
1080.0000001s vs 1080s creep into an identity hash and silently defeat the render
cache. Width/height are ``int``; fps is ``Rational`` because 30000/1001 is a real
frame rate and rounding it to 30 changes the artifact's identity.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from fractions import Fraction
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hevi.production.operation import ArtifactRef


class RenderJobStatus(StrEnum):
    PLANNED = "PLANNED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_RENDER_TRANSITIONS: dict[RenderJobStatus, frozenset[RenderJobStatus]] = {
    RenderJobStatus.PLANNED: frozenset({RenderJobStatus.QUEUED, RenderJobStatus.CANCELLED}),
    RenderJobStatus.QUEUED: frozenset(
        {RenderJobStatus.RUNNING, RenderJobStatus.CANCELLED, RenderJobStatus.FAILED}
    ),
    RenderJobStatus.RUNNING: frozenset(
        {RenderJobStatus.SUCCEEDED, RenderJobStatus.FAILED, RenderJobStatus.CANCELLED}
    ),
    RenderJobStatus.SUCCEEDED: frozenset(),
    RenderJobStatus.FAILED: frozenset(),
    RenderJobStatus.CANCELLED: frozenset(),
}


class OutputSpec(BaseModel):
    """What the job is asked to produce, declared before it runs."""

    model_config = ConfigDict(frozen=True)

    width: int
    height: int
    fps: Fraction
    duration_ms: int
    #: §60: a job must declare its target container and codec. "Whatever came out" is
    #: not an output spec.
    container: str = "mp4"
    video_codec: str = "h264"
    audio_codec: str | None = "aac"
    audio_required: bool = True

    @field_validator("width", "height")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("OUTPUT_SPEC_NON_POSITIVE_DIMENSION")
        return value

    @field_validator("duration_ms")
    @classmethod
    def _positive_duration(cls, value: int) -> int:
        if value < 0:
            raise ValueError("OUTPUT_SPEC_NEGATIVE_DURATION")
        return value

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["fps"] = str(self.fps)
        return data


class RenderJob(BaseModel):
    """One render, fully described and addressed by identity.

    ``idempotency_key`` and ``deterministic_key`` are distinct on purpose:

        idempotency_key  "this logical render was requested" -- a retry must reuse it
        deterministic_key "these inputs would produce these bytes" -- the cache key

    Conflating them would let a cache hit satisfy an idempotency check, which is
    backwards: idempotency is about not repeating work, the cache is about not
    recomputing it, and a cache hit still needs its own receipt.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    production_id: str
    timeline_id: str | None = None
    operation_id: str

    renderer: str
    encoder: str | None = None
    renderer_version: str = ""
    encoder_version: str = ""

    input_refs: tuple[ArtifactRef, ...] = ()
    output_spec: OutputSpec

    #: §41's cache key, §14's render identity. Empty means "no cache", which is the
    #: honest default for a renderer that has not declared determinism.
    deterministic_key: str = ""
    deterministic: bool = False

    idempotency_key: str = ""
    status: RenderJobStatus = RenderJobStatus.PLANNED

    @field_validator("job_id", "production_id", "operation_id", "renderer")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("RENDER_JOB_EMPTY_REQUIRED_FIELD")
        return value

    @model_validator(mode="after")
    def _determinism_is_declared(self) -> Self:
        if self.deterministic and not self.deterministic_key:
            raise ValueError(
                f"RENDER_JOB_DETERMINISTIC_WITHOUT_KEY:{self.job_id}; a deterministic "
                "render with no key cannot be cached or proven reproducible"
            )
        return self

    def compute_deterministic_key(self) -> str:
        """§41: timeline hash + scene hash + asset hashes + versions + parameters.

        Renderer and encoder versions are inside the key, so upgrading either
        invalidates the cache rather than serving artifacts the new version would not
        have produced (R6/R7).
        """
        payload = {
            "job": self.output_spec.to_dict(),
            "assets": sorted((ref.artifact_id, ref.content_hash) for ref in self.input_refs),
            "encoder": self.encoder,
            "encoder_version": self.encoder_version,
            "renderer": self.renderer,
            "renderer_version": self.renderer_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

    def with_status(self, status: RenderJobStatus) -> RenderJob:
        """Return a copy in a new status, refusing illegal transitions."""
        allowed = _RENDER_TRANSITIONS[self.status]
        if status not in allowed:
            raise ValueError(f"ILLEGAL_RENDER_JOB_TRANSITION:{self.job_id}:{self.status.value}->{status.value}")
        return self.model_copy(update={"status": status})

    @property
    def terminal(self) -> bool:
        return self.status in (
            RenderJobStatus.SUCCEEDED,
            RenderJobStatus.FAILED,
            RenderJobStatus.CANCELLED,
        )


class RenderReceipt(BaseModel):
    """Immutable proof that a render ran and what it produced.

    Immutable means ``frozen=True``, not "nobody mutates it": a receipt is the evidence
    that a specific render happened, and editing one after the fact destroys the only
    thing it is for.
    """

    model_config = ConfigDict(frozen=True)

    receipt_id: str
    job_id: str
    production_id: str

    renderer: str
    renderer_version: str
    encoder: str | None = None
    encoder_version: str | None = None

    input_hash: str
    timeline_hash: str
    scene_hash: str | None = None

    output_artifact: ArtifactRef

    duration_ms: int
    width: int
    height: int
    fps: Fraction

    audio_present: bool = False
    #: ffprobe output is required. A receipt without it cannot be checked against the
    #: output spec, which is the entire reason the receipt exists.
    ffprobe_summary: dict[str, Any] = Field(min_length=1)

    deterministic_key: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("receipt_id", "job_id", "production_id", "renderer", "input_hash",
                     "timeline_hash")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("RENDER_RECEIPT_EMPTY_REQUIRED_FIELD")
        return value

    @model_validator(mode="after")
    def _receipt_matches_the_job(self) -> Self:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"RENDER_RECEIPT_BAD_DIMENSIONS:{self.receipt_id}")
        if self.duration_ms < 0:
            raise ValueError(f"RENDER_RECEIPT_NEGATIVE_DURATION:{self.receipt_id}")
        return self

    @classmethod
    def for_job(
        cls,
        *,
        job: RenderJob,
        output_artifact: ArtifactRef,
        duration_ms: int,
        width: int,
        height: int,
        fps: Fraction,
        audio_present: bool,
        ffprobe_summary: dict[str, Any],
        timeline_hash: str,
        scene_hash: str | None = None,
        input_hash: str = "",
    ) -> RenderReceipt:
        if not ffprobe_summary:
            raise ValueError(
                f"RENDER_RECEIPT_WITHOUT_FFPROBE:{job.job_id}; a render receipt with no "
                "ffprobe data is a claim, not evidence"
            )
        digest = hashlib.sha256(
            "|".join([job.job_id, job.renderer, job.renderer_version, output_artifact.content_hash])
            .encode()
        ).hexdigest()[:16]
        return cls(
            receipt_id=f"rreceipt-{digest}",
            job_id=job.job_id,
            production_id=job.production_id,
            renderer=job.renderer,
            renderer_version=job.renderer_version,
            encoder=job.encoder,
            encoder_version=job.encoder_version,
            input_hash=input_hash or job.compute_deterministic_key(),
            timeline_hash=timeline_hash,
            scene_hash=scene_hash,
            output_artifact=output_artifact,
            duration_ms=duration_ms,
            width=width,
            height=height,
            fps=fps,
            audio_present=audio_present,
            ffprobe_summary=ffprobe_summary,
            deterministic_key=job.deterministic_key or job.compute_deterministic_key(),
        )

    def matches_output_spec(self, spec: OutputSpec) -> tuple[bool, list[str]]:
        """Compare the receipt against the spec it was asked to satisfy (R4).

        Returns mismatches rather than raising: a caller collecting checks across a
        whole production needs the list, not the first exception.
        """
        problems: list[str] = []
        if (self.width, self.height) != (spec.width, spec.height):
            problems.append(
                f"resolution:{self.width}x{self.height}!={spec.width}x{spec.height}"
            )
        if self.fps != spec.fps:
            problems.append(f"fps:{self.fps}!={spec.fps}")
        if abs(self.duration_ms - spec.duration_ms) > _DURATION_TOLERANCE_MS:
            problems.append(f"duration_ms:{self.duration_ms}!={spec.duration_ms}")
        if spec.audio_required and not self.audio_present:
            problems.append("audio_required_but_absent")
        return (not problems, problems)

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["fps"] = str(self.fps)
        return data


#: §32 says "within tolerance". One frame at 30fps is the tightest tolerance that does
#: not fail a correct render on container rounding.
_DURATION_TOLERANCE_MS = 34


__all__ = ["OutputSpec", "RenderJob", "RenderJobStatus", "RenderReceipt"]
