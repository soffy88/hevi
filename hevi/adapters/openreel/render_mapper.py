"""P0.8 — OpenReel render parameters.

Kept separate from ``receipt_mapper`` because the two directions fail differently: a bad
render *request* is a mapping error caught before any work happens, while a bad render
*result* is a receipt error caught after bytes exist. Folding them together would make
the first look like the second.

All values are forwarded as declared. Nothing here decides a resolution, a codec or a
frame rate -- those come from the canonical ``OutputSpec`` on the ``RenderJob``.
"""

from __future__ import annotations

from typing import Any

from hevi.production.render_job import RenderJob


def render_request(job: RenderJob) -> dict[str, Any]:
    """The parameter payload for an OpenReel render action.

    Derived entirely from the canonical job. If OpenReel needs something the job does
    not carry, the job schema is what should change -- not this function inventing a
    default, which would be a second source of render parameters.
    """
    spec = job.output_spec
    return {
        "job_id": job.job_id,
        "scene_id": job.timeline_id or job.production_id,
        "output": str(spec.container),
        "width": spec.width,
        "height": spec.height,
        "fps_numerator": spec.fps.numerator,
        "fps_denominator": spec.fps.denominator,
        "duration_ms": spec.duration_ms,
        "video_codec": spec.video_codec,
        "audio_codec": spec.audio_codec,
        "audio_required": spec.audio_required,
    }


__all__ = ["render_request"]
