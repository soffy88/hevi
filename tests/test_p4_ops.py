"""P4 Production Operations — fast unit tests (no render)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hevi.ops.p4_delivery import (
    check_editable_project,
    deliver_local,
    package_delivery,
    validate_delivery_source,
)
from hevi.ops.p4_duration import DurationController
from hevi.ops.p4_scheduler import (
    ProviderQuota,
    ResourceLedger,
    Scheduler,
    classify_error,
    create_batch,
)
from hevi.ops.p4_types import (
    ProductionJob,
    validate_batch_transition,
    validate_job_transition,
)


def _job(jid: str, priority: int = 5) -> ProductionJob:
    return ProductionJob(job_id=jid, profile_id="SCIENCE_EXPLAINER",
                         topic="t", narration="Black hole gravity orbit.", priority=priority)


def test_batch_job_transitions() -> None:
    validate_batch_transition("CREATED", "QUEUED")
    validate_job_transition("QUEUED", "RUNNING")
    with pytest.raises(ValueError):
        validate_job_transition("CREATED", "COMPLETED")


def test_fairness_no_starvation(tmp_path: Path) -> None:
    jobs = [_job("high", 0)] + [_job(f"low-{i}", 9) for i in range(3)]
    batch, store = create_batch(tmp_path / "b", jobs, concurrency_limit=1)
    order: list[str] = []

    async def _run(job: ProductionJob, root: Path) -> dict[str, object]:
        order.append(job.job_id)
        return {"actual_cost_usd": 0.0, "final_mp4": "", "duration_s": 0.0}

    batch.set_status("QUEUED")
    store.save(batch)
    sched = Scheduler(store)
    asyncio.run(sched.run(batch, _run))
    assert order[0] == "high"
    assert sorted(order[1:]) == ["low-0", "low-1", "low-2"]
    assert batch.status == "COMPLETED"


def test_concurrency_cap_observed(tmp_path: Path) -> None:
    jobs = [_job(f"j{i}") for i in range(4)]
    batch, store = create_batch(tmp_path / "b", jobs, concurrency_limit=2)
    batch.set_status("QUEUED")
    store.save(batch)

    async def _run(job: ProductionJob, root: Path) -> dict[str, object]:
        await asyncio.sleep(0.05)
        return {"actual_cost_usd": 0.0, "final_mp4": "", "duration_s": 0.0}

    sched = Scheduler(store)
    asyncio.run(sched.run(batch, _run))
    assert sched.max_observed_concurrency <= 2
    assert sched.max_observed_concurrency >= 1


def test_quota_throttle_and_block() -> None:
    q = ProviderQuota(requests_per_min=2, requests_per_day=3)
    assert q.acquire("2026-01-01T00:00:00Z")[0]
    assert q.acquire("2026-01-01T00:00:10Z")[0]
    ok, reason = q.acquire("2026-01-01T00:00:20Z")
    assert not ok and reason == "PROVIDER_QUOTA_THROTTLE"
    q.acquire("2026-01-01T00:01:05Z")
    ok, reason = q.acquire("2026-01-01T00:02:00Z")
    assert not ok and reason == "PROVIDER_QUOTA_BLOCKED"


def test_budget_blocks_job(tmp_path: Path) -> None:
    jobs = [_job("expensive")]
    jobs[0].estimated_cost_usd = 999.0
    batch, store = create_batch(tmp_path / "b", jobs, budget_usd=10.0)
    batch.set_status("QUEUED")
    store.save(batch)

    async def _run(job: ProductionJob, root: Path) -> dict[str, object]:
        raise AssertionError("must not run over budget")

    sched = Scheduler(store)
    asyncio.run(sched.run(batch, _run))
    assert batch.job("expensive").status == "BLOCKED"


def test_retry_bounded_and_classify() -> None:
    assert classify_error("connection timeout, try again") == "TRANSIENT"
    assert classify_error("out of memory") == "RESOURCE"
    assert classify_error("quota exhausted") == "PROVIDER"
    assert classify_error("unverified source claim") == "CONTENT"
    assert classify_error("visual quality gate blocked") == "QA"
    assert classify_error("weird unknown") == "PERMANENT"


def test_retry_exhausted(tmp_path: Path) -> None:
    jobs = [_job("flaky")]
    jobs[0].max_attempts = 2
    batch, store = create_batch(tmp_path / "b", jobs)
    batch.set_status("QUEUED")
    store.save(batch)
    calls: list[str] = []

    async def _run(job: ProductionJob, root: Path) -> dict[str, object]:
        calls.append(job.job_id)
        raise RuntimeError("connection timeout, try again")

    sched = Scheduler(store)
    asyncio.run(sched.run(batch, _run))
    assert batch.job("flaky").status == "FAILED"
    assert "RETRY_EXHAUSTED" in batch.job("flaky").error
    assert len(calls) == 2


def test_lease_orphan_recovery(tmp_path: Path) -> None:
    jobs = [_job("orphan")]
    batch, store = create_batch(tmp_path / "b", jobs)
    job = batch.job("orphan")
    assert job is not None
    job.set_status("QUEUED")
    job.set_status("RUNNING")
    store.save(batch)
    sched = Scheduler(store)
    # Unknown worker + expired lease → reaped
    lease = sched.issue_lease(job, ttl_s=-1)
    assert lease.expired("2999-01-01T00:00:00Z")
    reaped = sched.reap_orphans(batch, live_workers={"someone-else"})
    assert reaped == ["orphan"]
    assert job.status == "QUEUED"


def test_pause_resume_cancel(tmp_path: Path) -> None:
    jobs = [_job("a"), _job("b")]
    batch, store = create_batch(tmp_path / "b", jobs)
    batch.set_status("QUEUED")
    store.save(batch)
    store.set_paused(True)
    assert store.paused()

    async def _run(job: ProductionJob, root: Path) -> dict[str, object]:
        return {"actual_cost_usd": 0.0, "final_mp4": "", "duration_s": 0.0}

    sched = Scheduler(store)
    # Paused scheduler must not dispatch; cancel to exit promptly.
    store.request_cancel()
    asyncio.run(sched.run(batch, _run))
    assert batch.status == "CANCELLED"
    assert all(j.status == "CANCELLED" for j in batch.jobs)


def test_delivery_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    src.write_bytes(b"0" * 1024)
    pkg = package_delivery(tmp_path, str(src))
    first = deliver_local("j1", 1, pkg, tmp_path / "dest")
    second = deliver_local("j1", 1, pkg, tmp_path / "dest")
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert first["hashes"] == second["hashes"]


def test_validate_delivery_source_rejects_empty(tmp_path: Path) -> None:
    empty = tmp_path / "e.mp4"
    empty.write_bytes(b"")
    ok, _detail = validate_delivery_source(str(empty))
    assert not ok


def test_editable_project_check(tmp_path: Path) -> None:
    seg = tmp_path / "seg-0"
    seg.mkdir()
    (seg / "motion_spec.json").write_text('{"shots": []}')
    res = check_editable_project([seg])
    assert res["status"] == "PASS"
    res2 = check_editable_project([tmp_path / "missing"])
    assert res2["status"] in ("NOT_APPLICABLE", "FAIL")


def test_duration_controller_math() -> None:
    dc = DurationController(chars_per_s=14.5, tolerance=0.15)
    plan = dc.plan(300.0)
    assert plan.chars_per_segment > 0
    rep = dc.report(300.0, 330.0)
    assert rep.within_tolerance
    rep2 = dc.report(300.0, 400.0)
    assert not rep2.within_tolerance
    parts = dc.split_budget("One. Two. Three. Four. Five. Six.", 3)
    assert len(parts) == 3
    assert all(p.endswith(".") for p in parts)


def test_resource_reserve_release() -> None:
    ledger = ResourceLedger(render_slots=1)
    assert ledger.reserve("render")
    assert not ledger.reserve("render")
    ledger.release("render")
    assert ledger.reserve("render")


def test_no_second_authorities_in_ops() -> None:
    import inspect

    import hevi.ops.p4_delivery as delivery
    import hevi.ops.p4_scheduler as scheduler

    combined = inspect.getsource(scheduler) + inspect.getsource(delivery)
    assert "remotion_render_workflow" not in combined
    assert "execute_local_media_task" not in combined
    assert "run_p2_production" not in combined
