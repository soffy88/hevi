"""Deterministic CPU runtime used by the permanent P0 Golden acceptance tests.

This is a test adapter at the Slate/runtime boundary: compiler output remains
provider-neutral, while the actual Remotion CLI creates and validates the MP4.
It is deliberately local and does not make a paid provider call.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hevi.production.artifacts import ArtifactManifest, verify_local_manifest
from hevi.production_graph.domain import ExecutionPlan, ProductionPlan
from hevi.studio.slate_bridge import production_plan_to_slate


def render_golden_mp4(
    plan: ProductionPlan,
    execution_plan: ExecutionPlan,
    output_path: Path,
    *,
    remotion_dir: Path,
) -> ArtifactManifest:
    """Execute a Slate handoff through the real CPU Remotion renderer."""

    slate = production_plan_to_slate(
        plan,
        line_id="golden-remotion",
        slots={
            "execution_plan_id": execution_plan.id,
            "provider": execution_plan.provider,
            "render_mode": execution_plan.parameters.get("render_mode", "video"),
        },
    )
    if not slate.slots["execution_plan_id"]:
        raise ValueError("Slate must carry the compiled ExecutionPlan")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    props_path = output_path.with_suffix(".props.json")
    props_path.write_text(
        json.dumps(
            {
                "beats": [{"text": execution_plan.prompt or "HEVI production"}],
                "title": execution_plan.provider,
                "transition": "cut",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    command = [
        "npx",
        "remotion",
        "render",
        "P0-Golden",
        str(output_path),
        "--frames=0-29",
        f"--concurrency={execution_plan.parameters['concurrency']}",
        f"--props={props_path}",
    ]
    subprocess.run(command, cwd=remotion_dir, check=True, capture_output=True, text=True)
    return verify_local_manifest(
        ArtifactManifest.for_video(output_path), require_primary=True, require_video_stream=True
    )


__all__ = ["render_golden_mp4"]
