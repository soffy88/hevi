"""Gold behaviour for the long-form stage workflow and recovery."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from hevi.creative.omodul import LONGFORM_STAGES, LongFormWorkflow, NarrativeStage
from hevi.creative.oprim import persist_model, restore_model
from hevi.obase.creative import ProductionRun, RunSnapshot


def _start() -> tuple[LongFormWorkflow, ProductionRun]:
    workflow = LongFormWorkflow()
    return workflow, workflow.start(project_id=uuid4(), run_key="gold")


def test_stage_order_is_enforced() -> None:
    workflow, run = _start()
    with pytest.raises(ValueError, match="invalid narrative stage transition"):
        workflow.advance(run, NarrativeStage.DRAFT)


def test_checkpoint_fail_resume_roundtrip(tmp_path: Path) -> None:
    workflow, run = _start()
    for stage in LONGFORM_STAGES[:3]:
        run = workflow.advance(run, stage)
    snapshot = workflow.checkpoint(run)
    assert snapshot.stage == LONGFORM_STAGES[3].value
    assert snapshot.run_id == run.object_id
    snapshot_path = tmp_path / "snapshot.json"
    persist_model(snapshot_path, snapshot)
    run_path = tmp_path / "run.json"
    persist_model(run_path, run)

    crashed = workflow.fail(
        run,
        stage=LONGFORM_STAGES[3],
        error_code="PROVIDER_FAILURE",
        message="boom",
    )
    assert crashed.status == "FAILED"
    assert crashed.failure is not None and crashed.failure.retryable
    persist_model(run_path, crashed, expected_previous_revision=run.revision)

    restarted = restore_model(run_path, ProductionRun)
    restored_snapshot = restore_model(snapshot_path, RunSnapshot)
    assert restarted.status == "FAILED"
    assert restored_snapshot.stage == LONGFORM_STAGES[3].value

    resumed = workflow.resume(restarted)
    assert resumed.status == "RUNNING"
    assert resumed.failure is None
    assert [result.status for result in resumed.stage_results] == ["SUCCEEDED"] * 3
    assert resumed.revision == restarted.revision + 1

    for stage in LONGFORM_STAGES[3:]:
        resumed = workflow.advance(resumed, stage)
    assert resumed.status == "SUCCEEDED"
    assert len(resumed.stage_results) == len(LONGFORM_STAGES)
    assert all(result.status == "SUCCEEDED" for result in resumed.stage_results)


def test_resume_requires_a_failure() -> None:
    workflow, run = _start()
    run = workflow.advance(run, NarrativeStage.RESEARCH)
    with pytest.raises(ValueError, match="RUN_NOT_RESUMABLE"):
        workflow.resume(run)


def test_summarize_chapter_is_bounded() -> None:
    workflow, _ = _start()
    chapter_id: UUID = uuid4()
    summary = workflow.summarize_chapter(
        project_id=uuid4(),
        chapter_id=chapter_id,
        text="Chapter 1: Mara sails.\nMore prose.",
        character_ids=(uuid4(),),
    )
    assert summary.chapter_id == chapter_id
    assert summary.summary == "Chapter 1: Mara sails."
    with pytest.raises(ValueError, match="LONGFORM_EMPTY_CHAPTER"):
        workflow.summarize_chapter(project_id=uuid4(), chapter_id=uuid4(), text="   ")
