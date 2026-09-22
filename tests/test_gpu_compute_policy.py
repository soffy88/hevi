from __future__ import annotations

import pytest

from hevi.production.gpu_compute import GpuComputeProvider, GpuCostEstimate, GpuLease, GpuWorkQueue
from hevi.production.policy import CostEstimate, ProductionConstraints, choose_mode


def test_auto_is_cpu_first_when_gpu_is_not_required() -> None:
    decision = choose_mode(
        "auto",
        gpu_required=False,
        local_gpu_available=False,
        hourly_gpu_available=False,
        estimate=CostEstimate(0.02, 1.50),
    )
    assert decision.mode == "low_cost"
    assert decision.reason == "GPU_NOT_REQUIRED"


def test_gpu_budget_guard_fails_closed() -> None:
    decision = choose_mode(
        "gpu",
        gpu_required=True,
        local_gpu_available=True,
        hourly_gpu_available=False,
        estimate=CostEstimate(0.02, 4.0),
        constraints=ProductionConstraints(max_cost_per_video=1.0),
    )
    assert decision.blocked is True
    assert decision.reason == "GPU_OVER_BUDGET"


class _FakeGpu(GpuComputeProvider):
    name = "fake-gpu"

    def __init__(self) -> None:
        self.released = 0

    def availability(self):
        return None

    def capabilities(self) -> list[str]:
        return ["test"]

    def estimate_cost(self, job):
        return GpuCostEstimate(1.0, 1.0)

    async def acquire(self, job):
        return object()

    async def health_check(self, handle):
        return True

    async def execute(self, handle, job):
        raise RuntimeError("job failure")

    async def collect_artifacts(self, handle, result):
        return []

    async def release(self, handle):
        self.released += 1


@pytest.mark.asyncio
async def test_gpu_lease_releases_on_failure() -> None:
    provider = _FakeGpu()
    with pytest.raises(RuntimeError, match="job failure"):
        async with GpuLease(provider, {"job_id": "one"}) as lease:
            await lease.run()
    assert provider.released == 1


def test_gpu_queue_drains_as_a_batch() -> None:
    queue = GpuWorkQueue()
    queue.submit({"job_id": "a"})
    queue.submit({"job_id": "b"})
    assert [job["job_id"] for job in queue.drain()] == ["a", "b"]
    assert queue.drain() == []
