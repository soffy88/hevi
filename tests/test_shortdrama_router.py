"""短剧创建入口路由测试(hevi/api/routers/shortdrama.py)。

直接调用路由函数(同 tests/test_tasks.py 的惯例),用 mock 隔离 LLM 抽取/规划/派发
真实调用;FastAPI TestClient 不自动跑 BackgroundTasks,这里手动执行 bg.tasks 模拟
后台任务真正跑完的效果。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from hevi.api.routers import shortdrama as sd
from hevi.season_planner.schemas import EpisodePlan, SeasonPlan, SubjectRef
from hevi.storygraph.schemas import (
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryMeta,
    StoryRelationship,
)
from hevi.tongjian.schemas import GateResult

_USER = {"id": str(uuid.uuid4())}


def _story() -> StoryGraph:
    return StoryGraph(
        meta=StoryMeta(source="测试短篇", char_count=100),
        characters=[
            StoryCharacter(char_id="C001", name="王生", role="protagonist"),
            StoryCharacter(char_id="C002", name="师父", role="supporting"),
        ],
        relationships=[
            StoryRelationship(from_char="C001", to_char="C002", relation_type="师徒", valence=0.5)
        ],
        events=[
            StoryEvent(
                event_id="E001",
                summary="拜师",
                actors=["C001", "C002"],
                beat_type="铺垫",
                dramatic_weight=3,
            ),
            StoryEvent(
                event_id="E002",
                summary="下山遇冲突",
                actors=["C001"],
                beat_type="冲突",
                dramatic_weight=5,
            ),
        ],
    )


def _plan(story: StoryGraph, target_episodes: int = 2) -> SeasonPlan:
    return SeasonPlan(
        story_source=story.meta.source,
        target_episodes=target_episodes,
        subject_refs=[SubjectRef(char_id=c.char_id, name=c.name) for c in story.characters],
        episodes=[
            EpisodePlan(
                ep_number=1,
                title="第一集",
                event_ids=["E001"],
                characters_present=["C001", "C002"],
            ),
            EpisodePlan(
                ep_number=2, title="第二集", event_ids=["E002"], characters_present=["C001"]
            ),
        ],
    )


def _passing_gate() -> GateResult:
    return GateResult(passed=True, coverage=1.0, errors=[], warnings=[])


def _seed_run(run_id: str, **overrides) -> dict:
    story = _story()
    rec = {
        "run_id": run_id,
        "user_id": _USER["id"],
        "status": "AWAITING_CHARACTERS",
        "source_name": "测试",
        "raw_text": "正文",
        "target_episodes": 2,
        "created_at": datetime.now(UTC),
        "story": story,
        "plan": _plan(story),
        "gate": _passing_gate(),
        "bindings": {},
        "series_id": None,
        "error": None,
    }
    rec.update(overrides)
    sd._RUNS[run_id] = rec
    return rec


async def _run_bg(bg: BackgroundTasks) -> None:
    for task in bg.tasks:
        await task()


@pytest.fixture(autouse=True)
def _clear_runs():
    sd._RUNS.clear()
    yield
    sd._RUNS.clear()


# ── 提交 → AWAITING_CHARACTERS ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_run_reaches_awaiting_characters():
    story = _story()
    plan = _plan(story)
    with (
        patch.object(sd, "extract_story_graph", AsyncMock(return_value=story)),
        patch.object(sd, "build_season_plan", AsyncMock(return_value=(plan, _passing_gate()))),
    ):
        bg = BackgroundTasks()
        resp = await sd.start_run(
            sd.RunRequest(source_name="崂山道士", raw_text="正文" * 10, target_episodes=2),
            bg,
            _USER,
        )
        assert resp["status"] == "PENDING"
        await _run_bg(bg)

    status = await sd.get_run(resp["run_id"], _USER)
    assert status["status"] == "AWAITING_CHARACTERS"
    assert status["season_plan"]["target_episodes"] == 2
    assert [c["char_id"] for c in status["characters"]] == ["C001", "C002"]
    assert all(c["bound"] is False for c in status["characters"])
    assert status["gate"]["passed"] is True


@pytest.mark.asyncio
async def test_start_run_rejects_empty_manuscript():
    with pytest.raises(HTTPException) as ei:
        await sd.start_run(
            sd.RunRequest(source_name="x", raw_text="   ", target_episodes=2),
            BackgroundTasks(),
            _USER,
        )
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_get_run_scoped_to_owner():
    run_id = str(uuid.uuid4())
    _seed_run(run_id)
    other_user = {"id": str(uuid.uuid4())}
    with pytest.raises(HTTPException) as ei:
        await sd.get_run(run_id, other_user)
    assert ei.value.status_code == 404


# ── 重新规划(不满意时用) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replan_resets_bindings_and_regenerates():
    run_id = str(uuid.uuid4())
    _seed_run(run_id, bindings={"C001": {"mode": "existing", "subject_id": "OLD"}})

    new_story = _story()
    new_plan = _plan(new_story)
    with (
        patch.object(sd, "extract_story_graph", AsyncMock(return_value=new_story)),
        patch.object(sd, "build_season_plan", AsyncMock(return_value=(new_plan, _passing_gate()))),
    ):
        bg = BackgroundTasks()
        resp = await sd.replan_run(run_id, bg, _USER)
        assert resp["status"] == "RUNNING"
        # 重新规划视为新一轮角色绑定:旧绑定立即清空,不等后台跑完
        assert sd._RUNS[run_id]["bindings"] == {}
        await _run_bg(bg)

    rec = sd._RUNS[run_id]
    assert rec["status"] == "AWAITING_CHARACTERS"
    assert rec["story"] is new_story
    assert rec["plan"] is new_plan


@pytest.mark.asyncio
async def test_replan_rejects_wrong_status():
    run_id = str(uuid.uuid4())
    _seed_run(run_id, status="DISPATCHED")
    with pytest.raises(HTTPException) as ei:
        await sd.replan_run(run_id, BackgroundTasks(), _USER)
    assert ei.value.status_code == 409


# ── 角色绑定确认 → 派发 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_dispatches_and_records_series_id_with_budget_threaded():
    run_id = str(uuid.uuid4())
    _seed_run(run_id)

    captured: dict = {}

    async def _fake_dispatch(plan_arg, story_arg, **kwargs):
        captured.update(kwargs)
        return {"series_id": "SER-123", "episodes": []}

    with (
        patch.object(sd, "get_hevi_pg_pool", AsyncMock(return_value=object())),
        patch.object(sd, "dispatch_season", AsyncMock(side_effect=_fake_dispatch)),
    ):
        bg = BackgroundTasks()
        body = sd.ConfirmRequest(
            bindings={
                "C001": sd.CharacterBinding(mode="existing", subject_id="S1"),
                "C002": sd.CharacterBinding(mode="existing", subject_id="S2"),
            },
            series_budget_usd=7.5,
        )
        resp = await sd.confirm_run(run_id, body, bg, _USER)
        assert resp["status"] == "DISPATCHING"
        await _run_bg(bg)

    rec = sd._RUNS[run_id]
    assert rec["status"] == "DISPATCHED"
    assert rec["series_id"] == "SER-123"
    # season_budget_usd 传递到 dispatch_season 的 spec(create_episode 靠这个键驱动 B3 熔断)
    assert captured["spec"]["budget_usd"] == 7.5
    assert captured["subject_id_map"] == {"C001": "S1", "C002": "S2"}


@pytest.mark.asyncio
async def test_confirm_actually_triggers_generation_via_tongjian_bridge():
    """2026-07-12 真实撞见的两个大漏洞:(1) dispatch_season 只建 pending 的
    VideoTask,不会自动被真实生成捞走;(2) 通用长视频管线没有对白能力,产出纯旁白。
    现在 confirm 后每集要真的调用 tongjian_bridge.render_episode(对白+口型管线),
    并把结果写回 video_tasks/shot_states,不是随便扔给 task_service.run_task。"""
    run_id = str(uuid.uuid4())
    _seed_run(run_id)

    ep_id = uuid.uuid4()

    async def _fake_dispatch(plan_arg, story_arg, **kwargs):
        return {
            "series_id": "SER-GEN",
            "episodes": [{"id": str(ep_id), "series_id": "SER-GEN", "episode_index": 0}],
        }

    render_calls = []
    from hevi.tongjian.schemas import FinalVideo as _FinalVideo

    async def _fake_render_episode(ep, story, *, run_dir, target_duration_sec, subject_ref_paths):
        render_calls.append((ep.ep_number, story.meta.source, target_duration_sec))
        return {
            "final_video": _FinalVideo(video_path="output/tasks/x/final.mp4"),
            "shots": [
                {
                    "index": 0,
                    "path": "clip0.mp4",
                    "passed": True,
                    "provider": "cloud_avatar",
                    "consistency_score": 0.8,
                    "diagnosis_category": None,
                    "retry_count": 0,
                }
            ],
            "gate_reports": {},
        }

    update_calls = []
    shot_calls = []

    async def _fake_update_task(self, task_id, data):
        update_calls.append((task_id, data))
        return True

    async def _fake_get_task(self, task_id):
        return {"config_json": {"estimated_usd": 12.3}}

    async def _fake_create_shot_state(self, data):
        shot_calls.append(data)
        return data

    async def _fake_delete_shots(self, task_id):
        return None

    with (
        patch.object(sd, "get_hevi_pg_pool", AsyncMock(return_value=object())),
        patch.object(sd, "dispatch_season", AsyncMock(side_effect=_fake_dispatch)),
        patch.object(sd, "render_episode", AsyncMock(side_effect=_fake_render_episode)),
        patch.object(sd.TaskRepository, "update_task", _fake_update_task),
        patch.object(sd.TaskRepository, "get_task", _fake_get_task),
        patch.object(sd.TaskRepository, "create_shot_state", _fake_create_shot_state),
        patch.object(sd.TaskRepository, "delete_shots", _fake_delete_shots),
    ):
        bg = BackgroundTasks()
        body = sd.ConfirmRequest(
            bindings={
                "C001": sd.CharacterBinding(mode="existing", subject_id="S1"),
                "C002": sd.CharacterBinding(mode="existing", subject_id="S2"),
            },
            video_provider="happyhorse_1_1_maas_lock",
        )
        await sd.confirm_run(run_id, body, bg, _USER)
        await _run_bg(bg)
        pending = list(sd._RUN_TASKS)
        if pending:
            await asyncio.gather(*pending)

    assert len(render_calls) == 1
    ep_number, source, target_duration_sec = render_calls[0]
    assert ep_number == 1
    assert target_duration_sec == 180  # "1-5min" 档 → duration_mapper 的 target_s

    statuses = [d["status"] for _tid, d in update_calls]
    assert statuses == ["running", "completed"]
    completed_update = update_calls[-1][1]
    assert completed_update["result_video_path"] == "output/tasks/x/final.mp4"
    assert completed_update["config_json"]["actual_usd"] == 12.3

    assert len(shot_calls) == 1
    assert shot_calls[0]["selection_json"]["consistency_score"] == 0.8


@pytest.mark.asyncio
async def test_confirm_episode_render_failure_marks_task_failed():
    run_id = str(uuid.uuid4())
    _seed_run(run_id)
    ep_id = uuid.uuid4()

    async def _fake_dispatch(plan_arg, story_arg, **kwargs):
        return {
            "series_id": "SER-FAIL",
            "episodes": [{"id": str(ep_id), "series_id": "SER-FAIL", "episode_index": 0}],
        }

    update_calls = []

    async def _fake_update_task(self, task_id, data):
        update_calls.append(dict(data))
        return True

    with (
        patch.object(sd, "get_hevi_pg_pool", AsyncMock(return_value=object())),
        patch.object(sd, "dispatch_season", AsyncMock(side_effect=_fake_dispatch)),
        patch.object(sd, "render_episode", AsyncMock(side_effect=RuntimeError("剧本生成为空壳"))),
        patch.object(sd.TaskRepository, "update_task", _fake_update_task),
    ):
        bg = BackgroundTasks()
        body = sd.ConfirmRequest(
            bindings={
                "C001": sd.CharacterBinding(mode="existing", subject_id="S1"),
                "C002": sd.CharacterBinding(mode="existing", subject_id="S2"),
            },
        )
        await sd.confirm_run(run_id, body, bg, _USER)
        await _run_bg(bg)
        pending = list(sd._RUN_TASKS)
        if pending:
            await asyncio.gather(*pending)

    assert [d["status"] for d in update_calls] == ["running", "failed"]
    assert "剧本生成为空壳" in update_calls[-1]["error"]


@pytest.mark.asyncio
async def test_confirm_reports_progress_while_auto_building_characters(tmp_path, monkeypatch):
    """派发中不该是一整块黑箱——每建一个角色参考图,rec["progress"] 要能看出是第几个、
    是谁,派发完清空(2026-07-12:客户反馈"派发中"卡半小时看不出进度)。"""
    monkeypatch.setattr(sd, "_OUTPUT_DIR", tmp_path / "shortdrama")
    run_id = str(uuid.uuid4())
    _seed_run(run_id)

    progress_snapshots: list[str | None] = []

    async def _fake_qwen_image_generate(*, prompt, output_path):
        progress_snapshots.append(sd._RUNS[run_id]["progress"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake")
        return output_path

    async def _fake_dispatch(plan_arg, story_arg, **kwargs):
        return {"series_id": "SER-777", "episodes": []}

    with (
        patch.object(sd, "get_hevi_pg_pool", AsyncMock(return_value=object())),
        patch.object(sd, "dispatch_season", AsyncMock(side_effect=_fake_dispatch)),
        patch(
            "hevi.image.qwen_image_service.qwen_image_generate",
            AsyncMock(side_effect=_fake_qwen_image_generate),
        ),
        patch.object(
            sd.SubjectService,
            "create_subject",
            AsyncMock(return_value={"id": "AUTO-SUB"}),
        ),
    ):
        bg = BackgroundTasks()
        # 两个角色都留空绑定 → 都走自动生成分支
        await sd.confirm_run(run_id, sd.ConfirmRequest(), bg, _USER)
        await _run_bg(bg)

    assert progress_snapshots == [
        "建角色参考图 1/2: 王生",
        "建角色参考图 2/2: 师父",
    ]
    assert sd._RUNS[run_id]["status"] == "DISPATCHED"
    assert sd._RUNS[run_id]["progress"] is None


@pytest.mark.asyncio
async def test_confirm_retries_transient_portrait_failure(tmp_path, monkeypatch):
    """qwen-image 偶发瞬时失败(2026-07-12 真实撞见对方服务端 bug)不该拖垮整条派发——
    重试几次,单次抖动能扛过去。"""
    monkeypatch.setattr(sd, "_OUTPUT_DIR", tmp_path / "shortdrama")
    monkeypatch.setattr(sd, "_PORTRAIT_RETRY_DELAY_S", 0.0)
    run_id = str(uuid.uuid4())
    _seed_run(run_id)

    calls = {"n": 0}

    async def _flaky_qwen_image_generate(*, prompt, output_path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("InternalError.Algo: DashscopeLogger has no attribute warning")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake")
        return output_path

    async def _fake_dispatch(plan_arg, story_arg, **kwargs):
        return {"series_id": "SER-RETRY", "episodes": []}

    with (
        patch.object(sd, "get_hevi_pg_pool", AsyncMock(return_value=object())),
        patch.object(sd, "dispatch_season", AsyncMock(side_effect=_fake_dispatch)),
        patch(
            "hevi.image.qwen_image_service.qwen_image_generate",
            AsyncMock(side_effect=_flaky_qwen_image_generate),
        ),
        patch.object(
            sd.SubjectService, "create_subject", AsyncMock(return_value={"id": "AUTO-SUB"})
        ),
    ):
        bg = BackgroundTasks()
        await sd.confirm_run(run_id, sd.ConfirmRequest(), bg, _USER)
        await _run_bg(bg)

    assert sd._RUNS[run_id]["status"] == "DISPATCHED"
    assert calls["n"] >= 2  # 第一次失败,重试后成功


@pytest.mark.asyncio
async def test_confirm_retriable_after_dispatch_failure_without_replan():
    """派发阶段失败(story/plan 都还在)不该逼用户重新规划——直接允许再调一次 confirm,
    已经建好的角色(落进 rec["bindings"])不会被重新生成。"""
    run_id = str(uuid.uuid4())
    _seed_run(
        run_id,
        status="FAILED",
        error="qwen-image 任务失败(FAILED): ...",
        bindings={"C001": {"mode": "existing", "subject_id": "ALREADY-BUILT"}},
    )

    captured: dict = {}

    async def _fake_dispatch(plan_arg, story_arg, **kwargs):
        captured.update(kwargs)
        return {"series_id": "SER-RECOVER", "episodes": []}

    with (
        patch.object(sd, "get_hevi_pg_pool", AsyncMock(return_value=object())),
        patch.object(sd, "dispatch_season", AsyncMock(side_effect=_fake_dispatch)),
    ):
        bg = BackgroundTasks()
        body = sd.ConfirmRequest(
            bindings={"C002": sd.CharacterBinding(mode="existing", subject_id="S2")}
        )
        resp = await sd.confirm_run(run_id, body, bg, _USER)
        assert resp["status"] == "DISPATCHING"
        await _run_bg(bg)

    rec = sd._RUNS[run_id]
    assert rec["status"] == "DISPATCHED"
    assert rec["series_id"] == "SER-RECOVER"
    assert rec["error"] is None
    # C001 沿用之前已经建好的 Subject,没有重新生成
    assert captured["subject_id_map"] == {"C001": "ALREADY-BUILT", "C002": "S2"}


@pytest.mark.asyncio
async def test_confirm_uses_pre_bound_upload_over_body_binding():
    """上传参考图预绑定的角色,confirm 时不应再走 body.bindings 或自动生成。"""
    run_id = str(uuid.uuid4())
    _seed_run(run_id, bindings={"C001": {"mode": "existing", "subject_id": "UPLOADED"}})

    captured: dict = {}

    async def _fake_dispatch(plan_arg, story_arg, **kwargs):
        captured.update(kwargs)
        return {"series_id": "SER-999", "episodes": []}

    with (
        patch.object(sd, "get_hevi_pg_pool", AsyncMock(return_value=object())),
        patch.object(sd, "dispatch_season", AsyncMock(side_effect=_fake_dispatch)),
    ):
        bg = BackgroundTasks()
        body = sd.ConfirmRequest(
            bindings={"C002": sd.CharacterBinding(mode="existing", subject_id="S2")},
        )
        await sd.confirm_run(run_id, body, bg, _USER)
        await _run_bg(bg)

    assert captured["subject_id_map"]["C001"] == "UPLOADED"
    assert captured["subject_id_map"]["C002"] == "S2"


@pytest.mark.asyncio
async def test_confirm_rejects_short_duration_archetype():
    run_id = str(uuid.uuid4())
    _seed_run(run_id)
    with pytest.raises(HTTPException) as ei:
        await sd.confirm_run(
            run_id,
            sd.ConfirmRequest(duration_archetype="short"),
            BackgroundTasks(),
            _USER,
        )
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_confirm_rejects_non_positive_budget():
    run_id = str(uuid.uuid4())
    _seed_run(run_id)
    with pytest.raises(HTTPException) as ei:
        await sd.confirm_run(
            run_id,
            sd.ConfirmRequest(series_budget_usd=0),
            BackgroundTasks(),
            _USER,
        )
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_confirm_rejects_wrong_status():
    run_id = str(uuid.uuid4())
    _seed_run(run_id, status="RUNNING")
    with pytest.raises(HTTPException) as ei:
        await sd.confirm_run(run_id, sd.ConfirmRequest(), BackgroundTasks(), _USER)
    assert ei.value.status_code == 409
