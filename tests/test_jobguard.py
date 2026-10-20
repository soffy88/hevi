"""Contract tests for the jobguard capabilities.

Offline: target capabilities are side-effect-free test doubles registered
directly in the registry; the webhook test only ever touches an unreachable
127.0.0.1 port (best-effort must not crash) or an injected poster double.
Background jobs are awaited by polling with a timeout — no sleeps of faith.
"""

import json
import time
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.jobguard import register_jobguard_capabilities_once
from hevi.capabilities.registry import Capability, CapabilityResult, compute_sha256, register
from hevi.jobguard import runner

register_jobguard_capabilities_once()

_ECHO = "test.jobguard_echo"
_FAIL = "test.jobguard_fail"


def _render_echo(params, out_dir, *, duration, aspect, seed):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artefact = out_dir / "echo.txt"
    artefact.write_text(str(params.get("text", "hello")), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0, sha256=compute_sha256(artefact), qa={"echo": str(artefact)}
    )


def _render_fail(params, out_dir, *, duration, aspect, seed):
    raise CapabilityError("test.jobguard_fail: deliberate failure")


def _ensure_doubles() -> None:
    if _ECHO not in caps.names():
        register(Capability(
            name=_ECHO, kind="line", aspects=["16:9"],
            params_schema={"type": "object", "properties": {"text": {"type": "string"}},
                           "additionalProperties": False},
            cpu_cost_hint=0.0, render=_render_echo,
            description="test double: writes echo.txt", line="test",
        ))
    if _FAIL not in caps.names():
        register(Capability(
            name=_FAIL, kind="line", aspects=["16:9"],
            params_schema={"type": "object", "properties": {}, "additionalProperties": False},
            cpu_cost_hint=0.0, render=_render_fail,
            description="test double: always raises CapabilityError", line="test",
        ))


_ensure_doubles()


def _run_and_wait(tmp_path: Path, capability: str, params: dict | None = None,
                  webhook_url: str | None = None) -> tuple[str, dict]:
    run = caps.get("job.run_background")
    payload: dict = {"capability": capability, "params": params or {},
                     "jobs_root": str(tmp_path / "jobs")}
    if webhook_url:
        payload["webhook_url"] = webhook_url
    result = run.render_safe(payload, tmp_path / "run-out", duration=1.0, aspect="16:9", seed=1)
    job_id = result.qa["job_id"]
    status = runner.wait_for_job(job_id, jobs_root=tmp_path / "jobs", timeout=15.0)
    return job_id, status


def _status_via_capability(tmp_path: Path, job_id: str) -> dict:
    cap = caps.get("job.status")
    result = cap.render_safe(
        {"job_id": job_id, "jobs_root": str(tmp_path / "jobs")},
        tmp_path / "status-out", duration=1.0, aspect="16:9", seed=1,
    )
    return result.qa["job"]


def test_jobguard_capabilities_registered_and_listable() -> None:
    names = caps.names()
    for expected in ("job.run_background", "job.status", "job.notifications"):
        assert expected in names
    listed = [c.name for c in caps.list(kind="line")]
    assert "job.run_background" in listed

    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for name in ("job.run_background", "job.status", "job.notifications"):
        assert by_name[name].get("description"), name


def test_jobguard_rejects_invalid_params(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError):
        caps.get("job.run_background").render_safe(
            {}, tmp_path / "o", duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        caps.get("job.run_background").render_safe(
            {"capability": _ECHO, "params": "not-an-object"},
            tmp_path / "o", duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        caps.get("job.status").render_safe(
            {}, tmp_path / "o", duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        caps.get("job.status").render_safe(
            {"job_id": "deadbeef", "jobs_root": str(tmp_path / "jobs")},
            tmp_path / "o", duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        caps.get("job.notifications").render_safe(
            {"limit": 0}, tmp_path / "o", duration=1.0, aspect="16:9", seed=1)


def test_job_full_lifecycle_and_notification(tmp_path: Path) -> None:
    job_id, status = _run_and_wait(tmp_path, _ECHO, {"text": "guarded"})
    assert status["status"] == "succeeded"
    assert status["started_at"] and status["finished_at"]
    assert status["error"] is None

    via_cap = _status_via_capability(tmp_path, job_id)
    assert via_cap["status"] == "succeeded"
    assert via_cap["capability"] == _ECHO

    job_dir = tmp_path / "jobs" / job_id
    artefact = job_dir / "artifacts" / "echo.txt"
    assert artefact.is_file() and artefact.read_text(encoding="utf-8") == "guarded"

    notification_file = job_dir / "notification.json"
    assert notification_file.is_file()
    note = json.loads(notification_file.read_text(encoding="utf-8"))
    assert note["job_id"] == job_id and note["status"] == "succeeded"

    log_lines = (tmp_path / "jobs" / "notifications.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["job_id"] == job_id for line in log_lines)

    notes_cap = caps.get("job.notifications")
    result = notes_cap.render_safe(
        {"jobs_root": str(tmp_path / "jobs")}, tmp_path / "notes-out",
        duration=1.0, aspect="16:9", seed=1)
    assert result.qa["count"] >= 1
    assert any(n["job_id"] == job_id for n in result.qa["notifications"])

    artefact.unlink()
    assert not artefact.exists(), "contract: deleting the artefact must break verification"


def test_failed_job_still_writes_notification(tmp_path: Path) -> None:
    job_id, status = _run_and_wait(tmp_path, _FAIL)
    assert status["status"] == "failed"
    assert "deliberate failure" in status["error"]

    note = json.loads((tmp_path / "jobs" / job_id / "notification.json").read_text(encoding="utf-8"))
    assert note["status"] == "failed"
    assert "deliberate failure" in note["error"]


def test_unknown_capability_job_fails_with_notification(tmp_path: Path) -> None:
    job_id, status = _run_and_wait(tmp_path, "no.such_capability")
    assert status["status"] == "failed"
    assert "unknown capability" in status["error"]
    assert (tmp_path / "jobs" / job_id / "notification.json").is_file()


def test_webhook_best_effort_unreachable_does_not_break_job(tmp_path: Path) -> None:
    # 127.0.0.1:9 (discard) refuses instantly; no external network involved.
    job_id, status = _run_and_wait(tmp_path, _ECHO, {"text": "x"},
                                   webhook_url="http://127.0.0.1:9/hook")
    assert status["status"] == "succeeded"
    note = json.loads((tmp_path / "jobs" / job_id / "notification.json").read_text(encoding="utf-8"))
    assert note["webhook"]["ok"] is False
    assert note["webhook"]["error"]


def test_webhook_injected_poster_receives_notification(tmp_path: Path) -> None:
    sent: list[tuple[str, dict]] = []
    job_id = runner.start_job(
        _ECHO, {"text": "hooked"}, jobs_root=tmp_path / "jobs",
        webhook_url="https://example.invalid/hook",
        webhook_post=lambda url, payload: sent.append((url, payload)),
    )
    status = runner.wait_for_job(job_id, jobs_root=tmp_path / "jobs", timeout=15.0)
    assert status["status"] == "succeeded"
    deadline = time.time() + 5.0
    while not sent and time.time() < deadline:
        time.sleep(0.02)
    assert sent and sent[0][0] == "https://example.invalid/hook"
    assert sent[0][1]["job_id"] == job_id
    note = json.loads((tmp_path / "jobs" / job_id / "notification.json").read_text(encoding="utf-8"))
    assert note["webhook"] == {"url": "https://example.invalid/hook", "ok": True, "error": None}


def test_deleted_status_record_breaks_job_status(tmp_path: Path) -> None:
    job_id, status = _run_and_wait(tmp_path, _ECHO, {"text": "gone"})
    assert status["status"] == "succeeded"
    status_file = tmp_path / "jobs" / job_id / "status.json"
    status_file.unlink()
    assert not status_file.exists()
    with pytest.raises(CapabilityError):
        _status_via_capability(tmp_path, job_id)
