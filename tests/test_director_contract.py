from __future__ import annotations

import pytest

from hevi.creative.direction_plan.errors import PlanValidationError
from hevi.creative.director_contract import (
    ApprovalBinding,
    BeatSpec,
    ClaimRef,
    ContinuityAnchor,
    ContinuityContract,
    ContinuityEdge,
    DirectorProposal,
    ShotSpec,
    changed_global_fields,
    compile_production_plan,
)


def _shot(
    shot_id: str,
    duration: float = 10.0,
    claim_id: str = "c1",
    *,
    in_anchor: str = "",
    out_anchor: str = "",
) -> ShotSpec:
    anchors_in = (
        (ContinuityAnchor(in_anchor, "object", "held") if in_anchor else None),
    )
    anchors_out = (
        (ContinuityAnchor(out_anchor, "object", "moving_right") if out_anchor else None),
    )
    beats = (
        BeatSpec(f"{shot_id}:b1", 0.0, 3.0, visual_action="establish", semantic_refs=(claim_id,)),
        BeatSpec(f"{shot_id}:b2", 3.0, 7.0, visual_action="escalate", semantic_refs=(claim_id,)),
        BeatSpec(f"{shot_id}:b3", 7.0, 10.0, visual_action="payoff", semantic_refs=(claim_id,)),
    )
    return ShotSpec(
        shot_id=shot_id,
        duration_sec=duration,
        narrative_function="explain",
        beats=beats,
        continuity=ContinuityContract(
            incoming=tuple(a for a in anchors_in if a is not None),
            outgoing=tuple(a for a in anchors_out if a is not None),
        ),
    )


def _proposal(*, style: str = "classic", ratio: str = "16:9") -> DirectorProposal:
    shots = (
        _shot("s1", in_anchor="start", out_anchor="handoff"),
        _shot("s2", in_anchor="handoff", out_anchor="end"),
    )
    p = DirectorProposal(
        direction_id="dir-test",
        revision=2,
        source_fingerprint="src-fp",
        aspect_ratio=ratio,  # type: ignore[arg-type]
        duration_sec=20.0,
        visual_style=style,
        narrative_strategy="EDUCATIONAL",
        claims=(ClaimRef("c1", "a supported claim", ("source:1",)),),
        shots=shots,
        continuity_edges=(ContinuityEdge("s1", "s2", ("handoff",)),),
    )
    return p.with_hash()


def test_proposal_hash_is_deterministic_and_validates():
    p = _proposal()
    assert len(p.proposal_hash) == 64
    assert p.canonical_hash() == p.proposal_hash
    p.validate()


def test_compile_requires_explicit_current_approval():
    p = _proposal()
    with pytest.raises(PlanValidationError, match="compile requires explicit approval"):
        compile_production_plan(p, None)


def test_compile_rejects_stale_hash_and_revision():
    p = _proposal()
    with pytest.raises(PlanValidationError, match="approval binds a stale proposal"):
        compile_production_plan(
            p,
            ApprovalBinding("0" * 64, p.revision, "human"),
        )
    with pytest.raises(PlanValidationError, match="approval binds a stale revision"):
        compile_production_plan(
            p,
            ApprovalBinding(p.proposal_hash, p.revision - 1, "human"),
        )


def test_continuity_edge_requires_shared_anchor():
    p = _proposal()
    broken = DirectorProposal(
        **{
            **p._payload(),
            "continuity_edges": (ContinuityEdge("s1", "s2", ("missing",)),),
            "proposal_hash": "",
        }
    ).with_hash()
    with pytest.raises(PlanValidationError, match="continuity edge s1->s2: anchor mismatch"):
        broken.validate()


def test_global_change_detection():
    p = _proposal()
    changed = DirectorProposal(
        **{
            **p._payload(),
            "visual_style": "modern",
            "proposal_hash": "",
        }
    ).with_hash()
    assert changed_global_fields(p, changed) == frozenset({"visual_style"})
