"""Backend-owned Local Media Golden Path composition.

This is a composition boundary over the already qualified Layer4 stages.  It
does not introduce a second task state machine or artifact authority: the
outer TaskService owns lifecycle/leases and the returned manifest is committed
by the canonical ArtifactRepository.
"""

from __future__ import annotations

import html
import uuid
from pathlib import Path
from typing import Any

from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.production.audio_master_clock_workflow import prepare_audio_master_clock
from hevi.production.motion_graphics_workflow import execute_motion_graphics_task
from hevi.production.visual_quality_workflow import execute_visual_quality_task


def _stable_id(production_id: str, role: str, sha256: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hevi:local-media:{production_id}:{role}:{sha256}"))


def _source_svg(path: Path, topic: str) -> None:
    title = html.escape(topic.strip()[:180] or "HEVI Local Media")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1280\" height=\"720\">"
        "<defs><linearGradient id=\"bg\" x1=\"0\" x2=\"1\"><stop stop-color=\"#101827\"/>"
        "<stop offset=\"1\" stop-color=\"#244b62\"/></linearGradient></defs>"
        "<rect width=\"100%\" height=\"100%\" fill=\"url(#bg)\"/>"
        f"<text x=\"64\" y=\"360\" fill=\"#f5f7fa\" font-size=\"44\" font-family=\"sans-serif\">{title}</text>"
        "</svg>",
        encoding="utf-8",
    )


def _choose_renderer() -> tuple[str, dict[str, Any]]:
    """Choose from the backend capability catalog; never fall back silently."""
    from hevi.production.capabilities import capability_catalog

    catalog = {item["id"]: item for item in capability_catalog()}
    candidates = ("motion_graphics", "blender_previz")
    eligible = [item for item in candidates if bool(catalog.get(item, {}).get("production_ready"))]
    rejected = [
        {"provider_id": item, "reasons": ["not_production_qualified"]}
        for item in candidates
        if item not in eligible
    ]
    if not eligible:
        raise RuntimeError(
            "no production-qualified local renderer satisfies local_media policy: "
            + "; ".join(f"{item['provider_id']} ({','.join(item['reasons'])})" for item in rejected)
        )
    selected = eligible[0]
    return selected, {
        "mode": "local_media",
        "quality_floor": 9,
        "candidates": list(candidates),
        "considered": list(candidates),
        "eligible": eligible,
        "rejected": rejected,
        "selected_provider": selected,
        "selected_reason": "backend capability catalog production_ready",
    }


async def execute_local_media_task(task: dict[str, Any], pool: Any) -> dict[str, Any]:
    config = dict(task.get("config_json") or {})
    production_id = str(config.get("production_id") or task.get("id") or "local-media")
    revision_id = str(task.get("_canonical_revision_id") or config.get("revision_id") or "")
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task.get("id")))
    output_dir.mkdir(parents=True, exist_ok=True)
    cached_manifest = config.get("artifact_manifest")
    if isinstance(cached_manifest, dict):
        manifest = ArtifactManifest.model_validate(cached_manifest)
        if all(Path(item.path).is_file() and Path(item.path).stat().st_size > 0 for item in manifest.artifacts):
            return {
                "status": "completed",
                "result_video_path": str(manifest.primary_path() or ""),
                "config_json": config,
                "artifacts": [item.model_dump(mode="json") for item in manifest.artifacts],
                "report": {"legacy_result": config.get("local_media_report") or {}},
                "review_pending": False,
            }

    try:
        renderer, provider_policy = _choose_renderer()
        if renderer != "motion_graphics":
            raise RuntimeError(
                "backend selected Blender, but the local-media composition has no Blender video adapter"
            )

        prepared = await prepare_audio_master_clock(task, config, output_dir, production_id)
        source_image_path = Path(str(config.get("source_image_path") or output_dir / "local_media_source.svg"))
        if not source_image_path.is_file():
            _source_svg(source_image_path, str(task.get("topic") or config.get("text") or "HEVI"))
        source_image = Artifact.from_path(
            source_image_path,
            kind="image",
            media_type="image/svg+xml",
            logical_role="local_media_source_image",
            metadata={"authority": "HEVI_LAYER4", "generated_from": "production_topic"},
        )
        source_image = source_image.model_copy(
            update={"artifact_id": _stable_id(production_id, "source_image", source_image.sha256 or "")}
        )

        aspect = str(config.get("output_spec") or config.get("aspect_ratio") or "9:16")
        width, height = (720, 1280) if aspect == "9:16" else ((1280, 720) if aspect == "16:9" else (720, 720))
        motion_config = {
            **config,
            "visual_mode": "local_media",
            "provider_mode": "local_media",
            "provider_policy": provider_policy,
            "source_audio_path": str(prepared["audio_path"]),
            "source_audio_artifact_id": prepared["tts_artifact"].artifact_id,
            "source_image_path": str(source_image_path),
            "source_image_artifact_id": source_image.artifact_id,
            "asr_cues": [
                {"start_ms": cue.start_ms, "end_ms": cue.end_ms, "text": cue.text, "emotion": cue.emotion}
                for cue in prepared["cues"]
            ],
            "width": width,
            "height": height,
            "fps": int(config.get("fps") or 24),
            "title": str(task.get("topic") or "HEVI Local Media"),
            "subtitle": "Local Media Golden Path",
            "output_dir": str(output_dir),
            "output_path": str(output_dir / "local_media_remotion.mp4"),
        }
        motion_result = await execute_motion_graphics_task(
            {**task, "config_json": motion_config, "_canonical_revision_id": revision_id}, pool
        )
        if motion_result.get("status") != "completed":
            raise RuntimeError(str(motion_result.get("error") or "local media renderer failed"))
        motion_config_result = dict(motion_result.get("config_json") or motion_config)
        motion_manifest = ArtifactManifest.model_validate(motion_config_result.get("artifact_manifest") or {})
        final = next(item for item in motion_manifest.artifacts if item.primary and item.kind == "video")

        quality_result = await execute_visual_quality_task(
            {
                **task,
                "config_json": {
                    **motion_config_result,
                    "source_video_path": final.path,
                    "source_video_artifact_id": final.artifact_id,
                    "source_audio_artifact_id": prepared["tts_artifact"].artifact_id,
                    "output_dir": str(output_dir / "quality"),
                },
                "_canonical_revision_id": revision_id,
            },
            pool,
        )
        if quality_result.get("status") != "completed":
            raise RuntimeError(str(quality_result.get("error") or "visual quality policy blocked artifact"))
        quality_manifest = ArtifactManifest.model_validate(
            (quality_result.get("config_json") or {}).get("artifact_manifest") or {}
        )

        final = final.model_copy(
            update={
                "parent_artifact_ids": [
                    prepared["tts_artifact"].artifact_id or "",
                    prepared["asr_artifact"].artifact_id or "",
                    source_image.artifact_id or "",
                ]
            }
        )
        artifacts = [
            prepared["tts_artifact"], prepared["asr_artifact"], source_image,
            *[item for item in motion_manifest.artifacts if not item.primary],
            *quality_manifest.artifacts,
            final,
        ]
        combined = ArtifactManifest(
            production_id=production_id,
            revision_id=revision_id,
            attempt_id=str(task.get("_attempt_id") or task.get("id") or ""),
            tenant_id="HEVI_LAYER4",
            artifacts=artifacts,
        )
        report = {
            "path": "LOCAL_MEDIA_GOLDEN_PATH",
            "provider_policy": provider_policy,
            "renderer": renderer,
            "audio_master_clock_report": prepared["report"],
            "remotion_report": motion_config_result.get("motion_graphics_report") or {},
            "visual_quality_report": (quality_result.get("config_json") or {}).get("visual_quality_report") or {},
            "final_video_artifact_id": final.artifact_id,
        }
        return {
            "status": "completed",
            "result_video_path": final.path,
            "config_json": {
                **config,
                **motion_config_result,
                "provider_policy": provider_policy,
                "provider_decision": provider_policy,
                "artifact_manifest": combined.model_dump(mode="json"),
                "local_media_report": report,
            },
            "artifacts": [item.model_dump(mode="json") for item in combined.artifacts],
            "report": {"legacy_result": report},
            "review_pending": False,
        }
    except Exception as exc:
        from hevi.creative.layer4.incident_store import track_task_failure

        track_task_failure(
            production_run_id=str(task.get("id") or production_id),
            node_key="local_media",
            failure="LOCAL_MEDIA_GOLDEN_PATH_FAILURE",
            evidence={"error_message": str(exc), "failure_code": "LOCAL_MEDIA_GOLDEN_PATH_FAILURE"},
            owner_id="HEVI_LAYER4",
        )
        return {
            "status": "failed",
            "error": str(exc),
            "review_pending": False,
            "artifacts": [],
            "report": {"legacy_result": {"error": str(exc)}},
        }


__all__ = ["execute_local_media_task"]
