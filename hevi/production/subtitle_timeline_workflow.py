"""Production adapter workflow for the subtitle/timeline capability.

The pure cue atoms live in ``hevi.voicepro.oprim.subtitle_timeline``.  This
module is the single composition boundary and delegates media assembly to the
existing ``hevi.assembly.assembler.assemble_longvideo`` owner.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from hevi.assembly.assembler import ShotSegment, assemble_longvideo, probe_duration
from hevi.assembly.subtitle_timeline_atoms import (
    align_cues,
    cues_to_ass,
    cues_to_srt,
    validate_ass,
    validate_srt,
)
from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.production.delivery_gate import DURATION_TOLERANCE, probe_video


def _ffmpeg_version() -> str:
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=False)
    return (result.stdout.splitlines() or [""])[0]


def _source_ids(config: dict[str, Any]) -> list[str]:
    raw = config.get("source_video_artifact_ids") or config.get("source_artifact_ids") or []
    return [str(item) for item in raw if str(item)]


def _lineage_metadata(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "authority": "HEVI_LAYER4",
        "source_video_artifact_ids": _source_ids(config),
        "source_audio_artifact_id": str(config.get("source_audio_artifact_id") or ""),
        "timeline_capability": "subtitle_timeline",
    }


def _persistable_parent_ids(values: list[str]) -> list[str]:
    """Keep metadata IDs even when external fixtures are not UUIDs, but only
    pass valid UUIDs to the PostgreSQL FK-backed artifact relation table."""

    result: list[str] = []
    for value in values:
        try:
            uuid.UUID(value)
        except ValueError, AttributeError:
            continue
        result.append(value)
    return result


async def execute_subtitle_timeline_task(task: dict[str, Any], _pool: Any) -> dict[str, Any]:
    """Execute a real subtitle timeline task through the existing adapter path."""

    config = dict(task.get("config_json") or {})
    production_id = str(config.get("production_id") or task.get("id") or "")
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task.get("id")))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(config.get("output_path") or output_dir / "final.mp4")
    video_paths = [Path(str(path)) for path in (config.get("source_video_paths") or [])]
    audio_path = Path(str(config.get("source_audio_path") or ""))
    try:
        if len(video_paths) < 2:
            raise FileNotFoundError("subtitle timeline requires at least two video clips")
        if any(not path.is_file() or path.stat().st_size <= 0 for path in video_paths):
            raise FileNotFoundError("subtitle timeline source video is missing or empty")
        if not audio_path.is_file() or audio_path.stat().st_size <= 0:
            raise FileNotFoundError("subtitle timeline source audio is missing or empty")
        fps = int(config.get("fps") or 24)
        width = int(config.get("width") or 320)
        height = int(config.get("height") or 240)
        audio_duration_ms = round(await probe_duration(audio_path) * 1000)
        if audio_duration_ms <= 0:
            raise ValueError("source audio duration is not readable")

        raw_cues = config.get("asr_cues") or config.get("cues") or config.get("segments")
        if not raw_cues:
            raise ValueError(
                "subtitle timeline requires ASR timestamps/cues; no guessed timing is allowed"
            )
        cues = align_cues(
            raw_cues,
            audio_duration_ms=audio_duration_ms,
            fps=fps,
            shot_boundaries_ms=config.get("shot_boundaries_ms"),
            unit=str(config.get("timestamp_unit") or "ms"),
        )
        if not cues:
            raise ValueError("ASR produced no non-empty subtitle cues")
        srt_path = output_dir / "subtitles.srt"
        ass_path = output_dir / "subtitles.ass"
        srt_text = cues_to_srt(cues)
        ass_text = cues_to_ass(
            cues,
            width=width,
            height=height,
            font_name=str(config.get("font_name") or "Noto Sans CJK SC"),
            font_size=int(config.get("font_size") or 32),
            margin_l=int(config.get("safe_margin_l") or 32),
            margin_r=int(config.get("safe_margin_r") or 32),
            margin_v=int(config.get("safe_margin_v") or 32),
        )
        srt_path.write_text(srt_text, encoding="utf-8", newline="\n")
        ass_path.write_text(ass_text, encoding="utf-8", newline="\n")
        validate_srt(srt_text, audio_duration_ms=audio_duration_ms)
        validate_ass(ass_text, audio_duration_ms=audio_duration_ms)

        source_durations = [await probe_duration(path) for path in video_paths]
        if any(duration <= 0 for duration in source_durations):
            raise ValueError("source video duration is not readable")
        total_source = sum(source_durations)
        target_durations = [
            audio_duration_ms / 1000 * duration / total_source for duration in source_durations
        ]
        shots = [
            ShotSegment(path, target_duration=duration)
            for path, duration in zip(video_paths, target_durations, strict=True)
        ]

        # ASS burn-in is the one canonical production path.  SRT remains an
        # independently validated subtitle artifact for downstream consumers.
        await assemble_longvideo(
            shots=shots,
            output_path=output_path,
            narration_audio=audio_path,
            subtitle_path=ass_path,
            subtitle_style=str(config.get("subtitle_style") or "default"),
            width=width,
            height=height,
            fps=fps,
            transition="cut",
            color_normalize=False,
            bgm_beat_align=False,
        )
        probe = probe_video(output_path)
        video_duration_ms = round(probe.duration_s * 1000)
        clock_drift_ms = abs(video_duration_ms - audio_duration_ms)
        if not probe.has_video or not probe.has_audio or probe.size_bytes <= 0:
            raise ValueError("final timeline failed video/audio/size validation")
        if clock_drift_ms > max(round(DURATION_TOLERANCE * 1000), round(1000 / fps)):
            raise ValueError(f"timeline clock drift exceeds policy: {clock_drift_ms}ms")

        lineage = _lineage_metadata(config)
        source_parent_ids = _source_ids(config) + (
            [lineage["source_audio_artifact_id"]] if lineage["source_audio_artifact_id"] else []
        )
        srt_sha = hashlib.sha256(srt_path.read_bytes()).hexdigest()
        ass_sha = hashlib.sha256(ass_path.read_bytes()).hexdigest()

        def _stable(sha: str) -> str:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hevi:timeline:{production_id}:{sha}"))

        subtitle_artifact = Artifact.from_path(
            srt_path,
            kind="subtitle",
            media_type="application/x-subrip",
            logical_role="subtitle_srt",
            parent_artifact_ids=_persistable_parent_ids(
                [lineage["source_audio_artifact_id"]] if lineage["source_audio_artifact_id"] else []
            ),
            metadata={**lineage, "format": "srt"},
        ).model_copy(update={"artifact_id": _stable(srt_sha)})
        ass_artifact = Artifact.from_path(
            ass_path,
            kind="subtitle",
            media_type="text/x-ass",
            logical_role="subtitle_ass",
            parent_artifact_ids=_persistable_parent_ids(
                [lineage["source_audio_artifact_id"]] if lineage["source_audio_artifact_id"] else []
            ),
            metadata={**lineage, "format": "ass"},
        ).model_copy(update={"artifact_id": _stable(ass_sha)})
        final_artifact = Artifact.from_path(
            output_path,
            kind="video",
            media_type="video/mp4",
            primary=True,
            logical_role="final_video",
            # ArtifactRepository assigns stable IDs at commit time.  Existing
            # source IDs can be linked now; subtitle children are retained in
            # the manifest and lineage metadata and are linked by role.
            parent_artifact_ids=_persistable_parent_ids(source_parent_ids),
            metadata={
                **lineage,
                "subtitle_artifact_roles": ["subtitle_srt", "subtitle_ass"],
                "subtitle_render": "ass_burn_in",
                "audio_duration_ms": audio_duration_ms,
                "video_duration_ms": video_duration_ms,
                "clock_drift_ms": clock_drift_ms,
                "ffmpeg_binary": shutil.which("ffmpeg") or "ffmpeg",
                "ffmpeg_version": _ffmpeg_version(),
            },
        )
        manifest = ArtifactManifest(
            production_id=production_id or None,
            revision_id=str(task.get("_canonical_revision_id") or config.get("revision_id") or "")
            or None,
            attempt_id=str(task.get("_attempt_id") or task.get("id") or "") or None,
            tenant_id="HEVI_LAYER4",
            artifacts=[subtitle_artifact, ass_artifact, final_artifact],
        )
        report = {
            "timeline_clock_source": "REAL_AUDIO_OR_ASR_TIMESTAMP",
            "audio_duration_ms": audio_duration_ms,
            "video_duration_ms": video_duration_ms,
            "clock_drift_ms": clock_drift_ms,
            "timestamp_normalization": "PASS",
            "timestamp_monotonicity": "PASS",
            "srt_generation": "PASS",
            "srt_parse_validation": "PASS",
            "ass_generation": "PASS",
            "ass_parse_or_render_validation": "PASS",
            "subtitle_render_real_smoke": "PASS",
            "timeline_output_validation": "PASS",
            "source_video_artifact_ids": _source_ids(config),
            "source_audio_artifact_id": lineage["source_audio_artifact_id"],
            "subtitle_artifact_id": None,
            "final_video_artifact_id": None,
        }
        return {
            "status": "completed",
            "result_video_path": str(output_path),
            "config_json": {
                **config,
                "artifact_manifest": manifest.model_dump(mode="json"),
                "timeline_report": report,
            },
            "artifacts": [item.model_dump(mode="json") for item in manifest.artifacts],
            "report": {
                "legacy_result": {
                    "result_video_path": str(output_path),
                    "config_json": {
                        **config,
                        "artifact_manifest": manifest.model_dump(mode="json"),
                        "timeline_report": report,
                    },
                }
            },
            "review_pending": False,
        }
    except Exception as exc:
        from hevi.creative.layer4.incident_store import track_task_failure

        track_task_failure(
            production_run_id=str(task.get("id") or production_id),
            node_key="subtitle_timeline",
            failure="SUBTITLE_TIMELINE_FAILURE",
            evidence={"error_message": str(exc), "failure_code": "SUBTITLE_TIMELINE_FAILURE"},
            owner_id="HEVI_LAYER4",
        )
        return {
            "status": "failed",
            "error": str(exc),
            "review_pending": False,
            "artifacts": [],
            "report": {"legacy_result": {"error": str(exc)}},
        }
