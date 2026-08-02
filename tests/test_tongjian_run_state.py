from datetime import UTC, datetime

from hevi.runs.tongjian_state import dump_tongjian_update, load_tongjian_record


def test_tongjian_state_preserves_shared_task_projection_ids() -> None:
    row = {
        "id": "run-1",
        "user_id": "user-1",
        "status": "RUNNING",
        "input_json": {"source_name": "资治通鉴·周纪"},
        "state_json": {
            "layers": {},
            "current_layer": "L3",
            "result_video_path": None,
            "error": None,
        },
        "task_ids": ["task-1"],
        "created_at": datetime.now(UTC),
        "completed_at": None,
    }

    record = load_tongjian_record(row)

    assert record["task_ids"] == ["task-1"]
    assert dump_tongjian_update(record)["task_ids"] == ["task-1"]
