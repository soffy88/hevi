"""JSON-safe persistence boundary for the shortdrama adapter."""

from __future__ import annotations

import uuid
from typing import Any

from hevi.runs.repository import AutomationRunRepository
from hevi.season_planner.schemas import SeasonPlan
from hevi.storygraph.schemas import StoryGraph
from hevi.tongjian.schemas import GateResult


def dump_shortdrama_state(record: dict[str, Any]) -> dict[str, Any]:
    """Turn a live shortdrama record into JSONB-safe adapter state."""
    state: dict[str, Any] = {
        "bindings": record.get("bindings") or {},
        "error": record.get("error"),
        "progress": record.get("progress"),
    }
    if record.get("story") is not None:
        state["story"] = record["story"].model_dump(mode="json")
    if record.get("plan") is not None:
        state["plan"] = record["plan"].model_dump(mode="json")
    if record.get("gate") is not None:
        state["gate"] = record["gate"].model_dump(mode="json")
    return state


def load_shortdrama_record(row: dict[str, Any]) -> dict[str, Any]:
    """Restore the rich planning objects expected by the existing adapter."""
    input_data = row.get("input_json") or {}
    state = row.get("state_json") or {}
    return {
        "run_id": str(row["id"]),
        "user_id": row["user_id"],
        "status": row["status"],
        "source_name": input_data["source_name"],
        "raw_text": input_data["raw_text"],
        "target_episodes": input_data["target_episodes"],
        "created_at": row["created_at"],
        "story": StoryGraph.model_validate(state["story"]) if state.get("story") else None,
        "plan": SeasonPlan.model_validate(state["plan"]) if state.get("plan") else None,
        "gate": GateResult.model_validate(state["gate"]) if state.get("gate") else None,
        "bindings": state.get("bindings") or {},
        "series_id": row.get("series_id"),
        "task_ids": row.get("task_ids") or [],
        "error": state.get("error"),
        "progress": state.get("progress"),
        "completed_at": row.get("completed_at"),
    }


def dump_shortdrama_update(record: dict[str, Any]) -> dict[str, Any]:
    """Database fields updated whenever the adapter mutates a run."""
    return {
        "status": record["status"],
        "state_json": dump_shortdrama_state(record),
        "series_id": record.get("series_id"),
        "task_ids": record.get("task_ids") or [],
        "completed_at": record.get("completed_at"),
    }


class ShortdramaRunStore:
    """Typed persistence facade used by the shortdrama adapter."""

    kind = "shortdrama"

    def __init__(self, repository: AutomationRunRepository) -> None:
        self._repository = repository

    async def create(
        self,
        *,
        user_id: str,
        source_name: str,
        raw_text: str,
        target_episodes: int,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        row = await self._repository.create(
            {
                **({"id": uuid.UUID(run_id)} if run_id is not None else {}),
                "kind": self.kind,
                "user_id": user_id,
                "status": "PENDING",
                "input_json": {
                    "source_name": source_name,
                    "raw_text": raw_text,
                    "target_episodes": target_episodes,
                },
                "state_json": {"bindings": {}},
            }
        )
        return load_shortdrama_record(row)

    async def get_owned(self, run_id: str, *, user_id: str) -> dict[str, Any] | None:
        row = await self._repository.get(run_id)
        if row is None or row.get("kind") != self.kind or row.get("user_id") != user_id:
            return None
        return load_shortdrama_record(row)

    async def get(self, run_id: str) -> dict[str, Any] | None:
        row = await self._repository.get(run_id)
        if row is None or row.get("kind") != self.kind:
            return None
        return load_shortdrama_record(row)

    async def save(self, record: dict[str, Any]) -> dict[str, Any] | None:
        row = await self._repository.update(record["run_id"], dump_shortdrama_update(record))
        return load_shortdrama_record(row) if row is not None else None
