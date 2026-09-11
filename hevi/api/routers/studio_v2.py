"""Versioned Studio domain API.

This router exposes canonical objects and revision operations while retaining
the RC6 ``/studio/slates`` and timeline routes. It intentionally returns
plans/envelopes to the caller; provider transport remains behind Compiler and
Slate/runtime boundaries.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.compiler import ProductionCompiler, ProviderCapabilities, ResourceBudget
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production_graph import (
    AdaptationPlan,
    ExecutionPlan,
    ProductionGraphRepository,
    ProductionMode,
    ProductionProject,
    ReadinessContext,
    ReadinessState,
    RevisionPatch,
    RevisionPatchOperation,
    SourceKind,
    apply_revision_patch,
    create_director_session,
    envelope_from_execution_plan,
    prepare_shot,
    record_director_decision,
)
from hevi.production_graph.adapters.tongjian import (
    chapter_characters,
    chapter_to_narrative,
    source_document_from_text,
)
from hevi.production_graph.durable_execution import PostgresDurableExecutionStore
from hevi.studio.slate_bridge import production_plan_to_slate
from hevi.tongjian.schemas import ChapterIR

router = APIRouter(prefix="/studio", tags=["studio-v2"])


class ProjectCreateRequest(BaseModel):
    title: str = "Untitled production"
    source_kind: str = SourceKind.IDEA
    creative_brief: str = ""
    target_platform: str = ""
    aspect_ratio: str = "9:16"
    target_duration: float | None = Field(default=None, ge=0)
    visual_style: str = ""
    language: str = "zh-CN"
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    production_mode: ProductionMode = ProductionMode.AUTO


class ProjectPatchRequest(BaseModel):
    title: str | None = None
    creative_brief: str | None = None
    target_platform: str | None = None
    aspect_ratio: str | None = None
    target_duration: float | None = Field(default=None, ge=0)
    visual_style: str | None = None
    budget_policy: dict[str, Any] | None = None
    production_mode: ProductionMode | None = None


class SourceRequest(BaseModel):
    title: str = "source"
    content: str = Field(min_length=1)
    kind: str = SourceKind.IDEA


class NarrativeBuildRequest(BaseModel):
    source_document_id: str
    chapter: dict[str, Any]


class AdaptRequest(BaseModel):
    source_event_ids: list[str] = Field(default_factory=list)
    target_episode_ids: list[str] = Field(default_factory=list)
    target_duration: float | None = Field(default=None, ge=0)
    objective: str = ""


class PatchRequest(BaseModel):
    reason: str = Field(min_length=1)
    operations: list[RevisionPatchOperation] = Field(min_length=1)


class PrepareRequest(BaseModel):
    context: ReadinessContext = Field(default_factory=ReadinessContext)


class CompileRequest(BaseModel):
    provider: ProviderCapabilities
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)


class RunRequest(BaseModel):
    line_id: str = "shortdrama"
    execute: bool = False
    slots: dict[str, Any] = Field(default_factory=dict)


class DirectorSessionRequest(BaseModel):
    objective: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    memory_scope: str = "PROJECT"


class DirectorMessageRequest(BaseModel):
    decision_type: str = "creative_revision"
    rationale: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    operations: list[RevisionPatchOperation] = Field(default_factory=list)


async def get_graph_repository(
    pool: Annotated[PgPool, Depends(get_hevi_pg_pool)],
) -> ProductionGraphRepository:
    return ProductionGraphRepository(pool)


UserDep = Annotated[dict[str, Any], Depends(get_current_user)]
RepoDep = Annotated[ProductionGraphRepository, Depends(get_graph_repository)]


def _user_id(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("sub") or "")


async def _owned_snapshot(repo: ProductionGraphRepository, project_id: str, user: dict[str, Any]):
    snapshot = await repo.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="unknown production project")
    if snapshot.project.user_id != _user_id(user):
        raise HTTPException(status_code=404, detail="unknown production project")
    return snapshot


def _dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_production_project(body: ProjectCreateRequest, user: UserDep, repo: RepoDep):
    project = ProductionProject(user_id=_user_id(user), **body.model_dump())
    snapshot = await repo.create_project(project)
    return _dump(snapshot)


@router.get("/projects/{project_id}")
async def get_production_project(project_id: str, user: UserDep, repo: RepoDep):
    return _dump(await _owned_snapshot(repo, project_id, user))


@router.get("/projects")
async def list_production_projects(user: UserDep, repo: RepoDep):
    projects = []
    for project_id in await repo.project_ids_for_user(_user_id(user)):
        snapshot = await repo.get_snapshot(project_id)
        if snapshot is not None:
            projects.append(_dump(snapshot.project))
    return {"projects": projects, "total": len(projects)}


@router.patch("/projects/{project_id}")
async def patch_production_project(
    project_id: str, body: ProjectPatchRequest, user: UserDep, repo: RepoDep
):
    snapshot = await _owned_snapshot(repo, project_id, user)
    updates = body.model_dump(exclude_unset=True)
    project = snapshot.project.model_copy(update=updates)
    child = snapshot.model_copy(update={"project": project})
    child = await repo.append_revision(child, actor=_user_id(user), reason="project metadata edit")
    return _dump(child)


@router.post("/projects/{project_id}/sources", status_code=status.HTTP_201_CREATED)
async def add_project_source(project_id: str, body: SourceRequest, user: UserDep, repo: RepoDep):
    snapshot = await _owned_snapshot(repo, project_id, user)
    document, chunk = source_document_from_text(
        project_id=project_id,
        revision_id=snapshot.revision.id,
        title=body.title,
        text=body.content,
    )
    document = document.model_copy(update={"kind": body.kind})
    patch = RevisionPatch(
        project_id=project_id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason="source imported",
        operations=[
            RevisionPatchOperation(
                op="add", path="/sources/-", value=document.model_dump(mode="json")
            ),
            RevisionPatchOperation(
                op="add", path="/source_chunks/-", value=chunk.model_dump(mode="json")
            ),
        ],
    )
    child = apply_revision_patch(snapshot, patch)
    await repo.save_snapshot(child)
    return {"source": _dump(document), "chunks": [_dump(chunk)], "revision": _dump(child.revision)}


@router.get("/projects/{project_id}/narrative")
async def get_project_narrative(project_id: str, user: UserDep, repo: RepoDep):
    snapshot = await _owned_snapshot(repo, project_id, user)
    return (
        _dump(snapshot.narrative)
        if snapshot.narrative
        else {"project_id": project_id, "events": [], "edges": []}
    )


@router.post("/projects/{project_id}/narrative/build")
async def build_project_narrative(
    project_id: str, body: NarrativeBuildRequest, user: UserDep, repo: RepoDep
):
    snapshot = await _owned_snapshot(repo, project_id, user)
    if not any(item.id == body.source_document_id for item in snapshot.sources):
        raise HTTPException(status_code=422, detail="unknown source document")
    try:
        chapter = ChapterIR.model_validate(body.chapter)
        narrative = chapter_to_narrative(
            chapter,
            project_id=project_id,
            revision_id=snapshot.revision.id,
            source_document_id=body.source_document_id,
        )
        characters = chapter_characters(
            chapter, project_id=project_id, revision_id=snapshot.revision.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = {item.id for item in snapshot.characters}
    operations = [
        RevisionPatchOperation(
            op="replace", path="/narrative", value=narrative.model_dump(mode="json")
        ),
        *[
            RevisionPatchOperation(
                op="add", path="/characters/-", value=item.model_dump(mode="json")
            )
            for item in characters
            if item.id not in existing
        ],
    ]
    patch = RevisionPatch(
        project_id=project_id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason="narrative graph built from source",
        operations=operations,
    )
    try:
        child = apply_revision_patch(snapshot, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await repo.save_snapshot(child)
    return {"narrative": _dump(child.narrative), "revision": _dump(child.revision)}


@router.post("/projects/{project_id}/adapt")
async def adapt_project(project_id: str, body: AdaptRequest, user: UserDep, repo: RepoDep):
    snapshot = await _owned_snapshot(repo, project_id, user)
    event_ids = {item.id for item in snapshot.narrative.events} if snapshot.narrative else set()
    if set(body.source_event_ids) - event_ids:
        raise HTTPException(status_code=422, detail="adaptation references unknown narrative event")
    plan = AdaptationPlan(
        project_id=project_id,
        revision_id=snapshot.revision.id,
        source_event_ids=body.source_event_ids,
        target_episode_ids=body.target_episode_ids,
        target_duration=body.target_duration,
        objective=body.objective,
    )
    patch = RevisionPatch(
        project_id=project_id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason="adaptation plan created",
        operations=[
            RevisionPatchOperation(
                op="add", path="/adaptation_plans/-", value=plan.model_dump(mode="json")
            )
        ],
    )
    try:
        child = apply_revision_patch(snapshot, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await repo.save_snapshot(child)
    return {"adaptation_plan": _dump(child.adaptation_plans[-1]), "revision": _dump(child.revision)}


@router.get("/projects/{project_id}/episodes")
async def list_project_episodes(project_id: str, user: UserDep, repo: RepoDep):
    snapshot = await _owned_snapshot(repo, project_id, user)
    return {"episodes": [_dump(item) for item in snapshot.episodes]}


@router.get("/episodes/{episode_id}/scenes")
async def list_episode_scenes(episode_id: str, user: UserDep, repo: RepoDep):
    for project_id in await _project_ids(repo, user):
        snapshot = await repo.get_snapshot(project_id)
        if snapshot and any(item.id == episode_id for item in snapshot.episodes):
            return {
                "scenes": [_dump(item) for item in snapshot.scenes if item.episode_id == episode_id]
            }
    raise HTTPException(status_code=404, detail="unknown episode")


@router.get("/scenes/{scene_id}/shots")
async def list_scene_shots(scene_id: str, user: UserDep, repo: RepoDep):
    for project_id in await _project_ids(repo, user):
        snapshot = await repo.get_snapshot(project_id)
        if snapshot and any(item.id == scene_id for item in snapshot.scenes):
            return {"shots": [_dump(item) for item in snapshot.shots if item.scene_id == scene_id]}
    raise HTTPException(status_code=404, detail="unknown scene")


@router.get("/shots/{shot_id}")
async def get_shot(shot_id: str, user: UserDep, repo: RepoDep):
    _snapshot, shot = await _find_shot(repo, shot_id, user)
    return _dump(shot)


@router.patch("/shots/{shot_id}")
async def patch_shot(shot_id: str, body: PatchRequest, user: UserDep, repo: RepoDep):
    snapshot, shot = await _find_shot(repo, shot_id, user)
    del shot
    patch = RevisionPatch(
        project_id=snapshot.project.id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason=body.reason,
        operations=body.operations,
    )
    try:
        child = apply_revision_patch(snapshot, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await repo.save_snapshot(child)
    updated = next(item for item in child.shots if item.id == shot_id)
    return {"shot": _dump(updated), "revision": _dump(child.revision)}


@router.post("/shots/{shot_id}/prepare")
async def prepare_production_shot(shot_id: str, body: PrepareRequest, user: UserDep, repo: RepoDep):
    snapshot, shot = await _find_shot(repo, shot_id, user)
    prepared, result = prepare_shot(shot, body.context)
    patch = RevisionPatch(
        project_id=snapshot.project.id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason="shot readiness preflight",
        operations=[
            RevisionPatchOperation(
                op="replace",
                path=f"/shots/{shot_id}/readiness_state",
                value=prepared.readiness_state,
            ),
        ],
    )
    child = apply_revision_patch(snapshot, patch)
    child.readiness_results.append(result.model_copy(update={"revision_id": child.revision.id}))
    child.validate_referential_integrity()
    await repo.save_snapshot(child)
    updated = next(item for item in child.shots if item.id == shot_id)
    return {"shot": _dump(updated), "readiness": _dump(result), "revision": _dump(child.revision)}


@router.post("/shots/{shot_id}/compile")
async def compile_production_shot(shot_id: str, body: CompileRequest, user: UserDep, repo: RepoDep):
    snapshot, shot = await _find_shot(repo, shot_id, user)
    if not shot.reference_bundle_id:
        raise HTTPException(status_code=422, detail="shot has no reference bundle")
    bundle = next(
        (item for item in snapshot.reference_bundles if item.id == shot.reference_bundle_id), None
    )
    if bundle is None:
        raise HTTPException(status_code=422, detail="shot reference bundle is missing")
    try:
        plan = ProductionCompiler().compile(shot, bundle, body.provider, body.resource_budget)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"execution_plan": _dump(plan), "immutable": plan.immutable}


@router.post("/shots/{shot_id}/generate")
async def queue_shot_generation(shot_id: str, body: CompileRequest, user: UserDep, repo: RepoDep):
    snapshot, shot = await _find_shot(repo, shot_id, user)
    if shot.readiness_state is not ReadinessState.READY:
        raise HTTPException(status_code=422, detail="generation dispatch requires READY shot")
    compiled = await compile_production_shot(shot_id, body, user, repo)
    plan = ExecutionPlan.model_validate(compiled["execution_plan"])
    envelope = envelope_from_execution_plan(plan)
    if repo.pool is not None:
        await PostgresDurableExecutionStore(repo.pool).persist_intent(envelope)
    patch = RevisionPatch(
        project_id=snapshot.project.id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason="shot queued for generation",
        operations=[
            RevisionPatchOperation(
                op="replace", path=f"/shots/{shot_id}/readiness_state", value=ReadinessState.QUEUED
            )
        ],
    )
    child = apply_revision_patch(snapshot, patch)
    await repo.save_snapshot(child)
    return {"status": "queued", "task": _dump(envelope), "execution_plan": _dump(plan)}


@router.post("/shots/{shot_id}/regenerate")
async def regenerate_shot(shot_id: str, body: CompileRequest, user: UserDep, repo: RepoDep):
    return await queue_shot_generation(shot_id, body, user, repo)


@router.post("/shots/{shot_id}/approve")
async def approve_shot(shot_id: str, user: UserDep, repo: RepoDep):
    return await _transition_shot(shot_id, ReadinessState.APPROVED, user, repo)


@router.post("/shots/{shot_id}/lock")
async def lock_shot(shot_id: str, user: UserDep, repo: RepoDep):
    return await _transition_shot(shot_id, ReadinessState.LOCKED, user, repo)


async def _transition_shot(
    shot_id: str, target: ReadinessState, user: dict[str, Any], repo: ProductionGraphRepository
):
    snapshot, shot = await _find_shot(repo, shot_id, user)
    patch = RevisionPatch(
        project_id=snapshot.project.id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason=f"shot {target.value.lower()}",
        operations=[
            RevisionPatchOperation(
                op="replace", path=f"/shots/{shot_id}/readiness_state", value=target
            )
        ],
    )
    try:
        child = apply_revision_patch(snapshot, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await repo.save_snapshot(child)
    return {
        "shot": _dump(next(item for item in child.shots if item.id == shot.id)),
        "revision": _dump(child.revision),
    }


@router.get("/shots/{shot_id}/revisions")
async def get_shot_revisions(shot_id: str, user: UserDep, repo: RepoDep):
    snapshot, _ = await _find_shot(repo, shot_id, user)
    revisions = [_dump(item) for item in await repo.list_revisions(snapshot.project.id)]
    return {"shot_id": shot_id, "revisions": revisions}


@router.get("/shots/{shot_id}/references")
async def get_shot_references(shot_id: str, user: UserDep, repo: RepoDep):
    snapshot, shot = await _find_shot(repo, shot_id, user)
    bundle = next(
        (item for item in snapshot.reference_bundles if item.id == shot.reference_bundle_id), None
    )
    return {"reference_bundle": _dump(bundle) if bundle else None}


@router.get("/shots/{shot_id}/qa")
async def get_shot_qa(shot_id: str, user: UserDep, repo: RepoDep):
    snapshot, shot = await _find_shot(repo, shot_id, user)
    result = next(
        (item for item in reversed(snapshot.readiness_results) if item.shot_id == shot.id), None
    )
    return {"readiness": _dump(result) if result else None, "qa": {}}


@router.post("/director/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: DirectorSessionRequest,
    project_id: str,
    user: UserDep,
    repo: RepoDep,
):
    snapshot = await _owned_snapshot(repo, project_id, user)
    session = create_director_session(
        snapshot.project,
        objective=body.objective,
        constraints=body.constraints,
        memory_scope=body.memory_scope,
    )
    patch = RevisionPatch(
        project_id=project_id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason="director session opened",
        operations=[
            RevisionPatchOperation(
                op="add", path="/director_sessions/-", value=session.model_dump(mode="json")
            )
        ],
    )
    child = apply_revision_patch(snapshot, patch)
    await repo.save_snapshot(child)
    stored = next(item for item in child.director_sessions if item.id == session.id)
    return {"session": _dump(stored), "revision": _dump(child.revision)}


@router.get("/director/sessions/{session_id}/decisions")
async def get_director_decisions(session_id: str, user: UserDep, repo: RepoDep):
    for project_id in await _project_ids(repo, user):
        snapshot = await repo.get_snapshot(project_id)
        if snapshot and any(item.id == session_id for item in snapshot.director_sessions):
            return {
                "session_id": session_id,
                "decisions": [
                    _dump(item)
                    for item in snapshot.director_decisions
                    if item.session_id == session_id
                ],
            }
    raise HTTPException(status_code=404, detail="unknown Director session")


@router.post("/director/sessions/{session_id}/messages")
async def post_director_message(
    session_id: str, body: DirectorMessageRequest, user: UserDep, repo: RepoDep
):
    snapshot = None
    session = None
    for project_id in await _project_ids(repo, user):
        candidate = await repo.get_snapshot(project_id)
        if candidate is not None:
            session = next(
                (item for item in candidate.director_sessions if item.id == session_id), None
            )
            if session is not None:
                snapshot = candidate
                break
    if snapshot is None or session is None:
        raise HTTPException(status_code=404, detail="unknown Director session")
    operations = list(body.operations)
    patch = RevisionPatch(
        project_id=snapshot.project.id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason=body.rationale or "Director session decision",
        operations=operations
        or [
            RevisionPatchOperation(
                op="replace",
                path=f"/director_sessions/{session.id}/objective",
                value=session.objective,
            )
        ],
    )
    decision = record_director_decision(
        session,
        decision_type=body.decision_type,
        inputs=body.inputs,
        rationale=body.rationale,
        patch=patch if body.operations else None,
    )
    patch.operations.append(
        RevisionPatchOperation(
            op="add", path="/director_decisions/-", value=decision.model_dump(mode="json")
        )
    )
    child = apply_revision_patch(snapshot, patch)
    await repo.save_snapshot(child)
    return {
        "decision": _dump(
            next(item for item in child.director_decisions if item.id == decision.id)
        ),
        "revision": _dump(child.revision),
    }


@router.post("/runs")
async def create_production_run(project_id: str, body: RunRequest, user: UserDep, repo: RepoDep):
    snapshot = await _owned_snapshot(repo, project_id, user)
    plan = snapshot.production_plans[-1] if snapshot.production_plans else None
    if plan is None:
        raise HTTPException(status_code=422, detail="project has no ProductionPlan")
    slate = production_plan_to_slate(
        plan, line_id=body.line_id, slots=body.slots, execute=body.execute
    )
    run = {
        "run_id": slate.slate_id,
        "project_id": project_id,
        "revision_id": snapshot.revision.id,
        "user_id": _user_id(user),
        "status": "scheduled",
        "slate": {"slate_id": slate.slate_id, "line_id": slate.line_id, "slots": slate.slots},
    }
    return await repo.save_run(run)


@router.get("/runs/{run_id}")
async def get_production_run(run_id: str, user: UserDep, repo: RepoDep):
    run = await repo.get_run(run_id, user_id=_user_id(user))
    if run is None:
        raise HTTPException(status_code=404, detail="unknown production run")
    return run


@router.get("/tasks")
async def list_domain_tasks(user: UserDep, repo: RepoDep):
    tasks = await repo.list_runs(user_id=_user_id(user))
    return {"tasks": tasks, "total": len(tasks)}


@router.post("/tasks/{task_id}/cancel")
async def cancel_domain_task(task_id: str, user: UserDep, repo: RepoDep):
    task = await repo.get_run(task_id, user_id=_user_id(user))
    if task is None:
        raise HTTPException(status_code=404, detail="unknown production task")
    task["status"] = "cancelled"
    return await repo.save_run(task)


@router.post("/tasks/{task_id}/retry")
async def retry_domain_task(task_id: str, user: UserDep, repo: RepoDep):
    task = await repo.get_run(task_id, user_id=_user_id(user))
    if task is None:
        raise HTTPException(status_code=404, detail="unknown production task")
    if task["status"] not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="task is not retryable from current state")
    task["status"] = "queued"
    return await repo.save_run(task)


async def _find_shot(repo: ProductionGraphRepository, shot_id: str, user: dict[str, Any]):
    for project_id in await _project_ids(repo, user):
        snapshot = await repo.get_snapshot(project_id)
        if snapshot:
            shot = next((item for item in snapshot.shots if item.id == shot_id), None)
            if shot is not None:
                return snapshot, shot
    raise HTTPException(status_code=404, detail="unknown shot")


async def _project_ids(repo: ProductionGraphRepository, user: dict[str, Any]) -> list[str]:
    return await repo.project_ids_for_user(_user_id(user))


__all__ = ["router"]
