"""Deterministically derive constraints from locked director documents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .models import Constraint, ConstraintGraph, CoverageReport


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _items(value: Any, key: str) -> list[dict[str, Any]]:
    raw = _dump(value) or {}
    if not isinstance(raw, Mapping):
        return []
    values = raw.get(key) or []
    return [dict(_dump(item) or {}) for item in values]


def _stable_id(constraint_type: str, scope: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        [constraint_type, scope, payload],
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"c_{hashlib.sha256(encoded).hexdigest()[:24]}"


def derive_constraints(
    *,
    design_list: Any = None,
    shot_list: Any = None,
    scene_stage: Any = None,
    revision_id: str | None = None,
) -> ConstraintGraph:
    """Build a stable graph without an LLM or provider-specific assumptions.

    Empty optional fields are intentionally inert.  When a source field is
    present, it either becomes a typed constraint or is counted as a silent
    drop, making coverage regressions observable in tests and dashboards.
    """

    characters = {item.get("name"): item for item in _items(design_list, "characters")}
    scenes = {item.get("name"): item for item in _items(design_list, "scenes")}
    constraints: dict[str, Constraint] = {}
    expected = 0

    def add(
        constraint_type: str,
        scope: str,
        source_path: str,
        payload: dict[str, Any],
        *,
        severity: str = "required",
        fallback_policy: str = "fail",
    ) -> None:
        constraint = Constraint(
            id=_stable_id(constraint_type, scope, payload),
            type=constraint_type,
            severity=severity,  # type: ignore[arg-type]
            scope=scope,
            source_revision_id=revision_id,
            source_path=source_path,
            payload=payload,
            fallback_policy=fallback_policy,  # type: ignore[arg-type]
        )
        constraints[constraint.id] = constraint

    for shot_index, shot in enumerate(_items(shot_list, "shots")):
        shot_id = str(shot.get("shot_id") or f"shot-{shot_index + 1}")
        scope = f"shot:{shot_id}"
        character_names = [str(name) for name in shot.get("character_names") or []]
        for char_index, name in enumerate(character_names):
            expected += 1
            design = characters.get(name) or {}
            subject_id = design.get("subject_id")
            if subject_id or name:
                add(
                    "identity",
                    f"{scope}:character:{name}",
                    f"shot_list.shots[{shot_index}].character_names[{char_index}]",
                    {"character_name": name, "subject_id": subject_id},
                    severity="critical" if subject_id else "required",
                    fallback_policy="fail" if subject_id else "warn",
                )
            if design.get("wardrobe"):
                expected += 1
                add(
                    "wardrobe",
                    f"{scope}:character:{name}",
                    f"design_list.characters[{name}].wardrobe",
                    {"character_name": name, "wardrobe": design["wardrobe"]},
                )

        scene_name = str(shot.get("scene_name") or "")
        if scene_name:
            expected += 1
            scene = scenes.get(scene_name) or {}
            add(
                "scene",
                scope,
                f"shot_list.shots[{shot_index}].scene_name",
                {
                    "scene_name": scene_name,
                    "subject_id": scene.get("subject_id"),
                    "scene_stage_ref": shot.get("scene_stage_ref"),
                },
            )

        camera_fields = {
            key: shot.get(key)
            for key in ("shot_size", "camera", "camera_angle", "azimuth_deg", "camera_setup_ref")
            if shot.get(key) not in (None, "")
        }
        if camera_fields:
            expected += len(camera_fields)
            add("camera", scope, f"shot_list.shots[{shot_index}]", camera_fields)

        # Performance IR is a first-class constraint source. Preserve the
        # complete structured track so provider compilers can encode it in
        # different ways without losing phase-level evidence.
        performance_track = shot.get("performance_track")
        if performance_track and (performance_track.get("phases") or []):
            expected += 1
            add(
                "performance",
                scope,
                f"shot_list.shots[{shot_index}].performance_track",
                dict(performance_track),
            )

        # Timing is always explicit at shot scope. This prevents duration and
        # scene-stage beat references from disappearing into prompt text.
        expected += 1
        add(
            "timing",
            scope,
            f"shot_list.shots[{shot_index}].duration_s",
            {
                "duration_s": shot.get("duration_s", 5.0),
                "scene_stage_ref": shot.get("scene_stage_ref"),
                "beat_range": list(shot.get("beat_range") or []),
            },
        )

        audio_track = shot.get("audio_track")
        if audio_track and (
            audio_track.get("segments")
            or audio_track.get("dialogue")
            or audio_track.get("music")
            or (audio_track.get("ambient") or {}).get("bed")
        ):
            expected += 1
            add(
                "audio",
                scope,
                f"shot_list.shots[{shot_index}].audio_track",
                dict(audio_track),
            )

        if shot.get("style_ref"):
            expected += 1
            add(
                "style",
                scope,
                f"shot_list.shots[{shot_index}].style_ref",
                {"style_ref": shot["style_ref"]},
            )
        for constraint_type, key in (
            ("continuity", "continuity_requirements"),
            ("safety", "safety_requirements"),
            ("delivery", "delivery_requirements"),
        ):
            values = list(shot.get(key) or [])
            if values:
                expected += 1
                add(
                    constraint_type,
                    scope,
                    f"shot_list.shots[{shot_index}].{key}",
                    {"requirements": values},
                    severity="critical" if constraint_type == "safety" else "required",
                )

        for line_index, line in enumerate(shot.get("dialogue_lines") or []):
            line = dict(_dump(line) or {})
            if line.get("text"):
                expected += 1
                add(
                    "dialogue_sync",
                    f"{scope}:dialogue:{line_index}",
                    f"shot_list.shots[{shot_index}].dialogue_lines[{line_index}]",
                    {
                        "speaker": line.get("character_name") or "narrator",
                        "target_name": line.get("target_name") or "",
                        "text": line["text"],
                        "duration_s": shot.get("duration_s"),
                    },
                )
                if line.get("target_name"):
                    expected += 1
                    add(
                        "eyeline",
                        f"{scope}:dialogue:{line_index}",
                        f"shot_list.shots[{shot_index}].dialogue_lines[{line_index}].target_name",
                        {
                            "speaker": line.get("character_name") or "narrator",
                            "target_name": line["target_name"],
                        },
                    )

        for blocking_index, blocking in enumerate(shot.get("blocking") or []):
            blocking = dict(_dump(blocking) or {})
            if blocking.get("character_name") and (
                blocking.get("position") or blocking.get("facing")
            ):
                expected += 1
                add(
                    "blocking",
                    f"{scope}:blocking:{blocking_index}",
                    f"shot_list.shots[{shot_index}].blocking[{blocking_index}]",
                    blocking,
                )

        if shot.get("manual_negatives"):
            expected += 1
            add(
                "negative",
                scope,
                f"shot_list.shots[{shot_index}].manual_negatives",
                {"items": list(shot["manual_negatives"])},
                severity="advisory",
                fallback_policy="warn",
            )

    for stage_index, stage in enumerate(_items(scene_stage, "stages")):
        scene_ref = stage.get("scene_ref")
        stage_scope = f"scene_stage:{scene_ref}"
        blocking = stage.get("blocking") or {}
        for index, position in enumerate(blocking.get("initial_positions") or []):
            expected += 1
            add(
                "blocking",
                f"{stage_scope}:position:{index}",
                f"scene_stage.stages[{stage_index}].blocking.initial_positions[{index}]",
                dict(_dump(position) or {}),
            )
        for index, sightline in enumerate(blocking.get("sightlines") or []):
            expected += 1
            add(
                "eyeline",
                f"{stage_scope}:sightline:{index}",
                f"scene_stage.stages[{stage_index}].blocking.sightlines[{index}]",
                dict(_dump(sightline) or {}),
            )
        coverage = (stage.get("coverage_plan") or {})
        setups = list(coverage.get("setups") or [])
        if coverage.get("master"):
            setups.append(coverage["master"])
        for index, setup in enumerate(setups):
            expected += 1
            add(
                "camera",
                f"{stage_scope}:camera:{index}",
                f"scene_stage.stages[{stage_index}].coverage_plan",
                dict(_dump(setup) or {}),
            )

    graph = ConstraintGraph(
        revision_id=revision_id,
        constraints=list(constraints.values()),
    )
    # Make the graph relationally traversable: shot-level constraints depend
    # on the identity anchors for that shot, while wardrobe is scoped to its
    # own character anchor.  The dependency edges are deterministic and do
    # not alter the stable constraint ids.
    identities = [item for item in graph.constraints if item.type == "identity"]

    def _shot_base(scope: str) -> str:
        parts = scope.split(":")
        return ":".join(parts[:2]) if parts[:1] == ["shot"] and len(parts) > 1 else scope

    for item in graph.constraints:
        if item.type == "identity":
            continue
        shot_scope = _shot_base(item.scope)
        item.depends_on_ids = [
            identity.id
            for identity in identities
            if _shot_base(identity.scope) == shot_scope
            and (item.type != "wardrobe" or identity.scope == item.scope)
        ]
    graph.coverage = CoverageReport(
        expected_fields=expected,
        derived_constraints=len(graph.constraints),
    )
    return graph


__all__ = ["derive_constraints"]
