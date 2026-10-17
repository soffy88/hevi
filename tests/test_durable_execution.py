import asyncio
from typing import Any

import pytest

from hevi.production_graph import (
    CanonicalShot,
    DurableExecutionCoordinator,
    ExecutionPlan,
    IdempotencyConflictError,
    InMemoryDurableExecutionStore,
    ReadinessTransitionError,
    TaskEnvelope,
    envelope_from_execution_plan,
)


class FakeProvider:
    def __init__(self) -> None:
        self.send_calls = 0
        self.poll_calls = 0
        self.cancel_calls = 0
        self.jobs: dict[str, str] = {}

    async def send(self, request: dict[str, Any], *, idempotency_key: str) -> str:
        del request
        self.send_calls += 1
        if idempotency_key in self.jobs:
            return self.jobs[idempotency_key]
        job = f"job-{len(self.jobs) + 1}"
        self.jobs[idempotency_key] = job
        return job

    async def poll(self, provider_job_id: str) -> dict[str, Any]:
        self.poll_calls += 1
        return {"status": "completed", "artifact_path": f"/tmp/{provider_job_id}.mp4"}

    async def cancel(self, provider_job_id: str) -> None:
        del provider_job_id
        self.cancel_calls += 1

    async def download(self, provider_job_id: str, destination: str) -> str:
        return f"{destination}/{provider_job_id}.mp4"

    def parse_error(self, error: Exception) -> dict[str, Any]:
        return {"error": str(error)}


def _envelope() -> TaskEnvelope:
    return TaskEnvelope(
        id="task-durable",
        project_id="project-durable",
        revision_id="revision-durable",
        shot_id="shot-durable",
        stage="video_generation",
        execution_plan_id="plan-durable",
        idempotency_key="idem-durable",
    )


def test_intent_is_persisted_before_send_and_job_before_poll() -> None:
    async def run() -> None:
        store = InMemoryDurableExecutionStore()
        provider = FakeProvider()
        result = await DurableExecutionCoordinator(store).execute(
            _envelope(), provider, {"prompt": "action"}
        )
        assert result.status == "completed"
        assert provider.send_calls == 1
        assert store.events[:2] == [
            ("intent_persisted", "idem-durable"),
            ("envelope:submitted", "idem-durable"),
        ]
        assert store.records["idem-durable"].provider_job_id == "job-1"
        assert store.records["idem-durable"].artifact_ids == ["/tmp/job-1.mp4"]

    asyncio.run(run())


def test_restart_resumes_persisted_provider_job_without_duplicate_send() -> None:
    async def run() -> None:
        store = InMemoryDurableExecutionStore()
        provider = FakeProvider()
        coordinator = DurableExecutionCoordinator(store)
        first = await coordinator.execute(_envelope(), provider, {})
        assert first.status == "completed"
        second = await DurableExecutionCoordinator(store).execute(_envelope(), provider, {})
        assert second.status == "completed"
        assert provider.send_calls == 1

    asyncio.run(run())


def test_idempotency_conflict_is_rejected() -> None:
    async def run() -> None:
        store = InMemoryDurableExecutionStore()
        await store.persist_intent(_envelope())
        other = _envelope().model_copy(update={"execution_plan_id": "different-plan"})
        with pytest.raises(IdempotencyConflictError):
            await store.persist_intent(other)

    asyncio.run(run())


def test_dispatch_gate_requires_ready_shot() -> None:
    """Durable execution must enforce READY gate before provider dispatch.

    This test simulates the coordinator dispatch boundary: even when the envelope
    has an idempotent provider job from a previous run, the readiness state must
    be READY before dispatch can proceed.
    """

    async def run() -> None:
        store = InMemoryDurableExecutionStore()
        provider = FakeProvider()
        coordinator = DurableExecutionCoordinator(store)

        # The canonical shot is supplied to the coordinator itself.  The
        # provider must not be reachable when that shot is not READY.
        ready_shot = CanonicalShot(
            id="shot-dispatch-test",
            project_id="p",
            revision_id="r",
            scene_id="s",
            action_description="test dispatch",
            cinematography_notes="test",
            readiness_state="READY",
        )
        envelope = _envelope().model_copy(update={"checkpoint": {"readiness_state": "READY"}})
        result = await coordinator.execute(envelope, provider, {}, shot=ready_shot)
        assert result.status == "completed"

        # Simulate restart: reload envelope from store; dispatch should still succeed
        # because READY was already established and the shot cannot transit away
        # from READY without going through QUEUED first.

        # Now test that a non-READY shot cannot dispatch through the same
        # canonical boundary, and that the adapter was not called again.
        non_ready_shot = CanonicalShot(
            id="shot-dispatch-blocked",
            project_id="p",
            revision_id="r",
            scene_id="s",
            action_description="test dispatch blocked",
            cinematography_notes="test",
            readiness_state="ANALYZED",
        )

        with pytest.raises(ReadinessTransitionError):
            await coordinator.execute(envelope, provider, {}, shot=non_ready_shot)
        assert provider.send_calls == 1

    asyncio.run(run())


def test_plan_to_envelope_pins_plan_identity() -> None:
    plan = ExecutionPlan(
        id="plan-envelope",
        project_id="project-envelope",
        revision_id="revision-envelope",
        shot_id="shot-envelope",
        idempotency_key="idem-envelope",
    )
    envelope = envelope_from_execution_plan(plan)
    assert envelope.execution_plan_id == plan.id
    assert envelope.project_id == plan.project_id
    assert envelope.idempotency_key == plan.idempotency_key
