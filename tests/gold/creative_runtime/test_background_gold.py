"""Gold behaviour for persisted background progress and notifications."""

from __future__ import annotations

from uuid import uuid4

from hevi.creative.omodul import BackgroundRunController
from hevi.creative.oprim import persist_model, restore_model
from hevi.obase.creative import ProductionRun, StageResult


def _run() -> ProductionRun:
    return ProductionRun(
        project_id=uuid4(),
        run_key="background",
        capability="creative.longform",
        status="RUNNING",
        stage_results=(
            StageResult(stage="plan", status="SUCCEEDED"),
            StageResult(stage="draft", status="RUNNING"),
        ),
    )


def test_progress_is_derived_and_notified() -> None:
    controller = BackgroundRunController()
    run = _run()
    progress = controller.progress(run)
    assert progress.completed_stages == 1
    assert progress.total_stages == 2
    assert progress.percent == 50.0
    assert progress.stage == "draft"
    notification = controller.notification(progress)
    assert notification["event_type"] == "creative.run.running"
    assert notification["percent"] == 50.0


def test_progress_survives_reconnect(tmp_path) -> None:
    controller = BackgroundRunController()
    run = _run()
    path = tmp_path / "run.json"
    persist_model(path, run)
    assert controller.progress(restore_model(path, ProductionRun)) == controller.progress(run)
