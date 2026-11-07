"""Draft task ledger (``video.draft_task_ledger``).

Clean-room rewrite of the method in ``hevi-vs-rain-before-stops.md``
item B1 (from the ``<雨停之前>`` field notes and the Volcano Ark
Seedance 2.5 documentation): a 480p draft sample and its 1080p
final are two separate paid tasks. The draft task id is the only
thing that converts a draft into a final, and it lives for **7
days**. A locally saved video file never substitutes for a valid
task id, and an expired id cannot convert -- a new draft is
needed.

This module is a *fake* backend: it records draft tasks in a local
JSON ledger, judges expiry from caller-supplied clocks (no wall
clock is read, so expiry is deterministic and testable), and
performs no network call, stores no key, and generates nothing.
A real Seedance route is a separate decision (key + budget); this
ledger is the bookkeeping that must exist before any such call.

States: ``draft`` -> ``final`` (converted) or ``expired``
(7 days elapsed without conversion). Conversion requires the
1080p tier only: a draft converts to the 1080p final tier, never
to another draft.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Draft task ids live 7 days (Ark documentation, confirmed by
# three independent guides; see hevi-vs-rain-before-stops.md F2).
DRAFT_TASK_TTL_S = 7 * 24 * 3600

DRAFT_RESOLUTION = "480p"
FINAL_RESOLUTION = "1080p"


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"video.draft_task_ledger: {detail}"}
    issue.update(extra)
    return issue


def parse_time(value: Any) -> dict[str, Any]:
    """Parse an ISO-8601 time to epoch seconds. Returns ``{ok, epoch_s, issue}``."""
    if not isinstance(value, str) or not value.strip():
        return {"ok": False, "epoch_s": None,
                "issue": "time must be a non-empty ISO-8601 string"}
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return {"ok": False, "epoch_s": None,
                "issue": f"time {value!r} is not ISO-8601"}
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return {"ok": True, "epoch_s": moment.timestamp(), "issue": None}


def _load_ledger(path: Path) -> dict[str, Any]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data
    return {"tasks": []}


def _save_ledger(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _find_task(data: dict[str, Any], draft_task_id: str) -> dict[str, Any] | None:
    for task in data["tasks"]:
        if task.get("draft_task_id") == draft_task_id:
            return task
    return None


def create_draft_task(ledger_path: Path, *, draft_task_id: str,
                      created_at: str, duration_s: float,
                      source_video_path: str | None = None) -> dict[str, Any]:
    """Record a draft task. Raises CapabilityError on bad input or duplicate id."""
    if not isinstance(draft_task_id, str) or not draft_task_id.strip():
        raise CapabilityError("video.draft_task_ledger: draft_task_id must be a non-empty string")
    parsed = parse_time(created_at)
    if not parsed["ok"]:
        raise CapabilityError(f"video.draft_task_ledger: {parsed['issue']}")
    if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool) or float(duration_s) <= 0:
        raise CapabilityError("video.draft_task_ledger: duration_s must be a positive number")
    path = Path(ledger_path)
    data = _load_ledger(path)
    if _find_task(data, draft_task_id) is not None:
        raise CapabilityError(f"video.draft_task_ledger: duplicate draft_task_id: {draft_task_id!r}")
    task = {
        "draft_task_id": draft_task_id,
        "created_at": created_at,
        "created_epoch_s": parsed["epoch_s"],
        "expires_epoch_s": parsed["epoch_s"] + DRAFT_TASK_TTL_S,
        "duration_s": float(duration_s),
        "draft_resolution": DRAFT_RESOLUTION,
        "status": "draft",
        "source_video_path": source_video_path,
        "final_task_id": None,
    }
    data["tasks"].append(task)
    _save_ledger(path, data)
    return copy.deepcopy(task)


def task_status(ledger_path: Path, draft_task_id: str, now: str) -> dict[str, Any]:
    """Report a task's status at ``now`` (caller-supplied clock). Never raises for bad input."""
    parsed = parse_time(now)
    if not parsed["ok"]:
        return {"ok": False, "status": None,
                "issues": [_issue("bad_clock", parsed["issue"])]}
    data = _load_ledger(Path(ledger_path))
    task = _find_task(data, draft_task_id) if isinstance(draft_task_id, str) else None
    if task is None:
        return {"ok": False, "status": None,
                "issues": [_issue("task_not_found", f"no draft task {draft_task_id!r}")]}
    if task["status"] == "final":
        return {"ok": True, "status": "final", "task": copy.deepcopy(task), "issues": []}
    if parsed["epoch_s"] >= task["expires_epoch_s"]:
        return {"ok": False, "status": "expired",
                "task": copy.deepcopy(task),
                "issues": [_issue(
                    "draft_task_expired",
                    "draft task id expired after 7 days; a new draft is needed",
                    draft_task_id=draft_task_id,
                )]}
    return {"ok": True, "status": "draft", "task": copy.deepcopy(task), "issues": []}


def convert_draft_to_final(ledger_path: Path, *, draft_task_id: str,
                           now: str, resolution: str) -> dict[str, Any]:
    """Convert a draft to its final. Fails closed on expiry, wrong tier, or missing id."""
    if not isinstance(draft_task_id, str) or not draft_task_id.strip():
        return {"ok": False, "status": None,
                "issues": [_issue(
                    "local_file_cannot_replace_task_id",
                    "a locally saved video cannot replace a valid draft task id",
                )]}
    if resolution != FINAL_RESOLUTION:
        return {"ok": False, "status": None,
                "issues": [_issue(
                    "final_tier_mismatch",
                    f"a draft converts only to the {FINAL_RESOLUTION} final tier, not {resolution!r}",
                    resolution=resolution,
                )]}
    status = task_status(ledger_path, draft_task_id, now)
    if status["status"] != "draft":
        return {"ok": False, "status": status["status"], "issues": status["issues"]}
    path = Path(ledger_path)
    data = _load_ledger(path)
    task = _find_task(data, draft_task_id)
    task["status"] = "final"
    task["final_task_id"] = f"{draft_task_id}:final"
    _save_ledger(path, data)
    return {"ok": True, "status": "final", "task": copy.deepcopy(task), "issues": []}


def check_draft_task_request(request: Any) -> dict[str, Any]:
    """Judge a conversion request record (pure check, no ledger write)."""
    issues: list[dict[str, Any]] = []
    if not isinstance(request, dict):
        return {"ok": False, "issues": [_issue("request_not_object", "request must be an object")]}
    if not isinstance(request.get("draft_task_id"), str) or not request["draft_task_id"].strip():
        issues.append(_issue(
            "local_file_cannot_replace_task_id",
            "a locally saved video cannot replace a valid draft task id",
        ))
    if request.get("resolution") != FINAL_RESOLUTION:
        issues.append(_issue(
            "final_tier_mismatch",
            f"a draft converts only to the {FINAL_RESOLUTION} final tier",
            resolution=request.get("resolution"),
        ))
    return {"ok": not issues, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    action = params.get("action")
    ledger_path = Path(out_dir) / "draft_task_ledger.json"
    if action == "create":
        try:
            task = create_draft_task(
                ledger_path,
                draft_task_id=params["draft_task_id"],
                created_at=params["created_at"],
                duration_s=params["duration_s"],
            )
            report: dict[str, Any] = {"ok": True, "status": "draft", "task": task, "issues": []}
        except (CapabilityError, KeyError, TypeError) as exc:
            report = {"ok": False, "status": None, "issues": [_issue("create_failed", str(exc))]}
    elif action == "status":
        report = task_status(ledger_path, params.get("draft_task_id", ""), params.get("now", ""))
    elif action == "convert":
        report = convert_draft_to_final(
            ledger_path, draft_task_id=params.get("draft_task_id", ""),
            now=params.get("now", ""), resolution=params.get("resolution", ""),
        )
    else:
        report = check_draft_task_request(params.get("request"))
    report_path = Path(out_dir) / "draft_task_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_draft_task_ledger_capabilities_once() -> list[str]:
    """Register ``video.draft_task_ledger`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.draft_task_ledger",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "draft_task_id": {"type": "string"},
                    "created_at": {"type": "string"},
                    "duration_s": {"type": "number"},
                    "now": {"type": "string"},
                    "resolution": {"type": "string"},
                    "request": {"type": "object"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Draft task ledger (fake backend): draft task ids live "
                "7 days and convert only to the 1080p final tier; a "
                "locally saved video never substitutes for a valid id. "
                "No network, no key, no generation."
            ),
            line="video",
        )
    )
    return ["video.draft_task_ledger"]


register_draft_task_ledger_capabilities_once()
