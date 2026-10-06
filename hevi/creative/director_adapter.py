"""Adapters between the canonical Director Contract and existing HEVI P10c/ShotIR.

The adapter never becomes an authority. Existing P10c Beat/Cue/Camera objects
remain the source representation; this module only projects them into the
renderer-independent Director Contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from hevi.creative.direction_plan.models import BeatPlan, CameraSpec
from hevi.creative.director_contract import (
    BeatSpec,
    ClaimRef,
    ContinuityAnchor,
    ContinuityContract,
    DirectorProposal,
    ShotSpec,
)
from hevi.storygraph.shot_ir import ShotIR, ShotNode

AnchorResolver = Callable[[Any], float]


def beat_plan_to_specs(
    plan: BeatPlan,
    *,
    resolve_anchor: AnchorResolver,
    known_claims: Mapping[str, ClaimRef] | None = None,
) -> tuple[BeatSpec, ...]:
    """Project P10c BeatPlan to timed BeatSpec.

    Absolute timing must come from the existing anchor resolver. We deliberately
    do not infer seconds from Anchor.target strings.
    """
    plan.validate()
    claims = known_claims or {}
    specs: list[BeatSpec] = []
    for beat in plan.beats:
        start = resolve_anchor(beat.start)
        end = resolve_anchor(beat.end)
        if end <= start:
            raise ValueError(f"beat {beat.id}: resolved end <= start")
        refs = tuple(r for r in (beat.narrative_function,) if r in claims)
        specs.append(
            BeatSpec(
                beat_id=beat.id,
                start_sec=start,
                end_sec=end,
                narrative_function=beat.narrative_function,
                emotional_function=beat.emotional_function,
                visual_action=beat.narrative_function or "directed beat",
                camera_intent="",
                audio_intent="",
                semantic_refs=refs,
            )
        )
    return tuple(specs)


def shot_spec_from_beat_plan(
    *,
    shot_id: str,
    duration_sec: float,
    narrative_function: str,
    beat_plan: BeatPlan,
    resolve_anchor: AnchorResolver,
    continuity_in: tuple[ContinuityAnchor, ...] = (),
    continuity_out: tuple[ContinuityAnchor, ...] = (),
    known_claims: Mapping[str, ClaimRef] | None = None,
    camera: CameraSpec | None = None,
) -> ShotSpec:
    beats = beat_plan_to_specs(
        beat_plan,
        resolve_anchor=resolve_anchor,
        known_claims=known_claims,
    )
    camera.validate() if camera else None
    return ShotSpec(
        shot_id=shot_id,
        duration_sec=duration_sec,
        narrative_function=narrative_function,
        beats=beats,
        composition=camera.composition if camera else "",
        camera_intent=camera.movement.motivation_reason if camera else "",
        continuity=ContinuityContract(
            incoming=continuity_in,
            outgoing=continuity_out,
        ),
    )


def proposal_to_shot_ir(proposal: DirectorProposal) -> ShotIR:
    """Compatibility projection only; ShotIR is not canonical."""
    proposal.validate()
    ir = ShotIR(
        intent=proposal.narrative_strategy.lower(),
        synopsis=proposal.direction_id,
    )
    for shot in proposal.shots:
        ir.add(
            ShotNode(
                id=shot.shot_id,
                kind="scene",
                title=shot.narrative_function,
                body="; ".join(b.visual_action for b in shot.beats),
                duration_sec=shot.duration_sec,
                extra={
                    "director_proposal_hash": proposal.canonical_hash(),
                    "beats": [
                        {
                            "id": b.beat_id,
                            "start_sec": b.start_sec,
                            "end_sec": b.end_sec,
                            "narrative_function": b.narrative_function,
                        }
                        for b in shot.beats
                    ],
                    "continuity_in": [a.anchor_id for a in shot.continuity.incoming],
                    "continuity_out": [a.anchor_id for a in shot.continuity.outgoing],
                },
            )
        )
    for edge in proposal.continuity_edges:
        ir.sequence(edge.from_shot, edge.to_shot, kind="sequence")
    return ir


__all__ = [
    "AnchorResolver",
    "beat_plan_to_specs",
    "proposal_to_shot_ir",
    "shot_spec_from_beat_plan",
]
