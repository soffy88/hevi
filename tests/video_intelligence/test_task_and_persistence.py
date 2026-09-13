from hevi.video_intelligence.cache import analysis_cache_key
from hevi.video_intelligence.models import VideoTask
from hevi.video_intelligence.persistence import atomic_write_model, read_model
from hevi.video_intelligence.task_contract import validate_task_dependencies


def test_task_dependencies_are_blocked_until_complete():
    task = VideoTask(task_id="t2", operation_id="op", task_type="analysis", dependencies=["t1"])
    assert validate_task_dependencies(task, set()).status == "BLOCKED"
    assert validate_task_dependencies(task, {"t1"}).status == "READY"


def test_atomic_model_roundtrip(tmp_path):
    task = VideoTask(task_id="t1", operation_id="op", task_type="probe")
    path = tmp_path / "task.json"
    atomic_write_model(path, task)
    assert read_model(path, VideoTask) == task


def test_cache_key_changes_when_source_or_config_changes():
    first = analysis_cache_key("a" * 64, {"threshold": 0.35})
    same = analysis_cache_key("a" * 64, {"threshold": 0.35})
    changed = analysis_cache_key("b" * 64, {"threshold": 0.35})
    assert first == same
    assert first != changed
