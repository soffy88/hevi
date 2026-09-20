"""HEVI Layer4 media pipeline assembly — P3 oservi composition facade.

This module is a **Layer4 assembly facade**, NOT a new authority. It declares a
generic pipeline topology over canonical P2 omodul transactions and delegates
execution to ``oservi.PipelineComposerEngine``.

Authority boundaries (enforced):
- HEVI Layer4 Production Graph owns project/artifact/presentation/repair state.
- This facade only maps a caller payload → declarative step graph → oservi run.
- It does NOT register artifacts, set presentation current, or create RepairIncident.
- It does NOT own task state; every run is stateless w.r.t. HEVI authorities.

Topology (P3 SPEC §9):

    STEP 1  audio/timing preparation        (caller-supplied; skipped if absent)
    STEP 2  visual fan-out
              branch A: remotion_template_render
              branch B: previz_generate → previz_guided_v2v_render
    STEP 3  fan-in
    STEP 4  media_timeline_assemble
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omodul.media_timeline_assemble import media_timeline_assemble
from omodul.previz_generate import previz_generate
from omodul.previz_guided_v2v_render import previz_guided_v2v_render
from omodul.remotion_template_render import remotion_template_render
from oservi import PipelineComposerEngine, StepSpec

logger = logging.getLogger(__name__)

__all__ = [
    "build_media_pipeline_steps",
    "run_media_pipeline",
]


def build_media_pipeline_steps(
    *,
    enable_previz_branch: bool = True,
    enable_remotion_branch: bool = True,
) -> list[StepSpec]:
    """Declare the generic media pipeline DAG over canonical omodul transactions.

    No HEVI semantics are encoded here beyond the branch topology; per-step
    input resolution is injected by the Layer4 caller.
    """
    steps: list[StepSpec] = []

    if enable_remotion_branch:
        steps.append(
            StepSpec(
                step_id="remotion_template_render",
                transaction=remotion_template_render,
                mode="fan_out",
                priority=0,
                optional=True,
            )
        )

    if enable_previz_branch:
        steps.append(
            StepSpec(
                step_id="previz_generate",
                transaction=previz_generate,
                mode="fan_out",
                priority=1,
            )
        )
        steps.append(
            StepSpec(
                step_id="previz_guided_v2v_render",
                transaction=previz_guided_v2v_render,
                depends_on=("previz_generate",),
                mode="sequential",
            )
        )

    # Fan-in: timeline assembly consumes whichever visual branches completed.
    visual_deps: tuple[str, ...] = tuple(
        s.step_id
        for s in steps
        if s.step_id in ("remotion_template_render", "previz_guided_v2v_render")
    )
    steps.append(
        StepSpec(
            step_id="media_timeline_assemble",
            transaction=media_timeline_assemble,
            depends_on=visual_deps,
            mode="fan_in",
            optional=False,
        )
    )
    return steps


def _make_input_resolver() -> Callable[..., dict[str, Any]]:
    """Layer4 input resolver: maps prior step results → next step input_data.

    Pure plumbing — reads generic step result envelopes and projects them onto
    the next transaction's declared input contract. No artifact registration.
    """

    def _resolve(
        *,
        step_id: str,
        dependency_results: dict[str, Any],
        base_input: dict[str, Any],
        config: Any,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}

        if step_id == "previz_guided_v2v_render":
            previz = dependency_results.get("previz_generate") or {}
            previz_result = (previz.get("result") or {}) if isinstance(previz, dict) else {}
            video_path = previz_result.get("video_path")
            if video_path:
                merged["previz_video_path"] = video_path
            merged.setdefault("prompt", base_input.get("prompt", ""))
            merged.setdefault("provider", base_input.get("v2v_provider", ""))
            merged.setdefault("shot_id", base_input.get("shot_id", "001"))

        if step_id == "media_timeline_assemble":
            # Collect visual clips produced by whichever branches ran.
            shots: list[dict[str, Any]] = list(base_input.get("shots", []))
            for dep_out in dependency_results.values():
                dep_result = (dep_out.get("result") or {}) if isinstance(dep_out, dict) else {}
                clip = dep_result.get("clip_path") or dep_result.get("video_path")
                if clip:
                    shots.append({"video_path": clip})
            if shots:
                merged["shots"] = shots

        return merged

    return _resolve


async def run_media_pipeline(
    *,
    payload: dict[str, Any],
    output_dir: Path,
    config: Any = None,
    decision_fn: Callable[..., Any] | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
    enable_previz_branch: bool = True,
    enable_remotion_branch: bool = True,
) -> dict[str, Any]:
    """Run the media pipeline via generic oservi composition.

    Args:
        payload: Caller-supplied input_data (shot_spec / prompt / composition_id / shots…).
        output_dir: Artifact output root (owned by Layer4 caller).
        config: Layer4 config object (thresholds etc.) passed verbatim to transactions.
        decision_fn: Optional Layer4 resume/reuse decision hook (RUN/REUSE_EXISTING/SKIP).
        on_step: Optional progress callback.
        enable_previz_branch: Toggle branch B.
        enable_remotion_branch: Toggle branch A.

    Returns:
        Generic oservi envelope::

            {"status": ..., "steps": {step_id: envelope}, "order": [...]}

        The Layer4 caller is responsible for interpreting results, registering
        artifacts, updating presentation, and routing failures to RepairIncident.
    """
    steps = build_media_pipeline_steps(
        enable_previz_branch=enable_previz_branch,
        enable_remotion_branch=enable_remotion_branch,
    )
    engine = PipelineComposerEngine(
        steps=steps,
        decision_fn=decision_fn,
        input_resolver=_make_input_resolver(),
        trigger={"on_demand": True},
        config=config,
        name="hevi-media-pipeline",
    )
    envelope: dict[str, Any] = await engine.run(
        config=config,
        input_data=payload,
        output_dir=output_dir,
        on_step=on_step,
    )
    return envelope
