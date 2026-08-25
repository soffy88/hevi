import uuid

import pytest

from hevi.tasks.dispatch import run_local_compat, schedule_local_compat


class _Pool:
    pass


class _Repo:
    pool = _Pool()


class _Service:
    repository = _Repo()

    async def run_task(self, task_id: uuid.UUID) -> dict[str, object]:
        return {"task_id": str(task_id), "status": "completed"}


class _Sink:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[object, ...]]] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.calls.append((func, args))


@pytest.mark.asyncio
async def test_local_dispatch_runs_only_compat_service() -> None:
    task_id = uuid.uuid4()
    assert await run_local_compat(_Service(), task_id) == {
        "task_id": str(task_id),
        "status": "completed",
    }


def test_local_dispatch_schedules_compat_service() -> None:
    sink = _Sink()
    task_id = uuid.uuid4()

    assert schedule_local_compat(sink, _Service(), task_id)
    assert len(sink.calls) == 1
    assert sink.calls[0][1][1] == task_id
