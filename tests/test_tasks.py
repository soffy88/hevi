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
        )


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
