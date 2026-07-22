"""主线导演流水线路由测试(hevi/api/routers/director_pipeline.py)。

直接调用路由函数(同 test_shortdrama_router.py/test_tasks.py 的既有惯例),mock 掉
真实 LLM 草稿生成 + SubjectService + TaskService,验证状态机推进/回退/守卫逻辑本身。

V1→V2 原地升级(2026-07-21):④/⑤两级从 V1 的 scene_stage/shot_list 换成 V2 的
world_bible/scene_script,`/produce` 真正调度的也从 `_run_director_via_tongjian` 换成
`_run_v2_produce_task`。逐镜头准备台(INC-001 §A/§G/§I/§L)端点已整段删除,对应测试
一并删除,不是遗漏。V1 专属但仍保留在文件里的辅助函数(`_scene_stage_has_angles`/
`_resolve_subject3d_views`)测试维持不动——那些函数本身没删,只是不再是这五级流程
的一部分。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from hevi.api.routers import director_pipeline as dp
from hevi.director.pipeline_schemas import (
    CharacterVolumeEntry,
    Concept,
    DesignCharacter,
    DesignList,
    DesignScene,
    SceneScript,
    SceneScriptDialogueLine,
    SceneScriptSegment,
    SceneScriptSet,
    Screenplay,
    ScreenplayDialogueLine,
    ScreenplayScene,
    VisualVolume,
    WorldBible,
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
    """裸 SQL 调用的最小假 pool:fetch 默认返回空。"""

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


def _world_bible() -> WorldBible:
    return WorldBible(
        characters=[
            CharacterVolumeEntry(name="智伯", identity_lock_sentence="智伯身份始终一致。"),
            CharacterVolumeEntry(name="韩康子", identity_lock_sentence="韩康子身份始终一致。"),
        ],
        visual=VisualVolume(style_manifesto="写实历史正剧质感。"),
    )


def _scene_script_set() -> SceneScriptSet:
    return SceneScriptSet(
        scripts=[
            SceneScript(
                scene_ref=1,
                characters_present=["智伯", "韩康子"],
                segments=[
                    SceneScriptSegment(
                        segment_id="sg001",
                        order=1,
                        t_start_s=0.0,
                        t_end_s=5.0,
                        narrative_text="智伯设宴索地。",
                        camera_movement="静态对话",
                        dialogue=[
                            SceneScriptDialogueLine(character_name="智伯", text="把地给我。"),
                            SceneScriptDialogueLine(character_name="韩康子", text="不给。"),
                        ],
                    )
                ],
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
    from fastapi import BackgroundTasks

    work_id = str(uuid.uuid4())
    dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    bg = BackgroundTasks()
    with patch.object(dp, "generate_screenplay_draft", AsyncMock(return_value=_screenplay())):
        resp = await dp.lock_concept(work_id, _concept(), _USER, bg)
        assert resp["locked_through"] == 0
        assert resp["status"] == "screenplay_generating"  # ②剧本改后台(含自审)
        await bg()  # 跑后台任务
    settled = dp._work_status(dp._WORKS[work_id])
    assert settled["status"] == "screenplay_draft"
    assert settled["screenplay"]["scenes"][0]["location"] == "宫殿"


# ── 阶段顺序守卫:上游没锁,下游操作 409 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_screenplay_rejected_before_concept_locked():
    from fastapi import BackgroundTasks

    work_id = str(uuid.uuid4())
    dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    with pytest.raises(HTTPException) as ei:
        await dp.regenerate_screenplay(work_id, _USER, BackgroundTasks())
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
    rec["world_bible"] = _world_bible().model_dump()
    rec["scene_script"] = _scene_script_set().model_dump()
    rec["locked_through"] = (
        4  # 全部锁定过(concept0/screenplay1/design_list2/world_bible3/scene_script4)
    )
    rec["video_task_id"] = "some-task-id"

    with patch.object(dp, "generate_concept_draft", AsyncMock(return_value=_concept())):
        resp = await dp.regenerate_concept(work_id, _USER)

    assert resp["locked_through"] == -1
    assert resp["screenplay"] is None
    assert resp["design_list"] is None
    assert resp["world_bible"] is None
    assert resp["scene_script"] is None
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

    from fastapi import BackgroundTasks

    resp = await dp.regenerate_screenplay(work_id, _USER, BackgroundTasks())

    # 回退语义是同步的(_rollback_downstream):concept 保留、下游清空,与后台化无关
    assert resp["locked_through"] == 0  # 退回到 concept 锁定但 screenplay 未锁
    assert resp["status"] == "screenplay_generating"
    assert resp["concept"] is not None
    assert resp["design_list"] is None


# ── ③设计清单锁定:建 Subject 资产 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lock_design_list_creates_subjects_and_advances_to_world_bible_draft(
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

    async def fake_qwen_generate(*, prompt, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG")
        return output_path

    bg = BackgroundTasks()
    with (
        patch("hevi.image.qwen_image_service.qwen_image_generate", fake_qwen_generate),
        patch.object(dp, "generate_world_bible_draft", AsyncMock(return_value=_world_bible())),
    ):
        immediate = await dp.lock_design_list(work_id, _design_list(), _USER, subject_svc, bg)
        assert immediate["status"] == "design_list_locking"
        await bg()

    # V1→V2:③锁定后自动生成的下一级是④World Bible 草案,不再是 V1 的③.5 场面调度。
    resp = dp._work_status(rec)
    assert resp["locked_through"] == 2  # design_list 锁定(index 2 未变)
    assert resp["status"] == "world_bible_draft"
    assert len(resp["world_bible"]["characters"]) == 2
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

    async def fake_qwen_generate(*, prompt, output_path, **kwargs):
        generated.append(str(output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG")
        return output_path

    bg = BackgroundTasks()
    with (
        patch("hevi.image.qwen_image_service.qwen_image_generate", fake_qwen_generate),
        patch.object(dp, "generate_world_bible_draft", AsyncMock(return_value=_world_bible())),
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

    async def fake_qwen_generate(*, prompt, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG")
        return output_path

    bg = BackgroundTasks()
    with (
        patch("hevi.image.qwen_image_service.qwen_image_generate", fake_qwen_generate),
        patch.object(dp, "generate_world_bible_draft", AsyncMock(return_value=_world_bible())),
    ):
        await dp.lock_design_list(work_id, design_list, _USER, subject_svc, bg)
        await bg()

    resp = dp._work_status(rec)
    assert resp["design_list"]["characters"][0]["subject_id"] == "already-locked-subj"
    assert subject_svc.create_subject.await_count == 2  # 只建剩下的 1 角色 + 1 场景


# ── V1 遗留辅助函数(仍保留在文件里,不属于这五级流程,但函数本身没删)──────────────


def test_scene_stage_has_angles():
    """SPEC-004 v2:只有真设了 facing_deg/azimuth_deg 才算有角度(否则不值当建 Subject3D 视图)。
    `_scene_stage_has_angles` 是 V1 遗留辅助函数,当前五级流程不再调用它,但函数本身
    没删(见模块 docstring),这个测试继续覆盖它没坏。"""
    from hevi.director.pipeline_schemas import (
        CameraSetup,
        CoveragePlan,
        InitialPosition,
        SceneBlocking,
        SceneStage,
        SceneStageSet,
    )

    empty = SceneStageSet(stages=[SceneStage(scene_ref=1)])
    assert dp._scene_stage_has_angles(empty) is False
    assert dp._scene_stage_has_angles(None) is False
    with_facing = SceneStageSet(
        stages=[
            SceneStage(
                scene_ref=1,
                blocking=SceneBlocking(
                    initial_positions=[InitialPosition(char_id="甲", facing_deg=90)]
                ),
            )
        ]
    )
    assert dp._scene_stage_has_angles(with_facing) is True
    with_az = SceneStageSet(
        stages=[
            SceneStage(
                scene_ref=1,
                coverage_plan=CoveragePlan(setups=[CameraSetup(setup_id="s1", azimuth_deg=0)]),
            )
        ]
    )
    assert dp._scene_stage_has_angles(with_az) is True


@pytest.mark.asyncio
async def test_resolve_subject3d_views_cached_and_built():
    """已建(metadata.subject3d.views)直接用;未建则调 generate_subject3d 现建。"""
    dl = DesignList(
        characters=[
            DesignCharacter(name="有视图", subject_id="s-cached"),
            DesignCharacter(name="没视图", subject_id="s-build"),
            DesignCharacter(name="无号", subject_id=None),  # 跳过
        ]
    )
    svc = AsyncMock()

    async def _get(sid):
        if sid == "s-cached":
            return {"metadata": {"subject3d": {"views": {"front": "/f.png", "right": "/r.png"}}}}
        return {"metadata": {}}  # 没视图 → 触发生成

    svc.get_subject.side_effect = _get
    svc.generate_subject3d.return_value = {"views": {"front": "/nf.png", "left": "/nl.png"}}

    out = await dp._resolve_subject3d_views(dl, subject_svc=svc)
    assert out["有视图"] == {"front": "/f.png", "right": "/r.png"}
    assert out["没视图"] == {"front": "/nf.png", "left": "/nl.png"}
    assert "无号" not in out
    svc.generate_subject3d.assert_awaited_once_with("s-build")  # 只为没视图的那个建


# ── ④World Bible 锁定 → ⑤Scene Script 草案自动生成 ────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_world_bible_rejected_before_design_list_locked():
    """④未就绪守卫:design_list 没锁,重生成 World Bible → 409。"""
    from fastapi import BackgroundTasks

    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["locked_through"] = 1  # 只锁到 screenplay
    with pytest.raises(HTTPException) as ei:
        await dp.regenerate_world_bible(work_id, _USER, BackgroundTasks())
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_lock_world_bible_advances_and_generates_scene_script_draft():
    """④锁定 → locked_through 推进到 world_bible(index 3),后台自动生成⑤Scene Script
    草案(逐场链式生成)。"""
    from fastapi import BackgroundTasks

    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    rec["design_list"] = _design_list().model_dump()
    rec["locked_through"] = 2  # design_list 锁定

    bg = BackgroundTasks()
    with patch.object(
        dp, "generate_scene_script_draft", AsyncMock(return_value=_scene_script_set().scripts[0])
    ):
        immediate = await dp.lock_world_bible(work_id, _world_bible(), _USER, bg)
        assert immediate["status"] == "world_bible_locking"
        assert immediate["locked_through"] == 3  # world_bible 锁定(index 3)
        await bg()

    resp = dp._work_status(rec)
    assert resp["status"] == "scene_script_draft"
    assert resp["scene_script"]["scripts"][0]["scene_ref"] == 1
    assert resp["scene_script"]["scripts"][0]["segments"][0]["segment_id"] == "sg001"


@pytest.mark.asyncio
async def test_regenerate_concept_clears_world_bible_too():
    """回退到①立意 → 下游(含④World Bible)全清。"""
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["world_bible"] = _world_bible().model_dump()
    rec["locked_through"] = 3  # world_bible 锁定
    with patch.object(dp, "generate_concept_draft", AsyncMock(return_value=_concept())):
        resp = await dp.regenerate_concept(work_id, _USER)
    assert resp["world_bible"] is None
    assert resp["locked_through"] == -1


# ── ⑤Scene Script 锁定 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lock_scene_script_advances_locked_through():
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["locked_through"] = 3  # world_bible 已锁(scene_script 是 index 4)
    resp = await dp.lock_scene_script(work_id, _scene_script_set(), _USER)
    assert resp["locked_through"] == 4
    assert resp["status"] == "scene_script_locked"


# ── ⑥产集 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_produce_rejected_before_scene_script_locked():
    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["locked_through"] = 2
    with pytest.raises(HTTPException) as ei:
        await dp.produce_work(
            work_id, dp.ProduceRequest(), object(), _USER, AsyncMock(), AsyncMock(), _FakePool()
        )
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_produce_schedules_v2_produce_with_voices_and_refs():
    """产集不走通用长视频管线(orchestrate_longvideo),也不走 V1 通鉴口型管线,改后台跑
    `_run_v2_produce_task`(document-first 多角色 reference-to-video 管线)。验证:
    create_task 只用于建行/计费(不 submit_task),后台任务拿到按角色分配的不同音色 +
    角色参考图 + 场景参考图。"""
    from fastapi import BackgroundTasks

    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    design_list = _design_list()
    design_list.characters[0].voice_id = "zh_male_deep"
    design_list.characters[0].subject_id = "subj-zhibo"
    design_list.scenes[0].subject_id = "subj-scene"
    rec["design_list"] = design_list.model_dump()
    rec["world_bible"] = _world_bible().model_dump()
    rec["scene_script"] = _scene_script_set().model_dump()
    rec["locked_through"] = 4  # scene_script 锁定(index 4)

    task_id = uuid.uuid4()
    svc = AsyncMock()
    svc.create_task.return_value = {"id": task_id, "status": "pending", "config_json": {}}

    subject_svc = AsyncMock()

    async def _get_subject(sid):
        return {
            "subj-zhibo": {"reference_images": ["output/subj-zhibo/ref.png"]},
            "subj-scene": {"reference_images": ["output/subj-scene/ref.png"]},
        }.get(sid, {"reference_images": []})

    subject_svc.get_subject.side_effect = _get_subject

    bg = BackgroundTasks()
    resp = await dp.produce_work(
        work_id, dp.ProduceRequest(), bg, _USER, svc, subject_svc, _FakePool()
    )

    assert resp["status"] == "producing"
    assert resp["video_task_id"] == str(task_id)
    svc.submit_task.assert_not_awaited()  # 明确不走 orchestrate_longvideo 执行路径

    # create_task 建行/计费用真实的 V2 provider 估价
    call_kwargs = svc.create_task.await_args.kwargs
    assert call_kwargs["video_provider"] == "happyhorse_1_1_maas_ref"

    # 后台调度了 V2 产集,且拿到了正确的音色映射 + 角色/场景参考图
    assert len(bg.tasks) == 1
    bt = bg.tasks[0]
    assert bt.func is dp._run_v2_produce_task
    cv = bt.kwargs["voice_by_speaker"]
    assert cv["智伯"] == "zh_male_deep"
    assert cv["韩康子"] and cv["韩康子"] != cv["智伯"]  # 同性别不同角色 → 不同音色
    assert bt.kwargs["subject_ref_paths"] == {"智伯": "output/subj-zhibo/ref.png"}
    assert bt.kwargs["scene_ref_paths"] == {"宫殿": "output/subj-scene/ref.png"}
    assert bt.kwargs["world_bible"].characters[0].name == "智伯"
    assert bt.kwargs["scene_script_set"].scripts[0].scene_ref == 1


@pytest.mark.asyncio
async def test_produce_insufficient_credits_returns_402_not_500():
    """线上真实复现:积分不够时 InsufficientCredits 原样往外冒,没接住 → 空的 500。"""
    from fastapi import BackgroundTasks

    from hevi.credits.billing_service import InsufficientCredits

    work_id = str(uuid.uuid4())
    rec = dp._init_work(work_id, material_text="素材", intent_hint="", user_id=_USER["id"])
    rec["concept"] = _concept().model_dump()
    rec["screenplay"] = _screenplay().model_dump()
    rec["design_list"] = _design_list().model_dump()
    rec["world_bible"] = _world_bible().model_dump()
    rec["scene_script"] = _scene_script_set().model_dump()
    rec["locked_through"] = 4  # scene_script 锁定(index 4)

    svc = AsyncMock()
    svc.create_task.side_effect = InsufficientCredits(credits_needed=3000, credits_available=1000)

    with pytest.raises(HTTPException) as ei:
        await dp.produce_work(
            work_id, dp.ProduceRequest(), BackgroundTasks(), _USER, svc, AsyncMock(), _FakePool()
        )
    assert ei.value.status_code == 402
    assert ei.value.detail["credits_needed"] == 3000
    assert ei.value.detail["credits_available"] == 1000
