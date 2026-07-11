import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from hevi.tasks.models import ShotState, VideoTask
from hevi.tasks.progress import get_task_progress_stream
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService


def test_video_task_model_instantiation():
    task_id = uuid.uuid4()
    task = VideoTask(
        id=task_id,
        topic="test",
        duration_archetype="1-5min",
        video_provider="v",
        audio_provider="a",
        status="pending",
    )
    assert task.id == task_id
    assert task.status == "pending"


def test_shot_state_model_instantiation():
    task_id = uuid.uuid4()
    shot = ShotState(
        task_id=task_id,
        shot_index=0,
        status="completed",
        output_path="path/to/shot.mp4",
    )
    assert shot.task_id == task_id
    assert shot.shot_index == 0
    assert shot.status == "completed"


@pytest.mark.asyncio
async def test_repository_direct_methods(repository, mock_pool):
    task_id = uuid.uuid4()

    # get_task
    with patch("hevi.tasks.repository.read_one", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = {"id": task_id}
        await repository.get_task(task_id)
        mock_read.assert_called_once_with(mock_pool, table="video_tasks", id=task_id)

    # update_task
    with patch("hevi.tasks.repository.update_one", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = True
        await repository.update_task(task_id, {"status": "completed"})
        mock_update.assert_called_once_with(
            mock_pool, table="video_tasks", id=task_id, data={"status": "completed"}
        )

    # create_shot_state
    with patch("hevi.tasks.repository.insert_one", new_callable=AsyncMock) as mock_insert:
        mock_insert.return_value = {"id": uuid.uuid4()}
        await repository.create_shot_state({"task_id": task_id, "shot_index": 0})
        mock_insert.assert_called_once()
        assert mock_insert.call_args.kwargs["table"] == "shot_states"


@pytest.fixture
def mock_pool():
    return AsyncMock()


@pytest.fixture
def repository(mock_pool):
    return TaskRepository(mock_pool)


@pytest.fixture
def task_service(repository):
    return TaskService(repository)


@pytest.mark.asyncio
async def test_create_task_persistence(task_service):
    task_id = uuid.uuid4()
    with (
        patch("hevi.tasks.repository.insert_one", new_callable=AsyncMock) as mock_insert,
        patch("hevi.tasks.repository.read_one", new_callable=AsyncMock) as mock_read,
    ):
        mock_insert.return_value = task_id
        mock_read.return_value = {"id": task_id, "status": "pending"}
        res = await task_service.create_task(
            topic="Space",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )
        assert res["status"] == "pending"
        mock_insert.assert_called_once()
        args = mock_insert.call_args.kwargs
        assert args["table"] == "video_tasks"
        assert args["data"]["topic"] == "Space"


@pytest.mark.asyncio
async def test_run_task_success(task_service, repository):
    task_id = uuid.uuid4()
    task_data = {
        "id": task_id,
        "topic": "test",
        "duration_archetype": "1-5min",
        "video_provider": "ltx2_cloud",
        "audio_provider": "vibevoice",
        "config_json": {"style": "cinematic"},
        "status": "pending",
        "progress_pct": 0.0,
    }

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(repository, "update_task", new_callable=AsyncMock) as mock_update,
        patch("hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock) as mock_orch,
    ):
        mock_orch.return_value = {"url": "video.mp4", "duration": 180.0, "metadata": {"shots": 10}}

        res = await task_service.run_task(task_id)
        assert res["status"] == "completed"
        assert res["result_video_path"] == "video.mp4"
        assert res["completed_shots"] == 10

        # Should be called for 'running' and then 'completed'
        assert mock_update.call_count >= 2
        from unittest.mock import ANY

        mock_orch.assert_called_once_with(
            topic="test",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
            output_dir=ANY,
            style="cinematic",
            progress_cb=ANY,  # SaaS-4:逐阶段进度回调随调用注入
            character_reference=ANY,  # 角色库:按 subject_id 解析的参考图(此处 None)
            subject_version=ANY,  # shot_verdict 版本快照(此处 None,无 subject_id)
        )


@pytest.mark.asyncio
async def test_persist_shots_writes_verdict_extension_fields(task_service, repository):
    """shot_verdict 扩展(HEVI 路线图 Phase1):_persist_shots 要把 result_mapper 补上的
    style_score/diagnosis_category/subject 快照等字段原样带进 selection_json,不是只落
    旧的 provider/consistency_score/passed/duration_s 五件套。"""
    task_id = uuid.uuid4()
    shots = [
        {
            "index": 0,
            "path": "s0.mp4",
            "provider": "wan_local",
            "variant_chosen": 0,
            "consistency_score": 0.9,
            "passed": True,
            "duration_s": 3.0,
            "style_score": None,
            "vlm_score": None,
            "diagnosis_category": None,
            "subject_id": "sub-1",
            "subject_version": 2,
            "style_pack_id": "pack-1",
            "style_pack_version": 4,
            "model_version": "wan_local",
            "tier0_passed": True,
            "tier1_passed": None,
        }
    ]
    with patch.object(repository, "create_shot_state", new_callable=AsyncMock) as mock_create:
        await task_service._persist_shots(task_id, shots)
        mock_create.assert_called_once()
        payload = mock_create.call_args.args[0]
        sel = payload["selection_json"]
        assert sel["subject_id"] == "sub-1"
        assert sel["subject_version"] == 2
        assert sel["style_pack_id"] == "pack-1"
        assert sel["style_pack_version"] == 4
        assert sel["tier0_passed"] is True
        assert sel["tier1_passed"] is None
        assert sel["retry_count"] == 0  # 未传入时默认 0(首次生成),不是 None


@pytest.mark.asyncio
async def test_regenerate_task_shots_increments_retry_count_only_for_regenerated(
    task_service, repository
):
    """重试次数硬上限(设计文档 §4.3):regenerate 整片删旧落新,但 retry_count 要按
    shot_index 从旧 shot_states 里读回来接着累加,本轮没点名的镜头保持原值不变。"""
    task_id = uuid.uuid4()
    task_data = {
        "id": task_id,
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "wan_local",
        "audio_provider": "vibevoice",
        "config_json": {},
        "status": "completed",
    }
    old_shots = [
        {"shot_index": 0, "selection_json": {"retry_count": 1}},
        {"shot_index": 1, "selection_json": {"retry_count": 0}},
    ]

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(repository, "get_shots", new_callable=AsyncMock, return_value=old_shots),
        patch.object(repository, "delete_shots", new_callable=AsyncMock),
        patch.object(repository, "create_shot_state", new_callable=AsyncMock) as mock_create,
        patch.object(repository, "update_task", new_callable=AsyncMock),
        patch("hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock) as mock_orch,
    ):
        mock_orch.return_value = {
            "url": "v.mp4",
            "shots": [
                {"index": 0, "provider": "wan_local", "passed": True},
                {"index": 1, "provider": "wan_local", "passed": True},
            ],
        }
        await task_service.regenerate_task_shots(task_id, shot_ids=[0])

        persisted = {
            c.args[0]["shot_index"]: c.args[0]["selection_json"]["retry_count"]
            for c in mock_create.call_args_list
        }
        assert persisted[0] == 2  # regenerated this round → 1 + 1
        assert persisted[1] == 0  # untouched → carried over unchanged


@pytest.mark.asyncio
async def test_regenerate_task_shots_raises_when_all_requested_shots_at_retry_cap(
    task_service, repository
):
    task_id = uuid.uuid4()
    task_data = {"id": task_id, "status": "completed", "config_json": {}}
    capped_shots = [{"shot_index": 0, "selection_json": {"retry_count": 3}}]

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(repository, "get_shots", new_callable=AsyncMock, return_value=capped_shots),
        patch("hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock) as mock_orch,
    ):
        with pytest.raises(ValueError, match="retry cap"):
            await task_service.regenerate_task_shots(task_id, shot_ids=[0])
        mock_orch.assert_not_awaited()  # 到上限就不该再花算力


@pytest.mark.asyncio
async def test_regenerate_task_shots_skips_capped_shot_but_proceeds_with_others(
    task_service, repository
):
    task_id = uuid.uuid4()
    task_data = {
        "id": task_id,
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "wan_local",
        "audio_provider": "vibevoice",
        "status": "completed",
        "config_json": {},
    }
    mixed_shots = [
        {"shot_index": 0, "selection_json": {"retry_count": 3}},  # 已到上限
        {"shot_index": 1, "selection_json": {"retry_count": 0}},
    ]

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(repository, "get_shots", new_callable=AsyncMock, return_value=mixed_shots),
        patch.object(repository, "delete_shots", new_callable=AsyncMock),
        patch.object(repository, "create_shot_state", new_callable=AsyncMock),
        patch.object(repository, "update_task", new_callable=AsyncMock),
        patch("hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock) as mock_orch,
    ):
        mock_orch.return_value = {"url": "v.mp4", "shots": [{"index": 1, "passed": True}]}
        await task_service.regenerate_task_shots(task_id, shot_ids=[0, 1])
        # 剔掉已到上限的 0,只把 1 传给 orchestrate。
        assert mock_orch.call_args.kwargs["regenerate_shot_ids"] == [1]


@pytest.mark.asyncio
async def test_regenerate_endpoint_409_when_all_shots_at_retry_cap():
    """fire-and-forget 端点:到上限这件事必须同步查完就 409,不能让请求看似成功、
    实际后台任务里悄悄抛 ValueError 没人看到(设计文档 §4.3)。"""
    from fastapi import BackgroundTasks

    from hevi.api.routers.tasks import RegenerateRequest
    from hevi.api.routers.tasks import regenerate_task_shots as regenerate_endpoint

    task_id = uuid.uuid4()
    svc = AsyncMock()
    svc.repository.get_task.return_value = {"id": task_id, "user_id": "u1", "status": "completed"}
    svc.repository.get_shots.return_value = [
        {"shot_index": 0, "selection_json": {"retry_count": 3}}
    ]
    body = RegenerateRequest(shot_ids=[0], hints=None)

    with pytest.raises(Exception) as ei:
        await regenerate_endpoint(task_id, body, {"id": "u1"}, svc, BackgroundTasks())
    assert getattr(ei.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_resolve_subject_version_returns_none_without_subject_id(task_service):
    task = {"config_json": {}}
    assert await task_service._resolve_subject_version(task) is None


@pytest.mark.asyncio
async def test_resolve_subject_version_reads_subject_service(task_service):
    task = {"config_json": {"subject_id": "sub-1"}}
    with patch(
        "hevi.subjects.subject_service.SubjectService.get_subject", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = {"id": "sub-1", "version": 7}
        assert await task_service._resolve_subject_version(task) == 7


@pytest.mark.asyncio
async def test_resolve_subject_version_swallows_errors(task_service):
    task = {"config_json": {"subject_id": "sub-1"}}
    with patch(
        "hevi.subjects.subject_service.SubjectService.get_subject", new_callable=AsyncMock
    ) as mock_get:
        mock_get.side_effect = RuntimeError("db down")
        assert await task_service._resolve_subject_version(task) is None


@pytest.mark.asyncio
async def test_run_task_auto_rework_on_failed_quality(task_service, repository):
    """L3 体检闭环:体检不过 + 镜头一致性偏低 → run_task 触发定向返工(封顶 1 轮)。"""
    task_id = uuid.uuid4()
    task_data = {
        "id": task_id,
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "wan_local",
        "audio_provider": "vibevoice",
        "config_json": {},  # auto_rework 走 settings 默认(1 轮)
        "status": "pending",
        "progress_pct": 0.0,
    }
    failing_shots = [
        {"shot_index": 0, "selection_json": {"passed": False, "consistency_score": 0.1}}
    ]

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(repository, "update_task", new_callable=AsyncMock),
        patch.object(repository, "get_shots", new_callable=AsyncMock, return_value=failing_shots),
        patch("hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock) as mock_orch,
        patch.object(task_service, "regenerate_task_shots", new_callable=AsyncMock) as mock_regen,
    ):
        mock_orch.return_value = {
            "url": "v.mp4",
            "duration": 180.0,
            "metadata": {"shots": 1},
            "quality": {"passed": False, "violations": ["dur"], "consistency": 0.5},
        }
        await task_service.run_task(task_id)
        # 封顶 1 轮 → 恰好定向返工一次,shot_ids 来自 Editor 裁决。
        mock_regen.assert_awaited_once()
        assert mock_regen.await_args.kwargs["shot_ids"] == [0]


@pytest.mark.asyncio
async def test_run_task_no_rework_when_quality_passes(task_service, repository):
    """L3:体检过 + 镜头合格 → 不返工(合格片零额外开销)。"""
    task_id = uuid.uuid4()
    task_data = {
        "id": task_id,
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "wan_local",
        "audio_provider": "vibevoice",
        "config_json": {},
        "status": "pending",
        "progress_pct": 0.0,
    }
    good_shots = [{"shot_index": 0, "selection_json": {"passed": True, "consistency_score": 0.95}}]

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(repository, "update_task", new_callable=AsyncMock),
        patch.object(repository, "get_shots", new_callable=AsyncMock, return_value=good_shots),
        patch("hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock) as mock_orch,
        patch.object(task_service, "regenerate_task_shots", new_callable=AsyncMock) as mock_regen,
    ):
        mock_orch.return_value = {
            "url": "v.mp4",
            "duration": 180.0,
            "metadata": {"shots": 1},
            "quality": {"passed": True, "violations": [], "consistency": 0.95},
        }
        await task_service.run_task(task_id)
        mock_regen.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_task_failure(task_service, repository):
    task_id = uuid.uuid4()
    task_data = {
        "id": task_id,
        "topic": "test",
        "duration_archetype": "1-5min",
        "video_provider": "v",
        "audio_provider": "a",
        "config_json": {},
        "status": "pending",
    }

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(repository, "update_task", new_callable=AsyncMock) as mock_update,
        patch(
            "hevi.tasks.task_service.orchestrate_longvideo", side_effect=Exception("API Overload")
        ),
    ):
        res = await task_service.run_task(task_id)
        assert res["status"] == "failed"
        assert res["error"] == "API Overload"
        mock_update.assert_called()


@pytest.mark.asyncio
async def test_resume_task_from_failed(task_service, repository):
    task_id = uuid.uuid4()
    task_data = {"id": task_id, "status": "failed", "topic": "t"}

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(task_service, "run_task", new_callable=AsyncMock) as mock_run,
    ):
        await task_service.resume_task(task_id)
        mock_run.assert_called_once_with(task_id)


@pytest.mark.asyncio
async def test_resume_task_already_running(task_service, repository):
    task_id = uuid.uuid4()
    task_data = {"id": task_id, "status": "running"}

    with (
        patch.object(repository, "get_task", return_value=task_data),
        patch.object(task_service, "run_task", new_callable=AsyncMock) as mock_run,
    ):
        res = await task_service.resume_task(task_id)
        assert res["status"] == "running"
        mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_progress_sse_stream(repository):
    task_id = uuid.uuid4()
    task_states = [
        {"status": "running", "progress_pct": 30.0, "total_shots": 10, "completed_shots": 3},
        {"status": "completed", "progress_pct": 100.0, "total_shots": 10, "completed_shots": 10},
    ]

    with patch.object(repository, "get_task", side_effect=task_states):
        stream = get_task_progress_stream(task_id, repository, interval_s=0.01)
        messages = []
        async for msg in stream:
            messages.append(msg)

        assert len(messages) == 2
        data0 = json.loads(messages[0].replace("data: ", "").strip())
        assert data0["status"] == "running"
        assert data0["progress_pct"] == 30.0

        data1 = json.loads(messages[1].replace("data: ", "").strip())
        assert data1["status"] == "completed"


@pytest.mark.asyncio
async def test_progress_stream_not_found(repository):
    task_id = uuid.uuid4()
    with patch.object(repository, "get_task", return_value=None):
        stream = get_task_progress_stream(task_id, repository)
        async for msg in stream:
            assert "Task not found" in msg
            break


@pytest.mark.asyncio
async def test_repository_list_tasks(repository, mock_pool):
    with patch("hevi.tasks.repository.query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [{"id": "1"}, {"id": "2"}]
        res = await repository.list_tasks(limit=5)
        assert len(res) == 2
        mock_query.assert_called_once()
        assert "SELECT * FROM video_tasks" in mock_query.call_args.kwargs["sql"]


@pytest.mark.asyncio
async def test_repository_get_shots(repository, mock_pool):
    task_id = uuid.uuid4()
    with patch("hevi.tasks.repository.query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [{"shot_index": 0}]
        res = await repository.get_shots(task_id)
        assert len(res) == 1
        mock_query.assert_called_once()
        assert "shot_states" in mock_query.call_args.kwargs["sql"]
        assert mock_query.call_args.kwargs["params"] == [task_id]


# ── /video, /cover, /export 取片端点(§7 成片规格 —— 封面此前只落盘从未暴露)────


@pytest.mark.asyncio
async def test_get_task_cover_serves_sidecar_jpg(tmp_path):
    """装配器自动产出的 <final>.cover.jpg —— 之前无端点暴露,现在能取到。"""
    from hevi.api.routers.tasks import get_task_cover

    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00" * 128)
    cover = tmp_path / "final.cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1", "result_video_path": str(video)}
    with patch("hevi.api.routers.tasks.decode_access_token", return_value={"sub": "u1"}):
        resp = await get_task_cover(uuid.uuid4(), repo, token="tok")
    assert resp.path == str(cover)
    assert resp.media_type == "image/jpeg"


@pytest.mark.asyncio
async def test_get_task_cover_404_when_missing(tmp_path):
    """封面还没生成(装配失败等)→ 404,不是裸异常。"""
    from hevi.api.routers.tasks import get_task_cover

    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00" * 128)  # 没有对应 .cover.jpg

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1", "result_video_path": str(video)}
    with patch("hevi.api.routers.tasks.decode_access_token", return_value={"sub": "u1"}):
        with pytest.raises(Exception) as ei:
            await get_task_cover(uuid.uuid4(), repo, token="tok")
    assert getattr(ei.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_export_task_video_mp4_passthrough(tmp_path):
    """format=mp4(默认)→ 直传 final.mp4,不转码。"""
    from hevi.api.routers.tasks import export_task_video

    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00" * 128)

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1", "result_video_path": str(video)}
    with patch("hevi.api.routers.tasks.decode_access_token", return_value={"sub": "u1"}):
        resp = await export_task_video(uuid.uuid4(), repo, token="tok", format="mp4")
    assert resp.path == str(video)
    assert resp.media_type == "video/mp4"


@pytest.mark.asyncio
async def test_export_task_video_mov_remuxes_via_exporter(tmp_path):
    """format=mov → 调 export_video 产出 .mov,缓存在成片旁(不重复转)。"""
    from hevi.api.routers.tasks import export_task_video

    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00" * 128)

    async def fake_export(input_path, output_path, fmt):
        output_path.write_bytes(b"\x00" * 64)
        return output_path

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1", "result_video_path": str(video)}
    with (
        patch("hevi.api.routers.tasks.decode_access_token", return_value={"sub": "u1"}),
        patch(
            "hevi.assembly.exporter.export_video", new_callable=AsyncMock, side_effect=fake_export
        ),
    ):
        resp = await export_task_video(uuid.uuid4(), repo, token="tok", format="mov")
    assert resp.path == str(video.with_suffix(".mov"))
    assert resp.media_type == "video/quicktime"


@pytest.mark.asyncio
async def test_export_task_video_bad_format_400():
    from fastapi import HTTPException

    from hevi.api.routers.tasks import export_task_video

    repo = AsyncMock()
    with pytest.raises(HTTPException) as ei:
        await export_task_video(uuid.uuid4(), repo, token="tok", format="avi")
    assert ei.value.status_code == 400


# ── /dub 翻译配音导出(§3 L2 护城河 —— 此前只有核心逻辑,无 API 出口)────────


@pytest.mark.asyncio
async def test_dub_task_video_generates_and_caches(tmp_path):
    """首次请求现算(mock dub_video)→ 落盘缓存;鉴权/归属校验同 /video。"""
    from hevi.api.routers.tasks import dub_task_video

    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00" * 128)

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1", "result_video_path": str(video)}

    async def fake_dub(*, video_path, target_language, output_path):
        output_path.write_bytes(b"\x00" * 64)
        return {"output": str(output_path), "language": target_language, "cues": 3}

    with (
        patch("hevi.api.routers.tasks.decode_access_token", return_value={"sub": "u1"}),
        patch("hevi.dub.dub_video", new_callable=AsyncMock, side_effect=fake_dub),
    ):
        resp = await dub_task_video(uuid.uuid4(), repo, token="tok", language="en")
    expected = tmp_path / "final.dub_en.mp4"
    assert resp.path == str(expected)
    assert expected.exists()


@pytest.mark.asyncio
async def test_dub_task_video_reuses_cached_file(tmp_path):
    """同语种已生成过 → 不重新跑 dub_video,直接回传缓存。"""
    from hevi.api.routers.tasks import dub_task_video

    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00" * 128)
    cached = tmp_path / "final.dub_en.mp4"
    cached.write_bytes(b"\x00" * 32)

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1", "result_video_path": str(video)}
    with (
        patch("hevi.api.routers.tasks.decode_access_token", return_value={"sub": "u1"}),
        patch("hevi.dub.dub_video", new_callable=AsyncMock) as mdub,
    ):
        resp = await dub_task_video(uuid.uuid4(), repo, token="tok", language="en")
    mdub.assert_not_awaited()
    assert resp.path == str(cached)


@pytest.mark.asyncio
async def test_dub_task_video_failure_returns_500(tmp_path):
    from hevi.api.routers.tasks import dub_task_video

    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00" * 128)

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1", "result_video_path": str(video)}
    with (
        patch("hevi.api.routers.tasks.decode_access_token", return_value={"sub": "u1"}),
        patch("hevi.dub.dub_video", new_callable=AsyncMock, side_effect=RuntimeError("asr down")),
    ):
        with pytest.raises(Exception) as ei:
            await dub_task_video(uuid.uuid4(), repo, token="tok", language="en")
    assert getattr(ei.value, "status_code", None) == 500


# ── 连续性报告(HEVI 路线图 Phase3 #41)────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_continuity_report_aggregates_shots():
    from hevi.api.routers.tasks import get_continuity_report

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1"}
    repo.get_shots.return_value = [
        {
            "shot_index": 0,
            "status": "completed",
            "selection_json": {"passed": True, "consistency_score": 0.9, "provider": "wan_local"},
        },
        {
            "shot_index": 1,
            "status": "failed",
            "selection_json": {
                "passed": False,
                "consistency_score": 0.2,
                "diagnosis_category": "参考图角色错配",
            },
        },
    ]
    report = await get_continuity_report(uuid.uuid4(), {"id": "u1"}, repo)
    assert report["summary"]["total_shots"] == 2
    assert report["summary"]["passed_shots"] == 1
    assert report["summary"]["diagnosis_breakdown"] == {"参考图角色错配": 1}


@pytest.mark.asyncio
async def test_get_continuity_report_404_for_missing_task():
    from hevi.api.routers.tasks import get_continuity_report

    repo = AsyncMock()
    repo.get_task.return_value = None
    with pytest.raises(Exception) as ei:
        await get_continuity_report(uuid.uuid4(), {"id": "u1"}, repo)
    assert getattr(ei.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_get_continuity_report_404_for_other_users_task():
    from hevi.api.routers.tasks import get_continuity_report

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "someone-else"}
    with pytest.raises(Exception) as ei:
        await get_continuity_report(uuid.uuid4(), {"id": "u1"}, repo)
    assert getattr(ei.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_list_task_shots_projects_shot_cards():
    from hevi.api.routers.tasks import list_task_shots

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "u1"}
    repo.get_shots.return_value = [
        {
            "shot_index": 0,
            "status": "completed",
            "output_path": "shots/0.mp4",
            "selection_json": {"passed": True, "consistency_score": 0.9, "retry_count": 0},
        },
        {
            "shot_index": 1,
            "status": "failed",
            "output_path": None,
            "selection_json": {"passed": False, "consistency_score": 0.2,
                               "diagnosis_category": "参考图角色错配", "retry_count": 2},
        },
    ]
    shots = await list_task_shots(uuid.uuid4(), {"id": "u1"}, repo)
    assert len(shots) == 2
    assert shots[0] == {
        "shot_index": 0, "status": "completed", "has_output": True,
        "consistency_score": 0.9, "passed": True, "diagnosis_category": None, "retry_count": 0,
    }
    assert shots[1]["has_output"] is False
    assert shots[1]["diagnosis_category"] == "参考图角色错配"


@pytest.mark.asyncio
async def test_list_task_shots_404_for_other_users_task():
    from hevi.api.routers.tasks import list_task_shots

    repo = AsyncMock()
    repo.get_task.return_value = {"id": "t1", "user_id": "someone-else"}
    with pytest.raises(Exception) as ei:
        await list_task_shots(uuid.uuid4(), {"id": "u1"}, repo)
    assert getattr(ei.value, "status_code", None) == 404
