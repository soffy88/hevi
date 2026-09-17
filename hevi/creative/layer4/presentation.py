"""Canonical presentation read model (Gap Closure W1, ARC-G01).

A presentation is the single deterministic answer to "what does the user
see / download / compose / subtitle / hand to Jianying": which video
artifact, which audio artifact, which subtitle artifact, in which versions,
at which real media durations. Studio preview, final composition,
download/export, subtitle rendering, Jianying export, and future publishing
must project from one committed :class:`PresentationSnapshot` instead of
re-selecting independently (split-brain presentation).

This module is a *read model*, not a production authority: it never
re-derives production decisions. Every field traces to an existing
authority (Production Graph revisions, Artifact Manifest entries, revision
or version state, probed media metadata). Selection without evidence is
refused with explicit error codes; requested/planned durations are never
used as a fallback for real durations.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AudioMode(StrEnum):
    """Which sound the presentation carries."""

    NATIVE = "native"
    TTS = "tts"
    UPLOADED = "uploaded"
    SILENT = "silent"


class MediaSourceType(StrEnum):
    """Provenance class of a selected artifact."""

    GENERATED = "generated"
    MANUAL_RAW = "manual_raw"


class DurationPolicy(StrEnum):
    """Explicit rule for collapsing real video/audio durations into one."""

    VIDEO_LED = "video_led"
    AUDIO_LED = "audio_led"
    TRIM_TO_SHORTEST = "trim_to_shortest"


class PresentationError(ValueError):
    """Selection/materialization refusal with a stable machine code."""


class CandidateMedia(BaseModel):
    """One selectable artifact offered to the selector, in preference order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    path: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    source_type: MediaSourceType = MediaSourceType.GENERATED
    dependency_revision: str = Field(min_length=1)
    provider_id: str | None = None
    generation_prompt_ref: str | None = None

    @model_validator(mode="after")
    def _manual_raw_carries_no_generation_claims(self) -> CandidateMedia:
        if self.source_type == MediaSourceType.MANUAL_RAW and (
            self.provider_id is not None or self.generation_prompt_ref is not None
        ):
            raise PresentationError("PRESENTATION_MANUAL_RAW_FORBIDDEN_PROVENANCE")
        return self


class SelectedMedia(BaseModel):
    """A committed selection with per-field provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    version: int
    path: str
    kind: str
    source_type: MediaSourceType
    currency_at_selection: Literal["CURRENT", "STALE", "HISTORY"]
    actual_duration_ms: int = Field(ge=0)
    provenance: tuple[str, ...]


class PresentationSnapshot(BaseModel):
    """Materialized answer to what the user sees and exports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: UUID = Field(default_factory=uuid4)
    project_id: str = Field(min_length=1)
    production_run_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    video: SelectedMedia
    audio: SelectedMedia | None = None
    audio_mode: AudioMode
    subtitle: SelectedMedia | None = None
    actual_video_duration_ms: int = Field(ge=0)
    actual_audio_duration_ms: int = Field(ge=0)
    effective_duration_ms: int = Field(ge=0)
    duration_policy: DurationPolicy
    duration_decision: str = Field(min_length=1)
    aspect_ratio: str = Field(min_length=1)
    presentation_version: int = Field(ge=1)
    history_source_version: int | None = None
    source_graph_revision: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _is_current(candidate: CandidateMedia, dependency_revisions: Mapping[str, str]) -> bool:
    """A candidate is current when its dependency revision still matches.

    Only keys present in ``dependency_revisions`` are compared, so callers
    declare exactly which dependencies gate freshness; anything undeclared
    cannot silently flip currency.
    """

    if not dependency_revisions:
        return True
    for key, revision in dependency_revisions.items():
        marker = f"{key}@{revision}"
        if marker in candidate.dependency_revision or candidate.dependency_revision == revision:
            return True
    return False


class PresentationSelector:
    """Deterministic materialization of snapshots from existing authorities."""

    def select(
        self,
        *,
        project_id: str,
        production_run_id: str,
        revision_id: str,
        scope_id: str,
        video_candidates: tuple[CandidateMedia, ...],
        actual_durations_ms: Mapping[str, int],
        audio_mode: AudioMode,
        audio_candidates: tuple[CandidateMedia, ...] = (),
        subtitle_candidates: tuple[CandidateMedia, ...] = (),
        dependency_revisions: Mapping[str, str] | None = None,
        allow_stale: bool = False,
        pinned_video_id: str | None = None,
        pinned_audio_id: str | None = None,
        pinned_subtitle_id: str | None = None,
        duration_policy: DurationPolicy = DurationPolicy.VIDEO_LED,
        aspect_ratio: str = "16:9",
        presentation_version: int = 1,
        history_source_version: int | None = None,
        source_graph_revision: str = "",
    ) -> PresentationSnapshot:
        """Select and materialize one snapshot; refuses on missing evidence.

        Preference order decides between qualified candidates; nothing is
        re-derived. Real durations are mandatory: ``actual_durations_ms``
        must contain every selected artifact id, otherwise selection fails
        instead of falling back to requested durations.
        """

        deps = dict(dependency_revisions or {})
        video = self._pick(
            video_candidates,
            role="video",
            deps=deps,
            allow_stale=allow_stale,
            pinned_id=pinned_video_id,
        )
        audio: CandidateMedia | None = None
        if audio_mode is not AudioMode.SILENT:
            if not audio_candidates:
                raise PresentationError("PRESENTATION_AUDIO_MODE_NEEDS_CANDIDATES")
            audio = self._pick(
                audio_candidates,
                role="audio",
                deps=deps,
                allow_stale=allow_stale,
                pinned_id=pinned_audio_id,
            )
        subtitle: CandidateMedia | None = None
        if subtitle_candidates:
            subtitle = self._pick(
                subtitle_candidates,
                role="subtitle",
                deps=deps,
                allow_stale=allow_stale,
                pinned_id=pinned_subtitle_id,
            )
        video_ms = self._actual_ms(video, actual_durations_ms)
        audio_ms = self._actual_ms(audio, actual_durations_ms) if audio is not None else 0
        effective_ms, decision = self._collapse(video_ms, audio_ms, audio_mode, duration_policy)
        return PresentationSnapshot(
            project_id=project_id,
            production_run_id=production_run_id,
            revision_id=revision_id,
            scope_id=scope_id,
            video=self._freeze(video, video_ms, deps, history_source_version),
            audio=self._freeze(audio, audio_ms, deps, history_source_version) if audio else None,
            audio_mode=audio_mode,
            subtitle=self._freeze_subtitle(
                subtitle, actual_durations_ms, deps, history_source_version
            ),
            actual_video_duration_ms=video_ms,
            actual_audio_duration_ms=audio_ms,
            effective_duration_ms=effective_ms,
            duration_policy=duration_policy,
            duration_decision=decision,
            aspect_ratio=aspect_ratio,
            presentation_version=presentation_version,
            history_source_version=history_source_version,
            source_graph_revision=source_graph_revision or revision_id,
        )

    @staticmethod
    def _pick(
        candidates: tuple[CandidateMedia, ...],
        *,
        role: str,
        deps: Mapping[str, str],
        allow_stale: bool,
        pinned_id: str | None,
    ) -> CandidateMedia:
        if pinned_id is not None:
            for candidate in candidates:
                if candidate.artifact_id == pinned_id:
                    return candidate
            raise PresentationError(f"PRESENTATION_PINNED_{role.upper()}_NOT_OFFERED")
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.artifact_id in seen:
                raise PresentationError(f"PRESENTATION_AMBIGUOUS_{role.upper()}_SELECTION")
            seen.add(candidate.artifact_id)
        for candidate in candidates:
            current = _is_current(candidate, deps)
            if current or allow_stale:
                return candidate
        raise PresentationError(f"PRESENTATION_NO_QUALIFIED_{role.upper()}_MEDIA")

    @staticmethod
    def _actual_ms(candidate: CandidateMedia | None, actual_durations_ms: Mapping[str, int]) -> int:
        if candidate is None:
            return 0
        try:
            value = actual_durations_ms[candidate.artifact_id]
        except KeyError:
            raise PresentationError("PRESENTATION_DURATION_UNKNOWN") from None
        if value < 0:
            raise PresentationError("PRESENTATION_DURATION_UNKNOWN")
        return value

    @staticmethod
    def _collapse(
        video_ms: int, audio_ms: int, audio_mode: AudioMode, policy: DurationPolicy
    ) -> tuple[int, str]:
        if audio_mode is AudioMode.SILENT or audio_ms == 0:
            return video_ms, f"video-led: no audio track, effective=video {video_ms}ms"
        if policy is DurationPolicy.VIDEO_LED:
            return (
                video_ms,
                f"video-led: effective=video {video_ms}ms; audio {audio_ms}ms mixed under",
            )
        if policy is DurationPolicy.AUDIO_LED:
            return (
                audio_ms,
                f"audio-led: effective=audio {audio_ms}ms; video {video_ms}ms trimmed/padded",
            )
        effective = min(video_ms, audio_ms)
        return (
            effective,
            f"trim-to-shortest: effective={effective}ms from video {video_ms}ms audio {audio_ms}ms",
        )

    @staticmethod
    def _freeze(
        candidate: CandidateMedia,
        duration_ms: int,
        deps: Mapping[str, str],
        history_source_version: int | None,
    ) -> SelectedMedia:
        if history_source_version is not None:
            currency: Literal["CURRENT", "STALE", "HISTORY"] = "HISTORY"
        elif _is_current(candidate, deps):
            currency = "CURRENT"
        else:
            currency = "STALE"
        return SelectedMedia(
            artifact_id=candidate.artifact_id,
            version=candidate.version,
            path=candidate.path,
            kind=candidate.kind,
            source_type=candidate.source_type,
            currency_at_selection=currency,
            actual_duration_ms=duration_ms,
            provenance=(
                f"manifest:{candidate.artifact_id}#v{candidate.version}",
                f"dependency:{candidate.dependency_revision}",
                f"source:{candidate.source_type.value}",
            ),
        )

    def _freeze_subtitle(
        self,
        candidate: CandidateMedia | None,
        actual_durations_ms: Mapping[str, int],
        deps: Mapping[str, str],
        history_source_version: int | None,
    ) -> SelectedMedia | None:
        if candidate is None:
            return None
        return self._freeze(
            candidate, self._actual_ms(candidate, actual_durations_ms), deps, history_source_version
        )


def _selection_view(snapshot: PresentationSnapshot) -> dict[str, Any]:
    """Shared selection core: every reader projects from this, never reselects."""

    return {
        "snapshot_id": str(snapshot.snapshot_id),
        "project_id": snapshot.project_id,
        "production_run_id": snapshot.production_run_id,
        "revision_id": snapshot.revision_id,
        "scope_id": snapshot.scope_id,
        "video_artifact_id": snapshot.video.artifact_id,
        "video_version": snapshot.video.version,
        "video_path": snapshot.video.path,
        "video_source": snapshot.video.source_type.value,
        "audio_artifact_id": snapshot.audio.artifact_id if snapshot.audio else None,
        "audio_version": snapshot.audio.version if snapshot.audio else None,
        "audio_path": snapshot.audio.path if snapshot.audio else None,
        "audio_mode": snapshot.audio_mode.value,
        "subtitle_artifact_id": snapshot.subtitle.artifact_id if snapshot.subtitle else None,
        "subtitle_version": snapshot.subtitle.version if snapshot.subtitle else None,
        "subtitle_path": snapshot.subtitle.path if snapshot.subtitle else None,
        "actual_video_duration_ms": snapshot.actual_video_duration_ms,
        "actual_audio_duration_ms": snapshot.actual_audio_duration_ms,
        "effective_duration_ms": snapshot.effective_duration_ms,
        "duration_policy": snapshot.duration_policy.value,
        "duration_decision": snapshot.duration_decision,
        "aspect_ratio": snapshot.aspect_ratio,
        "presentation_version": snapshot.presentation_version,
        "currency": {
            "video": snapshot.video.currency_at_selection,
            "audio": snapshot.audio.currency_at_selection if snapshot.audio else None,
            "subtitle": snapshot.subtitle.currency_at_selection if snapshot.subtitle else None,
        },
    }


def for_preview(snapshot: PresentationSnapshot) -> dict[str, Any]:
    """Studio preview view: same selection, preview affordances only."""

    return {**_selection_view(snapshot), "reader": "preview"}


def for_composition(snapshot: PresentationSnapshot) -> dict[str, Any]:
    """Final-composition view: same selection plus assembly inputs."""

    return {
        **_selection_view(snapshot),
        "reader": "composition",
        "assembly": {
            "video_path": snapshot.video.path,
            "audio_path": snapshot.audio.path if snapshot.audio else None,
            "audio_mode": snapshot.audio_mode.value,
            "effective_duration_ms": snapshot.effective_duration_ms,
        },
    }


def for_download(snapshot: PresentationSnapshot) -> dict[str, Any]:
    """Download/export view: same selection, delivery paths only."""

    return {**_selection_view(snapshot), "reader": "download"}


def for_subtitles(
    snapshot: PresentationSnapshot, cues: tuple[dict[str, Any], ...] = ()
) -> dict[str, Any]:
    """Subtitle-rendering view: binds caller-loaded cues to effective duration."""

    clipped = [
        cue for cue in cues if float(cue.get("start_ms", 0)) < snapshot.effective_duration_ms
    ]
    return {
        **_selection_view(snapshot),
        "reader": "subtitles",
        "cues": clipped,
        "cue_count": len(clipped),
    }


def for_jianying(snapshot: PresentationSnapshot) -> dict[str, Any]:
    """Jianying/editable-export view: track layout from the same selection."""

    tracks: list[dict[str, Any]] = [
        {
            "track": "video",
            "path": snapshot.video.path,
            "duration_ms": snapshot.effective_duration_ms,
            "source": snapshot.video.source_type.value,
        }
    ]
    if snapshot.audio is not None:
        tracks.append(
            {
                "track": "audio",
                "path": snapshot.audio.path,
                "duration_ms": snapshot.effective_duration_ms,
                "mode": snapshot.audio_mode.value,
                "gain": 1.0,
            }
        )
    if snapshot.subtitle is not None:
        tracks.append(
            {
                "track": "text",
                "path": snapshot.subtitle.path,
                "duration_ms": snapshot.effective_duration_ms,
            }
        )
    return {**_selection_view(snapshot), "reader": "jianying", "tracks": tracks}


def for_publish(snapshot: PresentationSnapshot) -> dict[str, Any]:
    """Future publishing/distribution view: same selection, distribution metadata."""

    return {
        **_selection_view(snapshot),
        "reader": "publish",
        "distributable": snapshot.video.currency_at_selection == "CURRENT",
    }


class PresentationLedger:
    """Versioned committed snapshots per scope with failure preservation.

    Only verified candidates commit: the caller supplies per-artifact
    verification evidence, and any unverified selection refuses while the
    previous presentation stays current. Regeneration failure therefore
    preserves the last good presentation instead of blanking it.
    """

    def __init__(self) -> None:
        self._versions: list[PresentationSnapshot] = []
        self._rejections: list[dict[str, Any]] = []

    @property
    def current(self) -> PresentationSnapshot | None:
        return self._versions[-1] if self._versions else None

    @property
    def rejections(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._rejections)

    def commit_candidate(
        self, snapshot: PresentationSnapshot, verification: Mapping[str, bool]
    ) -> PresentationSnapshot:
        """Commit only when every selected artifact verifies True."""

        required = [snapshot.video.artifact_id]
        if snapshot.audio is not None:
            required.append(snapshot.audio.artifact_id)
        if snapshot.subtitle is not None:
            required.append(snapshot.subtitle.artifact_id)
        failed = [
            artifact_id for artifact_id in required if verification.get(artifact_id) is not True
        ]
        if failed:
            self._rejections.append(
                {
                    "snapshot_id": str(snapshot.snapshot_id),
                    "failed": failed,
                    "preserved_version": self._versions[-1].presentation_version
                    if self._versions
                    else None,
                }
            )
            raise PresentationError("PRESENTATION_CANDIDATE_UNVERIFIED")
        self._versions.append(snapshot)
        return snapshot

    def select_history(self, presentation_version: int) -> PresentationSnapshot:
        """Re-commit a historical version's selection as a new version.

        History is read-only: the old content is carried forward with
        ``history_source_version`` set, never mutated in place.
        """

        for stored in self._versions:
            if stored.presentation_version == presentation_version:
                return stored.model_copy(
                    update={
                        "snapshot_id": uuid4(),
                        "presentation_version": self._versions[-1].presentation_version + 1,
                        "history_source_version": presentation_version,
                        "created_at": datetime.now(UTC),
                    }
                )
        raise PresentationError("PRESENTATION_HISTORY_VERSION_UNKNOWN")


def snapshot_from_manifest(
    manifest: Any,
    *,
    project_id: str,
    production_run_id: str,
    revision_id: str,
    scope_id: str,
    actual_durations_ms: Mapping[str, int],
    audio_mode: AudioMode = AudioMode.SILENT,
    aspect_ratio: str = "16:9",
    source_graph_revision: str = "",
) -> PresentationSnapshot:
    """Bridge existing ArtifactManifest-shaped state into one snapshot.

    Duck-typed on ``manifest.artifacts`` (``artifact_id``/``path``/``kind``/
    ``logical_role``/``media_type``) so the production manifest type can
    evolve without this read model importing it. Role mapping: the primary
    video (or ``final_video`` role) wins; primary ``audio``/``tts``/
    ``voiceover`` wins for audio; ``subtitle``/``srt``/``ass`` wins for
    subtitles. Manual entries (``manual``/``uploaded``/``raw`` in kind or
    role) become ``MANUAL_RAW`` with no generation claims.
    """

    items = list(getattr(manifest, "artifacts", None) or ())

    def _is_manual(item: Any) -> bool:
        haystack = f"{getattr(item, 'kind', '')} {getattr(item, 'logical_role', '')}".lower()
        return any(token in haystack for token in ("manual", "upload", "raw"))

    def _candidate(item: Any) -> CandidateMedia:
        artifact_id = str(getattr(item, "artifact_id", None) or getattr(item, "path", ""))
        kind = str(getattr(item, "kind", "") or "file")
        return CandidateMedia(
            artifact_id=artifact_id,
            version=int(getattr(item, "version", 1) or 1),
            path=str(getattr(item, "path", "")),
            kind=kind,
            source_type=MediaSourceType.MANUAL_RAW
            if _is_manual(item)
            else MediaSourceType.GENERATED,
            dependency_revision=str(revision_id),
            provider_id=None,
            generation_prompt_ref=None,
        )

    videos = [
        item
        for item in items
        if (getattr(item, "kind", "") == "video") or "video" in str(getattr(item, "media_type", ""))
    ]
    if not videos:
        raise PresentationError("PRESENTATION_NO_QUALIFIED_VIDEO_MEDIA")

    def _video_rank(item: Any) -> tuple[int, int]:
        role = str(getattr(item, "logical_role", "") or "")
        return (0 if (getattr(item, "primary", False) or role == "final_video") else 1, 0)

    videos.sort(key=_video_rank)
    audios = [
        item
        for item in items
        if getattr(item, "kind", "") in {"audio", "tts", "voiceover", "dub"}
        or str(getattr(item, "logical_role", "") or "") in {"audio", "tts", "voiceover", "dub"}
    ]
    subs = [
        item
        for item in items
        if getattr(item, "kind", "") in {"subtitle", "srt", "ass", "captions"}
        or str(getattr(item, "logical_role", "") or "") in {"subtitle", "srt", "ass", "captions"}
    ]
    return PresentationSelector().select(
        project_id=project_id,
        production_run_id=production_run_id,
        revision_id=revision_id,
        scope_id=scope_id,
        video_candidates=tuple(_candidate(item) for item in videos),
        actual_durations_ms=actual_durations_ms,
        audio_mode=audio_mode,
        audio_candidates=tuple(_candidate(item) for item in audios),
        subtitle_candidates=tuple(_candidate(item) for item in subs),
        aspect_ratio=aspect_ratio,
        source_graph_revision=source_graph_revision or revision_id,
    )


def presentation_from_task(
    task: Mapping[str, Any], *, actual_durations_ms: Mapping[str, int]
) -> PresentationSnapshot | None:
    """Read-only bridge from a task-shaped dict to its presentation.

    Prefers a stored ``presentation_snapshot`` in ``config_json`` (roundtrip
    without re-selection); otherwise materializes from
    ``config_json.artifact_manifest``. Returns None when the task carries no
    manifest state at all. Never writes to the task.
    """

    config = task.get("config_json") or {}
    stored = config.get("presentation_snapshot")
    if stored:
        return PresentationSnapshot.model_validate(stored)
    raw_manifest = config.get("artifact_manifest")
    if not raw_manifest:
        return None
    from hevi.production.artifacts import ArtifactManifest

    manifest = ArtifactManifest.model_validate(raw_manifest)
    return snapshot_from_manifest(
        manifest,
        project_id=str(task.get("project_id") or config.get("project_id") or "unknown"),
        production_run_id=str(task.get("id") or task.get("task_id") or "unknown"),
        revision_id=str(config.get("revision_id") or "unknown"),
        scope_id=str(config.get("scope_id") or "default"),
        actual_durations_ms=actual_durations_ms,
    )


__all__ = [
    "AudioMode",
    "CandidateMedia",
    "DurationPolicy",
    "MediaSourceType",
    "PresentationError",
    "PresentationLedger",
    "PresentationSelector",
    "PresentationSnapshot",
    "SelectedMedia",
    "for_composition",
    "for_download",
    "for_jianying",
    "for_preview",
    "for_publish",
    "for_subtitles",
    "presentation_from_task",
    "snapshot_from_manifest",
]
