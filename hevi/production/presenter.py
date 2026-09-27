"""HEVI P5.2 — presenter production.

A digital presenter is generated *from* the finished audio, never the other way
round. The canonical P0 ``AudioLock`` is the master clock; the presenter is made
to fit it. Generating a presenter first and then forcing narration onto it is the
single most common way a talking-head video ends up with drifting lip-sync, and
it is refused here.

This is not a new profile registry and not a new provider registry. It declares
a plan, resolves a provider through the existing capability matrix, and records
an artifact whose continuity is auditable across shots.

The presenter also does not take over the film. A presenter's visibility is a
per-shot decision compatible with P5.1's speaker/evidence semantics, so the
presenter can hand the frame to real product evidence and come back as a
picture-in-picture without regenerating the presenter asset.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class PresenterScale(StrEnum):
    """How much of the frame the presenter occupies in a given shot."""

    FULL = "FULL"
    MEDIUM = "MEDIUM"
    PIP = "PIP"
    HIDDEN = "HIDDEN"


class PresenterLipSyncPolicy(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    NONE = "NONE"


class PresenterBackgroundPolicy(StrEnum):
    TRANSPARENT = "TRANSPARENT"
    CHROME_KEY = "CHROME_KEY"
    SOLID = "SOLID"
    REAL = "REAL"


class PresenterProviderCapability(StrEnum):
    AVATAR_GENERATION = "AVATAR_GENERATION"
    LIP_SYNC = "LIP_SYNC"
    SOURCE_IMAGE = "SOURCE_IMAGE"
    SOURCE_VIDEO = "SOURCE_VIDEO"
    VOICE_CLONING = "VOICE_CLONING"


#: Presenter providers declare these through the existing registry capability
#: surface. HEVI does not hardcode a product as the authority.
PRESENTER_CAPABILITY = PresenterProviderCapability.AVATAR_GENERATION.value
LIPSYNC_CAPABILITY = PresenterProviderCapability.LIP_SYNC.value


@dataclass
class AudioLock:
    """The canonical audio the presenter must fit.

    ``P5_PRESENTER_AUDIO_DRIFT`` is measured against this, not against a
    separately-trimmed copy.
    """

    audio_lock_id: str
    audio_path: str
    audio_hash: str
    duration_s: float
    sample_rate: int = 48000

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PresenterShotRange:
    """A span of the master timeline the presenter occupies."""

    shot_id: str
    start_s: float
    end_s: float
    scale: PresenterScale = PresenterScale.MEDIUM
    semantic_role: str = "DIRECT_ADDRESS"

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scale"] = self.scale.value
        return d


@dataclass
class PresenterPlan:
    """How the presenter will be produced and where it appears."""

    plan_id: str
    presenter_entity_id: str
    audio_lock: AudioLock
    provider_capability: str = PRESENTER_CAPABILITY
    provider_id: str = ""
    presentation_style: str = "DIRECT_ADDRESS"
    shot_ranges: list[PresenterShotRange] = field(default_factory=list)
    background_policy: PresenterBackgroundPolicy = PresenterBackgroundPolicy.TRANSPARENT
    lip_sync_policy: PresenterLipSyncPolicy = PresenterLipSyncPolicy.REQUIRED
    framing_policy: str = "medium"
    source_image: str = ""
    source_video: str = ""
    voice_artifact: str = ""
    voice_identity_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["background_policy"] = self.background_policy.value
        d["lip_sync_policy"] = self.lip_sync_policy.value
        d["shot_ranges"] = [r.to_dict() for r in self.shot_ranges]
        return d


@dataclass
class PresenterArtifact:
    """A produced presenter clip, with lineage to its audio lock."""

    presenter_id: str
    entity_id: str
    provider: str
    source_image: str = ""
    source_video: str = ""
    audio_hash: str = ""
    video_hash: str = ""
    video_path: str = ""
    duration_s: float = 0.0
    lip_sync_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    scale: PresenterScale = PresenterScale.MEDIUM
    background_policy: PresenterBackgroundPolicy = PresenterBackgroundPolicy.TRANSPARENT
    frame_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scale"] = self.scale.value
        d["background_policy"] = self.background_policy.value
        return d


@dataclass
class PresenterIssue:
    kind: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PresenterQaReport:
    ok: bool = True
    issues: list[PresenterIssue] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_presenter_provider(
    candidates: list[Any], *, require_lip_sync: bool = True
) -> tuple[Any | None, str]:
    """Pick a presenter provider from the existing capability matrix.

    HEVI declares what it needs; the provider registry decides who can do it. No
    product is hardcoded as the authority, and a provider that cannot lip-sync
    is not silently accepted for a plan that requires it.
    """
    rejected: list[str] = []
    for provider in candidates:
        capabilities = {
            getattr(c, "value", str(c)) for c in getattr(provider, "capabilities", [])
        }
        if PRESENTER_CAPABILITY not in capabilities:
            rejected.append(f"{provider}:missing:{PRESENTER_CAPABILITY}")
            continue
        if require_lip_sync and LIPSYNC_CAPABILITY not in capabilities:
            rejected.append(f"{provider}:missing:{LIPSYNC_CAPABILITY}")
            continue
        return provider, f"CAPABILITY_MATCH:{sorted(capabilities & {PRESENTER_CAPABILITY, LIPSYNC_CAPABILITY})}"
    return None, "NO_CAPABLE_PROVIDER:" + ";".join(rejected)


def build_presenter_plan(
    *,
    plan_id: str,
    presenter_entity_id: str,
    audio_lock: AudioLock,
    shot_ranges: list[PresenterShotRange] | None = None,
    provider_id: str = "",
    source_image: str = "",
    source_video: str = "",
    voice_identity_ref: str = "",
    lip_sync_policy: PresenterLipSyncPolicy | None = None,
    provider_capability: str = "",
    background_policy: PresenterBackgroundPolicy | None = None,
) -> PresenterPlan:
    """Build a presenter plan bound to a finished audio lock.

    How the presenter came into existence is recorded from what was actually
    supplied, never defaulted to "generated". A plan handed a real source clip
    is a ``SOURCE_VIDEO`` plan: the background is the one already in that
    footage, and the lip sync is whatever the real performance had, so demanding
    a fresh lip-sync pass on it would be nonsense. Defaulting those fields to
    generation semantics would make the plan claim a generation that never
    happened, which is the one thing a provenance record must not do.
    """
    if audio_lock.duration_s <= 0:
        raise ValueError("AUDIO_LOCK_EMPTY: presenter generation needs a finished voice track")

    if provider_capability:
        capability = provider_capability
    elif source_video:
        capability = PresenterProviderCapability.SOURCE_VIDEO.value
    elif source_image:
        capability = PresenterProviderCapability.SOURCE_IMAGE.value
    else:
        capability = PresenterProviderCapability.AVATAR_GENERATION.value

    if background_policy is not None:
        background = background_policy
    elif source_video:
        background = PresenterBackgroundPolicy.REAL
    else:
        background = PresenterBackgroundPolicy.TRANSPARENT

    if lip_sync_policy is not None:
        lip_sync = lip_sync_policy
    elif source_video:
        lip_sync = PresenterLipSyncPolicy.NONE
    else:
        lip_sync = PresenterLipSyncPolicy.REQUIRED

    return PresenterPlan(
        plan_id=plan_id,
        presenter_entity_id=presenter_entity_id,
        audio_lock=audio_lock,
        provider_capability=capability,
        provider_id=provider_id,
        shot_ranges=shot_ranges or [],
        source_image=source_image,
        source_video=source_video,
        background_policy=background,
        voice_identity_ref=voice_identity_ref,
        lip_sync_policy=lip_sync,
    )


def assert_audio_lock(
    plan: PresenterPlan, audio_path: str, audio_hash: str, duration_s: float
) -> None:
    """Refuse a presenter built against the wrong audio (adversarial A8)."""
    import hashlib
    from pathlib import Path

    path = Path(audio_path)
    if not path.is_file():
        raise ValueError(f"AUDIO_LOCK_MISSING:{audio_path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    actual = f"sha256:{digest.hexdigest()}"
    if audio_hash and actual != audio_hash:
        raise ValueError(f"PRESENTER_AUDIO_HASH_MISMATCH:{actual[:19]}!={audio_hash[:19]}")
    if plan.audio_lock.duration_s and abs(duration_s - plan.audio_lock.duration_s) > 0.25:
        raise ValueError(
            f"PRESENTER_AUDIO_DRIFT:{duration_s:.3f} vs lock {plan.audio_lock.duration_s:.3f}"
        )


def check_presenter_qa(
    artifact: PresenterArtifact,
    plan: PresenterPlan,
    *,
    audio_duration_s: float = 0.0,
    continuity: dict[str, str] | None = None,
) -> PresenterQaReport:
    """Run presenter QA (§34).

    Checks duration against the lock, truncation, the existence of lip-sync
    metadata, cross-shot visual continuity and the audio hash.
    """
    report = PresenterQaReport()

    report.checked.append("duration_matches_audio_lock")
    if plan.audio_lock.duration_s and abs(artifact.duration_s - plan.audio_lock.duration_s) > 0.35:
        report.issues.append(
            PresenterIssue(
                "PRESENTER_DURATION_MISMATCH",
                f"presenter {artifact.duration_s:.3f}s vs lock {plan.audio_lock.duration_s:.3f}s",
            )
        )

    report.checked.append("no_truncation")
    if (
        artifact.duration_s > 0
        and audio_duration_s > 0
        and artifact.duration_s + 0.35 < audio_duration_s
    ):
        report.issues.append(
            PresenterIssue(
                "PRESENTER_TRUNCATES_NARRATION",
                f"presenter ends {audio_duration_s - artifact.duration_s:.3f}s before the narration",
            )
        )

    report.checked.append("lip_sync_artifact_exists")
    if plan.lip_sync_policy is PresenterLipSyncPolicy.REQUIRED and not artifact.lip_sync_metadata:
        report.issues.append(
            PresenterIssue("LIP_SYNC_METADATA_MISSING", "policy requires lip sync but none recorded")
        )

    report.checked.append("audio_hash_correct")
    if plan.audio_lock.audio_hash and artifact.audio_hash != plan.audio_lock.audio_hash:
        report.issues.append(
            PresenterIssue(
                "PRESENTER_AUDIO_HASH_MISMATCH",
                f"{artifact.audio_hash[:19]} != {plan.audio_lock.audio_hash[:19]}",
            )
        )

    report.checked.append("visual_continuity")
    for key, expected in (continuity or {}).items():
        actual = (artifact.provenance.get("continuity") or {}).get(key, "")
        if actual and expected and actual != expected:
            report.issues.append(
                PresenterIssue("PRESENTER_CONTINUITY_DRIFT", f"{key}:{actual}!={expected}")
            )

    report.ok = not report.issues
    return report


def scale_for_role(role: str, *, evidence_visible: bool) -> PresenterScale:
    """Map an editorial role to a presenter scale.

    Compatible with P5.1's speaker/evidence semantics: when real evidence owns
    the frame the presenter steps down to a picture-in-picture rather than
    disappearing or taking over.
    """
    if evidence_visible:
        return PresenterScale.PIP
    if role in ("DIRECT_ADDRESS", "EMOTIONAL_PRESENCE"):
        return PresenterScale.MEDIUM
    if role == "CONTEXTUAL_BROLL":
        return PresenterScale.PIP
    return PresenterScale.HIDDEN


def validate_presentation_mix(
    shot_ranges: list[PresenterShotRange], *, minimum_role_switches: int = 2
) -> tuple[bool, list[str]]:
    """Reject a cut that is presenter-full-screen for every shot (adversarial A10).

    The switch requirement is capped at what the cut can physically contain: a
    two-shot cut has one boundary, so demanding two switches from it would fail a
    perfectly reasonable edit.
    """
    violations: list[str] = []
    if not shot_ranges:
        return False, ["NO_PRESENTER_SHOTS"]
    full = [r for r in shot_ranges if r.scale is PresenterScale.FULL]
    if len(full) == len(shot_ranges) and len(shot_ranges) >= 3:
        violations.append("PRESENTER_FULL_SCREEN_EVERYWHERE")
    switches = sum(
        1 for a, b in itertools.pairwise(shot_ranges) if a.scale is not b.scale
    )
    achievable = min(minimum_role_switches, max(0, len(shot_ranges) - 1))
    if switches < achievable:
        violations.append(f"PRESENTER_SCALE_SWITCHES_{switches}_BELOW_{achievable}")
    return (not violations), violations


__all__ = [
    "LIPSYNC_CAPABILITY",
    "PRESENTER_CAPABILITY",
    "AudioLock",
    "PresenterArtifact",
    "PresenterBackgroundPolicy",
    "PresenterIssue",
    "PresenterLipSyncPolicy",
    "PresenterPlan",
    "PresenterProviderCapability",
    "PresenterQaReport",
    "PresenterScale",
    "PresenterShotRange",
    "assert_audio_lock",
    "build_presenter_plan",
    "check_presenter_qa",
    "resolve_presenter_provider",
    "scale_for_role",
    "validate_presentation_mix",
]
