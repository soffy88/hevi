"""3O production boundary for the explainer's E2 narrated render.

E0/E1 remain HEVI product policy: structured storyboard generation and its
six-segment gate.  E2 is intentionally delegated to the public
``omodul.narrated_video_produce`` transaction and executed by ``oservi``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omodul.narrated_video_produce import narrated_video_produce
from oservi import SequentialComposerEngine

from hevi.explainer.render import RenderResult, render_storyboard
from hevi.explainer.schemas import Storyboard
from hevi.explainer.voiceover import DEFAULT_RATE, DEFAULT_VOICE
from hevi.production.execution import execute_standard_operation


class NarratedProductionError(RuntimeError):
    """A structured narrated production failure exposed as an E2 failure."""


@dataclass(frozen=True)
class NarratedRenderResult:
    portrait_path: Path
    landscape_path: Path
    engine_result: dict[str, Any]


async def _render_remotion_storyboard(
    storyboard_data: dict[str, Any], output_dir: Path, config: dict[str, Any]
) -> dict[str, Any]:
    """Injected application renderer; ``omodul`` never imports HEVI code."""

    result: RenderResult = await render_storyboard(
        Storyboard.model_validate(storyboard_data),
        output_dir,
        voice=str(config.get("voice") or DEFAULT_VOICE),
        rate=str(config.get("rate") or DEFAULT_RATE),
    )
    return {
        "portrait_path": str(result.portrait_path),
        "landscape_path": str(result.landscape_path),
    }


def _path_from_artifact(result: dict[str, Any], *, primary: bool) -> Path | None:
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("kind") != "video":
            continue
        if bool(artifact.get("primary")) is primary and isinstance(artifact.get("path"), str):
            path = Path(artifact["path"])
            if path.is_file() and path.stat().st_size > 0:
                return path
    return None


async def render_narrated_storyboard(
    storyboard: Storyboard,
    output_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
) -> NarratedRenderResult:
    """Execute E2 through standard 3O transaction + stateless service engine."""

    config = {
        "renderer": "hevi-remotion",
        "voice": voice,
        "rate": rate,
        "format": "explainer-remotion-v1",
        "schema_version": 1,
        "require_landscape": True,
    }
    input_data = {
        "schema_version": 1,
        "storyboard": storyboard.model_dump(mode="json"),
        "renderer": _render_remotion_storyboard,
    }

    async def narrated_step(*, input_data: dict[str, Any], step_no: int) -> dict[str, Any]:
        del step_no
        return await execute_standard_operation(
            operation=narrated_video_produce,
            config=config,
            input_data=input_data,
            output_dir=output_dir,
        )

    composer = SequentialComposerEngine(
        steps=[narrated_step],
        trigger={"on_demand": True},
        config=config,
        name="explainer-v8-assembly",
    )
    composed: Any = await composer.run(input_data=input_data, output_dir=output_dir)
    raw_results = composed.get("results") if isinstance(composed, dict) else None
    result: dict[str, Any]
    if isinstance(raw_results, list) and raw_results:
        result = dict(raw_results[0])
    else:
        result = {
            "status": "failed",
            "error": {"code": "COMPOSER_EMPTY", "message": "oservi composer returned no result"},
        }
    if result.get("status") != "succeeded":
        error = result.get("error") or {}
        code = error.get("code", "NARRATED_PRODUCTION_FAILED")
        message = error.get("message", "narrated video transaction failed")
        raise NarratedProductionError(f"{code}: {message}")

    # Step 10 is best-effort for compatibility with old fake/test renderers;
    # a real render receives a verified cover artifact in the same manifest.
    from hevi.explainer.cover import cover_extract_and_render

    cover = await cover_extract_and_render(
        Path(str(result.get("artifacts", [{}])[0].get("path", output_dir / "portrait.mp4"))),
        output_dir / "cover.jpg",
        title=storyboard.topic,
    )
    if cover.get("status") == "succeeded":
        result.setdefault("artifacts", []).append(
            {
                "kind": "cover",
                "path": cover["path"],
                "media_type": cover["media_type"],
                "primary": False,
            }
        )
        result.setdefault("decision_trail", []).append(
            {"stage": "cover_extract_and_render", "outcome": "completed"}
        )

    portrait_path = _path_from_artifact(result, primary=True)
    if portrait_path is None:
        raise NarratedProductionError(
            "ARTIFACT_MISSING: narrated transaction returned no primary video"
        )
    landscape_path = _path_from_artifact(result, primary=False)
    if landscape_path is None:
        raise NarratedProductionError(
            "ARTIFACT_MISSING: narrated transaction returned no landscape video"
        )
    return NarratedRenderResult(
        portrait_path=portrait_path,
        landscape_path=landscape_path,
        engine_result=result,
    )
