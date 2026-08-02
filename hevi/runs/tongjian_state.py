"""Durable layer-state snapshot for the Tongjian adapter."""

from __future__ import annotations

from typing import Any


def dump_tongjian_state(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_layer": record.get("current_layer"),
        "layers": record.get("layers") or {},
        "result_video_path": record.get("result_video_path"),
        "error": record.get("error"),
    }


def load_tongjian_record(row: dict[str, Any]) -> dict[str, Any]:
    state = row.get("state_json") or {}
    source = row.get("input_json") or {}
    return {
        "run_id": str(row["id"]),
        "user_id": row.get("user_id"),
        "status": row["status"],
        "source_name": source.get("source_name", ""),
        "created_at": row["created_at"],
        "completed_at": row.get("completed_at"),
        "current_layer": state.get("current_layer"),
        "layers": state.get("layers") or {},
        "result_video_path": state.get("result_video_path"),
        "error": state.get("error"),
        "task_ids": [str(task_id) for task_id in (row.get("task_ids") or [])],
    }


def dump_tongjian_update(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": record["status"],
        "state_json": dump_tongjian_state(record),
        "completed_at": record.get("completed_at"),
        "task_ids": record.get("task_ids") or [],
    }
