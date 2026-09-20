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

    _DEFAULT.register("checkpoint_render", execute_checkpoint, replace=True)
    _DEFAULT.register("clip_video", execute_clip_video, replace=True)
    _DEFAULT.register("localize_video", execute_localize_video, replace=True)
    _DEFAULT.register("mpt", execute_mpt, replace=True)
    _DEFAULT.register("lot", execute_lot, replace=True)
    _DEFAULT.register("blender_previz", execute_blender_previz, replace=True)


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
