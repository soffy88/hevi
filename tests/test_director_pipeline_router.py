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


class _FakeConn:
    def __init__(self, fetch_rows: list) -> None:
        self._rows = fetch_rows

    async def fetch(self, *a, **k) -> list:
        return self._rows

    async def fetchrow(self, *a, **k):
        return None

    async def execute(self, *a, **k) -> None:
        return None


class _FakeAcquire:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *a) -> bool:
        return False


class _FakePool:
    """produce_blockers 等 PgPool 裸 SQL 调用的最小假 pool:fetch 默认返回空(无拦截)。"""

    def __init__(self, fetch_rows: list | None = None) -> None:
        self._conn = _FakeConn(fetch_rows or [])

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


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


def test_assign_character_voices_distinct_and_gendered() -> None:
    dl = DesignList(
        characters=[
            DesignCharacter(name="豫让", voice_hint="低沉沙哑"),
            DesignCharacter(name="赵襄子"),
            DesignCharacter(name="侍女", voice_hint="清亮女声"),
            DesignCharacter(name="老将军", voice_id="zh_male_mature"),  # 显式锁定优先
        ]
    )
    cv = dp._assign_character_voices(dl)
    assert cv["老将军"] == "zh_male_mature"  # 显式 voice_id 原样用
    assert cv["侍女"].startswith("zh_female")  # 女声进女池
    assert "deep" in cv["豫让"]  # "低沉沙哑" → deep 音色
    male_voices = [cv["豫让"], cv["赵襄子"]]
    assert len(set(male_voices)) == 2  # 同性别不同角色 → 不同音色(治"都一个声音")


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
    from fastapi import BackgroundTasks

    monkeypatch.chdir(tmp_path)
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    rec["locked_through"] = 1

    subject_svc = AsyncMock()
    subject_svc.create_subject.side_effect = lambda **kw: {"id": f"subj-{kw['name']}"}
    subject_svc.search_subjects.return_value = []  # 无同名已有资产 → 走新建

    async def fake_qwen_generate(*, prompt, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG")
        return output_path

    bg = BackgroundTasks()
    with (
        patch("hevi.image.qwen_image_service.qwen_image_generate", fake_qwen_generate),
        patch.object(dp, "generate_shot_list_draft", AsyncMock(return_value=_shot_list())),
    ):
        immediate = await dp.lock_design_list(work_id, _design_list(), _USER, subject_svc, bg)
        assert immediate["status"] == "design_list_locking"
        await bg()

    resp = dp._work_status(rec)
    assert resp["locked_through"] == 2
    assert resp["status"] == "shot_list_draft"
    char_subject_ids = [c["subject_id"] for c in resp["design_list"]["characters"]]
    assert char_subject_ids == ["subj-智伯", "subj-韩康子"]
    assert subject_svc.create_subject.await_count == 3  # 2 角色 + 1 场景


@pytest.mark.asyncio
async def test_lock_design_list_reuses_existing_same_name_subject(tmp_path, monkeypatch):
    """去重(2026-07-14):锁定时同名(同 kind、同 user)已有 Subject 直接复用,不重建、
    不重新生成参考图——治"每次锁定都新建、角色库堆几十份同名"。"""
    from fastapi import BackgroundTasks

    monkeypatch.chdir(tmp_path)
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    rec["locked_through"] = 1

    subject_svc = AsyncMock()
    subject_svc.create_subject.side_effect = lambda **kw: {"id": f"new-{kw['name']}"}

    async def fake_search(*, kind, query, user_id):
        # 智伯已有一版(复用);韩康子/场景没有(新建)。ILIKE 可能带回近似项,
        # _ensure_subject 只认精确同名。
        if query == "智伯":
            return [{"id": "existing-智伯", "name": "智伯"}, {"id": "noise", "name": "智伯他爹"}]
        return []

    subject_svc.search_subjects.side_effect = fake_search

    generated: list[str] = []

    async def fake_qwen_generate(*, prompt, output_path):
        generated.append(str(output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG")
        return output_path

    bg = BackgroundTasks()
    with (
        patch("hevi.image.qwen_image_service.qwen_image_generate", fake_qwen_generate),
        patch.object(dp, "generate_shot_list_draft", AsyncMock(return_value=_shot_list())),
    ):
        await dp.lock_design_list(work_id, _design_list(), _USER, subject_svc, bg)
        await bg()

    resp = dp._work_status(rec)
    ids = {c["name"]: c["subject_id"] for c in resp["design_list"]["characters"]}
    assert ids["智伯"] == "existing-智伯"  # 复用,精确同名(不误取"智伯他爹")
    assert ids["韩康子"] == "new-韩康子"  # 无同名 → 新建
    # 智伯复用 → 没为它生成参考图,也没为它建号
    assert not any("智伯" in g for g in generated)
    created_names = {c.kwargs["name"] for c in subject_svc.create_subject.await_args_list}
    assert "智伯" not in created_names
    assert "韩康子" in created_names


@pytest.mark.asyncio
async def test_lock_design_list_skips_already_locked_assets(tmp_path, monkeypatch):
    """回退后重锁:已有 subject_id 的项不重复建号(不重复花钱)。"""
    from fastapi import BackgroundTasks

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
    subject_svc.search_subjects.return_value = []  # 无同名已有资产 → 走新建

    async def fake_qwen_generate(*, prompt, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG")
        return output_path

    bg = BackgroundTasks()
    with (
        patch("hevi.image.qwen_image_service.qwen_image_generate", fake_qwen_generate),
        patch.object(dp, "generate_shot_list_draft", AsyncMock(return_value=_shot_list())),
    ):
        await dp.lock_design_list(work_id, design_list, _USER, subject_svc, bg)
        await bg()

    resp = dp._work_status(rec)
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
            work_id, dp.ProduceRequest(), object(), _USER, AsyncMock(), AsyncMock(), _FakePool()
        )
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_produce_schedules_tongjian_render_with_voices_and_refs():
    """产集不走通用长视频管线(orchestrate_longvideo),改后台跑通鉴对白+口型管线
    (_run_director_via_tongjian)。验证:create_task 只用于建行/计费(不 submit_task),
    后台任务拿到按角色分配的不同音色 + 角色参考图。"""
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

    subject_svc = AsyncMock()
    subject_svc.get_subject.return_value = {"reference_images": ["output/subj-zhibo/ref.png"]}

    bg = BackgroundTasks()
    resp = await dp.produce_work(
        work_id, dp.ProduceRequest(), bg, _USER, svc, subject_svc, _FakePool()
    )

    assert resp["status"] == "producing"
    assert resp["video_task_id"] == str(task_id)
    svc.submit_task.assert_not_awaited()  # 明确不走 orchestrate_longvideo 执行路径

    # create_task 建行/计费用真实的数字人 provider 估价
    call_kwargs = svc.create_task.await_args.kwargs
    assert call_kwargs["video_provider"] == "happyhorse_1_1_maas_lock"

    # 后台调度了通鉴渲染,且拿到了正确的音色映射 + 角色参考图
    assert len(bg.tasks) == 1
    bt = bg.tasks[0]
    assert bt.func is dp._run_director_via_tongjian
    cv = bt.kwargs["voice_by_speaker"]
    assert cv["智伯"] == "zh_male_deep"
    assert cv["韩康子"] and cv["韩康子"] != cv["智伯"]  # 同性别不同角色 → 不同音色
    assert bt.kwargs["subject_ref_paths"] == {"智伯": "output/subj-zhibo/ref.png"}


@pytest.mark.asyncio
async def test_produce_insufficient_credits_returns_402_not_500():
    """线上真实复现:积分不够时 InsufficientCredits 原样往外冒,没接住 → 空的 500。"""
    from fastapi import BackgroundTasks

    from hevi.credits.billing_service import InsufficientCredits

    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["design_list"] = _design_list().model_dump()
    rec["shot_list"] = _shot_list().model_dump()
    rec["locked_through"] = 3

    svc = AsyncMock()
    svc.create_task.side_effect = InsufficientCredits(credits_needed=3000, credits_available=1000)

    with pytest.raises(HTTPException) as ei:
        await dp.produce_work(
            work_id, dp.ProduceRequest(), BackgroundTasks(), _USER, svc, AsyncMock(), _FakePool()
        )
    assert ei.value.status_code == 402
    assert ei.value.detail["credits_needed"] == 3000
    assert ei.value.detail["credits_available"] == 1000


# ── 逐镜头准备台端点(INC-001 §A/§G/§I/§L)────────────────────────────────────


def _locked_work() -> str:
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["design_list"] = _design_list().model_dump()
    rec["shot_list"] = _shot_list().model_dump()
    rec["locked_through"] = 3
    return work_id


@pytest.mark.asyncio
async def test_extract_endpoint_passes_shotlistitem_to_service():
    """§G:extract 端点从锁定的 shot_list 取出该 shot 的 ShotListItem 交给服务物化候选。"""
    work_id = _locked_work()
    with (
        patch.object(dp._prep, "extract_shot", AsyncMock()) as ex,
        patch.object(
            dp._prep, "get_preparation_state", AsyncMock(return_value={"status": "pending"})
        ),
    ):
        resp = await dp.extract_shot_candidates(work_id, "SH001_01", _USER, _FakePool())
    assert resp["action"] == "extract"
    assert ex.await_args.args[2].shot_id == "SH001_01"  # 传的是该镜的 ShotListItem


@pytest.mark.asyncio
async def test_extract_endpoint_404_for_unknown_shot():
    work_id = _locked_work()
    with pytest.raises(HTTPException) as ei:
        await dp.extract_shot_candidates(work_id, "NOPE", _USER, _FakePool())
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_confirm_asset_invalid_status_rejected_422():
    work_id = _locked_work()
    with pytest.raises(HTTPException) as ei:
        await dp.confirm_shot_candidate(
            work_id,
            "SH001_01",
            str(uuid.uuid4()),
            dp.ConfirmCandidateRequest(kind="asset", status="bogus"),
            _USER,
            _FakePool(),
        )
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_confirm_invalid_candidate_uuid_422():
    work_id = _locked_work()
    with pytest.raises(HTTPException) as ei:
        await dp.confirm_shot_candidate(
            work_id,
            "SH001_01",
            "not-a-uuid",
            dp.ConfirmCandidateRequest(kind="asset", status="linked"),
            _USER,
            _FakePool(),
        )
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_confirm_dialogue_calls_service_with_status():
    work_id = _locked_work()
    with (
        patch.object(dp._prep, "set_dialogue_candidate", AsyncMock()) as s,
        patch.object(
            dp._prep, "get_preparation_state", AsyncMock(return_value={"status": "ready"})
        ),
    ):
        resp = await dp.confirm_shot_candidate(
            work_id,
            "SH001_01",
            str(uuid.uuid4()),
            dp.ConfirmCandidateRequest(
                kind="dialogue", status="accepted", linked_dialog_line_id="ln1"
            ),
            _USER,
            _FakePool(),
        )
    assert resp["action"] == "confirm"
    assert s.await_args.kwargs["status"] == "accepted"


@pytest.mark.asyncio
async def test_patch_readiness_sets_skip_extraction():
    """§I:PATCH readiness 置 skip_extraction。"""
    work_id = _locked_work()
    with (
        patch.object(dp._prep, "set_skip_extraction", AsyncMock()) as s,
        patch.object(
            dp._prep, "get_preparation_state", AsyncMock(return_value={"status": "ready"})
        ),
    ):
        resp = await dp.patch_shot_readiness(
            work_id, "SH001_01", dp.ReadinessPatch(skip_extraction=True), _USER, _FakePool()
        )
    assert resp["action"] == "skip_extraction"
    assert s.await_args.args[3] is True  # skip 值透传


@pytest.mark.asyncio
async def test_produce_blocked_when_shots_unprepared():
    """§L.2 就绪门:提取后仍 pending 的镜头拦产集(409)。"""
    from fastapi import BackgroundTasks

    work_id = _locked_work()
    with (
        patch.object(dp._prep, "produce_blockers", AsyncMock(return_value=["SH001_01"])),
        pytest.raises(HTTPException) as ei,
    ):
        await dp.produce_work(
            work_id,
            dp.ProduceRequest(),
            BackgroundTasks(),
            _USER,
            AsyncMock(),
            AsyncMock(),
            _FakePool(),
        )
    assert ei.value.status_code == 409
    assert "未完成准备" in ei.value.detail


@pytest.mark.asyncio
async def test_preparation_overview_merges_shotlist_with_readiness():
    """§L.1:概览把锁定 shot_list 的每镜与就绪行合并;未准备过的镜默认 pending。"""
    work_id = _locked_work()
    with (
        patch.object(
            dp._prep,
            "readiness_overview",
            AsyncMock(
                return_value=[
                    {
                        "shot_id": "SH001_01",
                        "status": "ready",
                        "extracted": True,
                        "skip_extraction": False,
                    }
                ]
            ),
        ),
        patch.object(dp._prep, "produce_blockers", AsyncMock(return_value=[])),
    ):
        resp = await dp.preparation_overview(work_id, _USER, _FakePool())
    assert resp["shots"][0]["shot_id"] == "SH001_01"
    assert resp["shots"][0]["status"] == "ready"
    assert resp["blockers"] == []
