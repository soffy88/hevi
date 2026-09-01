from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from hevi.production.adapters import ProductionAdapterRegistry
from hevi.production.artifacts import ArtifactManifest
from hevi.tasks.task_service import TaskService


@pytest.mark.asyncio
async def test_task_service_dispatches_explainer_to_adapter_executor(tmp_path) -> None:
    task_id = uuid4()
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 40)
    repo = MagicMock()
    repo.pool = MagicMock()
    repo.update_task = AsyncMock()
    adapters = ProductionAdapterRegistry()
    service = TaskService(repo, production_adapters=adapters)
    task = {
        "id": task_id,
        "status": "pending",
        "config_json": {"production_source": "explainer", "run_id": "run-1"},
    }
    expected = {
        **task,
        "status": "completed",
        "result_video_path": None,
        "config_json": {
            **task["config_json"],
            "artifact_manifest": {
                "artifacts": [{"kind": "audio", "path": str(audio), "primary": True}]
            },
        },
    }

    with patch(
        "hevi.api.routers.explainer.execute_task", new_callable=AsyncMock, return_value=expected
    ) as execute:
        adapters.register("explainer", execute)
        result = await service._run_adapter_task(task)

    assert result["status"] == "completed"
    assert result["config_json"]["artifact_manifest"]["artifacts"][0]["sha256"]
    execute.assert_awaited_once_with(task, repo.pool)
    # TaskService projects the oservi start/success events in addition to the
    # initial running-state write, preserving existing task/SSE semantics.
    assert repo.update_task.await_count >= 4
    assert repo.update_task.await_args_list[1].args[1]["config_json"]["stage"] == "started"
    assert repo.update_task.await_args_list[2].args[1]["config_json"]["stage"] == "succeeded"


@pytest.mark.asyncio
async def test_task_service_persists_audio_manifest_after_engine_projection(tmp_path) -> None:
    task_id = uuid4()
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 40)
    repo = MagicMock()
    repo.pool = MagicMock()
    repo.update_task = AsyncMock()
    adapters = ProductionAdapterRegistry()

    async def voice_adapter(task, pool):
        return {
            **task,
            "status": "completed",
            "config_json": {
                **task["config_json"],
                "artifact_manifest": ArtifactManifest(
                    artifacts=[{"kind": "audio", "path": str(audio), "primary": True}]
                ).model_dump(mode="json"),
            },
        }

    adapters.register("voice_studio_tts", voice_adapter)
    service = TaskService(repo, production_adapters=adapters)
    result = await service._run_adapter_task(
        {"id": task_id, "config_json": {"production_source": "voice_studio_tts"}}
    )

    manifest = ArtifactManifest.model_validate(result["config_json"]["artifact_manifest"])
    assert manifest.path_for("audio") is not None
    config_updates = [
        call.args[1].get("config_json")
        for call in repo.update_task.await_args_list
        if "config_json" in call.args[1]
    ]
    assert config_updates[-1]["artifact_manifest"]


@pytest.mark.asyncio
async def test_task_service_keeps_human_review_adapter_paused() -> None:
    """A review checkpoint is not a failed render and must not claim delivery."""
    task_id = uuid4()
    repo = MagicMock()
    repo.pool = MagicMock()
    repo.update_task = AsyncMock()
    adapters = ProductionAdapterRegistry()

    async def review_adapter(task, pool):
        return {**task, "status": "awaiting_review", "review_pending": True}

    adapters.register("tongjian", review_adapter)
    service = TaskService(repo, production_adapters=adapters)
    result = await service._run_adapter_task(
        {
            "id": task_id,
            "status": "claimed",
            "progress_pct": 32.0,
            "config_json": {"production_source": "tongjian"},
        }
    )

    assert result["status"] == "paused"
    assert result["review_pending"] is True
    statuses = [call.args[1].get("status") for call in repo.update_task.await_args_list]
    assert "paused" in statuses
