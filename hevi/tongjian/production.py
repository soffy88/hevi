"""3O boundary for Tongjian's L3-L8 presenter-video production.

Historical provenance, review checkpoints, and layer-state projection remain
in HEVI.  This module delegates the actual presentation transaction to the
public ``omodul.presenter_video_produce`` operation through ``oservi``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omodul.presenter_video_produce import presenter_video_produce

from hevi.production.execution import execute_standard_operation

LayerRenderer = Callable[[dict[str, Any], Path, dict[str, Any]], Awaitable[dict[str, Any]]]


class PresenterProductionError(RuntimeError):
    """Structured presentation transaction failure exposed to Tongjian runs."""


@dataclass(frozen=True)
class PresenterRenderResult:
    video_path: Path
    engine_result: dict[str, Any]


async def render_presenter_video(
    *,
    output_dir: Path,
    renderer: LayerRenderer,
    presentation_kind: str = "tongjian-history",
) -> PresenterRenderResult:
    """Run L3-L8 through the stateless standard presentation transaction."""

    result = await execute_standard_operation(
        operation=presenter_video_produce,
        config={
            "renderer": "hevi-tongjian-l3-l8",
            "format": "tongjian-presenter-v1",
            "schema_version": 1,
        },
        input_data={
            "schema_version": 1,
            # Deliberately structural only: source text, citations, scripts,
            # voices and provider credentials remain within HEVI's renderer.
            "presentation": {"kind": presentation_kind},
            "renderer": renderer,
        },
        output_dir=output_dir,
    )
    if result.get("status") != "succeeded":
        error = result.get("error") or {}
        raise PresenterProductionError(
            f"{error.get('code', 'PRESENTER_PRODUCTION_FAILED')}: "
            f"{error.get('message', 'presenter video transaction failed')}"
        )
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        raise PresenterProductionError("ARTIFACT_MISSING: transaction returned no video artifacts")
    for artifact in artifacts:
        if (
            isinstance(artifact, dict)
            and artifact.get("kind") == "video"
            and artifact.get("primary")
        ):
            path = artifact.get("path")
            if isinstance(path, str):
                return PresenterRenderResult(video_path=Path(path), engine_result=result)
    raise PresenterProductionError("ARTIFACT_MISSING: transaction returned no primary video")
