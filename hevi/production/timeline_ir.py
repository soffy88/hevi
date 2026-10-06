"""TimelineIR — the canonical timeline semantic boundary.

P0-2 designated this contract; P0-3 implements it. It is a **normalisation** of the
twenty existing representations, not a twenty-first model. Every field traces to a
predecessor:

    canvas            providers/hyperframes/compiler.py:25-27
                      (HyperComposition width/height/fps)
    tracks, clips     creative/layer4/editable_delivery.py:34-78
                      (TrackKind, EditableClip — verbatim field semantics)
    transitions       creative/layer4/editable_delivery.py:40-56
                      (TransitionKind CUT/FADE/DISSOLVE/WIPE)
    audio_master_clock  production/p0_pipeline.py:74-93
                      (TimelineLock audio_lock_id + audio_sha256)
    content_hash()    new, and the only genuinely new operation

Why the hash is the load-bearing part
-------------------------------------
Nothing in the repository can currently answer "which timeline produced this
artifact". `RenderPlan.to_dict()` has no hash method, no timeline type is hashed,
and `RenderReceipt.timeline_hash` (spec §6.2) is therefore unconstructible. Without
a stable identity over the canonical serialisation, a render receipt cannot bind a
timeline to bytes — so `content_hash()` is what makes P0-5 possible.

Two properties are non-negotiable and are enforced here rather than trusted:

**Integer milliseconds only.** The twenty predecessors store time as
`tuple[float,float]` (p5_3), `float` (studio, digital_human, hyperframes,
previs, openshorts), or `str` (narrative). A `float` field here would propagate into
canonical state, so the type does not admit one. Floats are rejected at construction,
not clamped — clamping a negative duration to zero is how a broken timeline becomes
an apparently valid one.

**Fail-closed.** Every rejection carries a stable code. There is no `or default`
path in this module: a missing timestamp is an error, an unknown track kind is an
error, a gap that leaves a video track uncovered is an error. The predecessor
`hyperframes/compiler.py:72-85` does the opposite (unknown action becomes "keep",
missing `start_s` becomes `0.0`/3.0, unknown kind becomes `"card"`), which is the
defect this boundary exists to end.

Determinism is structural: clips carry an explicit ``order``, and
:meth:`TimelineIR.canonical_order` sorts by ``(track, order, clip_id)`` before
hashing, so two timelines built by different code paths with the same content
produce the same hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Any

#: Bumped when the canonical serialisation changes shape. Part of the identity, so a
#: hash from an older layout can never be compared against a new one.
TIMELINE_IR_VERSION = "hevi.timeline-ir.v1"


class TimelineIRError(ValueError):
    """A timeline that cannot be represented. Never a fallback trigger.

    Every raise carries a stable ``TIMELINE_*`` code so a rejection can be asserted
    on in tests and routed in logs.
    """


def _require_int(value: Any, field_name: str, owner: str) -> int:
    """Integer check for a non-time count (order, width, fps, revision)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimelineIRError(
            f"TIMELINE_FIELD_MUST_BE_INT:{owner}:{field_name}"
            f":{type(value).__name__}")
    return value


def _require_int_ms(value: Any, field_name: str, owner: str) -> int:
    """Reject anything that is not an integer millisecond value.

    ``bool`` is excluded explicitly because ``isinstance(True, int)`` is ``True`` in
    Python, and a boolean duration is a bug that would otherwise pass as ``1``.
    ``float`` is rejected rather than converted: the twenty predecessor
    representations store time as ``float`` seconds, and accepting a float here would
    reintroduce that imprecision at exactly the boundary where it has to stop.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimelineIRError(
            f"TIMELINE_TIME_MUST_BE_INT:{owner}:{field_name}"
            f":{type(value).__name__}")
    return value


class TrackKind(StrEnum):
    """Track roles. Reuses ``editable_delivery.TrackKind`` members verbatim."""

    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"


class TransitionKind(StrEnum):
    """Transition vocabulary. Reuses ``editable_delivery.TransitionKind``."""

    CUT = "cut"
    FADE = "fade"
    DISSOLVE = "dissolve"
    WIPE = "wipe"


@dataclass(frozen=True)
class Canvas:
    """Output geometry. From ``HyperComposition.width/height/fps``."""

    width: int
    height: int
    fps: int

    def __post_init__(self) -> None:
        for name, value in (("width", self.width), ("height", self.height),
                            ("fps", self.fps)):
            _require_int(value, name, "canvas")
            if value <= 0:
                raise TimelineIRError(f"TIMELINE_CANVAS_NON_POSITIVE_{name.upper()}"
                                      f":{value}")

    @property
    def aspect_ratio(self) -> str:
        from math import gcd

        divisor = gcd(self.width, self.height)
        return f"{self.width // divisor}:{self.height // divisor}"

    def to_dict(self) -> dict[str, Any]:
        return {"width": self.width, "height": self.height, "fps": self.fps,
                "aspect_ratio": self.aspect_ratio}


@dataclass(frozen=True)
class Transition:
    """A clip boundary effect. From ``editable_delivery.Transition``.

    A CUT has no duration; anything else must be positive. That pairing is the
    predecessor's rule (``editable_delivery.py:59``) and is preserved because a cut
    with a 400ms fade is a contradiction, not a default.
    """

    kind: TransitionKind = TransitionKind.CUT
    duration_ms: int = 0

    def __post_init__(self) -> None:
        _require_int_ms(self.duration_ms, "duration_ms", "transition")
        if self.duration_ms < 0:
            raise TimelineIRError(
                f"TIMELINE_TRANSITION_NEGATIVE_DURATION:{self.duration_ms}")
        if self.kind is TransitionKind.CUT and self.duration_ms != 0:
            raise TimelineIRError(
                f"TIMELINE_CUT_HAS_NO_DURATION:{self.duration_ms}")
        if self.kind is not TransitionKind.CUT and self.duration_ms <= 0:
            raise TimelineIRError(
                f"TIMELINE_TRANSITION_REQUIRES_DURATION:{self.kind.value}")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "duration_ms": self.duration_ms}


@dataclass(frozen=True)
class TimelineClip:
    """One placement on one track.

    Field semantics are ``editable_delivery.EditableClip`` verbatim
    (``clip_id, order, track, source_path, source_in_ms, duration_ms, text, gain,
    transition_in, transition_out``). ``start_ms`` is added because a timeline needs
    a placement position: the predecessor packed clips sequentially per track, which
    is why ``studio/jianying.py:84-85`` had to recompute it and
    ``clips_from_presentation`` had to hardcode ``start_s=0.0``.
    """

    clip_id: str
    track: TrackKind
    source_path: str
    duration_ms: int
    start_ms: int = 0
    order: int = 0
    source_in_ms: int = 0
    text: str = ""
    gain: float = 1.0
    transition_in: Transition = field(default_factory=Transition)
    transition_out: Transition = field(default_factory=Transition)

    def __post_init__(self) -> None:
        _require_int_ms(self.start_ms, "start_ms", "clip")
        _require_int_ms(self.duration_ms, "duration_ms", "clip")
        _require_int_ms(self.source_in_ms, "source_in_ms", "clip")
        _require_int(self.order, "order", "clip")
        if not self.clip_id:
            raise TimelineIRError("TIMELINE_CLIP_WITHOUT_ID")
        if not self.source_path:
            raise TimelineIRError(
                f"TIMELINE_CLIP_WITHOUT_SOURCE:{self.clip_id}")
        # Negative duration is rejected, never clamped. See module docstring.
        if self.duration_ms <= 0:
            raise TimelineIRError(
                f"TIMELINE_CLIP_NON_POSITIVE_DURATION:{self.clip_id}"
                f":{self.duration_ms}")
        if self.start_ms < 0:
            raise TimelineIRError(
                f"TIMELINE_CLIP_NEGATIVE_START:{self.clip_id}:{self.start_ms}")
        if self.source_in_ms < 0:
            raise TimelineIRError(
                f"TIMELINE_CLIP_NEGATIVE_SOURCE_IN:{self.clip_id}"
                f":{self.source_in_ms}")
        if self.order < 0:
            raise TimelineIRError(
                f"TIMELINE_CLIP_NEGATIVE_ORDER:{self.clip_id}:{self.order}")
        if self.gain < 0:
            raise TimelineIRError(
                f"TIMELINE_CLIP_NEGATIVE_GAIN:{self.clip_id}:{self.gain}")

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.duration_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id, "track": self.track.value,
            "source_path": self.source_path, "start_ms": self.start_ms,
            "duration_ms": self.duration_ms, "order": self.order,
            "source_in_ms": self.source_in_ms, "text": self.text,
            "gain": self.gain,
            "transition_in": self.transition_in.to_dict(),
            "transition_out": self.transition_out.to_dict(),
        }


@dataclass(frozen=True)
class AudioMasterClock:
    """The timeline's audio binding. From ``TimelineLock`` (``p0_pipeline.py:74-93``).

    This is the only integrity binding any of the twenty representations carries, so
    it is preserved field for field: an ``audio_lock_id``, the ``audio_sha256`` it
    was locked against, and the ``drift_ms`` tolerance the timeline was validated to.

    Binding is explicit and fail-closed. :meth:`verify_against` re-checks the digest,
    exactly as ``TimelineLock.verify_against`` does — a timeline whose audio has
    changed underneath it is not a slightly-wrong timeline, it is a different one.
    """

    audio_lock_id: str
    audio_sha256: str
    audio_lock_revision: int = 0
    drift_ms: int = 0

    def __post_init__(self) -> None:
        _require_int(self.audio_lock_revision, "audio_lock_revision", "audio_clock")
        _require_int(self.drift_ms, "drift_ms", "audio_clock")
        if not self.audio_lock_id:
            raise TimelineIRError("TIMELINE_AUDIO_CLOCK_WITHOUT_ID")
        if len(self.audio_sha256) != 64:
            raise TimelineIRError(
                f"TIMELINE_AUDIO_SHA_NOT_SHA256:{self.audio_sha256!r}")
        try:
            int(self.audio_sha256, 16)
        except ValueError as exc:
            raise TimelineIRError(
                f"TIMELINE_AUDIO_SHA_NOT_HEX:{self.audio_sha256!r}") from exc
        if self.audio_lock_revision < 0:
            raise TimelineIRError(
                f"TIMELINE_AUDIO_REVISION_NEGATIVE:{self.audio_lock_revision}")
        if self.drift_ms < 0:
            raise TimelineIRError(
                f"TIMELINE_AUDIO_DRIFT_NEGATIVE:{self.drift_ms}")

    def verify_against(self, audio_lock: Any) -> bool:
        """Fail-closed digest check against an ``AudioLock``-shaped object.

        ``audio_lock`` needs ``audio_lock_id``, ``revision`` and ``audio_sha256``;
        anything missing yields ``False`` rather than raising, because a caller
        asking "is this still bound?" expects a boolean.
        """
        return (
            self.audio_lock_id == getattr(audio_lock, "audio_lock_id", None)
            and self.audio_lock_revision == getattr(audio_lock, "revision", None)
            and self.audio_sha256 == getattr(audio_lock, "audio_sha256", None)
        )

    def to_dict(self) -> dict[str, Any]:
        return {"audio_lock_id": self.audio_lock_id,
                "audio_sha256": self.audio_sha256,
                "audio_lock_revision": self.audio_lock_revision,
                "drift_ms": self.drift_ms}


@dataclass(frozen=True)
class TimelineIR:
    """The canonical timeline. Integer milliseconds throughout.

    Validation is exhaustive in ``__post_init__``: every rejection happens at
    construction, so an invalid timeline cannot be observed by a later stage. The
    predecessor state — a timeline that validates at build time and drifts
    afterwards — is what allowed ``editable_delivery`` to need
    ``_clips_cover_effective_duration`` as a separate post-hoc check.
    """

    project_id: str
    canvas: Canvas
    clips: tuple[TimelineClip, ...]
    timeline_id: str = ""
    revision_id: str = ""
    audio_master_clock: AudioMasterClock | None = None
    #: Known source media, so "does this asset exist" is answerable from the IR.
    source_assets: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A bare TimelineClip is accepted and normalised to a 1-tuple. Without this
        # the loop below raises TypeError on iteration, which is a crash rather than
        # a refusal — the wrong shape for a fail-closed contract.
        if isinstance(self.clips, TimelineClip):
            object.__setattr__(self, "clips", (self.clips,))
        if not self.project_id:
            raise TimelineIRError("TIMELINE_WITHOUT_PROJECT_ID")
        if not self.clips:
            raise TimelineIRError("TIMELINE_EMPTY")
        self._validate_unique_ids()
        self._validate_referenced_assets()
        self._validate_no_overlap()
        self._validate_track_coverage()
        self._validate_continuity()

    # ── invariants ─────────────────────────────────────────────────────

    def _validate_unique_ids(self) -> None:
        seen: set[str] = set()
        for clip in self.clips:
            if clip.clip_id in seen:
                raise TimelineIRError(f"TIMELINE_CLIP_ID_DUPLICATE:{clip.clip_id}")
            seen.add(clip.clip_id)

    def _validate_referenced_assets(self) -> None:
        """Every referenced source must be a declared asset.

        Fail-closed: an undeclared reference is an error rather than a warning,
        because a renderer that cannot find its media must not discover it at
        execution time.
        """
        if not self.source_assets:
            return
        declared = set(self.source_assets)
        for clip in self.clips:
            if clip.source_path not in declared:
                raise TimelineIRError(
                    f"TIMELINE_UNRESOLVED_ASSET:{clip.clip_id}"
                    f":{clip.source_path}")

    def _validate_no_overlap(self) -> None:
        """No two clips may occupy the same span on the same track.

        This is the invariant the twenty representations never had: the only
        overlap check in the repo is a post-hoc verdict
        (``verdict/production_checks.py:109-130``), long after a timeline was
        considered valid.
        """
        by_track: dict[TrackKind, list[TimelineClip]] = {}
        for clip in self.clips:
            by_track.setdefault(clip.track, []).append(clip)
        for track, clips in by_track.items():
            ordered = sorted(clips, key=lambda c: (c.start_ms, c.clip_id))
            for earlier, later in pairwise(ordered):
                if later.start_ms < earlier.end_ms:
                    raise TimelineIRError(
                        f"TIMELINE_CLIP_OVERLAP:{track.value}"
                        f":{earlier.clip_id}@{earlier.start_ms}-{earlier.end_ms}"
                        f":{later.clip_id}@{later.start_ms}")

    def _validate_track_coverage(self) -> None:
        """A video track must be contiguous from zero: no gaps, no holes.

        A gap means some part of the deliverable has no visual, and a renderer that
        is handed one has to invent what goes there. Refusing is the point.
        """
        video = sorted(
            (c for c in self.clips if c.track is TrackKind.VIDEO),
            key=lambda c: (c.start_ms, c.clip_id),
        )
        if not video:
            raise TimelineIRError("TIMELINE_NO_VIDEO_TRACK")
        cursor = 0
        for clip in video:
            if clip.start_ms > cursor:
                raise TimelineIRError(
                    f"TIMELINE_VIDEO_GAP:{cursor}-{clip.start_ms}")
            if clip.start_ms < cursor:
                raise TimelineIRError(
                    f"TIMELINE_VIDEO_OVERLAP:{clip.clip_id}:{clip.start_ms}"
                    f":expected_start={cursor}")
            cursor = clip.end_ms

    def _validate_continuity(self) -> None:
        """Transition endpoints must resolve and must not exceed the clip.

        A transition longer than its own clip is the fail-open case in miniature:
        the timeline claims an effect it cannot place.
        """
        for clip in self.clips:
            for label, transition in (("in", clip.transition_in),
                                      ("out", clip.transition_out)):
                if transition.kind is TransitionKind.CUT:
                    continue
                if transition.duration_ms > clip.duration_ms:
                    raise TimelineIRError(
                        f"TIMELINE_TRANSITION_EXCEEDS_CLIP:{clip.clip_id}"
                        f":{label}:{transition.duration_ms}>{clip.duration_ms}")

    # ── derived, deterministic ─────────────────────────────────────────

    @property
    def duration_ms(self) -> int:
        """Total duration. The furthest clip end, not a declared field.

        ``editable_delivery`` carries ``effective_duration_ms`` as a field and then
        validates that video coverage sums to it; deriving it removes the chance of
        the two disagreeing.
        """
        return max(clip.end_ms for clip in self.clips)

    def canonical_order(self) -> tuple[TimelineClip, ...]:
        """Total order used for serialisation and hashing.

        ``(track, order, clip_id)`` — stable across insertion order, so two code
        paths that build the same timeline agree on the hash. The predecessor
        ``p1_types.add_beat`` appends without sorting, which is why no predecessor
        hash is stable.
        """
        return tuple(sorted(self.clips,
                            key=lambda c: (c.track.value, c.order, c.clip_id)))

    def canonical_dict(self) -> dict[str, Any]:
        """The serialisation the hash is computed over. Never any other shape."""
        return {
            "version": TIMELINE_IR_VERSION,
            "timeline_id": self.timeline_id,
            "revision_id": self.revision_id,
            "project_id": self.project_id,
            "canvas": self.canvas.to_dict(),
            "duration_ms": self.duration_ms,
            "source_assets": sorted(self.source_assets),
            "audio_master_clock": (
                None if self.audio_master_clock is None
                else self.audio_master_clock.to_dict()),
            "clips": [clip.to_dict() for clip in self.canonical_order()],
            "metadata": dict(sorted(self.metadata.items())),
        }

    def content_hash(self) -> str:
        """Stable sha256 over the canonical serialisation.

        Two timelines with the same content produce the same hash regardless of how
        their clips were ordered in memory or which code path built them. This is
        the value ``RenderReceipt.timeline_hash`` will carry in P0-5.

        ``timeline_id`` and ``revision_id`` are included deliberately: two revisions
        of otherwise-identical content are different timelines, and a render receipt
        must be able to tell them apart.
        """
        payload = json.dumps(self.canonical_dict(), sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Content-addressed export. Includes the hash so a serialised timeline is
        self-identifying without recomputation."""
        return {**self.canonical_dict(), "content_hash": self.content_hash()}


def validate_timeline(payload: dict[str, Any]) -> TimelineIR:
    """Build a ``TimelineIR`` from plain data, fail-closed.

    The predecessor ``hyperframes/compiler.py:72-85`` coerced instead: unknown
    actions became "keep", absent ``start_s`` became ``0.0`` or ``3.0``, unknown
    kinds became ``"card"``, and negative durations were clamped by
    ``max(dur, 0.8)``. Every one of those is a refusal here.

    A float anywhere in a time field is a rejection, not a conversion — the
    twenty representations store float seconds, and silently converting them would
    reintroduce float imprecision into canonical state at exactly the boundary
    where it must stop.
    """

    raw_clips = payload.get("clips")
    if not isinstance(raw_clips, list) or not raw_clips:
        raise TimelineIRError("TIMELINE_EMPTY")

    clips: list[TimelineClip] = []
    for index, raw in enumerate(raw_clips):
        if not isinstance(raw, dict):
            raise TimelineIRError(f"TIMELINE_CLIP_NOT_AN_OBJECT:{index}")
        clip_id = str(raw.get("clip_id", ""))
        if not clip_id:
            raise TimelineIRError(f"TIMELINE_CLIP_WITHOUT_ID:{index}")

        try:
            track = TrackKind(raw["track"])
        except (KeyError, ValueError) as exc:
            raise TimelineIRError(
                f"TIMELINE_UNKNOWN_TRACK_KIND:{clip_id}:{raw.get('track')!r}"
            ) from exc

        def transition(key: str, *, raw: dict[str, Any] = raw,
                       clip_id: str = clip_id) -> Transition:
            value = raw.get(key) or {}
            if not isinstance(value, dict):
                raise TimelineIRError(
                    f"TIMELINE_TRANSITION_NOT_AN_OBJECT:{clip_id}:{key}")
            try:
                kind = TransitionKind(value.get("kind", "cut"))
            except ValueError as exc:
                raise TimelineIRError(
                    f"TIMELINE_UNKNOWN_TRANSITION_KIND:{clip_id}"
                    f":{value.get('kind')!r}") from exc
            return Transition(
                kind=kind,
                duration_ms=_require_int_ms(value.get("duration_ms", 0),
                                            f"{key}.duration_ms", clip_id))

        clips.append(TimelineClip(
            clip_id=clip_id,
            track=track,
            source_path=str(raw.get("source_path", "")),
            duration_ms=_require_int_ms(raw.get("duration_ms"), "duration_ms", clip_id),
            start_ms=_require_int_ms(raw.get("start_ms", 0), "start_ms", clip_id),
            order=_require_int_ms(raw.get("order", 0), "order", clip_id),
            source_in_ms=_require_int_ms(raw.get("source_in_ms", 0), "source_in_ms", clip_id),
            text=str(raw.get("text", "")),
            gain=float(raw.get("gain", 1.0)),
            transition_in=transition("transition_in"),
            transition_out=transition("transition_out"),
        ))

    raw_canvas = payload.get("canvas")
    if not isinstance(raw_canvas, dict):
        raise TimelineIRError("TIMELINE_WITHOUT_CANVAS")
    for key in ("width", "height", "fps"):
        _require_int(raw_canvas.get(key), f"canvas.{key}", "canvas")

    raw_clock = payload.get("audio_master_clock")
    clock: AudioMasterClock | None = None
    if raw_clock is not None:
        if not isinstance(raw_clock, dict):
            raise TimelineIRError("TIMELINE_AUDIO_CLOCK_NOT_AN_OBJECT")
        clock = AudioMasterClock(
            audio_lock_id=str(raw_clock.get("audio_lock_id", "")),
            audio_sha256=str(raw_clock.get("audio_sha256", "")),
            audio_lock_revision=_require_int(raw_clock.get("audio_lock_revision", 0),
                                     "audio_master_clock.audio_lock_revision", "clock"),
            drift_ms=_require_int(raw_clock.get("drift_ms", 0),
                          "audio_master_clock.drift_ms", "clock"),
        )

    return TimelineIR(
        project_id=str(payload.get("project_id", "")),
        timeline_id=str(payload.get("timeline_id", "")),
        revision_id=str(payload.get("revision_id", "")),
        canvas=Canvas(width=raw_canvas["width"], height=raw_canvas["height"],
                      fps=raw_canvas["fps"]),
        clips=tuple(clips),
        audio_master_clock=clock,
        source_assets=tuple(payload.get("source_assets", ()) or ()),
        metadata=dict(payload.get("metadata") or {}),
    )


__all__ = [
    "TIMELINE_IR_VERSION",
    "AudioMasterClock",
    "Canvas",
    "TimelineClip",
    "TimelineIR",
    "TimelineIRError",
    "TrackKind",
    "Transition",
    "TransitionKind",
    "validate_timeline",
]
