"""Versioned Studio domain API.

This router exposes canonical objects and revision operations while retaining
the RC6 ``/studio/slates`` and timeline routes. It intentionally returns
plans/envelopes to the caller; provider transport remains behind Compiler and
Slate/runtime boundaries.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.compiler import ProductionCompiler, ProviderCapabilities, ResourceBudget
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.production_graph import (
    AdaptationPlan,
    ExecutionAttempt,
    ExecutionPlan,
    ProductionGraphRepository,
    ProductionMode,
    ProductionProject,
    ProvenanceLink,
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
from hevi.production_graph.adapters.canvas import CanvasProjection, canvas_semantic_patch
from hevi.production_graph.adapters.tongjian import (
    chapter_characters,
    chapter_to_narrative,
    source_document_from_text,
)
from hevi.production_graph.durable_execution import PostgresDurableExecutionStore
from hevi.production_graph.golden_runtime import render_golden_mp4
from hevi.production_graph.ids import new_id
from hevi.production_graph.orchestration import (
    historical_product_entrypoint,
    long_form_product_entrypoint,
    one_prompt_product_entrypoint,
)
from hevi.production_graph.workbench import (
    CandidateRecord,
    CandidateState,
    CreativeMemoryKind,
    CreativeMemoryRecord,
    DependencyRecord,
    DependencyStatus,
    TemplatePolicy,
    VersionRecord,
)
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
    base_revision_id: str | None = None
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
    base_revision_id: str | None = None
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
    base_revision_id: str | None = None
    decision_type: str = "creative_revision"
    rationale: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    operations: list[RevisionPatchOperation] = Field(default_factory=list)


class OnePromptRequest(BaseModel):
    request: str = Field(min_length=1)
    # Local CPU acceptance runs may ask the same product entrypoint to finish
    # the render.  Normal clients omit this field; production storage remains
    # behind the canonical repository/artifact boundary.
    render_path: str | None = None


class HistoricalProductRequest(BaseModel):
    title: str = "Historical Workbench acceptance"
    source_text: str = Field(min_length=20)
    render_path: str | None = None


class LongFormProductRequest(BaseModel):
    title: str = "Long-form Workbench acceptance"
    source_text: str = Field(min_length=40)
    render_path: str | None = None


class CanvasSemanticPatchRequest(BaseModel):
    base_revision_id: str
    reason: str = Field(min_length=1)
    node: dict[str, Any]
    field: str = Field(min_length=1)
    value: Any


class CandidateActionRequest(BaseModel):
    base_revision_id: str | None = None


class MemoryCreateRequest(BaseModel):
    scope: str
    scope_id: str | None = None
    kind: CreativeMemoryKind
    content: str = Field(min_length=1)
    source_session_id: str | None = None


class VersionCreateRequest(BaseModel):
    registry_type: str = Field(pattern="^(prompt|skill)$")
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content: str = Field(min_length=1)


class VersionActivateRequest(BaseModel):
    version_id: str


class TemplateApplyRequest(BaseModel):
    base_revision_id: str | None = None


class ReworkRequest(BaseModel):
    base_revision_id: str
    field: str = "costume"
    value: Any


class CandidateRenderRequest(CompileRequest):
    output_path: str | None = None


async def get_graph_repository(
    pool: Annotated[PgPool, Depends(get_hevi_pg_pool)],
) -> ProductionGraphRepository:
    return ProductionGraphRepository(pool)


UserDep = Annotated[dict[str, Any], Depends(get_current_user)]


async def _finish_one_prompt_render(
    repository: ProductionGraphRepository,
    run: Any,
    task: dict[str, Any],
    output_path: Path,
) -> None:
    """Finish the accepted One-Prompt run through the existing CPU runtime.

    The task projection is written before this function is scheduled.  The
    graph snapshot and attempt are updated only after the real Remotion
    artifact has passed the same manifest validation as the P0 Goldens.
    """

    try:
        manifest = await asyncio.to_thread(
            render_golden_mp4,
            run.production_plan,
            run.execution_plan,
            output_path,
            remotion_dir=Path(__file__).parents[3] / "hevi-remotion",
        )
        artifact = manifest.artifacts[0]
        artifact_id = artifact.artifact_id or artifact.sha256 or artifact.path
        attempt = run.execution_attempt.model_copy(
            update={
                "status": "completed",
                "artifact_ids": [artifact_id],
                "finished_at": datetime.now(UTC),
            }
        )
        final = run.snapshot.model_copy(
            update={
                "execution_attempts": [attempt],
                "provenance_links": [
                    *run.snapshot.provenance_links,
                    ProvenanceLink(
                        id=new_id(),
                        project_id=run.snapshot.project.id,
                        source_type="ExecutionAttempt",
                        source_id=attempt.id,
                        target_type="Artifact",
                        target_id=artifact_id,
                        relation="produced",
                    ),
                ],
            }
        )
        final = await repository.append_revision(
            final, actor="one-prompt-runtime", reason="artifact registered"
        )
        await repository.save_run(
            {
                **task,
                "revision_id": final.revision.id,
                "status": "completed",
                "artifact_id": artifact_id,
                "artifact_path": str(output_path),
                "sha256": artifact.sha256,
                "completed_at": datetime.now(UTC).isoformat(),
            }
        )
        if repository.pool is not None:
            durable = PostgresDurableExecutionStore(repository.pool)
            envelope = await durable.get_by_idempotency(run.execution_plan.idempotency_key)
            if envelope is not None:
                await durable.save(
                    envelope.model_copy(
                        update={
                            "status": "completed",
                            "artifact_ids": [artifact_id],
                            "checkpoint": {"artifact_sha256": artifact.sha256},
                        }
                    )
                )
    except Exception as exc:  # pragma: no cover - exercised by live runtime
        await repository.save_run({**task, "status": "failed", "error": str(exc)})


@router.post("/one-prompt", status_code=status.HTTP_201_CREATED)
async def one_prompt(
    body: OnePromptRequest,
    user: UserDep,
    repository: Annotated[ProductionGraphRepository, Depends(get_graph_repository)],
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Canonical user-facing one-prompt product entrypoint."""

    # Keep the direct orchestration seam used by the frozen P0 Gold C test
    # synchronous when called without FastAPI's injected BackgroundTasks. The
    # real HTTP product path always receives BackgroundTasks and uses the
    # accepted/async branch below.
    if background_tasks is None:
        run = await one_prompt_product_entrypoint(
            repository,
            raw_request=body.request,
            user_id=str(user["id"]),
            render_path=Path(body.render_path) if body.render_path else None,
        )
        return {
            "project_id": run.snapshot.project.id,
            "revision_id": run.snapshot.revision.id,
            "director_session_id": run.snapshot.director_sessions[0].id,
            "director_decision_id": run.snapshot.director_decisions[0].id,
            "production_plan_id": run.production_plan.id,
            "execution_plan_id": run.execution_plan.id,
            "execution_attempt_id": run.execution_attempt.id,
            "task_id": run.execution_attempt.id,
            "status": "completed" if run.execution_attempt.artifact_ids else "accepted",
            "artifact_id": (
                run.execution_attempt.artifact_ids[0]
                if run.execution_attempt.artifact_ids
                else None
            ),
        }

    run = await one_prompt_product_entrypoint(
        repository,
        raw_request=body.request,
        user_id=str(user["id"]),
        render_path=None,
    )
    task_id = run.execution_attempt.id
    output_path = (
        Path(body.render_path)
        if body.render_path
        else Path("/tmp") / f"hevi-one-prompt-{task_id}.mp4"
    )
    task = {
        "run_id": task_id,
        "project_id": run.snapshot.project.id,
        "revision_id": run.snapshot.revision.id,
        "user_id": _user_id(user),
        "status": "queued",
        "stage": "remotion_render",
        "execution_plan_id": run.execution_plan.id,
        "execution_attempt_id": run.execution_attempt.id,
        "artifact_id": None,
    }
    await repository.save_run(task)
    if repository.pool is not None:
        await PostgresDurableExecutionStore(repository.pool).persist_intent(
            envelope_from_execution_plan(run.execution_plan)
        )
    background_tasks.add_task(_finish_one_prompt_render, repository, run, task, output_path)
    return {
        "project_id": run.snapshot.project.id,
        "revision_id": run.snapshot.revision.id,
        "director_session_id": run.snapshot.director_sessions[0].id,
        "director_decision_id": run.snapshot.director_decisions[0].id,
        "production_plan_id": run.production_plan.id,
        "execution_plan_id": run.execution_plan.id,
        "execution_attempt_id": run.execution_attempt.id,
        "task_id": task_id,
        "status": "accepted",
        "artifact_id": None,
    }


@router.post("/product/historical", status_code=status.HTTP_201_CREATED)
async def historical_product(
    body: HistoricalProductRequest,
    user: UserDep,
    repository: Annotated[ProductionGraphRepository, Depends(get_graph_repository)],
) -> dict[str, Any]:
    run = await historical_product_entrypoint(
        repository,
        source_text=body.source_text,
        title=body.title,
        user_id=str(user["id"]),
        render_path=Path(body.render_path) if body.render_path else None,
    )
    return {
        "project_id": run.snapshot.project.id,
        "revision_id": run.snapshot.revision.id,
        "director_session_id": run.snapshot.director_sessions[0].id,
        "production_plan_id": run.production_plan.id,
        "execution_plan_id": run.execution_plan.id,
        "execution_attempt_id": run.execution_attempt.id,
        "artifact_id": run.execution_attempt.artifact_ids[0]
        if run.execution_attempt.artifact_ids
        else None,
    }


@router.post("/product/long-form", status_code=status.HTTP_201_CREATED)
async def long_form_product(
    body: LongFormProductRequest,
    user: UserDep,
    repository: Annotated[ProductionGraphRepository, Depends(get_graph_repository)],
) -> dict[str, Any]:
    run = await long_form_product_entrypoint(
        repository,
        source_text=body.source_text,
        title=body.title,
        user_id=str(user["id"]),
        render_path=Path(body.render_path) if body.render_path else None,
    )
    return {
        "project_id": run.snapshot.project.id,
        "revision_id": run.snapshot.revision.id,
        "director_session_id": run.snapshot.director_sessions[0].id,
        "production_plan_id": run.production_plan.id,
        "execution_plan_id": run.execution_plan.id,
        "execution_attempt_id": run.execution_attempt.id,
        "artifact_id": run.execution_attempt.artifact_ids[0]
        if run.execution_attempt.artifact_ids
        else None,
    }


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
    if body.base_revision_id and body.base_revision_id != snapshot.revision.id:
        raise HTTPException(status_code=409, detail="STALE_REVISION")
    updates = body.model_dump(exclude_unset=True, exclude={"base_revision_id"})
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
    if body.base_revision_id and body.base_revision_id != snapshot.revision.id:
        raise HTTPException(status_code=409, detail="STALE_REVISION")
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


@router.get("/projects/{project_id}/revisions")
async def list_project_revisions(project_id: str, user: UserDep, repo: RepoDep):
    """Read immutable revision metadata for compare/reopen workflows."""

    await _owned_snapshot(repo, project_id, user)
    return {"revisions": [_dump(item) for item in await repo.list_revisions(project_id)]}


@router.get("/projects/{project_id}/canvas")
async def get_project_canvas(project_id: str, user: UserDep, repo: RepoDep):
    """Return a canonical-ID canvas projection; layout is never production state."""

    snapshot = await _owned_snapshot(repo, project_id, user)
    nodes: list[dict[str, Any]] = []
    for collection, production_type in (
        (snapshot.narrative.events if snapshot.narrative else [], "narrative_events"),
        (snapshot.characters, "characters"),
        (snapshot.locations, "locations"),
        (snapshot.props, "props"),
        (snapshot.episodes, "episodes"),
        (snapshot.scenes, "scenes"),
        (snapshot.shots, "shots"),
        (snapshot.keyframes, "keyframes"),
    ):
        for item in collection:
            label = (
                getattr(item, "summary", None)
                or getattr(item, "title", None)
                or getattr(item, "action_description", None)
                or getattr(item, "name", None)
                or item.id
            )
            nodes.append(
                {
                    "node_id": f"{production_type}:{item.id}",
                    "node_type": production_type,
                    "label": str(label),
                    "production_object_id": item.id,
                    "production_type": production_type,
                }
            )
    return CanvasProjection(
        graph_id=f"workbench:{project_id}",
        project_id=project_id,
        revision_id=snapshot.revision.id,
        nodes=nodes,
    ).model_dump(mode="json")


@router.post("/projects/{project_id}/canvas/semantic-patch")
async def patch_project_canvas(
    project_id: str,
    body: CanvasSemanticPatchRequest,
    user: UserDep,
    repo: RepoDep,
):
    """Convert a Canvas semantic action into the same canonical patch path."""

    snapshot = await _owned_snapshot(repo, project_id, user)
    if body.base_revision_id != snapshot.revision.id:
        raise HTTPException(status_code=409, detail="STALE_REVISION")
    try:
        patch = canvas_semantic_patch(
            project_id=project_id,
            revision_id=snapshot.revision.id,
            actor=_user_id(user),
            reason=body.reason,
            node=body.node,
            field=body.field,
            value=body.value,
        )
        if patch is None:
            return {"revision": _dump(snapshot.revision), "semantic": False}
        child = apply_revision_patch(snapshot, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await repo.save_snapshot(child)
    return {"revision": _dump(child.revision), "semantic": True}


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


@router.post("/shots/{shot_id}/candidate-render")
async def render_shot_candidate(
    shot_id: str, body: CandidateRenderRequest, user: UserDep, repo: RepoDep
):
    """Create a second real CPU candidate through Compiler → Slate/runtime.

    This endpoint is intentionally a product-controlled acceptance adapter: it
    records a new immutable plan/attempt and registers the Remotion artifact,
    rather than manufacturing a frontend candidate record.
    """
    snapshot, shot = await _find_shot(repo, shot_id, user)
    if shot.readiness_state is not ReadinessState.READY:
        raise HTTPException(status_code=422, detail="candidate render requires READY shot")
    bundle = next(
        (item for item in snapshot.reference_bundles if item.id == shot.reference_bundle_id), None
    )
    if bundle is None:
        raise HTTPException(status_code=422, detail="shot reference bundle is missing")
    try:
        plan = ProductionCompiler().compile(shot, bundle, body.provider, body.resource_budget)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    candidate_no = (
        len([item for item in snapshot.execution_attempts if item.shot_id == shot.id]) + 1
    )
    # Preserve independent candidate identity in the immutable execution
    # plan, even when deterministic CPU rendering starts from the same Shot.
    plan = plan.model_copy(
        update={
            "prompt": f"{plan.prompt} Candidate {candidate_no}",
            "idempotency_key": f"{plan.idempotency_key}:candidate:{candidate_no}",
            "parameters": {
                **plan.parameters,
                "candidate_variant": candidate_no,
                "version_bindings": [
                    item
                    for item in await repo.list_workbench_records(snapshot.project.id, "p1_version")
                    if item.get("active", False)
                ],
            },
        }
    )
    attempt = ExecutionAttempt(
        project_id=snapshot.project.id,
        revision_id=snapshot.revision.id,
        shot_id=shot.id,
        execution_plan_id=plan.id,
        attempt_no=candidate_no,
        status="running",
        idempotency_key=plan.idempotency_key or new_id(),
        started_at=datetime.now(UTC),
    )
    output = Path(body.output_path or f"/tmp/hevi-candidate-{attempt.id}.mp4")
    production = snapshot.production_plans[-1] if snapshot.production_plans else None
    if production is None:
        raise HTTPException(status_code=422, detail="project has no ProductionPlan")
    try:
        manifest = await asyncio.to_thread(
            render_golden_mp4,
            production,
            plan,
            output,
            remotion_dir=Path(__file__).parents[3] / "hevi-remotion",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"candidate runtime failed: {exc}") from exc
    artifact_id = (
        manifest.artifacts[0].artifact_id
        or manifest.artifacts[0].sha256
        or manifest.artifacts[0].path
    )
    completed = attempt.model_copy(
        update={
            "status": "completed",
            "artifact_ids": [artifact_id],
            "finished_at": datetime.now(UTC),
        }
    )
    child = snapshot.model_copy(
        update={
            "execution_plans": [*snapshot.execution_plans, plan],
            "execution_attempts": [*snapshot.execution_attempts, completed],
            "provenance_links": [
                *snapshot.provenance_links,
                ProvenanceLink(
                    id=new_id(),
                    project_id=snapshot.project.id,
                    source_type="ExecutionAttempt",
                    source_id=completed.id,
                    target_type="Artifact",
                    target_id=artifact_id,
                    relation="produced",
                ),
            ],
        }
    )
    final = await repo.append_revision(
        child, actor=_user_id(user), reason="candidate artifact rendered"
    )
    return {
        "revision": _dump(final.revision),
        "execution_plan": _dump(plan),
        "execution_attempt": _dump(completed),
        "artifact_id": artifact_id,
    }


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


async def _shot_candidates(repo: ProductionGraphRepository, snapshot: Any, shot_id: str):
    records = await repo.list_workbench_records(snapshot.project.id, "p1_candidate")
    candidates = [
        CandidateRecord.model_validate(item) for item in records if item.get("shot_id") == shot_id
    ]
    for attempt in snapshot.execution_attempts:
        if attempt.shot_id != shot_id:
            continue
        if any(item.execution_attempt_id == attempt.id for item in candidates):
            continue
        candidate = CandidateRecord(
            id=attempt.id,
            project_id=snapshot.project.id,
            shot_id=shot_id,
            execution_attempt_id=attempt.id,
            execution_plan_id=attempt.execution_plan_id,
            artifact_id=attempt.artifact_ids[0] if attempt.artifact_ids else None,
            revision_id=snapshot.revision.id,
        )
        await repo.save_workbench_record(
            snapshot.project.id, "p1_candidate", candidate.model_dump(mode="json")
        )
        candidates.append(candidate)
    return candidates


@router.get("/shots/{shot_id}/candidates")
async def list_shot_candidates(shot_id: str, user: UserDep, repo: RepoDep):
    snapshot, _ = await _find_shot(repo, shot_id, user)
    candidates = await _shot_candidates(repo, snapshot, shot_id)
    return {"candidates": [_dump(item) for item in candidates]}


@router.post("/shots/{shot_id}/candidates/{candidate_id}/{action}")
async def candidate_action(
    shot_id: str,
    candidate_id: str,
    action: str,
    body: CandidateActionRequest,
    user: UserDep,
    repo: RepoDep,
):
    snapshot, _ = await _find_shot(repo, shot_id, user)
    if body.base_revision_id and body.base_revision_id != snapshot.revision.id:
        raise HTTPException(status_code=409, detail="STALE_REVISION")
    candidates = await _shot_candidates(repo, snapshot, shot_id)
    candidate = next((item for item in candidates if item.id == candidate_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="unknown candidate")
    allowed: dict[str, set[CandidateState]] = {
        "select": {CandidateState.CANDIDATE},
        "reject": {CandidateState.CANDIDATE, CandidateState.SELECTED},
        "lock": {CandidateState.SELECTED},
        "unlock": {CandidateState.LOCKED},
        "archive": {CandidateState.REJECTED, CandidateState.CANDIDATE},
    }
    if action not in allowed or candidate.state not in allowed[action]:
        raise HTTPException(status_code=422, detail="invalid candidate lifecycle transition")
    if action == "select" and not candidate.artifact_id:
        raise HTTPException(status_code=422, detail="candidate has no real artifact")
    if action == "select":
        for other in candidates:
            if other.id != candidate.id and other.state == CandidateState.LOCKED:
                raise HTTPException(status_code=409, detail="a locked candidate protects this shot")
    target = {
        "select": CandidateState.SELECTED,
        "reject": CandidateState.REJECTED,
        "lock": CandidateState.LOCKED,
        "unlock": CandidateState.SELECTED,
        "archive": CandidateState.ARCHIVED,
    }[action]
    candidate.state = target
    candidate.updated_at = datetime.now(UTC)
    child = await repo.append_revision(snapshot, actor=_user_id(user), reason=f"candidate {action}")
    for item in candidates:
        item.revision_id = child.revision.id
        await repo.save_workbench_record(
            child.project.id, "p1_candidate", item.model_dump(mode="json")
        )
    return {"candidate": _dump(candidate), "revision": _dump(child.revision)}


@router.get("/projects/{project_id}/memory")
async def list_project_memory(project_id: str, user: UserDep, repo: RepoDep):
    await _owned_snapshot(repo, project_id, user)
    records = await repo.list_workbench_records(project_id, "p1_memory")
    return {"memory": records}


@router.post("/projects/{project_id}/memory", status_code=status.HTTP_201_CREATED)
async def create_project_memory(
    project_id: str, body: MemoryCreateRequest, user: UserDep, repo: RepoDep
):
    snapshot = await _owned_snapshot(repo, project_id, user)
    record = CreativeMemoryRecord(
        id=new_id(),
        project_id=project_id,
        revision_id=snapshot.revision.id,
        **body.model_dump(),
    )
    await repo.save_workbench_record(project_id, "p1_memory", record.model_dump(mode="json"))
    return {"memory": _dump(record)}


@router.get("/projects/{project_id}/versions")
async def list_project_versions(project_id: str, user: UserDep, repo: RepoDep):
    await _owned_snapshot(repo, project_id, user)
    records = await repo.list_workbench_records(project_id, "p1_version")
    return {"versions": records}


@router.post("/projects/{project_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_project_version(
    project_id: str, body: VersionCreateRequest, user: UserDep, repo: RepoDep
):
    await _owned_snapshot(repo, project_id, user)
    record = VersionRecord(id=new_id(), project_id=project_id, **body.model_dump())
    await repo.save_workbench_record(project_id, "p1_version", record.model_dump(mode="json"))
    return {"version": _dump(record)}


@router.post("/projects/{project_id}/versions/activate")
async def activate_project_version(
    project_id: str, body: VersionActivateRequest, user: UserDep, repo: RepoDep
):
    snapshot = await _owned_snapshot(repo, project_id, user)
    records = [
        VersionRecord.model_validate(item)
        for item in await repo.list_workbench_records(project_id, "p1_version")
    ]
    target = next((item for item in records if item.id == body.version_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="unknown prompt/skill version")
    for item in records:
        # Activation is scoped to one registry/name pair.  A prompt rollback
        # must never silently deactivate an unrelated skill (or another
        # prompt registry entry) in the same project.
        if item.registry_type == target.registry_type and item.name == target.name:
            item.active = item.id == target.id
        await repo.save_workbench_record(project_id, "p1_version", item.model_dump(mode="json"))
    return {"active_version": _dump(target), "revision_id": snapshot.revision.id}


@router.get("/projects/{project_id}/versions/diff")
async def diff_project_versions(
    project_id: str, from_id: str, to_id: str, user: UserDep, repo: RepoDep
):
    await _owned_snapshot(repo, project_id, user)
    records = [
        VersionRecord.model_validate(item)
        for item in await repo.list_workbench_records(project_id, "p1_version")
    ]
    left = next((item for item in records if item.id == from_id), None)
    right = next((item for item in records if item.id == to_id), None)
    if left is None or right is None:
        raise HTTPException(status_code=404, detail="unknown version")
    return {
        "from": _dump(left),
        "to": _dump(right),
        "changed": left.content != right.content or left.version != right.version,
    }


@router.get("/templates/policies")
async def list_workbench_template_policies(user: UserDep):
    policies = [
        (
            "historical-documentary",
            "Historical Documentary",
            "SHOT_REVIEW",
            "16:9",
            "historical documentary",
            "source-grounded",
            "narration-first",
        ),
        (
            "ai-drama",
            "AI Drama",
            "KEYFRAME_REVIEW",
            "16:9",
            "cinematic drama",
            "coverage",
            "dialogue",
        ),
        (
            "motion-comic",
            "Motion Comic",
            "SHOT_REVIEW",
            "16:9",
            "illustrated panels",
            "panel rhythm",
            "narration",
        ),
        (
            "talking-head",
            "Talking Head",
            "FULL_AUTO",
            "9:16",
            "studio presenter",
            "portrait close-up",
            "voice-first",
        ),
        (
            "explainer",
            "Explainer",
            "FULL_AUTO",
            "16:9",
            "clean explainer",
            "diagram coverage",
            "narration",
        ),
        (
            "kinetic-promo",
            "Kinetic Promo",
            "FULL_AUTO",
            "9:16",
            "kinetic typography",
            "short beats",
            "music-first",
        ),
        (
            "product-ad",
            "Product Ad",
            "KEYFRAME_REVIEW",
            "9:16",
            "product photography",
            "hero/detail",
            "music-first",
        ),
        (
            "trailer",
            "Trailer",
            "SHOT_REVIEW",
            "16:9",
            "trailer contrast",
            "escalating montage",
            "sound-design",
        ),
        (
            "social-short",
            "Social Short",
            "FULL_AUTO",
            "9:16",
            "social native",
            "hook-first",
            "caption-first",
        ),
    ]
    return {
        "templates": [
            TemplatePolicy(
                template_id=template_id,
                name=name,
                production_mode=mode,
                aspect_ratio=aspect,
                visual_style=style,
                shot_strategy=shots,
                audio_strategy=audio,
            ).model_dump(mode="json")
            for template_id, name, mode, aspect, style, shots, audio in policies
        ]
    }


@router.post("/projects/{project_id}/templates/{template_id}/apply")
async def apply_workbench_template(
    project_id: str,
    template_id: str,
    body: TemplateApplyRequest,
    user: UserDep,
    repo: RepoDep,
):
    snapshot = await _owned_snapshot(repo, project_id, user)
    templates = (await list_workbench_template_policies(user))["templates"]
    template = next((item for item in templates if item["template_id"] == template_id), None)
    if template is None:
        raise HTTPException(status_code=404, detail="unknown production template")
    if body.base_revision_id and body.base_revision_id != snapshot.revision.id:
        raise HTTPException(status_code=409, detail="STALE_REVISION")
    budget = dict(snapshot.project.budget_policy)
    budget["workbench_template"] = template
    return await patch_production_project(
        project_id,
        ProjectPatchRequest(
            base_revision_id=snapshot.revision.id,
            aspect_ratio=template["aspect_ratio"],
            visual_style=template["visual_style"],
            production_mode=(
                ProductionMode.AUTO
                if template["production_mode"] == "FULL_AUTO"
                else template["production_mode"]
            ),
            budget_policy=budget,
        ),
        user,
        repo,
    )


def _look_rework_scope(snapshot: Any, look_variant_id: str) -> dict[str, list[str]]:
    look = next((item for item in snapshot.look_variants if item.id == look_variant_id), None)
    if look is None:
        return {"shots": [], "keyframes": [], "reference_bundles": [], "execution_attempts": []}
    shot_ids = [item.id for item in snapshot.shots if look.character_id in item.character_ids]
    return {
        "shots": shot_ids,
        "keyframes": [item.id for item in snapshot.keyframes if item.shot_id in shot_ids],
        "reference_bundles": [
            item.id for item in snapshot.reference_bundles if item.shot_id in shot_ids
        ],
        "execution_attempts": [
            item.id for item in snapshot.execution_attempts if item.shot_id in shot_ids
        ],
    }


@router.get("/projects/{project_id}/rework/look-variants/{look_variant_id}")
async def preview_look_variant_rework(
    project_id: str, look_variant_id: str, user: UserDep, repo: RepoDep
):
    snapshot = await _owned_snapshot(repo, project_id, user)
    scope = _look_rework_scope(snapshot, look_variant_id)
    return {
        "look_variant_id": look_variant_id,
        "scope": scope,
        "unrelated_shots": [item.id for item in snapshot.shots if item.id not in scope["shots"]],
        "status": "STALE" if scope["shots"] else "VALID",
    }


@router.get("/projects/{project_id}/dependencies")
async def list_project_dependencies(project_id: str, user: UserDep, repo: RepoDep):
    """Machine-readable dependency status projection for Workbench and QA."""
    await _owned_snapshot(repo, project_id, user)
    records = await repo.list_workbench_records(project_id, "p1_dependency")
    return {"dependencies": records}


@router.post("/projects/{project_id}/rework/look-variants/{look_variant_id}")
async def apply_look_variant_rework(
    project_id: str,
    look_variant_id: str,
    body: ReworkRequest,
    user: UserDep,
    repo: RepoDep,
):
    snapshot = await _owned_snapshot(repo, project_id, user)
    if body.base_revision_id != snapshot.revision.id:
        raise HTTPException(status_code=409, detail="STALE_REVISION")
    scope = _look_rework_scope(snapshot, look_variant_id)
    operation = RevisionPatchOperation(
        op="replace", path=f"/look_variants/{look_variant_id}/{body.field}", value=body.value
    )
    patch = RevisionPatch(
        project_id=project_id,
        base_revision_id=snapshot.revision.id,
        actor=_user_id(user),
        reason="look variant targeted rework",
        operations=[operation],
    )
    try:
        child = apply_revision_patch(snapshot, patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await repo.save_snapshot(child)
    for target_type, ids in (
        ("reference_bundle", scope["reference_bundles"]),
        ("keyframe", scope["keyframes"]),
        ("shot_artifact", scope["shots"]),
    ):
        for target_id in ids:
            record = DependencyRecord(
                id=new_id(),
                project_id=project_id,
                source_type="look_variant",
                source_id=look_variant_id,
                target_type=target_type,
                target_id=target_id,
                status=DependencyStatus.STALE,
                reason="look variant changed",
                revision_id=child.revision.id,
            )
            await repo.save_workbench_record(
                project_id, "p1_dependency", record.model_dump(mode="json")
            )
    return {"revision": _dump(child.revision), "scope": scope, "status": "STALE"}


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
    if body.base_revision_id and body.base_revision_id != snapshot.revision.id:
        raise HTTPException(status_code=409, detail="STALE_REVISION")
    persisted_memory = [
        item
        for item in await repo.list_workbench_records(snapshot.project.id, "p1_memory")
        if item.get("active", True) and item.get("scope") == "PROJECT"
    ]
    persisted_versions = [
        item
        for item in await repo.list_workbench_records(snapshot.project.id, "p1_version")
        if item.get("active", False)
    ]
    # Memory is advisory context only.  The current user message remains the
    # explicit authority and is stored separately in the decision inputs.
    inputs = dict(body.inputs)
    inputs["creative_memory"] = [item.get("content", "") for item in persisted_memory]
    inputs["memory_authority"] = "current_instruction > canonical_state > project_memory"
    inputs["version_bindings"] = [
        {
            "id": item.get("id"),
            "registry_type": item.get("registry_type"),
            "name": item.get("name"),
            "version": item.get("version"),
        }
        for item in persisted_versions
    ]
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
        inputs=inputs,
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
