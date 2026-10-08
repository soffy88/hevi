"""P0.8 — HEVI TimelineIR ↔ OpenReel timeline (bounded view).

§13 forbids creating a second timeline. This is not one: it is a *projection* of the
canonical `TimelineIR` into the flat track/clip shape OpenReel's action layer uses, and
nothing here may be read back as timeline truth. `hevi/production/timeline_adapters.py`
already owns legacy-timeline projection for the same reason.

The direction matters. ``to_openreel_timeline`` reads `TimelineIR` and emits. There is
deliberately no ``from_openreel_timeline``: §42 forbids OpenReel actions becoming HEVI
semantic intent, and a two-way mapping is how that would creep in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hevi.production.timeline_ir import TimelineIR


@dataclass(frozen=True)
class OpenReelTimeline:
    """Flat track/clip view for the OpenReel action layer."""

    timeline_id: str
    #: §14: the canonical content hash travels with every projection, so an artifact
    #: built from this timeline can cite what it was built from.
    content_hash: str
    duration_ms: int
    tracks: tuple[dict[str, Any], ...]


def to_openreel_timeline(timeline: TimelineIR) -> OpenReelTimeline:
    """Project a canonical TimelineIR into OpenReel's shape.

    Read-only. No semantic judgement is applied: track kinds, clip placement and
    durations are carried across as declared, because this adapter is not the authority
    for any of them.
    """
    # Grouped by track kind. `canonical_order()` is used rather than the raw `clips`
    # tuple so the projection is stable across insertion order -- otherwise the same
    # timeline built by two code paths would produce different action payloads and
    # defeat both idempotency and the render cache.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for clip in timeline.canonical_order():
        grouped.setdefault(clip.track.value, []).append(
            {
                "clip_id": clip.clip_id,
                "start_ms": clip.start_ms,
                "duration_ms": clip.duration_ms,
                "order": clip.order,
                "source_path": clip.source_path,
                "text": clip.text,
                "gain": clip.gain,
            }
        )

    tracks = tuple(
        {"index": index, "kind": kind, "clips": tuple(clips)}
        for index, (kind, clips) in enumerate(sorted(grouped.items()))
    )
    return OpenReelTimeline(
        timeline_id=timeline.timeline_id,
        content_hash=timeline.content_hash(),
        duration_ms=timeline.duration_ms,
        tracks=tracks,
    )


__all__ = ["OpenReelTimeline", "to_openreel_timeline"]
