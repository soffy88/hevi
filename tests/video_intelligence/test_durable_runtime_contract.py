from __future__ import annotations

from hevi.production.adapters import default_production_adapters


def test_case_operations_use_the_canonical_task_adapter_registry() -> None:
    sources = default_production_adapters().sources()
    assert "case_analysis" in sources
    assert "case_reproduction" in sources


def test_case_queue_payload_is_named_operation_not_a_second_worker() -> None:
    # The production source names are the durable TaskService boundary.  The
    # intelligence package contains adapters only; it has no queue/worker
    # module of its own.
    from pathlib import Path

    assert not (Path("hevi/video_intelligence/job_queue.py")).exists()
    assert not (Path("hevi/video_intelligence/worker.py")).exists()
