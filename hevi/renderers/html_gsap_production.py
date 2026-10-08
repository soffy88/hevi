"""P0.6/P0.12 — the real HTML/Gsap execution adapter.

Wires the execution contract to the existing canonical renderer:

    ProductionOperation
      -> compile_scene(VisualSceneIR)          # html_gsap_scene.py, the only place
      -> RenderPlan                            #    scene semantics are decided
      -> HtmlGsapRenderer.render()             # hevi/renderers/html_gsap.py, unchanged
      -> real frames -> real MP4

`html_gsap.py` is not modified or subclassed. §0.1 forbids a second HTML renderer
authority, and rewriting the canonical one to consume a scene graph would have risked
the existing P5.2 acceptance path that §48 requires to keep passing.

Real work only. This adapter produces actual bytes through a real browser capture and
real FFmpeg encode; there is no mock path in it, because §33 and §60 forbid a
validation that a mock can satisfy.
"""

from __future__ import annotations

from pathlib import Path

from hevi.production.execution_executor import ExecutionContext
from hevi.production.execution_result import AdapterError, ExecutionResult
from hevi.production.operation import ProductionOperation, ProductionOperationType
from hevi.production.visual_scene_ir import VisualSceneIR
from hevi.renderers.base import RenderPlan
from hevi.renderers.html_gsap import HtmlGsapRenderer
from hevi.renderers.html_gsap_scene import compile_scene

#: Errors that mean "the renderer could not run", as opposed to "the request was bad".
_RENDER_INFRA_ERRORS = frozenset({"timeout", "browser_launch_failure", "ffmpeg_transient"})


class HtmlGsapProductionAdapter:
    """Executes a RENDER operation by compiling its scene and driving the real renderer."""

    name = "html_gsap"
    renderer_ref = "html_gsap"

    def __init__(self, renderer: HtmlGsapRenderer | None = None) -> None:
        self.renderer = renderer or HtmlGsapRenderer()

    def can_execute(self, operation: ProductionOperation) -> bool:
        return (
            operation.operation_type is ProductionOperationType.RENDER
            and operation.renderer_ref in (None, self.renderer_ref)
        )

    def execute(
        self, operation: ProductionOperation, context: ExecutionContext
    ) -> ExecutionResult:
        if context.dry_run:
            raise AdapterError("capability_mismatch", "dry run must not render")

        if not self.renderer.detect():
            # Named, not swallowed. A renderer that reports itself unavailable must not
            # be able to produce a successful-looking empty result.
            raise AdapterError(
                "capability_mismatch",
                f"HTML_GSAP_UNAVAILABLE:{self.renderer.unavailable_reason}",
            )

        scene = _scene_for(operation)
        compiled = compile_scene(scene, shot_id=operation.operation_id,
                                 semantic_intent=str(
                                     operation.metadata.get("semantic_intent", "")))
        plan: RenderPlan = compiled.plan

        work_dir = context.work_dir or Path("output/execution")
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            outcome = self.renderer.render(plan, work_dir)
        except TimeoutError as exc:
            raise AdapterError("timeout", f"html/gsap render timed out: {exc}") from exc
        except Exception as exc:  # re-raised below as a typed adapter error
            raise AdapterError(
                "browser_launch_failure", f"html/gsap render failed: {exc}"
            ) from exc

        if getattr(outcome, "outcome", None) is None or str(outcome.outcome) != "OK":
            raise AdapterError(
                "capability_mismatch",
                f"HTML_GSAP_RENDER_NOT_OK:{getattr(outcome, 'reason', 'unknown')}",
            )

        video = _produced_video(work_dir, operation)
        if video is None:
            raise AdapterError(
                "capability_mismatch",
                "HTML_GSAP_PRODUCED_NO_VIDEO:renderer reported OK but wrote no mp4",
            )

        # Deliberately no hash here. A renderer returns a locator; it does not prove its
        # own artifact. `tests/test_p9_1d_local_render_authority.py::T2` forbids a
        # renderer module from importing hashlib for exactly this reason, and it is the
        # right rule -- the adapter that produced the bytes is the least independent
        # party able to attest to them. The executor hashes the produced file through
        # the artifact layer instead.
        artifact_id = f"{operation.operation_id}-video"
        return ExecutionResult(
            operation_id=operation.operation_id,
            status="SUCCEEDED",
            artifacts=(artifact_id,),
            duration_ms=int(plan.duration_s * 1000),
            metadata={
                f"kind:{artifact_id}": "video",
                f"uri:{artifact_id}": str(video),
                "scene_hash": compiled.scene_hash,
                "width": plan.width,
                "height": plan.height,
                "fps": plan.fps,
                "duration_ms": plan.duration_s * 1000,
                "audio_present": False,
            },
        )


def _scene_for(operation: ProductionOperation) -> VisualSceneIR:
    """Rebuild the scene the operation was compiled from.

    Sourced from the operation's declared scene when present. Reconstructing it from the
    operation's own parameters is what keeps the IR in front of the renderer: the
    adapter never receives a VisualIntent, only a scene.
    """
    declared = operation.metadata.get("scene")
    if declared is not None:
        return VisualSceneIR.model_validate(declared)
    raise AdapterError(
        "capability_mismatch",
        f"RENDER_OPERATION_WITHOUT_SCENE:{operation.operation_id}; §19 forbids a "
        "renderer being handed a VisualIntent directly",
    )


def _produced_video(work_dir: Path, operation: ProductionOperation) -> Path | None:
    candidates = sorted(work_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


__all__ = ["HtmlGsapProductionAdapter"]
