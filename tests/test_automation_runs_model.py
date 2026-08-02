from hevi.db.models import AutomationRun


def test_automation_runs_has_a_single_adapter_session_contract() -> None:
    columns = AutomationRun.__table__.columns

    required = {"id", "kind", "user_id", "status", "input_json", "state_json", "task_ids"}
    assert required <= set(columns.keys())
    assert columns["kind"].type.length == 32
    assert columns["series_id"].nullable is True
