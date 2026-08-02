from datetime import UTC, datetime
from uuid import uuid4

from hevi.runs.shortdrama_state import (
    ShortdramaRunStore,
    dump_shortdrama_state,
    dump_shortdrama_update,
    load_shortdrama_record,
)
from hevi.season_planner.schemas import EpisodePlan, SeasonPlan
from hevi.storygraph.schemas import StoryCharacter, StoryGraph, StoryMeta
from hevi.tongjian.schemas import GateResult


def test_shortdrama_state_round_trip_restores_planning_models() -> None:
    record = {
        "run_id": str(uuid4()),
        "user_id": "user-1",
        "status": "AWAITING_CHARACTERS",
        "source_name": "测试故事",
        "raw_text": "正文",
        "target_episodes": 1,
        "created_at": datetime.now(UTC),
        "story": StoryGraph(
            meta=StoryMeta(source="测试故事"),
            characters=[StoryCharacter(char_id="C001", name="主角")],
        ),
        "plan": SeasonPlan(target_episodes=1, episodes=[EpisodePlan(ep_number=1)]),
        "gate": GateResult(passed=True, coverage=1.0, errors=[], warnings=[]),
        "bindings": {"C001": {"mode": "existing", "subject_id": "sub-1"}},
        "series_id": None,
        "task_ids": ["task-1", "task-2"],
        "error": None,
        "progress": "等待绑定",
        "completed_at": None,
    }
    state = dump_shortdrama_state(record)
    row = {
        "id": record["run_id"],
        "user_id": record["user_id"],
        "status": record["status"],
        "input_json": {
            "source_name": record["source_name"],
            "raw_text": record["raw_text"],
            "target_episodes": record["target_episodes"],
        },
        "state_json": state,
        "series_id": None,
        "task_ids": ["task-1", "task-2"],
        "created_at": record["created_at"],
        "completed_at": None,
    }

    restored = load_shortdrama_record(row)

    assert restored["story"].characters[0].name == "主角"
    assert restored["plan"].episodes[0].ep_number == 1
    assert restored["gate"].passed is True
    assert restored["bindings"] == record["bindings"]
    assert restored["task_ids"] == ["task-1", "task-2"]
    assert dump_shortdrama_update(restored)["task_ids"] == ["task-1", "task-2"]
    assert dump_shortdrama_update(restored)["state_json"] == state


def test_shortdrama_store_declares_its_single_adapter_kind() -> None:
    assert ShortdramaRunStore.kind == "shortdrama"
