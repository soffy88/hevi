"""SPEC-003 主线导演流水线路由测试(hevi/api/routers/director_pipeline.py)。

直接调用路由函数(同 test_shortdrama_router.py/test_tasks.py 的既有惯例),mock 掉
真实 LLM 草稿生成 + SubjectService + TaskService,验证状态机推进/回退/守卫逻辑本身。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from hevi.api.routers import director_pipeline as dp
from hevi.director.pipeline_schemas import (
    Concept,
    DesignCharacter,
    DesignList,
    DesignScene,
    Screenplay,
    ScreenplayDialogueLine,
    ScreenplayScene,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
)
from hevi.providers.registry import register_all_providers

_USER = {"id": str(uuid.uuid4())}


@pytest.fixture(autouse=True)
def _clear_works():
    # _resolve_llm() 在草稿生成函数被 mock 掉的情况下依然会真的解析一次 llm(只是
    # 解析出来的对象没被用到)——注册一遍 provider,免得每个测试都要单独 patch。
    register_all_providers()
    dp._WORKS.clear()
    yield
    dp._WORKS.clear()


def _concept() -> Concept:
    return Concept(theme="权臣索地", tone="压抑蓄力", duration_archetype="1-5min")


def _screenplay() -> Screenplay:
    return Screenplay(
        scenes=[
            ScreenplayScene(
                scene_no=1,
                location="宫殿",
                characters_present=["智伯", "韩康子"],
                narration="智伯设宴。",
                dialogue=[
                    ScreenplayDialogueLine(character_name="智伯", text="把地给我。"),
                    ScreenplayDialogueLine(character_name="韩康子", text="不给。"),
                ],
            )
        ]
    )


def _design_list() -> DesignList:
    return DesignList(
        characters=[DesignCharacter(name="智伯"), DesignCharacter(name="韩康子")],
        scenes=[DesignScene(name="宫殿")],
    )


def _shot_list() -> ShotList:
    return ShotList(
        shots=[
            ShotListItem(
                shot_id="SH001_01",
                scene_no=1,
                dialogue_lines=[
                    ShotListDialogueLine(character_name="智伯", text="把地给我。"),
                    ShotListDialogueLine(character_name="韩康子", text="不给。"),
                ],
                character_names=["智伯", "韩康子"],
                scene_name="宫殿",
            )
        ]
    )


# ── work 创建 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_work_generates_concept_draft():
    with patch.object(dp, "generate_concept_draft", AsyncMock(return_value=_concept())):
        resp = await dp.create_work(dp.CreateWorkRequest(material_text="智伯求地于韩康子"), _USER)
    assert resp["status"] == "concept_draft"
    assert resp["locked_through"] == -1
    assert resp["concept"]["theme"] == "权臣索地"


@pytest.mark.asyncio
async def test_create_work_rejects_empty_material():
    with pytest.raises(HTTPException) as ei:
        await dp.create_work(dp.CreateWorkRequest(material_text="   "), _USER)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_get_work_scoped_to_owner():
    work_id = str(uuid.uuid4())
    dp._init_work(work_id, material_text="x", intent_hint="", user_id=_USER["id"])
    other_user = {"id": str(uuid.uuid4())}
    with pytest.raises(HTTPException) as ei:
        await dp.get_work(work_id, other_user)
    assert ei.value.status_code == 404


# ── ①立意锁定 → ②剧本草稿自动生成 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lock_concept_advances_to_screenplay_draft():
    work_id = str(uuid.uuid4())
    dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    with patch.object(dp, "generate_screenplay_draft", AsyncMock(return_value=_screenplay())):
        resp = await dp.lock_concept(work_id, _concept(), _USER)
    assert resp["locked_through"] == 0
    assert resp["status"] == "screenplay_draft"
    assert resp["screenplay"]["scenes"][0]["location"] == "宫殿"


# ── 阶段顺序守卫:上游没锁,下游操作 409 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_screenplay_rejected_before_concept_locked():
    work_id = str(uuid.uuid4())
    dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    with pytest.raises(HTTPException) as ei:
        await dp.regenerate_screenplay(work_id, _USER)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_regenerate_design_list_rejected_before_screenplay_locked():
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["locked_through"] = 0  # concept 锁了,screenplay 还没锁
    with pytest.raises(HTTPException) as ei:
        await dp.regenerate_design_list(work_id, _USER)
    assert ei.value.status_code == 409


# ── 回退语义:重新生成已锁定的上游级 → 清空全部下游 ────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_concept_on_advanced_work_clears_all_downstream():
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    rec["design_list"] = _design_list().model_dump()
    rec["shot_list"] = _shot_list().model_dump()
    rec["locked_through"] = 3  # 全部锁定过
    rec["video_task_id"] = "some-task-id"

    with patch.object(dp, "generate_concept_draft", AsyncMock(return_value=_concept())):
        resp = await dp.regenerate_concept(work_id, _USER)

    assert resp["locked_through"] == -1
    assert resp["screenplay"] is None
    assert resp["design_list"] is None
    assert resp["shot_list"] is None
    assert resp["video_task_id"] is None


@pytest.mark.asyncio
async def test_regenerate_screenplay_on_advanced_work_clears_downstream_only():
    """回退到②剧本 —— ①立意保留(下游 = screenplay 及其后),不清 concept。"""
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    rec["design_list"] = _design_list().model_dump()
    rec["locked_through"] = 2

    with patch.object(dp, "generate_screenplay_draft", AsyncMock(return_value=_screenplay())):
        resp = await dp.regenerate_screenplay(work_id, _USER)

    assert resp["locked_through"] == 0  # 退回到 concept 锁定但 screenplay 未锁
    assert resp["concept"] is not None
    assert resp["design_list"] is None


# ── ③设计清单锁定:建 Subject 资产 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lock_design_list_creates_subjects_and_advances_to_shot_list_draft(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    rec["locked_through"] = 1

    subject_svc = AsyncMock()
    subject_svc.create_subject.side_effect = lambda **kw: {"id": f"subj-{kw['name']}"}

    async def fake_qwen_generate(*, prompt, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG")
        return output_path

    with (
        patch("hevi.image.qwen_image_service.qwen_image_generate", fake_qwen_generate),
        patch.object(dp, "generate_shot_list_draft", AsyncMock(return_value=_shot_list())),
    ):
        resp = await dp.lock_design_list(work_id, _design_list(), _USER, subject_svc)

    assert resp["locked_through"] == 2
    assert resp["status"] == "shot_list_draft"
    char_subject_ids = [c["subject_id"] for c in resp["design_list"]["characters"]]
    assert char_subject_ids == ["subj-智伯", "subj-韩康子"]
    assert subject_svc.create_subject.await_count == 3  # 2 角色 + 1 场景


@pytest.mark.asyncio
async def test_lock_design_list_skips_already_locked_assets(tmp_path, monkeypatch):
    """回退后重锁:已有 subject_id 的项不重复建号(不重复花钱)。"""
    monkeypatch.chdir(tmp_path)
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    rec["locked_through"] = 1

    design_list = _design_list()
    design_list.characters[0].subject_id = "already-locked-subj"

    subject_svc = AsyncMock()
    subject_svc.create_subject.side_effect = lambda **kw: {"id": f"subj-{kw['name']}"}

    async def fake_qwen_generate(*, prompt, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG")
        return output_path

    with (
        patch("hevi.image.qwen_image_service.qwen_image_generate", fake_qwen_generate),
        patch.object(dp, "generate_shot_list_draft", AsyncMock(return_value=_shot_list())),
    ):
        resp = await dp.lock_design_list(work_id, design_list, _USER, subject_svc)

    assert resp["design_list"]["characters"][0]["subject_id"] == "already-locked-subj"
    assert subject_svc.create_subject.await_count == 2  # 只建剩下的 1 角色 + 1 场景


# ── ④分镜锁定 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lock_shot_list_advances_locked_through():
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["locked_through"] = 2
    resp = await dp.lock_shot_list(work_id, _shot_list(), _USER)
    assert resp["locked_through"] == 3
    assert resp["status"] == "shot_list_locked"


# ── ⑤产集 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_produce_rejected_before_shot_list_locked():
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["locked_through"] = 2
    with pytest.raises(HTTPException) as ei:
        await dp.produce_work(
            work_id, dp.ProduceRequest(), object(), _USER, AsyncMock(), AsyncMock()
        )
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_produce_builds_task_and_threads_locked_shot_list_and_voices():
    from fastapi import BackgroundTasks

    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    design_list = _design_list()
    design_list.characters[0].voice_id = "zh_male_deep"
    design_list.characters[0].subject_id = "subj-zhibo"
    rec["design_list"] = design_list.model_dump()
    rec["shot_list"] = _shot_list().model_dump()
    rec["locked_through"] = 3

    task_id = uuid.uuid4()
    svc = AsyncMock()
    svc.create_task.return_value = {"id": task_id, "status": "pending"}
    svc.submit_task.return_value = {"status": "queued"}

    subject_svc = AsyncMock()
    subject_svc.get_subject.return_value = {"reference_images": ["output/subj-zhibo/ref.png"]}

    bg = BackgroundTasks()
    resp = await dp.produce_work(work_id, dp.ProduceRequest(), bg, _USER, svc, subject_svc)

    assert resp["status"] == "producing"
    assert resp["video_task_id"] == str(task_id)
    call_kwargs = svc.create_task.await_args.kwargs
    assert call_kwargs["locked_shot_list"] == rec["shot_list"]
    assert call_kwargs["character_voices"] == {"智伯": "zh_male_deep"}
    # shot 0 出场"智伯"和"韩康子",只有智伯锁了 subject_id → 只解析出智伯这一个参考图。
    assert call_kwargs["shot_character_refs"] == {0: ["output/subj-zhibo/ref.png"]}
