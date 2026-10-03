"""P10c compiler skeleton: manifest -> checks -> CreativeProgram -> ShotIntent set.

No provider orchestration (coarse capability negotiation only); no renderer;
ShotPlanner is called by the caller, never re-implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass

from hevi.creative.direction_plan.errors import PlanValidationError
from hevi.creative.direction_plan.models import plan_hash

COMPILER_VERSION = "p10c-spike-0.1"


@dataclass(frozen=True)
class DegradeEvent:
    when: str
    replace: str
    preserve: tuple[str, ...] = ()
    pre_approved: bool = False


@dataclass(frozen=True)
class CreativeProgram:
    direction_revision: int
    manifest_hash: str
    authority_pins: tuple[str, ...] = ()
    cue_refs: tuple[str, ...] = ()
    decision_refs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    degrade_events: tuple[DegradeEvent, ...] = ()
    compile_hash: str = ""


def compile_program(*, manifest: dict[str, object], authority_pins: list[str],
                    decisions: list[dict[str, object]],
                    compiler_version: str = COMPILER_VERSION) -> CreativeProgram:
    """Fail-loud: missing approval/pins/decisions -> PlanValidationError."""
    if not manifest.get("approval"):
        raise PlanValidationError("compile requires approval", code="APPROVAL_MISSING")
    if not authority_pins:
        raise PlanValidationError("compile requires authority_pins", code="AUTHORITY_REF_UNPINNED")
    for decision in decisions:
        if not decision.get("change_set"):
            raise PlanValidationError(f"decision {decision.get('id')}: change_set required",
                                      code="DECISION_NO_CHANGESET")
    manifest_hash = plan_hash([manifest.get("direction_revision"), sorted(authority_pins)])
    compile_hash = plan_hash([manifest_hash, sorted(authority_pins), compiler_version])
    cue_refs = manifest.get("cue_refs", [])
    constraints = manifest.get("constraints", [])
    assert isinstance(cue_refs, list) and isinstance(constraints, list)
    return CreativeProgram(
        direction_revision=int(str(manifest.get("direction_revision", 0))),
        manifest_hash=manifest_hash, authority_pins=tuple(authority_pins),
        cue_refs=tuple(str(c) for c in cue_refs),
        decision_refs=tuple(str(d.get("id")) for d in decisions),
        constraints=tuple(str(c) for c in constraints),
        compile_hash=compile_hash)


def negotiate(requirements: dict[str, str], capabilities: dict[str, set[str]],
              degrade_policy: list[dict[str, object]]) -> tuple[str, list[DegradeEvent]]:
    """Coarse capability negotiation -> SATISFIED | DEGRADABLE | UNSATISFIABLE.

    requirements: {need: capability}; capabilities: {provider: {caps}}.
    DEGRADABLE only with a matching pre-approved policy entry, else UNSATISFIABLE.
    """
    events: list[DegradeEvent] = []
    for need, cap in requirements.items():
        if any(cap in caps for caps in capabilities.values()):
            continue
        match = next((p for p in degrade_policy
                      if p.get("capability_missing") == cap and p.get("pre_approved")), None)
        if match is None:
            return "UNSATISFIABLE", []
        events.append(DegradeEvent(when=need, replace=str(match.get("replace", "")),
                                   preserve=tuple(match.get("preserve", [])),  # type: ignore[arg-type]
                                   pre_approved=True))
    return ("DEGRADABLE", events) if events else ("SATISFIED", [])
