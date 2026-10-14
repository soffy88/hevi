"""ShotSpec API —— 单镜规格的读写(GAP_PLAN §2 W1)。

挂在 ``/api`` 前缀下(与 tasks 路由同),端点:

  - ``GET   /tasks/{id}/shots/{i}/spec``  读单镜规格(未设置 → ``spec: null``)
  - ``PATCH /tasks/{id}/shots/{i}/spec``  部分更新(只覆盖显式给出的字段)
  - ``PUT   /tasks/{id}/shots/spec``      批量整组替换(逐条校验,任一非法整体 422)

规格持久化在任务现有 shot 存储里(``shot_states.selection_json["shot_spec"]``),
不新建数据库表——与 ``hevi.season_planner.preparation`` 的零迁移做法一致。

最小侵入:不新增 router 文件之外的东西,复用 tasks 路由的 ``get_repository`` 依赖
与鉴权。单独挂到 app(见 ``hevi/api/main.py``)。
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from hevi.api.routers.tasks import get_repository
from hevi.auth.dependencies import get_current_user
from hevi.production.shot_spec import (
    SFXCue,
    ShotSpec,
    clear_cached_task_spec,
    merge_patch,
    read_spec,
    upsert_spec,
)
from hevi.production.shot_spec_render import is_pure_transition_template
from hevi.tasks.repository import TaskRepository

router = APIRouter(prefix="/tasks", tags=["shot-spec"])


# ── Request schemas ──────────────────────────────────────────────────────────


class ShotSpecPatch(BaseModel):
    """PATCH 请求体:全部字段可选。只更新显式给出的键(``exclude_unset``)。

    这里不做逐字段校验——单字段单独看未必合法(如只改 ``sfx`` 而 duration 由旧值
    提供),校验放到合并后的完整规格上做。
    """

    model_config = ConfigDict(extra="forbid")

    template: str | None = None
    transition_in: str | None = None
    effect: str | None = None
    style: str | None = None
    sfx: list[SFXCue] | None = None
    camera: str | None = None
    subtitle_style: str | None = None
    duration: float | None = None


class ShotSpecEntry(BaseModel):
    """批量里的单条:镜号 + 完整规格。"""

    shot_index: int
    spec: ShotSpec


class ShotSpecBatch(BaseModel):
    """PUT 请求体:整组规格。列出的镜号按 spec 替换,未列出的镜号清空规格。"""

    specs: list[ShotSpecEntry]


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _load_owned_task(
    task_id: UUID, user: dict[str, Any], repo: TaskRepository
) -> dict[str, Any]:
    task = await repo.get_task(task_id)
    if not task or (task.get("user_id") and task["user_id"] != str(user["id"])):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _load_shot(repo: TaskRepository, task_id: UUID, shot_index: int) -> dict[str, Any]:
    shots = await repo.get_shots(task_id)
    shot = next((s for s in shots if s["shot_index"] == shot_index), None)
    if shot is None:
        raise HTTPException(status_code=404, detail=f"shot {shot_index} not found")
    return shot


def _validation_detail(exc: ValidationError) -> list[dict[str, Any]]:
    """pydantic 错误 → JSON 安全 detail(ctx 里可能塞着 ValueError 对象,不能直接序列化)。"""
    return [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors(include_url=False)
    ]


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/{task_id}/shots/{shot_index}/spec")
async def get_shot_spec(
    task_id: UUID,
    shot_index: int,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """读一镜规格;未设置时 ``spec`` 为 null。"""
    await _load_owned_task(task_id, user, repo)
    shot = await _load_shot(repo, task_id, shot_index)
    spec = read_spec(shot)
    return {
        "task_id": str(task_id),
        "shot_index": shot_index,
        "spec": spec.to_dict() if spec is not None else None,
    }


@router.patch("/{task_id}/shots/{shot_index}/spec")
async def patch_shot_spec(
    task_id: UUID,
    shot_index: int,
    body: ShotSpecPatch,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """部分更新一镜规格。只覆盖请求体里显式给出的字段;校验失败 422。"""
    await _load_owned_task(task_id, user, repo)
    shot = await _load_shot(repo, task_id, shot_index)

    base = read_spec(shot) or ShotSpec()
    patch = body.model_dump(exclude_unset=True)
    try:
        merged = merge_patch(base, patch)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc

    if shot_index == 0 and is_pure_transition_template(merged.template):
        raise HTTPException(
            status_code=422,
            detail="纯转场模板仅作用于入场接缝，不可用于第 1 镜 (shot_index 0 无入场转场)",
        )

    upsert_spec(shot, merged)
    await repo.save_shot(shot)
    return {
        "task_id": str(task_id),
        "shot_index": shot_index,
        "spec": merged.to_dict(),
    }


@router.put("/{task_id}/shots/spec")
async def put_shot_specs(
    task_id: UUID,
    body: ShotSpecBatch,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    repo: Annotated[TaskRepository, Depends(get_repository)],
) -> dict[str, Any]:
    """批量整组替换:逐条校验(任一非法整体 422,不落任何一条),列出的镜号替换,
    未列出的镜号规格清空。"""
    await _load_owned_task(task_id, user, repo)
    shots = await repo.get_shots(task_id)
    by_index = {s["shot_index"]: s for s in shots}

    # 先整体校验镜号存在(任一不存在 → 404,不落任何一条)。
    # 纯转场模板不可用于第 1 镜 (shot_index 0)。
    for entry in body.specs:
        if entry.shot_index not in by_index:
            raise HTTPException(status_code=404, detail=f"shot {entry.shot_index} not found")
        if entry.shot_index == 0 and is_pure_transition_template(entry.spec.template):
            raise HTTPException(
                status_code=422,
                detail="纯转场模板仅作用于入场接缝，不可用于第 1 镜 (shot_index 0 无入场转场)",
            )

    # body.specs 里的 spec 已由 pydantic 逐条校验(非法 → FastAPI 自动 422)。

    listed = {entry.shot_index for entry in body.specs}
    # 整组替换:未列出的镜号清空规格。
    for idx, shot in by_index.items():
        if idx not in listed:
            sel = dict(shot.get("selection_json") or {})
            if "shot_spec" in sel:
                sel.pop("shot_spec")
                shot["selection_json"] = sel
                await repo.save_shot(shot)
            clear_cached_task_spec(task_id, idx)

    for entry in body.specs:
        shot = by_index[entry.shot_index]
        upsert_spec(shot, entry.spec)
        await repo.save_shot(shot)

    return {
        "task_id": str(task_id),
        "count": len(body.specs),
        "specs": [{"shot_index": e.shot_index, "spec": e.spec.to_dict()} for e in body.specs],
    }
