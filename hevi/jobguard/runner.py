"""Background job runner with on-disk status + completion notifications.

Layout under a jobs root (default: ``$HEVI_JOBS_ROOT`` or ``./jobs``)::

    jobs/<job_id>/status.json        # running -> succeeded | failed
    jobs/<job_id>/artifacts/         # the capability's out_dir
    jobs/<job_id>/notification.json   # written once, when the job terminates
    jobs/notifications.jsonl          # one appended line per terminated job

A job executes ``hevi.capabilities.get(name).render_safe(params, artifacts)``
in a daemon thread.  Completion *and* failure both write a notification; an
optional ``webhook_url`` gets a best-effort POST of the notification —
delivery failure is recorded in the notification, never raised, and never
changes the job's own outcome.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError

TERMINAL_STATUSES = ("succeeded", "failed")

_append_lock = threading.Lock()

WebhookPoster = Callable[[str, dict[str, Any]], None]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=1))
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def default_jobs_root() -> Path:
    env = os.environ.get("HEVI_JOBS_ROOT")
    if env:
        return Path(env)
    return Path.cwd() / "jobs"


def resolve_jobs_root(jobs_root: str | Path | None = None) -> Path:
    """Resolve an explicit jobs root, or the default when none is given."""
    return Path(jobs_root) if jobs_root else default_jobs_root()


def _root(jobs_root: str | Path | None) -> Path:
    return resolve_jobs_root(jobs_root)


def _job_dir(root: Path, job_id: str) -> Path:
    if not job_id or "/" in str(job_id) or "\\" in str(job_id) or str(job_id) in (".", ".."):
        raise CapabilityError(f"jobguard: invalid job_id {job_id!r}")
    return root / str(job_id)


def _default_webhook_post(url: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def start_job(
    capability_name: str,
    capability_params: dict[str, Any] | None = None,
    *,
    jobs_root: str | Path | None = None,
    webhook_url: str | None = None,
    duration: float = 5.0,
    aspect: str = "16:9",
    seed: int = 42,
    webhook_post: WebhookPoster | None = None,
) -> str:
    """Start ``capability_name`` in a background thread; return the job_id."""
    if not isinstance(capability_name, str) or not capability_name.strip():
        raise CapabilityError("jobguard: capability must be a non-empty string")
    params: dict[str, Any] = {} if capability_params is None else capability_params
    if not isinstance(params, dict):
        raise CapabilityError("jobguard: capability params must be an object")
    if webhook_url is not None and not isinstance(webhook_url, str):
        raise CapabilityError("jobguard: webhook_url must be a string")

    root = _root(jobs_root)
    job_id = uuid.uuid4().hex
    jdir = root / job_id
    jdir.mkdir(parents=True, exist_ok=False)
    status: dict[str, Any] = {
        "job_id": job_id,
        "capability": capability_name,
        "params": params,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "artifacts_dir": str(jdir / "artifacts"),
        "artifacts": [],
        "result": None,
        "error": None,
        "webhook_url": webhook_url,
    }
    _atomic_write_json(jdir / "status.json", status)
    thread = threading.Thread(
        target=_run_job,
        kwargs={
            "job_id": job_id,
            "capability_name": capability_name,
            "params": params,
            "root": root,
            "webhook_url": webhook_url,
            "duration": duration,
            "aspect": aspect,
            "seed": seed,
            "webhook_post": webhook_post,
        },
        daemon=True,
        name=f"hevi-job-{job_id[:8]}",
    )
    thread.start()
    return job_id


def _run_job(
    *,
    job_id: str,
    capability_name: str,
    params: dict[str, Any],
    root: Path,
    webhook_url: str | None,
    duration: float,
    aspect: str,
    seed: int,
    webhook_post: WebhookPoster | None,
) -> None:
    jdir = root / job_id
    status_path = jdir / "status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover - status was just written by start_job
        status = {"job_id": job_id, "capability": capability_name}
    try:
        import hevi.capabilities as caps

        cap = caps.get(capability_name)
        result = cap.render_safe(
            params, jdir / "artifacts", duration=duration, aspect=aspect, seed=seed
        )
        status["status"] = "succeeded"
        status["result"] = result.as_dict()
        status["artifacts"] = [p for p in (result.mp4, result.png, result.wav) if p]
        status["error"] = None
    except Exception as exc:
        status["status"] = "failed"
        status["result"] = None
        status["error"] = f"{type(exc).__name__}: {exc}"
    status["finished_at"] = _now()

    notification: dict[str, Any] = {
        "job_id": job_id,
        "capability": capability_name,
        "status": status["status"],
        "finished_at": status["finished_at"],
        "error": status["error"],
        "artifacts": status.get("artifacts", []),
        "webhook": None,
    }
    if webhook_url:
        poster = webhook_post or _default_webhook_post
        try:
            poster(webhook_url, dict(notification))
            notification["webhook"] = {"url": webhook_url, "ok": True, "error": None}
        except Exception as exc:
            notification["webhook"] = {"url": webhook_url, "ok": False, "error": str(exc)}
    # Notification lands BEFORE the terminal status write, so any poller that
    # observes succeeded/failed is guaranteed the notification already exists.
    _atomic_write_json(jdir / "notification.json", notification)
    with _append_lock:
        root.mkdir(parents=True, exist_ok=True)
        with open(root / "notifications.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(notification, ensure_ascii=False) + "\n")
    _atomic_write_json(status_path, status)


def get_job_status(job_id: str, *, jobs_root: str | Path | None = None) -> dict[str, Any]:
    """Read ``jobs/<job_id>/status.json``; CapabilityError if it does not exist."""
    root = _root(jobs_root)
    status_path = _job_dir(root, job_id) / "status.json"
    if not status_path.is_file():
        raise CapabilityError(f"jobguard: unknown job {job_id!r} (no {status_path})")
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CapabilityError(f"jobguard: status file unreadable for job {job_id!r}: {exc}") from exc


def list_notifications(
    *, jobs_root: str | Path | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Return the most recent completion notifications (oldest first)."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise CapabilityError("jobguard: limit must be a positive integer")
    log_path = _root(jobs_root) / "notifications.jsonl"
    if not log_path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-limit:]


def wait_for_job(
    job_id: str, *, jobs_root: str | Path | None = None, timeout: float = 30.0, poll_s: float = 0.05
) -> dict[str, Any]:
    """Poll until the job reaches a terminal status; return its status dict."""
    deadline = time.monotonic() + timeout
    while True:
        status = get_job_status(job_id, jobs_root=jobs_root)
        if status.get("status") in TERMINAL_STATUSES:
            return status
        if time.monotonic() >= deadline:
            raise CapabilityError(
                f"jobguard: job {job_id!r} did not finish within {timeout}s "
                f"(last status: {status.get('status')!r})"
            )
        time.sleep(poll_s)
