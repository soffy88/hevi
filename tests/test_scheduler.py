from datetime import UTC, datetime, timedelta
from uuid import uuid4

from hevi.execution import ResourceSnapshot, Scheduler, SchedulingRequest


def request(**overrides: object) -> SchedulingRequest:
    values: dict[str, object] = {
        "task_id": uuid4(),
        "tenant_id": "tenant-a",
        "priority": 0,
        "resource_class": "gpu-video",
        "provider_id": "wan_local",
        "expected_cost_usd": 1.0,
        "budget_remaining_usd": 10.0,
    }
    values.update(overrides)
    return SchedulingRequest(**values)


def resources(**overrides: object) -> ResourceSnapshot:
    values: dict[str, object] = {
        "worker_id": "gpu-1",
        "resource_class": "gpu-video",
        "available_vram_mb": 10_000,
        "capacity_slots": 2,
        "warm_providers": {"wan_local"},
    }
    values.update(overrides)
    return ResourceSnapshot(**values)


def test_scheduler_exposes_components_and_prefers_urgent_work() -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    scheduler = Scheduler(clock=lambda: now)
    urgent = request(deadline_at=now + timedelta(minutes=5), priority=0)
    relaxed = request(deadline_at=now + timedelta(days=2), priority=0)

    ranked = scheduler.rank([relaxed, urgent], resources())

    assert ranked[0].task_id == urgent.task_id
    assert ranked[0].components["deadline"] > ranked[1].components["deadline"]
    assert "expected_cost" in ranked[0].components
    assert ranked[0].explain().startswith(str(urgent.task_id))


def test_scheduler_rejects_resource_and_budget_mismatch() -> None:
    scheduler = Scheduler()
    decision = scheduler.decide(
        request(required_vram_mb=12_000, expected_cost_usd=12.0, budget_remaining_usd=10.0),
        resources(available_vram_mb=8_000),
    )

    assert decision.feasible is False
    assert "insufficient_vram" in decision.reasons
    assert "budget_remaining_below_expected_cost" in decision.reasons


def test_scheduler_uses_tenant_fairness_as_a_tie_breaker() -> None:
    scheduler = Scheduler()
    favored = request(tenant_id="tenant-a")
    busy = request(tenant_id="tenant-b")
    ranked = scheduler.rank(
        [busy, favored],
        resources(tenant_running={"tenant-a": 0, "tenant-b": 4}),
    )

    assert ranked[0].task_id == favored.task_id
    assert ranked[0].components["tenant_fairness"] > ranked[1].components["tenant_fairness"]


def test_request_projection_reads_persisted_task_fields() -> None:
    task_id = uuid4()
    projected = SchedulingRequest.from_task(
        {
            "id": task_id,
            "user_id": "tenant-1",
            "priority": 7,
            "resource_class": "gpu-audio",
            "required_vram_mb": 2048,
            "video_provider": "vibevoice",
            "config_json": {"estimated_usd": 0.4},
        }
    )

    assert projected.task_id == task_id
    assert projected.tenant_id == "tenant-1"
    assert projected.priority == 7
    assert projected.resource_class == "gpu-audio"
    assert projected.required_vram_mb == 2048
    assert projected.expected_cost_usd == 0.4
