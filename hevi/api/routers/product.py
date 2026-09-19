"""D6 product projections: project health + next action (HEVI Layer 4 read-only).

These are UI projections over existing canonical sources — Artifact Currency,
Production Plan, and RepairIncident. They add NO new canonical state enum and
NO analytics truth: ``status`` is a presentation value derived at request time.
The browser must not recompute it.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from hevi.api.routers.tasks import get_repository
from hevi.auth.dependencies import get_current_user
from hevi.creative.layer4.continuity_gate import ProductionStage
from hevi.creative.layer4.identity_store import IdentityStore, load_owner_registry
from hevi.creative.layer4.incident_store import IncidentService
from hevi.tasks.repository import TaskRepository

router = APIRouter(prefix="/products", tags=["products"])


def _owner(user: dict[str, Any]) -> str:
    return str(user["id"])


def _incident_signal(incident: Any) -> dict[str, Any]:
    selected = incident.selected_action
    candidate = incident.candidate_actions[0] if incident.candidate_actions else None
    policy = ""
    if selected is not None:
        policy = selected.policy.value
    elif candidate is not None:
        policy = candidate.policy.value
    estimated = 0.0
    if selected is not None:
        estimated = float(selected.estimated_cost_usd)
    elif candidate is not None:
        estimated = float(candidate.estimated_cost_usd)
    return {
        "incident_id": incident.incident_id,
        "node_key": incident.node_key,
        "status": incident.status.value,
        "root_cause": incident.root_cause.value,
        "diagnosis": incident.diagnosis,
        "policy": policy,
        "requires_confirmation": policy == "confirm_required",
        "estimated_cost_usd": estimated,
        "attempts": incident.attempts,
    }


def _currency_signal(task: dict[str, Any]) -> dict[str, Any]:
    from hevi.creative.layer4.currency import ArtifactBasis, evaluate_all
    from hevi.creative.layer4.plan_projection import TargetFact, project_plan
    from hevi.production.artifacts import manifest_from_task

    manifest = manifest_from_task(task)
    if manifest is None:
        return {"available": False, "counts": {}, "next_actions": [], "stale": 0}
    config = task.get("config_json") or {}
    revision = str(config.get("revision_id") or config.get("production_revision") or "")
    deps = {"revision": revision} if revision else {}
    bases = tuple(
        ArtifactBasis(
            artifact_id=str(item.artifact_id or item.path),
            role=str(item.logical_role or item.kind),
            exists=True,
            integrity_ok=bool(item.sha256),
            dependency_revision=revision,
        )
        for item in manifest.artifacts
    )
    evaluations = evaluate_all(bases, deps)
    plans = project_plan(
        tuple(TargetFact(target_id=e.artifact_id, currency=e.currency) for e in evaluations)
    )
    counts: dict[str, int] = {}
    for evaluation in evaluations:
        counts[evaluation.currency.value] = counts.get(evaluation.currency.value, 0) + 1
    next_actions = sorted({action for plan in plans for action in plan.next_actions})
    return {
        "available": True,
        "counts": counts,
        "next_actions": next_actions,
        "stale": counts.get("stale", 0),
        "missing": counts.get("missing", 0),
        "blocked": counts.get("blocked", 0),
    }


def _derive_status(
    task: dict[str, Any] | None, incidents: list[Any], currency: dict[str, Any]
) -> str:
    task_status = str((task or {}).get("status") or "")
    if any(i.status.value == "escalated_manual" for i in incidents):
        return "BLOCKED"
    if any(i.status.value == "repair_failed" for i in incidents):
        return "NEEDS_ATTENTION"
    if any(i.status.value in ("open", "repair_planned") for i in incidents):
        return "NEEDS_ATTENTION"
    if currency.get("blocked") or currency.get("missing"):
        return "NEEDS_ATTENTION"
    if task_status in ("queued", "running"):
        return "GENERATING"
    if task_status == "completed":
        return "COMPLETE" if not currency.get("stale") else "NEEDS_ATTENTION"
    if task_status == "failed":
        return "NEEDS_ATTENTION"
    if task is None:
        return "UNKNOWN"
    return "READY"


def _derive_next_action(
    task: dict[str, Any] | None, incidents: list[Any], status: str
) -> dict[str, Any]:
    for incident in incidents:
        selected = incident.selected_action
        candidate = incident.candidate_actions[0] if incident.candidate_actions else None
        policy = ""
        if selected is not None:
            policy = selected.policy.value
        elif candidate is not None:
            policy = candidate.policy.value
        if incident.status.value == "escalated_manual":
            return {
                "kind": "manual_fix",
                "label": "需要你处理",
                "incident_id": incident.incident_id,
                "detail": incident.diagnosis,
            }
        if incident.status.value == "repair_failed":
            return {
                "kind": "review_repair",
                "label": "修复未成功，需查看",
                "incident_id": incident.incident_id,
            }
        if incident.status.value in ("open", "repair_planned"):
            if policy == "manual_only":
                return {
                    "kind": "manual_fix",
                    "label": "需要你处理",
                    "incident_id": incident.incident_id,
                    "detail": incident.diagnosis,
                }
            if policy == "confirm_required":
                return {
                    "kind": "confirm_repair",
                    "label": "确认修复",
                    "incident_id": incident.incident_id,
                    "requires_confirmation": True,
                }
            return {
                "kind": "repair",
                "label": "HEVI 正在自动修复",
                "incident_id": incident.incident_id,
            }
    task_status = str((task or {}).get("status") or "")
    if task_status == "failed":
        return {"kind": "resume", "label": "重新开始制作"}
    if status == "COMPLETE":
        return {"kind": "export", "label": "导出成片"}
    if status == "GENERATING":
        return {"kind": "wait", "label": "制作中"}
    if status == "READY":
        return {"kind": "continue", "label": "继续制作"}
    return {"kind": "none", "label": "暂无待办"}


@router.get("/projects/{project_id}/health")
async def project_health(
    project_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
    binding_id: str = "",
) -> dict[str, Any]:
    """UI health projection for a project. ``project_id`` is the production
    run id (the current Studio treats a video task as a project)."""
    owner_id = _owner(user)
    task: dict[str, Any] | None = None
    try:
        task_uuid = UUID(project_id)
    except ValueError:
        task_uuid = None
    if task_uuid is not None:
        task = await repo.get_task(task_uuid)
        if task is not None and task.get("user_id") and task["user_id"] != owner_id:
            task = None

    incidents = IncidentService().list_incidents(
        production_run_id=project_id, owner_id=owner_id
    )
    currency = _currency_signal(task) if task is not None else {"available": False, "counts": {}}
    status = _derive_status(task, incidents, currency)

    continuity: dict[str, Any] | None = None
    if binding_id.strip():
        store = IdentityStore()
        registry = load_owner_registry(store, owner_id)
        try:
            binding = registry.get_binding(binding_id.strip(), owner_id=owner_id)
        except Exception as exc:  # unknown / not yours
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        from hevi.creative.layer4.persistent_identity import validate_pre_production

        verdict = validate_pre_production(
            registry=registry, binding=binding, owner_id=owner_id
        )
        continuity = {
            "verdict": verdict.verdict.value,
            "issues": [
                {"severity": f.severity.value, "code": f.code, "detail": f.detail}
                for f in verdict.findings
            ],
        }
        if verdict.verdict.value == "block":
            status = "BLOCKED"
        elif task is None and status == "UNKNOWN":
            # A bound project with no task yet and no blockers is ready to produce.
            status = "READY"

    return {
        "project_id": project_id,
        "status": status,
        "task_status": str((task or {}).get("status") or ""),
        "currency": currency,
        "continuity": continuity,
        "incidents": [_incident_signal(i) for i in incidents],
        "next_action": _derive_next_action(task, incidents, status),
    }


@router.get("/continuity/stages")
async def continuity_stages(
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Product labels for the continuity gate stages (no internal jargon)."""
    labels = {
        ProductionStage.STORYBOARD_APPROVAL.value: "分镜确认",
        ProductionStage.REFERENCE_PREPARATION.value: "素材准备",
        ProductionStage.VIDEO_GENERATION.value: "视频生成",
        ProductionStage.VOICE_GENERATION.value: "声音生成",
    }
    return {"stages": labels}


@router.get("/metrics")
async def product_metrics(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Product analytics computed from canonical stores only (no second ledger).

    Owner-scoped counts; the duplicate-billing-prevented counter is store-wide
    (the incident fingerprint table has no owner column)."""
    from hevi.creative.layer4.differentiation_metrics import compute_metrics

    owner_id = _owner(user)
    metrics = compute_metrics(
        IdentityStore(), IncidentService().store, owner_id=owner_id
    )
    return {"owner_id": owner_id, "metrics": metrics}
