"""D3-B/D: continuity product surface (HEVI API).

- ``POST /continuity/facts`` — canonical fact ingestion (approved sources
  write BLOCK-capable truth; anything else is forced ``inferred``).
- ``GET /continuity/identities/{id}/facts`` — current state with provenance
  and episode/scene/shot/revision scope filters.
- ``POST /continuity/validate`` — pre-production validation for a binding.
- ``POST /continuity/gate`` — stage gate; BLOCK → 409 (paid generation must
  not enqueue); WARN without override → 422; WARN with override → 200 and
  the audited decision is persisted.
- ``GET /continuity/decisions`` — WARN-override audit trail.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.creative.layer4.continuity_gate import (
    GateError,
    GateRefusal,
    ProductionStage,
    gate_production_stage,
    record_production_fact,
)
from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    IdentityError,
    PersistentIdentityRegistry,
)

router = APIRouter(prefix="/continuity", tags=["continuity"])


def _owner(user: dict[str, Any]) -> str:
    return str(user["id"])


def _load_registry(store: IdentityStore, owner_id: str) -> PersistentIdentityRegistry:
    return load_owner_registry(store, owner_id)


class FactCreateRequest(BaseModel):
    identity_id: str
    category: str
    statement: str
    source: str = "user"
    source_artifact_id: str = ""
    episode: str = ""
    scene: str = ""
    shot: str = ""
    revision: str = ""


class ValidateRequest(BaseModel):
    binding_id: str
    planned_appearance_id: str = "default"
    planned_voice_id: str = ""
    planned_location: str = ""
    planned_props: list[str] = []
    planned_statements: list[str] = []


class GateRequest(ValidateRequest):
    stage: str = "reference_preparation"
    overridden_by: str = ""


@router.post("/facts", status_code=201)
async def record_fact(
    body: FactCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    store = IdentityStore()
    registry = _load_registry(store, owner_id)
    try:
        category = ContinuityCategory(str(body.category).strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"unknown continuity category: {body.category}"
        ) from None
    if not body.statement.strip():
        raise HTTPException(status_code=422, detail="statement must not be empty")
    try:
        fact = record_production_fact(
            store=store,
            registry=registry,
            owner_id=owner_id,
            identity_id=body.identity_id,
            category=category,
            statement=body.statement,
            source=body.source,
            source_artifact_id=body.source_artifact_id,
            episode=body.episode,
            scene=body.scene,
            shot=body.shot,
            revision=body.revision,
        )
    except IdentityError as exc:
        if "IDENTITY_OWNER_MISMATCH" in str(exc) or "IDENTITY_UNKNOWN" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return fact.model_dump(mode="json")


@router.get("/identities/{identity_id}/facts")
async def list_facts(
    identity_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    episode: str = "",
    scene: str = "",
    shot: str = "",
) -> dict[str, Any]:
    owner_id = _owner(user)
    store = IdentityStore()
    registry = _load_registry(store, owner_id)
    try:
        registry.get_identity(identity_id, owner_id=owner_id)
    except IdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    facts = registry.ledger.facts_for_scope(
        identity_id, episode=episode, scene=scene, shot=shot
    )
    return {
        "identity_id": identity_id,
        "facts": [fact.model_dump(mode="json") for fact in facts],
    }


@router.post("/validate")
async def validate_binding(
    body: ValidateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    from hevi.creative.layer4.persistent_identity import validate_pre_production

    owner_id = _owner(user)
    registry = _load_registry(IdentityStore(), owner_id)
    try:
        binding = registry.get_binding(body.binding_id, owner_id=owner_id)
    except IdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        verdict = validate_pre_production(
            registry=registry,
            binding=binding,
            owner_id=owner_id,
            planned_appearance_id=body.planned_appearance_id,
            planned_voice_id=body.planned_voice_id,
            planned_location=body.planned_location,
            planned_props=tuple(body.planned_props),
            planned_statements=tuple(body.planned_statements),
        )
    except IdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return verdict.model_dump(mode="json")


@router.post("/gate")
async def gate_stage(
    body: GateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    store = IdentityStore()
    registry = _load_registry(store, owner_id)
    try:
        stage = ProductionStage(str(body.stage).strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"unknown stage: {body.stage}") from None
    try:
        binding = registry.get_binding(body.binding_id, owner_id=owner_id)
    except IdentityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        decision = gate_production_stage(
            store=store,
            registry=registry,
            binding=binding,
            owner_id=owner_id,
            stage=stage,
            planned_appearance_id=body.planned_appearance_id,
            planned_voice_id=body.planned_voice_id,
            planned_location=body.planned_location,
            planned_props=tuple(body.planned_props),
            planned_statements=tuple(body.planned_statements),
            overridden_by=body.overridden_by,
        )
    except GateRefusal as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (GateError, IdentityError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return decision.model_dump(mode="json")


@router.get("/decisions")
async def list_decisions(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    binding_id: str = "",
) -> dict[str, Any]:
    owner_id = _owner(user)
    decisions = IdentityStore().load_decisions(owner_id, binding_id=binding_id)
    return {"decisions": decisions}
