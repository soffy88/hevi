from __future__ import annotations

from pathlib import Path

import pytest

from hevi.production.execution import execute_standard_operation, execution_binding


@pytest.mark.asyncio
async def test_execution_bridge_runs_standard_operation_and_projects_events(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []

    async def operation(
        config: dict[str, object], input_data: dict[str, object], output_dir: Path
    ) -> dict[str, object]:
        artifact = output_dir / "final.mp4"
        artifact.write_bytes(b"video")
        return {
            "status": "succeeded",
            "error": None,
            "artifacts": [{"kind": "video", "path": str(artifact), "primary": True}],
            "fingerprint": "safe",
            "decision_trail": [],
            "cost": {},
            "report": {"source": config["source"], "request": input_data["request"]},
        }

    result = await execute_standard_operation(
        operation=operation,
        config={"source": "explainer"},
        input_data={"request": "task-ref"},
        output_dir=tmp_path,
        event_sink=events.append,
    )

    assert result["status"] == "succeeded"
    assert [event["stage"] for event in events] == ["started", "succeeded"]
    assert result["report"] == {"source": "explainer", "request": "task-ref"}


def test_execution_binding_is_versioned_and_immutable_shape() -> None:
    binding = execution_binding("explainer", adapter_version="2026.08.01")
    assert binding.capability_id == "explainer"
    assert binding.engine == "oservi.production_execution"
    assert binding.engine_version
