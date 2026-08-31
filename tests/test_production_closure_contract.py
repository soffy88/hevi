"""Production closure contracts for Studio, artifact verification, and NLE state."""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.production.artifacts import (
    Artifact,
    ArtifactManifest,
    ArtifactVerificationError,
    verify_local_manifest,
)
from hevi.production.capabilities import capability_catalog
from hevi.services.drama_integration import DramaIntegration
from hevi.studio.nle_workspace import (
    create_project,
    get_project,
    reset_projects,
)
from hevi.studio.slate import Slate, run_slate
from hevi.studio.timeline import get_timeline, reset_timelines, timeline_from_edit_plan


@pytest.mark.asyncio
async def test_execute_without_line_renderer_is_blocked() -> None:
    result = await run_slate(
        Slate(line_id="shorts_clip", slots={}, execute=True)
    )
    assert result.status == "blocked"
    assert "media_path" in result.missing


def test_local_audio_manifest_is_verified_and_missing_artifact_rejected(tmp_path: Path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 40)
    verified = verify_local_manifest(
        ArtifactManifest(
            artifacts=[Artifact(kind="audio", path=str(audio), primary=True)]
        )
    )
    assert verified.artifacts[0].sha256
    assert verified.artifacts[0].byte_size == audio.stat().st_size

    with pytest.raises(ArtifactVerificationError, match="missing"):
        verify_local_manifest(
            ArtifactManifest(
                artifacts=[Artifact(kind="audio", path=str(tmp_path / "missing.wav"), primary=True)]
            )
        )


def test_capability_catalog_separates_interface_from_production() -> None:
    catalog = {item["id"]: item for item in capability_catalog()}
    dubbing = catalog["voice_dubbing"]
    assert dubbing["interface_available"] is True
    assert dubbing["execution_ready"] is False
    assert dubbing["quality_gate_ready"] is False
    assert dubbing["production_ready"] is False
    assert dubbing["readiness"] == "planning_only"

    video_agent = catalog["video_agent"]
    assert video_agent["execution_ready"] is True
    assert video_agent["production_ready"] is False


@pytest.mark.asyncio
async def test_drama_review_requires_artifact_evidence() -> None:
    evaluation = await DramaIntegration().review("plan-without-artifact")
    assert evaluation.passed is False
    assert evaluation.violations[0].status == "unknown"
    assert evaluation.evidence[0].artifact_id == ""


def test_timeline_and_nle_project_survive_process_memory_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEVI_TIMELINE_DIR", str(tmp_path / "timelines"))
    monkeypatch.setenv("HEVI_NLE_DIR", str(tmp_path / "nle"))
    reset_timelines()
    reset_projects()

    timeline = timeline_from_edit_plan(
        {"cuts": [{"start_s": 0, "duration_s": 2, "text": "hook"}]},
        title="persisted",
    )
    project = create_project("project", timeline)
    timeline_id = timeline.timeline_id
    project_id = project.project_id

    reset_timelines()
    reset_projects()
    restored_timeline = get_timeline(timeline_id)
    restored_project = get_project(project_id)
    assert restored_timeline is not None
    assert restored_timeline.title == "persisted"
    assert restored_project is not None
    assert restored_project.active_timeline_id == timeline_id
