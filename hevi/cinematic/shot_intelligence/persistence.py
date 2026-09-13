"""Canonical ShotPlan serialization and replay helpers."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from hevi.cinematic.shot_intelligence.models import (
    SHOT_PLAN_SCHEMA_VERSION,
    BeatCue,
    CameraMotion,
    Composition,
    ShotPlan,
    ShotRecipe,
    TransitionIntent,
)


class ShotPlanSchemaError(ValueError):
    """Raised when a persisted plan is missing or has an unknown schema."""


def serialize_plan(plan: ShotPlan) -> dict[str, Any]:
    return asdict(plan)


def canonical_json(plan: ShotPlan) -> str:
    return json.dumps(serialize_plan(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def persist_plan(plan: ShotPlan, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(plan) + "\n", encoding="utf-8")
    return path


def deserialize_plan(payload: dict[str, Any]) -> ShotPlan:
    version = payload.get("shot_plan_schema_version")
    if version != SHOT_PLAN_SCHEMA_VERSION:
        raise ShotPlanSchemaError(f"unsupported shot_plan_schema_version={version!r}")
    return ShotPlan(
        line=str(payload.get("line", "")),
        shots=tuple(_recipe(item) for item in payload.get("shots", [])),
        beat_cues=tuple(_cue(item) for item in payload.get("beat_cues", [])),
        diagnostics=tuple(str(item) for item in payload.get("diagnostics", [])),
        canonical=bool(payload.get("canonical", True)),
        shot_plan_schema_version=version,
    )


def load_plan(path: Path) -> ShotPlan:
    return deserialize_plan(json.loads(path.read_text(encoding="utf-8")))


def replay_plan(plan: ShotPlan) -> ShotPlan:
    return deserialize_plan(serialize_plan(plan))


def _cue(value: dict[str, Any]) -> BeatCue:
    return BeatCue(time_s=float(value["time_s"]), kind=str(value.get("kind", "beat")), strength=float(value.get("strength", 1.0)))


def _recipe(value: dict[str, Any]) -> ShotRecipe:
    return ShotRecipe(
        id=str(value["id"]),
        shot_type=str(value["shot_type"]),
        framing=str(value["framing"]),
        subject_count=int(value.get("subject_count", 1)),
        camera_motion=CameraMotion(**(value.get("camera_motion") or {})),
        lens_intent=str(value.get("lens_intent", "normal perspective")),
        composition=Composition(**(value.get("composition") or {})),
        duration_range_s=_duration_range(value.get("duration_range_s", (1.0, 6.0))),
        transition=TransitionIntent(**(value.get("transition") or {})),
        dialogue_compatible=bool(value.get("dialogue_compatible", True)),
        narration_compatible=bool(value.get("narration_compatible", True)),
        music_compatible=bool(value.get("music_compatible", True)),
        text_overlay_compatible=bool(value.get("text_overlay_compatible", True)),
        renderer_capabilities=tuple(value.get("renderer_capabilities", ("remotion", "ffmpeg", "generated_video"))),
        constraints=tuple(value.get("constraints", ())),
        tags=tuple(value.get("tags", ())),
        provenance={str(k): str(v) for k, v in (value.get("provenance") or {}).items()},
    )


def _duration_range(value: Any) -> tuple[float, float]:
    values = tuple(float(v) for v in value)
    if len(values) != 2:
        raise ShotPlanSchemaError("duration_range_s must contain exactly two values")
    return values[0], values[1]
