"""Durable state boundary for the Tongjian adapter.

The renderer still keeps an execution snapshot while a task is actively
running, but this module is the recovery boundary: every value required by a
resume or a worker takeover is JSON-safe in ``automation_runs.state_json``.
No renderer input is reconstructed from ``output/``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hevi.runs.repository import AutomationRunRepository


def _json_value(value: Any) -> Any:
    """Convert pydantic/domain values to a JSONB-safe value."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def dump_tongjian_state(record: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "current_layer": record.get("current_layer"),
        "layers": _json_value(record.get("layers") or {}),
        "result_video_path": record.get("result_video_path"),
        "artifact_manifest": _json_value(record.get("artifact_manifest")),
        "error": record.get("error"),
    }
    # These are the actual inputs to L3-L8 and to the human review API.  Keep
    # them beside the layer projection so a new worker can resume from DB.
    for key in (
        "request",
        "req",
        "chapter_ir",
        "constitution",
        "script",
        "run_dir",
        "reference",
        "mix",
        "character_states",
    ):
        value = record.get(key)
        if value is not None:
            state[key if key != "req" else "request"] = _json_value(value)
    return state


def load_tongjian_record(row: dict[str, Any]) -> dict[str, Any]:
    """Restore rich domain models from an ``automation_runs`` row."""

    from hevi.tongjian.schemas import ChapterIR, Constitution, Script

    state = row.get("state_json") or {}
    source = row.get("input_json") or {}
    request = state.get("request") or source.get("request")
    run_id = str(row["id"])
    run_dir = state.get("run_dir") or f"output/tongjian/{run_id}"
    return {
        "run_id": run_id,
        "user_id": row.get("user_id"),
        "status": row["status"],
        "source_name": source.get("source_name", ""),
        "raw_text": source.get("raw_text", ""),
        "created_at": row["created_at"],
        "completed_at": row.get("completed_at"),
        "current_layer": state.get("current_layer"),
        "layers": state.get("layers") or {},
        "result_video_path": state.get("result_video_path"),
        "artifact_manifest": state.get("artifact_manifest"),
        "error": state.get("error"),
        "task_ids": [str(task_id) for task_id in (row.get("task_ids") or [])],
        "request": request,
        "req": request,
        "chapter_ir": ChapterIR.model_validate(state["chapter_ir"])
        if state.get("chapter_ir")
        else None,
        "constitution": Constitution.model_validate(state["constitution"])
        if state.get("constitution")
        else None,
        "script": Script.model_validate(state["script"]) if state.get("script") else None,
        "run_dir": run_dir,
        "reference": state.get("reference"),
        "mix": state.get("mix"),
        "character_states": state.get("character_states"),
    }


def dump_tongjian_update(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": record["status"],
        "state_json": dump_tongjian_state(record),
        "completed_at": record.get("completed_at"),
        "task_ids": record.get("task_ids") or [],
    }


class TongjianRunStore:
    """Typed persistence facade for API review/resume and worker recovery."""

    kind = "tongjian"

    def __init__(self, repository: AutomationRunRepository) -> None:
        self._repository = repository

    async def get_owned(self, run_id: str, *, user_id: str) -> dict[str, Any] | None:
        row = await self._repository.get(run_id)
        if row is None or row.get("kind") != self.kind or row.get("user_id") != user_id:
            return None
        return load_tongjian_record(row)

    async def get(self, run_id: str) -> dict[str, Any] | None:
        row = await self._repository.get(run_id)
        if row is None or row.get("kind") != self.kind:
            return None
        return load_tongjian_record(row)

    async def save(self, record: dict[str, Any]) -> dict[str, Any] | None:
        row = await self._repository.update(record["run_id"], dump_tongjian_update(record))
        return load_tongjian_record(row) if row is not None else None
