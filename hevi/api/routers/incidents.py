"""D3-C/D: self-healing product surface (HEVI API).

Canonical adoption of the D2 repair authority:

- ``POST /incidents/open`` — detection entry: fingerprint dedupe means the
  same root cause on the same node reuses the open incident (no storms).
- ``GET /incidents`` / ``GET /incidents/{id}`` — active incidents, root
  cause, evidence, proposed actions, policy class, attempts, status.
- ``POST /incidents/{id}/propose`` — agent proposal entry (only when the
  incident needs a creative decision; rejected otherwise).
- ``POST /incidents/{id}/confirm`` — CONFIRM_REQUIRED gate: explicit
  ``confirmed:true`` authorizes; anything else → 409 and nothing executes.
- ``POST /incidents/{id}/refuse`` — explicit user refusal (terminal).
- ``POST /incidents/{id}/executed`` — runtime callback after the existing
  runtime authority performs the authorized action.
- ``POST /incidents/{id}/retry`` — re-authorize after REPAIR_FAILED.
- ``POST /incidents/{id}/verify`` — enforced post-repair verification.
  With ``task_id``, artifact/currency/presentation evidence is recomputed
  server-side from the task manifest — never trusted blindly.

This router never executes provider work: it gates, tracks, and verifies.
Execution stays with the existing runtime authority.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hevi.api.routers.tasks import get_task_service
from hevi.auth.dependencies import get_current_user
from hevi.creative.layer4.incident_store import IncidentService
from hevi.creative.layer4.plan_projection import RepairKind
from hevi.creative.layer4.repair_incident import (
    IncidentError,
    RepairActionProposal,
    RepairPolicy,
)
from hevi.tasks.task_service import TaskService

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _service() -> IncidentService:
    return IncidentService()


class IncidentOpenRequest(BaseModel):
    production_run_id: str
    node_key: str
    failure: str
    artifact_id: str = ""
    evidence: dict[str, Any] = {}


class ProposeRequest(BaseModel):
    kind: str
    target_id: str = ""
    detail: str = ""
    policy: str = "confirm_required"
    estimated_cost_usd: float = 0.0


class ConfirmRequest(BaseModel):
    confirmed: bool = False


class RefuseRequest(BaseModel):
    reason: str = "user_declined"


class VerifyRequest(BaseModel):
    verification: dict[str, bool] = {}
    task_id: str = ""
    preserved_artifact_ids: list[str] = []
    preserved_intact: bool = True


def _serialize(incident: Any) -> dict[str, Any]:
    return dict(incident.model_dump(mode="json"))


def _product_view(incident: Any) -> dict[str, Any]:
    """Product-facing projection: outcome, cost, preserved, confirmation.

    No new canonical truth — derived from the incident's own fields.
    """
    selected = incident.selected_action
    policy = selected.policy.value if selected is not None else ""
    candidate = incident.candidate_actions[0] if incident.candidate_actions else None
    if not policy and candidate is not None:
        policy = candidate.policy.value
    estimated = (
        selected.estimated_cost_usd
        if selected is not None
        else (candidate.estimated_cost_usd if candidate is not None else 0.0)
    )
    evidence = incident.evidence or {}
    preserved = evidence.get("preserved_artifact_ids") or []
    return {
        "incident_id": incident.incident_id,
        "production_run_id": incident.production_run_id,
        "node_key": incident.node_key,
        "status": incident.status.value,
        "root_cause": incident.root_cause.value,
        "failure_code": incident.failure_code,
        "diagnosis": incident.diagnosis,
        "needs_agent": incident.needs_agent,
        "policy": policy,
        "requires_confirmation": policy == "confirm_required",
        "estimated_cost_usd": estimated,
        "preserved_artifact_ids": list(preserved),
        "preserved_intact": bool(evidence.get("preserved_intact", True)),
        "attempts": incident.attempts,
        "verification_result": dict(incident.verification_result or {}),
        "candidate_action": candidate.model_dump(mode="json") if candidate else None,
        "selected_action": selected.model_dump(mode="json") if selected else None,
    }


def _owner(user: dict[str, Any]) -> str:
    return str(user["id"])


def _not_found(exc: IncidentError) -> HTTPException:
    if "REPAIR_OWNER_MISMATCH" in str(exc):
        return HTTPException(status_code=404, detail="Incident not found")
    return HTTPException(status_code=404, detail=str(exc))


@router.post("/open", status_code=201)
async def open_incident(
    body: IncidentOpenRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    if not body.production_run_id.strip() or not body.node_key.strip():
        raise HTTPException(status_code=422, detail="production_run_id and node_key required")
    try:
        incident = _service().open_or_get(
            production_run_id=body.production_run_id,
            node_key=body.node_key,
            failure=body.failure,
            artifact_id=body.artifact_id,
            evidence=dict(body.evidence or {}),
            owner_id=_owner(user),
        )
    except IncidentError as exc:
        if "REPAIR_OWNER_MISMATCH" in str(exc):
            raise HTTPException(status_code=409, detail="Incident owned by another tenant") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(incident)


@router.get("")
async def list_incidents(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    production_run_id: str = "",
    product: bool = False,
) -> dict[str, Any]:
    incidents = _service().list_incidents(
        production_run_id=production_run_id, owner_id=_owner(user)
    )
    if product:
        return {"incidents": [_product_view(incident) for incident in incidents]}
    return {"incidents": [_serialize(incident) for incident in incidents]}


@router.get("/{incident_id}/timeline")
async def incident_timeline(
    incident_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Product repair timeline: detected → diagnosed → proposed → … → resolved."""
    try:
        events = _service().timeline(incident_id, owner_id=_owner(user))
    except IncidentError as exc:
        raise _not_found(exc) from exc
    return {"incident_id": incident_id, "events": events}


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    product: bool = False,
) -> dict[str, Any]:
    try:
        incident = _service().get(incident_id, owner_id=_owner(user))
    except IncidentError as exc:
        raise _not_found(exc) from exc
    return _product_view(incident) if product else _serialize(incident)


@router.post("/{incident_id}/propose")
async def propose_action(
    incident_id: str,
    body: ProposeRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        kind = RepairKind(str(body.kind).strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"unknown repair kind: {body.kind}") from None
    try:
        policy = RepairPolicy(str(body.policy).strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"unknown repair policy: {body.policy}"
        ) from None
    try:
        incident = _service().propose_agent_action(
            incident_id,
            RepairActionProposal(
                kind=kind,
                target_id=body.target_id,
                detail=body.detail,
                policy=policy,
                estimated_cost_usd=max(0.0, body.estimated_cost_usd),
            ),
            owner_id=_owner(user),
        )
    except IncidentError as exc:
        if "REPAIR_OWNER_MISMATCH" in str(exc):
            raise _not_found(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(incident)


@router.post("/{incident_id}/confirm")
async def confirm_action(
    incident_id: str,
    body: ConfirmRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    try:
        service = _service()
        incident = service.get(incident_id, owner_id=owner_id)
    except IncidentError as exc:
        raise _not_found(exc) from exc
    action = incident.selected_action
    if action is None:
        if not incident.candidate_actions:
            raise HTTPException(
                status_code=422, detail="no candidate action: propose one first"
            )
        action = incident.candidate_actions[0]
    approved, reason = service.authorize(
        incident_id, action, confirmed=body.confirmed, owner_id=owner_id
    )
    if not approved:
        raise HTTPException(status_code=409, detail=reason)
    return {
        "approved": True,
        "reason": reason,
        "incident": _serialize(service.get(incident_id, owner_id=owner_id)),
    }


@router.post("/{incident_id}/refuse")
async def refuse_action(
    incident_id: str,
    body: RefuseRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        incident = _service().decline(
            incident_id, reason=body.reason, owner_id=_owner(user)
        )
    except IncidentError as exc:
        if "REPAIR_OWNER_MISMATCH" in str(exc):
            raise _not_found(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(incident)


@router.post("/{incident_id}/executed")
async def mark_executed(
    incident_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        incident = _service().record_execution(incident_id, owner_id=_owner(user))
    except IncidentError as exc:
        if "REPAIR_OWNER_MISMATCH" in str(exc):
            raise _not_found(exc) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize(incident)


@router.post("/{incident_id}/retry")
async def retry_repair(
    incident_id: str,
    body: ConfirmRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    try:
        service = _service()
        incident = service.get(incident_id, owner_id=owner_id)
    except IncidentError as exc:
        raise _not_found(exc) from exc
    action = incident.selected_action or (
        incident.candidate_actions[0] if incident.candidate_actions else None
    )
    if action is None:
        raise HTTPException(status_code=422, detail="no candidate action: propose one first")
    approved, reason = service.authorize(
        incident_id, action, confirmed=body.confirmed, owner_id=owner_id
    )
    if not approved:
        raise HTTPException(status_code=409, detail=reason)
    return {
        "approved": True,
        "reason": reason,
        "incident": _serialize(service.get(incident_id, owner_id=owner_id)),
    }


def _server_verification(
    task: dict[str, Any] | None, client: dict[str, bool]
) -> dict[str, bool]:
    """Recompute artifact/currency/presentation evidence server-side."""
    if task is None:
        return dict(client)
    from hevi.creative.layer4.currency import ArtifactBasis, evaluate_all
    from hevi.production.artifacts import manifest_from_task

    merged = dict(client)
    manifest = manifest_from_task(task)
    if manifest is None:
        return merged
    bases = tuple(
        ArtifactBasis(
            artifact_id=str(item.artifact_id or item.path),
            role=str(item.logical_role or item.kind),
            exists=True,
            integrity_ok=bool(item.sha256),
            dependency_revision="",
        )
        for item in manifest.artifacts
    )
    evaluations = evaluate_all(bases, {})
    merged["task_ok"] = task.get("status") == "completed"
    merged["artifact_ok"] = bool(evaluations) and all(e.usable for e in evaluations)
    merged["currency_ok"] = bool(evaluations) and all(
        e.currency.value == "current" for e in evaluations
    )
    merged["presentation_ok"] = any(
        "video" in str(item.logical_role or item.kind).lower() and bool(item.sha256)
        for item in manifest.artifacts
    )
    return merged


@router.post("/{incident_id}/verify")
async def verify_repair(
    incident_id: str,
    body: VerifyRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[TaskService, Depends(get_task_service)],
) -> dict[str, Any]:
    owner_id = _owner(user)
    service = _service()
    try:
        service.get(incident_id, owner_id=owner_id)
    except IncidentError as exc:
        raise _not_found(exc) from exc
    task: dict[str, Any] | None = None
    if body.task_id.strip():
        try:
            task_uuid = UUID(body.task_id.strip())
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid task_id") from None
        task = await svc.repository.get_task(task_uuid)
        if task is None or (task.get("user_id") and task["user_id"] != owner_id):
            # Owner-scoped: never use another tenant's task as evidence.
            raise HTTPException(status_code=404, detail="Task not found")
    verification = _server_verification(task, dict(body.verification or {}))
    try:
        incident = service.verify(
            incident_id,
            verification,
            preserved_artifact_ids=tuple(body.preserved_artifact_ids),
            preserved_intact=body.preserved_intact,
            owner_id=owner_id,
        )
    except IncidentError as exc:
        if "REPAIR_OWNER_MISMATCH" in str(exc):
            raise _not_found(exc) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize(incident)
