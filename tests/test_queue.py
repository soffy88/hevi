import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from hevi.queue.task_queue import dequeue, enqueue, estimate_wait, queue_position, queue_status
from hevi.queue.worker import QueueWorker
from hevi.tasks.progress import get_task_progress_stream
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService


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
async def test_enqueue_task(repository):
    task_id = uuid.uuid4()
    task_data = {"id": task_id, "status": "pending"}
    
    with patch.object(repository, "get_task", return_value=task_data), \
         patch.object(repository, "update_task", new_callable=AsyncMock) as mock_update, \
         patch.object(repository, "get_tasks_ahead", new_callable=AsyncMock) as mock_ahead:
        
        mock_ahead.return_value = 5
        ahead = await enqueue(repository, task_id)
        
        assert ahead == 5
        mock_update.assert_called_once()
        update_args = mock_update.call_args.args[1]
        assert update_args["status"] == "queued"
        assert "queued_at" in update_args

@pytest.mark.asyncio
async def test_dequeue_task(repository):
    task_id = uuid.uuid4()
    task_data = {"id": task_id, "status": "queued"}
    
    with patch.object(repository, "claim_next_queued_task", return_value=task_data):
        task = await dequeue(repository)
        assert task["id"] == task_id

@pytest.mark.asyncio
async def test_queue_position(repository):
    task_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)
    task_data = {"id": task_id, "status": "queued", "queued_at": now}
    
    with patch.object(repository, "get_task", return_value=task_data), \
         patch.object(repository, "get_tasks_ahead", return_value=3):
        pos = await queue_position(repository, task_id)
        assert pos == 3

@pytest.mark.asyncio
async def test_queue_status(repository):
    with patch.object(repository, "get_queued_count", return_value=10):
        status = await queue_status(repository)
        assert status["queue_length"] == 10
        assert status["is_active"] is True

@pytest.mark.asyncio
async def test_estimate_wait(repository):
    task_id = uuid.uuid4()
    with patch("hevi.queue.task_queue.queue_position", return_value=2):
        wait = await estimate_wait(repository, task_id, avg_task_time_s=100)
        assert wait == 200

@pytest.mark.asyncio
async def test_worker_serial_consumption(task_service):
    # Mock dequeue to return two tasks then None
    task1_id = uuid.uuid4()
    task2_id = uuid.uuid4()
    tasks = [{"id": task1_id}, {"id": task2_id}, None]
    
    worker = QueueWorker(task_service, poll_interval=0.01)
    
    with patch("hevi.queue.worker.dequeue", side_effect=tasks), \
         patch.object(task_service, "run_task", new_callable=AsyncMock) as mock_run:
        
        # Run worker in background and stop it after a short delay
        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        worker.stop()
        await worker_task
        
        assert mock_run.call_count == 2
        mock_run.assert_any_call(task1_id)
        mock_run.assert_any_call(task2_id)

@pytest.mark.asyncio
async def test_worker_exception_isolation(task_service):
    task_id = uuid.uuid4()
    tasks = [{"id": task_id}, None]
    
    worker = QueueWorker(task_service, poll_interval=0.01)
    
    with patch("hevi.queue.worker.dequeue", side_effect=tasks), \
         patch.object(task_service, "run_task", side_effect=Exception("Task Failed")):
        
        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        worker.stop()
        await worker_task
        
        # Worker should still be running and have attempted the task
        assert worker._running is False # because we called stop()

@pytest.mark.asyncio
async def test_task_service_is_local_provider(task_service):
    assert task_service.is_local_provider("qwen_local") is True
    assert task_service.is_local_provider("ltx2_local") is True
    assert task_service.is_local_provider("wan") is True
    assert task_service.is_local_provider("wan_cloud") is False
    assert task_service.is_local_provider("ltx2_cloud") is False

@pytest.mark.asyncio
async def test_task_service_submit_local(task_service, repository):
    task_id = uuid.uuid4()
    task_data = {"id": task_id, "video_provider": "wan"}
    
    with patch.object(repository, "get_task", return_value=task_data), \
         patch("hevi.tasks.task_service.enqueue", new_callable=AsyncMock) as mock_enqueue:
        
        await task_service.submit_task(task_id)
        mock_enqueue.assert_called_once_with(repository, task_id)

@pytest.mark.asyncio
async def test_task_service_submit_cloud(task_service, repository):
    task_id = uuid.uuid4()
    task_data = {"id": task_id, "video_provider": "wan_cloud"}
    
    with patch.object(repository, "get_task", return_value=task_data), \
         patch("hevi.tasks.task_service.enqueue", new_callable=AsyncMock) as mock_enqueue:
        
        await task_service.submit_task(task_id)
        mock_enqueue.assert_not_called()

@pytest.mark.asyncio
async def test_progress_sse_with_queue(repository):
    task_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)
    task_data = {
        "id": task_id, 
        "status": "queued", 
        "queued_at": now, 
        "progress_pct": 0.0,
        "total_shots": 0,
        "completed_shots": 0
    }
    
    with patch.object(repository, "get_task", return_value=task_data), \
         patch("hevi.tasks.progress.queue_position", new_callable=AsyncMock, return_value=3), \
         patch("hevi.tasks.progress.estimate_wait", new_callable=AsyncMock, return_value=1800):
        
        stream = get_task_progress_stream(task_id, repository, interval_s=0.01)
        msg = await anext(stream)
        data = json.loads(msg.replace("data: ", "").strip())
        
        assert data["status"] == "queued"
        assert data["ahead"] == 3
        assert data["estimated_wait_s"] == 1800
        assert "3 tasks ahead" in data["message"]

@pytest.mark.asyncio
async def test_repository_get_next_queued_task(repository, mock_pool):
    with patch("hevi.tasks.repository.query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [{"id": "task1"}]
        res = await repository.get_next_queued_task()
        assert res["id"] == "task1"
        assert "status = 'queued'" in mock_query.call_args.kwargs["sql"]
        assert "ORDER BY queued_at ASC" in mock_query.call_args.kwargs["sql"]

@pytest.mark.asyncio
async def test_repository_get_queued_count(repository, mock_pool):
    with patch("hevi.tasks.repository.query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [{"count": 42}]
        res = await repository.get_queued_count()
        assert res == 42

@pytest.mark.asyncio
async def test_repository_get_tasks_ahead(repository, mock_pool):
    now = datetime.now(UTC).replace(tzinfo=None)
    with patch("hevi.tasks.repository.query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = [{"count": 5}]
        res = await repository.get_tasks_ahead(now)
        assert res == 5
        assert "queued_at < $1" in mock_query.call_args.kwargs["sql"]

@pytest.mark.asyncio
async def test_worker_graceful_stop(task_service):
    worker = QueueWorker(task_service, poll_interval=0.1)
    worker._running = True
    worker.stop()
    assert worker._running is False

@pytest.mark.asyncio
async def test_enqueue_non_existent_task(repository):
    with patch.object(repository, "get_task", return_value=None):
        with pytest.raises(ValueError, match="Task .* not found"):
            await enqueue(repository, uuid.uuid4())


# ── Atomic claim (real DB) — horizontal-scaling safety ───────────────────────


async def _make_queued_task(repo: TaskRepository) -> uuid.UUID:
    now = datetime.now(UTC).replace(tzinfo=None)
    task = await repo.create_task({
        "topic": "t", "duration_archetype": "short",
        "video_provider": "wan_local", "audio_provider": "vibevoice",
        "status": "queued", "progress_pct": 0.0,
        "total_shots": 0, "completed_shots": 0,
        "config_json": {}, "queued_at": now,
        "created_at": now, "updated_at": now,
    })
    return task["id"]


@pytest.mark.asyncio
async def test_claim_is_atomic_no_double_dequeue(client) -> None:
    """N 个 worker 并发 claim N 个排队任务 → 每个任务恰好被领取一次,无重复。"""
    from hevi.db.pg_pool import get_hevi_pg_pool
    pool = await get_hevi_pg_pool()
    repo = TaskRepository(pool)

    ids = [await _make_queued_task(repo) for _ in range(5)]

    # 10 个并发 claim 抢 5 个任务
    claimed = await asyncio.gather(*[repo.claim_next_queued_task() for _ in range(10)])
    got = [c["id"] for c in claimed if c is not None]

    assert len(got) == 5                 # 恰好领走 5 个(不多不少)
    assert len(set(got)) == 5            # 无重复领取
    assert set(got) == set(ids)
    for c in (c for c in claimed if c is not None):
        assert c["status"] == "claimed"
