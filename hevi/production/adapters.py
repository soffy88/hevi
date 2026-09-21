"""Application-owned production adapter registry.

TaskService owns persistence and scheduling.  The application composition root
injects product adapters here; this module never imports API routers.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol


class ProductionAdapter(Protocol):
    async def __call__(self, task: dict[str, Any], pool: Any) -> dict[str, Any]: ...


class ProductionAdapterRegistry:
    """Explicit source → injected application adapter mapping."""

    def __init__(self) -> None:
        self._targets: dict[str, ProductionAdapter] = {}

    def register(self, source: str, target: ProductionAdapter, *, replace: bool = False) -> None:
        if source in self._targets and not replace:
            raise ValueError(f"production adapter already registered: {source}")
        self._targets[source] = target

    def sources(self) -> tuple[str, ...]:
        return tuple(sorted(self._targets))

    def resolve(self, source: str) -> ProductionAdapter:
        target = self._targets.get(source)
        if target is None:
            raise ValueError(f"Unsupported adapter production source: {source}")
        return target

    async def execute(self, task: dict[str, Any], pool: Any) -> dict[str, Any]:
        source = str((task.get("config_json") or {}).get("production_source", ""))
        result = self.resolve(source)(task, pool)
        if isinstance(result, Awaitable):
            return await result
        raise RuntimeError(f"Production adapter returned non-awaitable result: {source}")


_DEFAULT = ProductionAdapterRegistry()


def _register_builtin_adapters() -> None:
    async def execute_checkpoint(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.execution.resumable_render import execute_checkpoint_render

        return await execute_checkpoint_render(task, pool)

    async def execute_clip_video(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.production.media_workflows import execute_clip_video_task

        return await execute_clip_video_task(task, pool)

    async def execute_localize_video(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.production.media_workflows import execute_video_localize_task

        return await execute_video_localize_task(task, pool)

    async def execute_mpt(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.services.mpt_adapter import execute_mpt_task

        return await execute_mpt_task(task, pool)

    async def execute_lot(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.studio.slate import execute_lot_task

        return await execute_lot_task(task, pool)

    async def execute_blender_previz(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.creative.layer4.blender_workflow import blender_render_workflow
        from hevi.production.artifacts import Artifact, ArtifactManifest

        shot_spec = task.get("config_json", {}).get("shot_spec", {})
        output_path = task.get("config_json", {}).get(
            "output_path", "output/blender_render.png"
        )

        result = blender_render_workflow(shot_spec=shot_spec, output_path=output_path)

        if not (
            result.success
            and result.render_output_exists
            and result.render_output_size
            and result.render_output_size > 0
        ):
            from hevi.creative.layer4.incident_store import track_task_failure

            track_task_failure(
                production_run_id=str(task.get("id", "")),
                node_key="blender_previz",
                failure=result.failure_code
                or f"BLENDER_EXIT_{result.exit_code}",
                evidence={
                    "exit_code": result.exit_code,
                    "error_message": result.error_message,
                    "failure_code": result.failure_code,
                    "script_sha256": result.script_sha256,
                },
                owner_id="hevi_layer4",
            )
            return {
                "status": "failed",
                "error": result.error_message
                or f"Blender render failed (exit_code={result.exit_code})",
                "review_pending": False,
                "artifacts": [],
                "report": {
                    "legacy_result": {"error": result.error_message}
                },
            }
        manifest_artifacts = [
            Artifact(
                kind="image",
                path=result.render_output_path or "output/blender_render.png",
                media_type="image/png",
                primary=True,
                logical_role="final_render",
                artifact_id=None,
                sha256=result.render_output_sha256,
                byte_size=result.render_output_size,
            )
        ]
        manifest = ArtifactManifest(
            production_id=str(
                task.get("config_json", {}).get("production_id", "tmp")
            ),
            revision_id=str(task.get("revision_id", "")),
            attempt_id=str(task.get("_attempt_id", "")),
            tenant_id="hevi_layer4",
            artifacts=manifest_artifacts,
        )
        return {
            "status": "completed",
            "result_video_path": result.render_output_path,
            "config_json": {
                "artifact_manifest": manifest.model_dump(mode="json"),
                "production_id": str(
                    task.get("config_json", {}).get("production_id", "tmp")
                ),
                "revision_id": str(task.get("revision_id", "")),
            },
            "review_pending": False,
            "artifacts": [a.model_dump(mode="json") for a in manifest_artifacts],
            "report": {
                "legacy_result": {"result_video_path": result.render_output_path}
            },
        }

    async def execute_v2v(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.creative.layer4.v2v_workflow import (
            V2VContractError,
            assess_v2v_quality,
            v2v_render_workflow,
        )
        from hevi.production.artifacts import Artifact, ArtifactManifest

        config = task.get("config_json", {})
        v2v_spec = dict(config.get("v2v_spec") or {})
        output_path = config.get("output_path", "output/v2v_result.mp4")

        async def _fail(
            reason: str, failure_code: str, job_id: str | None = None
        ) -> dict[str, Any]:
            from hevi.creative.layer4.incident_store import track_task_failure

            track_task_failure(
                production_run_id=str(task.get("id", "")),
                node_key="v2v",
                failure=failure_code,
                evidence={
                    "error_message": reason,
                    "failure_code": failure_code,
                    "provider_job_id": job_id,
                },
                owner_id="hevi_layer4",
            )
            return {
                "status": "failed",
                "error": reason,
                "review_pending": False,
                "artifacts": [],
                "config_json": {
                    **config,
                    "v2v_job_id": job_id,
                    "v2v_failure_code": failure_code,
                },
                "report": {"legacy_result": {"error": reason}},
            }

        # Resolve the reference from the artifact authority by id (lineage);
        # an explicit source_path is accepted but recorded as such.
        source_artifact_id = str(v2v_spec.get("source_artifact_id") or "")
        source_path = str(v2v_spec.get("source_path") or config.get("source_path") or "")
        source_sha256: str | None = None
        lineage_by_id = False
        if source_artifact_id:
            from obase.persistence import PgPool

            if isinstance(pool, PgPool):
                from hevi.artifact_store import ArtifactRepository

                manifest = await ArtifactRepository(pool).get_manifest(
                    str(config.get("production_id", ""))
                )
                found = None
                if manifest is not None:
                    for art in manifest.artifacts:
                        if str(art.artifact_id or "") == source_artifact_id:
                            found = art
                            break
                if found is None:
                    return await _fail(
                        f"V2V source artifact not found: {source_artifact_id}",
                        "V2V_REFERENCE_UNRESOLVED",
                    )
                from hevi.creative.layer4.v2v_workflow import (
                    resolve_artifact_local_path as _resolve,
                )

                local = _resolve(found)
                if local is None:
                    return await _fail(
                        f"V2V source artifact not on this host: {source_artifact_id}",
                        "V2V_REFERENCE_UNRESOLVED",
                    )
                source_path = local
                source_sha256 = found.sha256
                lineage_by_id = True
        if not source_path:
            return await _fail("V2V reference input missing", "V2V_REFERENCE_REQUIRED")
        try:
            result = await v2v_render_workflow(
                v2v_spec={**v2v_spec, "source_artifact_id": source_artifact_id},
                source_path=source_path,
                output_path=output_path,
                timeout_s=float(v2v_spec.get("timeout_s") or 480.0),
                durable={
                    "project_id": str(config.get("production_id") or task.get("id")),
                    "revision_id": str(
                        task.get("_canonical_revision_id")
                        or config.get("revision_id")
                        or ""
                    ),
                },
            )
        except V2VContractError as exc:
            return await _fail(str(exc), str(exc))
        if not result.success:
            return await _fail(
                result.error_message or "V2V provider execution failed",
                result.failure_code or "V2V_PROVIDER_FAILURE",
                result.provider_job_id,
            )
        quality_signal = assess_v2v_quality(
            requested_duration=(
                float(v2v_spec["duration"])
                if v2v_spec.get("duration") is not None
                else None
            ),
            actual_duration=result.duration_s,
            has_video=True,
            lineage_ok=bool(source_artifact_id) or bool(source_path),
        )
        manifest_artifacts = [
            Artifact(
                kind="video",
                path=result.output_path or output_path,
                media_type="video/mp4",
                primary=True,
                logical_role="final_render",
                artifact_id=None,
                sha256=result.output_sha256,
                byte_size=result.output_size,
            )
        ]
        manifest = ArtifactManifest(
            production_id=str(config.get("production_id", "tmp")),
            revision_id=str(
                task.get("_canonical_revision_id") or config.get("revision_id") or ""
            ),
            attempt_id=str(task.get("_attempt_id", "")),
            tenant_id="hevi_layer4",
            artifacts=manifest_artifacts,
        )
        return {
            "status": "completed",
            "result_video_path": result.output_path,
            "config_json": {
                "artifact_manifest": manifest.model_dump(mode="json"),
                "production_id": str(config.get("production_id", "tmp")),
                "revision_id": str(
                    task.get("_canonical_revision_id") or config.get("revision_id") or ""
                ),
                "v2v_provider": result.provider,
                "v2v_model": result.model,
                "v2v_job_id": result.provider_job_id,
                "v2v_quality_signal": quality_signal,
                "v2v_source_artifact_id": source_artifact_id,
                "v2v_source_sha256": source_sha256,
                "v2v_source_lineage_by_id": lineage_by_id,
            },
            "review_pending": False,
            "artifacts": [a.model_dump(mode="json") for a in manifest_artifacts],
            "report": {"legacy_result": {"result_video_path": result.output_path}},
        }

    async def execute_subtitle_timeline(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.production.subtitle_timeline_workflow import execute_subtitle_timeline_task

        return await execute_subtitle_timeline_task(task, pool)

    async def execute_audio_master_clock(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.production.audio_master_clock_workflow import execute_audio_master_clock_task

        return await execute_audio_master_clock_task(task, pool)

    async def execute_motion_graphics(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.production.motion_graphics_workflow import execute_motion_graphics_task

        return await execute_motion_graphics_task(task, pool)

    async def execute_visual_quality(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.production.visual_quality_workflow import execute_visual_quality_task

        return await execute_visual_quality_task(task, pool)

    _DEFAULT.register("checkpoint_render", execute_checkpoint, replace=True)
    _DEFAULT.register("clip_video", execute_clip_video, replace=True)
    _DEFAULT.register("localize_video", execute_localize_video, replace=True)
    _DEFAULT.register("mpt", execute_mpt, replace=True)
    _DEFAULT.register("lot", execute_lot, replace=True)
    _DEFAULT.register("blender_previz", execute_blender_previz, replace=True)
    _DEFAULT.register("v2v", execute_v2v, replace=True)
    _DEFAULT.register("subtitle_timeline", execute_subtitle_timeline, replace=True)
    _DEFAULT.register("audio_master_clock", execute_audio_master_clock, replace=True)
    _DEFAULT.register("motion_graphics", execute_motion_graphics, replace=True)
    _DEFAULT.register("visual_quality", execute_visual_quality, replace=True)


_register_builtin_adapters()


def default_production_adapters() -> ProductionAdapterRegistry:
    """Return the application-configured registry without importing routers."""
    return _DEFAULT


def configure_default_adapters(**adapters: ProductionAdapter) -> ProductionAdapterRegistry:
    """Inject adapters at process composition time.

    Reconfiguration is intentional for tests and application reloads.  Existing
    task bindings stay immutable; this only selects the adapter for newly run
    process instances.
    """
    for source, adapter in adapters.items():
        _DEFAULT.register(source, adapter, replace=True)
    return _DEFAULT
