"""Authority visibility and settings surfaces (Gap Closure W13).

Read-mostly product exposure for the W1-W9 authorities — no second
statistics source, no re-selection, no secret acceptance:

- usage ledger (W4 store): list / detail / analytics;
- endpoint registry (W5 lifecycle): list / create / validate /
  preview-request / check-response / check-capability / trial-record /
  enable / disable / delete. Billable trials never execute here;
- creative memory (W9 store): inspect / remember+edit / disable —
  the PII/secret gate stays inside the memory path;
- character variants (W6 view): appearances, default, voice inheritance;
- task presentation + currency (W1/W2 over live task state).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.creative.layer4.authority_stores import CallLedgerStore, EndpointRegistry
from hevi.creative.layer4.creative_memory import CreativeMemory
from hevi.db.pg_pool import get_hevi_pg_pool

router = APIRouter(prefix="/authorities", tags=["authorities"])


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


# ── usage ledger ─────────────────────────────────────────────────────────


@router.get("/usage/calls")
async def usage_calls(
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    provider: str = "",
    model: str = "",
    operation: str = "",
    status: str = "",
    project: str = "",
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> dict[str, Any]:
    """List call rows. The ledger is the only usage source (USAGE_UI_AUTHORITY)."""

    rows, total = CallLedgerStore().list_records(
        provider=provider,
        model=model,
        operation=operation,
        status=status,
        project_ref=project,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "calls": rows}


@router.get("/usage/calls/{call_id}")
async def usage_call_detail(
    call_id: str, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """Deep-link target: one call row with input/response/error evidence."""

    row = CallLedgerStore().get(call_id)
    if row is None:
        raise HTTPException(status_code=404, detail="call not found")
    return row


@router.get("/usage/analytics")
async def usage_analytics(
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Cost/latency/rate rollups + attention flags, computed from ledger rows."""

    from hevi.creative.layer4.usage_ledger import (
        ProviderCallRecord,
        aggregate,
        detect_attention,
    )

    records = tuple(
        ProviderCallRecord.model_validate(row) for row in CallLedgerStore().all_records()
    )
    analytics = aggregate(records)
    attention = detect_attention(records)
    return {
        **analytics.model_dump(mode="json"),
        "attention": [flag.model_dump(mode="json") for flag in attention],
    }


# ── endpoint registry ────────────────────────────────────────────────────


class DefinitionBody(BaseModel):
    definition: dict[str, Any]


class ParamsBody(BaseModel):
    params: dict[str, Any] = {}


class SampleBody(BaseModel):
    raw_response: dict[str, Any] = {}


class RequirementBody(BaseModel):
    requirement: dict[str, Any] = {}


class TrialBody(BaseModel):
    outcome: str = "success"
    provider_job_ref: str = ""


def _registry() -> EndpointRegistry:
    return EndpointRegistry()


@router.get("/endpoints")
async def endpoints_list(
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return {"endpoints": _registry().list_definitions()}


@router.post("/endpoints", status_code=201)
async def endpoints_create(
    body: DefinitionBody, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """Import a definition: validated secret-free, always stored at DRAFT."""

    from hevi.creative.layer4.endpoint_lifecycle import import_definition

    try:
        definition = import_definition(body.definition)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid definition: {exc}") from exc
    return {"name": _registry().save(definition.model_dump(mode="json"))}


@router.get("/endpoints/{name}")
async def endpoints_inspect(
    name: str, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    row = _registry().get(name)
    if row is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    return row


@router.delete("/endpoints/{name}")
async def endpoints_delete(
    name: str, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    if not _registry().delete(name):
        raise HTTPException(status_code=404, detail="endpoint not found")
    return {"deleted": name}


def _loaded_definition(name: str) -> dict[str, Any]:
    row = _registry().get(name)
    if row is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    return row


@router.post("/endpoints/{name}/validate")
async def endpoints_validate(
    name: str, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    from hevi.creative.layer4.endpoint_lifecycle import (
        DeclarativeEndpointDefinition,
        mark_validated,
        validate_definition,
    )

    definition = DeclarativeEndpointDefinition.model_validate(_loaded_definition(name))
    report = validate_definition(definition)
    if report.valid:
        _registry().save(mark_validated(definition).model_dump(mode="json"))
    return report.model_dump(mode="json")


@router.post("/endpoints/{name}/preview-request")
async def endpoints_preview_request(
    name: str, body: ParamsBody, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """Render-only: never sends, never bills, secrets stay symbolic."""

    from hevi.creative.layer4.endpoint_lifecycle import (
        DeclarativeEndpointDefinition,
        preview_request,
    )

    definition = DeclarativeEndpointDefinition.model_validate(_loaded_definition(name))
    return preview_request(definition, body.params).model_dump(mode="json")


@router.post("/endpoints/{name}/check-response")
async def endpoints_check_response(
    name: str, body: SampleBody, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """Validate taking paths against a supplier sample. Sends nothing."""

    from hevi.creative.layer4.endpoint_lifecycle import (
        DeclarativeEndpointDefinition,
        preview_result,
    )

    definition = DeclarativeEndpointDefinition.model_validate(_loaded_definition(name))
    return preview_result(definition, body.raw_response).model_dump(mode="json")


@router.post("/endpoints/{name}/check-capability")
async def endpoints_check_capability(
    name: str, body: RequirementBody, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    from hevi.creative.layer4.endpoint_lifecycle import (
        CapabilityRequirement,
        DeclarativeEndpointDefinition,
        check_capability,
    )

    definition = DeclarativeEndpointDefinition.model_validate(_loaded_definition(name))
    requirement = CapabilityRequirement.model_validate(body.requirement)
    return check_capability(definition, requirement).model_dump(mode="json")


@router.post("/endpoints/{name}/trial")
async def endpoints_record_trial(
    name: str, body: TrialBody, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """Record a caller-executed trial. This API never executes billable runs."""

    from hevi.creative.layer4.endpoint_lifecycle import (
        DeclarativeEndpointDefinition,
        record_trial,
    )

    definition = DeclarativeEndpointDefinition.model_validate(_loaded_definition(name))
    try:
        updated = record_trial(
            definition, outcome=body.outcome, provider_job_ref=body.provider_job_ref
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _registry().save(updated.model_dump(mode="json"))
    return {"name": name, "state": updated.state.value, "trial_summary": updated.trial_summary}


@router.post("/endpoints/{name}/enable")
async def endpoints_enable(
    name: str, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    from hevi.creative.layer4.endpoint_lifecycle import DeclarativeEndpointDefinition, enable

    definition = DeclarativeEndpointDefinition.model_validate(_loaded_definition(name))
    try:
        updated = enable(definition)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _registry().save(updated.model_dump(mode="json"))
    return {"name": name, "state": updated.state.value}


@router.post("/endpoints/{name}/disable")
async def endpoints_disable(
    name: str, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    from hevi.creative.layer4.endpoint_lifecycle import DeclarativeEndpointDefinition, disable

    definition = DeclarativeEndpointDefinition.model_validate(_loaded_definition(name))
    try:
        updated = disable(definition)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _registry().save(updated.model_dump(mode="json"))
    return {"name": name, "state": updated.state.value}


# ── creative memory settings ─────────────────────────────────────────────


class MemoryBody(BaseModel):
    scope: str = "user"
    key: str = ""
    content: str = ""
    project_id: str = ""
    session_id: str = ""


def _memory() -> CreativeMemory:
    from hevi.creative.layer4.authority_stores import memory_db_path

    return CreativeMemory.at_path(memory_db_path())


@router.get("/memory")
async def memory_inspect(
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    scope: str = "user",
    project_id: str = "",
    include_disabled: bool = False,
) -> dict[str, Any]:
    return {
        "entries": [
            entry.model_dump(mode="json")
            for entry in _memory().inspect(
                scope=scope, project_id=project_id, include_disabled=include_disabled
            )
        ]
    }


@router.put("/memory")
async def memory_remember(
    body: MemoryBody, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """Remember/edit through the memory path, so the PII gate cannot be bypassed."""

    from hevi.creative.layer4.creative_memory import MemoryError

    try:
        entry = _memory().edit(
            scope=body.scope,
            key=body.key,
            content=body.content,
            project_id=body.project_id,
            session_id=body.session_id,
        )
    except MemoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return entry.model_dump(mode="json")


@router.delete("/memory")
async def memory_disable(
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    scope: str = "user",
    key: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    _memory().disable(scope=scope, key=key, project_id=project_id)
    return {"disabled": key, "scope": scope}


class RunBody(BaseModel):
    params: dict[str, Any] = {}
    secrets: dict[str, str] = {}
    topic: str = "declarative endpoint run"


@router.post("/endpoints/{name}/run", status_code=201)
async def endpoints_run(
    name: str,
    body: RunBody,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """Create a production task that executes this endpoint (W17-B).

    The task runs through the standard runtime: worker -> durable provider
    plane -> usage ledger -> artifact manifest -> presentation. No
    endpoint-specific execution path.
    """

    from hevi.tasks.repository import TaskRepository as _TaskRepository
    from hevi.tasks.task_service import TaskService as _TaskService

    if _registry().get(name) is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    service = _TaskService(_TaskRepository(pool))
    task = await service.create_task(
        topic=body.topic,
        duration_archetype="1-5min",
        video_provider="declarative_endpoint",
        audio_provider="none",
        user_id=str(user["id"]),
        production_source="declarative_endpoint",
        endpoint_name=name,
        endpoint_params=body.params,
        endpoint_secrets=body.secrets,
    )
    submitted = await service.submit_task(task["id"])
    return {"task_id": str(submitted.get("id") or task["id"]), "status": submitted.get("status")}


# ── character variants ───────────────────────────────────────────────────


async def _load_subject(pool: PgPool, character_id: str) -> dict[str, Any] | None:
    from hevi.subjects.repository import SubjectRepository
    from hevi.subjects.subject_service import SubjectService

    try:
        return await SubjectService(SubjectRepository(pool)).get_subject(character_id)
    except Exception:
        return None


@router.get("/characters/{character_id}/variants")
async def character_variants(
    character_id: str,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """Appearances, default look, and per-appearance voice inheritance."""

    from hevi.creative.layer4.character_authority import character_view_from_sources

    subject = await _load_subject(pool, character_id)
    if not subject:
        raise HTTPException(status_code=404, detail="character not found")
    metadata = (subject or {}).get("metadata") or {}
    refs = (subject or {}).get("reference_images") or []
    voice_ref = metadata.get("voice_ref") if isinstance(metadata, dict) else None
    from hevi.creative.layer4.character_authority import appearances_from_records

    appearances = appearances_from_records(metadata.get("appearances") or ())
    view = character_view_from_sources(
        character_id=str((subject or {}).get("id") or character_id),
        canonical_name=str((subject or {}).get("name") or character_id),
        aliases=tuple((subject or {}).get("aliases") or ()),
        voice_id=str(voice_ref or ""),
        reference_images=tuple(str(r) for r in refs),
        appearances=appearances or None,
    )
    return view.model_dump(mode="json")


# ── task presentation + currency visibility ──────────────────────────────


async def _load_task(pool: PgPool, task_id: uuid.UUID) -> dict[str, Any] | None:
    from hevi.tasks.repository import TaskRepository

    return await TaskRepository(pool).get_task(task_id)


@router.get("/tasks/{task_id}/presentation")
async def task_presentation(
    task_id: str,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """Current selected presentation for a task: same snapshot readers consume."""

    from hevi.creative.layer4.presentation import for_download, snapshot_for_serving
    from hevi.production.artifacts import manifest_from_task
    from hevi.production.delivery_gate import probe_manifest_durations_ms

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid task id") from exc
    task = await _load_task(pool, task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    manifest = manifest_from_task(task)
    if manifest is None:
        raise HTTPException(status_code=404, detail="no artifact manifest")
    try:
        snapshot = snapshot_for_serving(
            manifest,
            task=task,
            probe_durations_ms=probe_manifest_durations_ms(manifest),
            allow_stale=True,  # explicit editable export: stale is usable
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409, detail=f"presentation not materializable: {exc}"
        ) from exc
    return for_download(snapshot)


@router.get("/tasks/{task_id}/plan")
async def task_plan(
    task_id: str,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """Production plan projection over current task state (K02 consumer).

    Pure projection: completed/ready/blocked/stale/missing per target with
    next_actions and repair_actions, derived from the artifact manifest and
    the W2 currency evaluator. Stores nothing.
    """

    from hevi.creative.layer4.currency import ArtifactBasis, evaluate_all
    from hevi.creative.layer4.plan_projection import TargetFact, project_plan
    from hevi.production.artifacts import manifest_from_task

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid task id") from exc
    task = await _load_task(pool, task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    manifest = manifest_from_task(task)
    if manifest is None:
        raise HTTPException(status_code=404, detail="no artifact manifest")
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
    facts = tuple(
        TargetFact(
            target_id=evaluation.artifact_id,
            currency=evaluation.currency,
        )
        for evaluation in evaluations
    )
    plans = project_plan(facts)
    return {
        "targets": [plan.model_dump(mode="json") for plan in plans],
        "counts": {
            "completed": sum(1 for p in plans if p.status.value == "completed"),
            "ready": sum(1 for p in plans if p.status.value == "ready"),
            "blocked": sum(1 for p in plans if p.status.value == "blocked"),
            "stale": sum(1 for p in plans if p.status.value == "stale"),
            "missing": sum(1 for p in plans if p.status.value == "missing"),
        },
    }


@router.get("/tasks/{task_id}/currency")
async def task_currency(
    task_id: str,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> dict[str, Any]:
    """CURRENT/STALE/MISSING/BLOCKED per manifest entry, judged uniformly."""

    from hevi.creative.layer4.currency import ArtifactBasis, annotate_selections, evaluate_all
    from hevi.production.artifacts import manifest_from_task

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid task id") from exc
    task = await _load_task(pool, task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    manifest = manifest_from_task(task)
    if manifest is None:
        raise HTTPException(status_code=404, detail="no artifact manifest")
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
    usable = sum(1 for e in evaluations if e.usable)
    return {
        "evaluations": annotate_selections(evaluations),
        "usable": usable,
        "total": len(evaluations),
    }


__all__ = ["router"]


# ── E04/E06: capability narrowing + pre-submit media admission ───────────


def _provider_declaration(provider: str) -> tuple[Any, Any]:
    """Bridge real provider limits into the canonical capability contract."""

    from hevi.creative.layer4.endpoint_lifecycle import CapabilityDeclaration
    from hevi.video.capability_guard import PROVIDER_LIMITS

    limits = PROVIDER_LIMITS.get(provider)
    if limits is None:
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider}")
    return (
        CapabilityDeclaration(
            media_type="video",
            resolutions=tuple(f"{w}x{h}" for w, h in (limits.max_resolution,)),
            native_audio=limits.native_audio,
            async_job=True,
        ),
        limits,
    )


def _media_limit_reasons(provider: str, requirement: Any) -> list[str]:
    """Provider envelope reasons shared by single and batch admission."""

    _declaration, limits = _provider_declaration(provider)
    reasons: list[str] = []
    if requirement.duration_s is not None and requirement.duration_s > limits.max_duration_s:
        reasons.append(
            f"duration {requirement.duration_s}s exceeds provider max {limits.max_duration_s}s"
        )
    return reasons


def _requirement_from_request(payload: dict[str, Any]) -> Any:
    from hevi.creative.layer4.endpoint_lifecycle import CapabilityRequirement

    references = payload.get("reference_images") or []
    return CapabilityRequirement(
        media_type=str(payload.get("media_type") or "video"),
        duration_s=(int(payload["duration_s"]) if payload.get("duration_s") is not None else None),
        resolution=payload.get("resolution"),
        references=len(references) if isinstance(references, (list, tuple)) else 0,
        start_end_frame=bool(payload.get("start_frame") or payload.get("end_frame")),
        native_audio=bool(payload.get("native_audio")),
        async_job=bool(payload.get("async_job", True)),
    )


@router.get("/providers/{provider}/capabilities")
async def provider_capabilities(
    provider: str, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """Server-narrowed capability options for provider settings (E04)."""

    declaration, limits = _provider_declaration(provider)
    return {
        "provider": provider,
        "media_type": declaration.media_type,
        "modes": sorted(limits.modes),
        "max_resolution": list(limits.max_resolution),
        "max_duration_s": limits.max_duration_s,
        "fps_options": sorted(limits.fps_options),
        "native_audio": declaration.native_audio,
        "lip_sync": limits.lip_sync,
        "last_verified": limits.last_verified,
    }


class MediaAdmissionBody(BaseModel):
    requirement: dict[str, Any] = {}


@router.post("/admission/media")
async def admission_media(
    body: MediaAdmissionBody, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """Admit one media request before submit; blocked never reaches a provider."""

    from hevi.creative.layer4.endpoint_lifecycle import (
        check_declared_capability as check_capability,
    )

    provider = str(body.requirement.get("provider") or "")
    declaration, limits = _provider_declaration(provider)
    requirement = _requirement_from_request(body.requirement)
    verdict = check_capability(declaration, requirement)
    reasons = list(verdict.reasons) + _media_limit_reasons(provider, requirement)
    return {
        "admitted": verdict.admitted and not reasons,
        "reasons": reasons,
        "provider": provider,
        "last_verified": limits.last_verified,
    }


class BatchItemBody(BaseModel):
    item_id: str
    requirement: dict[str, Any] = {}
    estimated_cost: float = 0.0


class BatchAdmissionBody(BaseModel):
    items: list[BatchItemBody] = []
    confirm_above_cost: float = 0.0


@router.get("/tasks/{task_id}/editable")
async def task_editable_export(
    task_id: str,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    pool: Annotated[PgPool, Depends(get_pg_pool)],
    as_history: bool = False,
) -> dict[str, Any]:
    """Editable delivery built from the Presentation read model (I02/J05).

    One selection source: the timeline, jianying projection, transitions and
    provenance all come from the same snapshot. STALE exports are explicit
    (never auto-regenerated); HISTORY re-commits the prior selection without
    silently switching back to current; manual/raw media exports unproven with
    no generation claims.
    """

    from hevi.creative.layer4.editable_delivery import (
        EditableError,
        assert_snapshot_parity,
        build_timeline,
        to_editable_doc,
    )
    from hevi.creative.layer4.presentation import (
        PresentationError,
        PresentationLedger,
        for_jianying,
        snapshot_for_serving,
    )
    from hevi.production.artifacts import manifest_from_task
    from hevi.production.delivery_gate import probe_manifest_durations_ms

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid task id") from exc
    task = await _load_task(pool, task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    manifest = manifest_from_task(task)
    if manifest is None:
        raise HTTPException(status_code=404, detail="no artifact manifest")
    try:
        snapshot = snapshot_for_serving(
            manifest,
            task=task,
            probe_durations_ms=probe_manifest_durations_ms(manifest),
            allow_stale=True,  # explicit editable export: stale is usable
        )
    except PresentationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if as_history:
        ledger = PresentationLedger()
        ledger.commit_candidate(snapshot, {snapshot.video.artifact_id: True})
        snapshot = ledger.select_history(snapshot.presentation_version)
    timeline = build_timeline(snapshot)
    try:
        assert_snapshot_parity(timeline, snapshot)
    except EditableError as exc:  # pragma: no cover - guard
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    transitions = [
        {
            "clip_id": clip.clip_id,
            "in": clip.transition_in.model_dump(mode="json"),
            "out": clip.transition_out.model_dump(mode="json"),
        }
        for clip in timeline.clips
    ]
    return {
        "editable": to_editable_doc(timeline),
        "jianying": for_jianying(snapshot),
        "transitions": transitions,
        "selection": {
            "presentation_version": timeline.presentation_version,
            "history_source_version": timeline.history_source_version,
            "currency": timeline.selection_currency,
            "source_unproven": timeline.source_unproven,
            "snapshot_id": str(snapshot.snapshot_id),
        },
    }


@router.post("/admission/batch")
async def admission_batch(
    body: BatchAdmissionBody, _user: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    """All-or-none batch admission before task creation (E06)."""

    from hevi.creative.layer4.plan_projection import admit_batch

    items: list[tuple[str, Any, Any, float]] = []
    limit_reasons: list[str] = []
    for item in body.items:
        provider = str(item.requirement.get("provider") or "")
        declaration, _limits = _provider_declaration(provider)
        requirement = _requirement_from_request(item.requirement)
        limit_reasons.extend(
            f"{item.item_id}: {reason}" for reason in _media_limit_reasons(provider, requirement)
        )
        items.append((item.item_id, declaration, requirement, item.estimated_cost))
    if limit_reasons:
        return {"decision": "blocked", "reasons": limit_reasons, "admitted_items": []}
    return admit_batch(tuple(items), confirm_above_cost=body.confirm_above_cost).model_dump(
        mode="json"
    )
