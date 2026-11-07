"""Preview and task-centre discipline (``pipeline.preview_tasks``).

Method borrowed from the BeefTV preview/task-centre shape
(H.265 originals kept directly, H.264 previews generated
on demand, async tasks with explicit states and retry),
rewritten from scratch for hevi; see
PRODUCTIZATION_ATTRIBUTION.md. No upstream text is used here.

Rules enforced by this module:

* The original is stored, never transcoded. ``store_original``
  copies the source bytes verbatim; the stored file's sha256
  must equal the source's. No preview step ever writes to the
  original path, and ``generate_preview`` verifies the
  original's hash before and after and refuses to report
  success if it changed.
* Previews are on demand and single-threaded. A preview is
  only generated when asked for. Generation takes a module
  lock without blocking: if another preview is already
  running, the second call is refused at once (it is not
  queued behind the first, and it never runs in parallel
  competing for the same resources). A preview failure
  deletes any partial preview file and leaves the original
  untouched, so a failed preview can never be mistaken for
  a delivered file.
* The H.264 preview path uses ffmpeg when no preview
  function is injected (``-c:v libx264``). When the caller
  injects ``preview_fn`` (tests, or a caller-owned encoder),
  that function writes the preview file itself and ffmpeg
  is not required.
* Async task state machine. Tasks move queued -> running ->
  completed or failed, and only along those edges: starting a
  task that is not queued, or retrying one that is not
  failed, raises naming the current state, and the record
  is left unchanged. A failed task keeps its input snapshot
  (deep-copied at creation, never mutated afterwards), its
  failure reason and its attempt history; ``retry_task``
  returns it to queued with all of that retained, so no
  task record is ever dropped because it failed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
_preview_lock = threading.Lock()


def _fail(message: str) -> None:
    raise CapabilityError(f"pipeline.preview_tasks: {message}")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            _fail(f"task store is not valid JSON: {path}")
        if not isinstance(data, dict) or "tasks" not in data:
            _fail(f"task store has no tasks block: {path}")
        return data
    return {"capability": "pipeline.preview_tasks", "tasks": {}}


def _save(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def store_original(source_path: Path, dest_path: Path) -> dict[str, Any]:
    """Copy an original verbatim. The stored bytes must match."""
    source = Path(source_path)
    dest = Path(dest_path)
    if not source.is_file():
        _fail(f"original not found: {source}")
    if source.resolve() == dest.resolve():
        _fail("store_original: source and destination are the same file")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    before = _sha256(source)
    after = _sha256(dest)
    if before != after:
        _fail("store_original: stored copy hash differs from source")
    return {"original_path": str(dest), "sha256": after,
            "bytes": dest.stat().st_size, "transcoded": False}


def _ffmpeg_preview(original: Path, preview: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        _fail("ffmpeg not found on PATH; inject preview_fn or install ffmpeg")
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(original),
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(preview)],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        _fail(f"ffmpeg preview failed: {proc.stderr.strip()}")


def generate_preview(
    original_path: Path,
    preview_path: Path,
    *,
    preview_fn: Callable[[Path, Path], Any] | None = None,
) -> dict[str, Any]:
    """Generate an H.264 preview on demand, single-threaded.

    Refuses at once when another preview is running, deletes a
    partial preview on failure, and verifies the original's
    hash before and after. Never writes to the original path.
    """
    original = Path(original_path)
    preview = Path(preview_path)
    if not original.is_file():
        _fail(f"original not found: {original}")
    if original.resolve() == preview.resolve():
        _fail("generate_preview: preview path must differ from original")
    if not _preview_lock.acquire(blocking=False):
        _fail("preview already running; previews are single-threaded "
              "and are not started in parallel")
    try:
        before = _sha256(original)
        preview.parent.mkdir(parents=True, exist_ok=True)
        try:
            if callable(preview_fn):
                preview_fn(original, preview)
            else:
                _ffmpeg_preview(original, preview)
        except CapabilityError:
            if preview.is_file():
                preview.unlink()
            raise
        except Exception as exc:
            if preview.is_file():
                preview.unlink()
            _fail(f"preview generation failed: {exc}")
        if not preview.is_file():
            _fail("preview generation produced no file")
        after = _sha256(original)
        if after != before:
            _fail("original changed during preview generation; "
                  "preview is not reported as success")
        return {"original_path": str(original),
                "original_sha256_before": before,
                "original_sha256_after": after,
                "original_unchanged": True,
                "preview_path": str(preview),
                "preview_bytes": preview.stat().st_size}
    finally:
        _preview_lock.release()


def create_task(
    store_path: Path,
    *,
    task_id: str,
    kind: str = "preview",
    input_snapshot: Any = None,
) -> dict[str, Any]:
    if not task_id or not isinstance(task_id, str):
        _fail("create_task: task_id must be a non-empty string")
    path = Path(store_path)
    data = _load(path)
    if task_id in data["tasks"]:
        _fail(f"task already exists: {task_id!r}")
    record = {
        "task_id": task_id,
        "kind": kind,
        "status": "queued",
        "input_snapshot": copy.deepcopy(input_snapshot),
        "result": None,
        "failure_reason": None,
        "attempts": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    data["tasks"][task_id] = record
    _save(path, data)
    return copy.deepcopy(record)


def get_task(store_path: Path, task_id: str) -> dict[str, Any]:
    data = _load(Path(store_path))
    record = data["tasks"].get(task_id)
    if record is None:
        _fail(f"unknown task: {task_id!r}")
    return copy.deepcopy(record)


def list_tasks(
    store_path: Path, status: str | None = None
) -> list[dict[str, Any]]:
    data = _load(Path(store_path))
    tasks = list(data["tasks"].values())
    if status is not None:
        tasks = [t for t in tasks if t.get("status") == status]
    return copy.deepcopy(tasks)


def run_task(
    store_path: Path,
    *,
    task_id: str,
    worker_fn: Callable[[Any], Any],
) -> dict[str, Any]:
    """Run a queued task to completed or failed.

    Only queued tasks may start. A worker exception marks the
    task failed with its reason and attempt history; the input
    snapshot and the task record are kept, never dropped.
    """
    path = Path(store_path)
    data = _load(path)
    record = data["tasks"].get(task_id)
    if record is None:
        _fail(f"unknown task: {task_id!r}")
    if record["status"] != "queued":
        _fail(
            f"task {task_id!r} cannot start from status "
            f"{record['status']!r}; only queued tasks may run"
        )
    record["status"] = "running"
    record["updated_at"] = _now_iso()
    _save(path, data)
    attempt = len(record["attempts"]) + 1
    try:
        result = worker_fn(copy.deepcopy(record["input_snapshot"]))
    except Exception as exc:
        record["status"] = "failed"
        record["failure_reason"] = str(exc)
        record["result"] = None
        record["attempts"].append({
            "attempt": attempt, "status": "failed",
            "reason": str(exc), "at": _now_iso(),
        })
        record["updated_at"] = _now_iso()
        _save(path, data)
        return copy.deepcopy(record)
    record["status"] = "completed"
    record["result"] = copy.deepcopy(result)
    record["failure_reason"] = None
    record["attempts"].append({
        "attempt": attempt, "status": "completed", "at": _now_iso(),
    })
    record["updated_at"] = _now_iso()
    _save(path, data)
    return copy.deepcopy(record)


def retry_task(store_path: Path, *, task_id: str) -> dict[str, Any]:
    """Return a failed task to queued, keeping its input snapshot,
    failure reason and attempt history."""
    path = Path(store_path)
    data = _load(path)
    record = data["tasks"].get(task_id)
    if record is None:
        _fail(f"unknown task: {task_id!r}")
    if record["status"] != "failed":
        _fail(
            f"task {task_id!r} cannot be retried from status "
            f"{record['status']!r}; only failed tasks may retry"
        )
    record["status"] = "queued"
    record["updated_at"] = _now_iso()
    _save(path, data)
    return copy.deepcopy(record)


def run_preview_task(
    store_path: Path,
    *,
    task_id: str,
    original_path: Path,
    preview_path: Path,
    preview_fn: Callable[[Path, Path], Any] | None = None,
) -> dict[str, Any]:
    """Run a queued task whose work is one preview generation."""
    def _work(_snapshot: Any) -> dict[str, Any]:
        return generate_preview(original_path, preview_path,
                                preview_fn=preview_fn)

    return run_task(store_path, task_id=task_id, worker_fn=_work)


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    store = Path(params["store_path"])
    action = params.get("action", "list")
    if action == "create":
        result: dict[str, Any] = {
            "capability": "pipeline.preview_tasks",
            "record": create_task(
                store, task_id=str(params["task_id"]),
                kind=str(params.get("kind", "preview")),
                input_snapshot=params.get("input_snapshot"),
            ),
        }
    elif action == "run_preview":
        result = {
            "capability": "pipeline.preview_tasks",
            "record": run_preview_task(
                store, task_id=str(params["task_id"]),
                original_path=Path(params["original_path"]),
                preview_path=Path(params["preview_path"]),
            ),
        }
    elif action == "retry":
        result = {
            "capability": "pipeline.preview_tasks",
            "record": retry_task(store, task_id=str(params["task_id"])),
        }
    elif action == "get":
        result = {
            "capability": "pipeline.preview_tasks",
            "record": get_task(store, str(params["task_id"])),
        }
    elif action == "list":
        result = {
            "capability": "pipeline.preview_tasks",
            "tasks": list_tasks(store, params.get("status")),
        }
    elif action == "store_original":
        result = {
            "capability": "pipeline.preview_tasks",
            "original": store_original(
                Path(params["source_path"]), Path(params["dest_path"])),
        }
    else:
        _fail(f"unknown action {action!r}; known: create, run_preview, "
              f"retry, get, list, store_original")
    report_path = out_dir / "preview_tasks_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_preview_tasks_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.preview_tasks",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "store_path": {"type": "string"},
                    "action": {"type": "string", "enum": [
                        "create", "run_preview", "retry", "get", "list",
                        "store_original"]},
                    "task_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "input_snapshot": {},
                    "status": {"type": "string"},
                    "original_path": {"type": "string"},
                    "preview_path": {"type": "string"},
                    "source_path": {"type": "string"},
                    "dest_path": {"type": "string"},
                },
                "required": ["store_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Preview and task-centre discipline: originals are "
                "stored verbatim (never transcoded by a preview); "
                "H.264 previews are generated on demand, "
                "single-threaded, and a preview failure deletes any "
                "partial file and leaves the original untouched; "
                "async tasks move queued -> running -> completed or "
                "failed only, failed tasks keep their input snapshot, "
                "failure reason and attempt history, and only failed "
                "tasks may retry, back to queued."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.preview_tasks"]


register_preview_tasks_capabilities_once()
