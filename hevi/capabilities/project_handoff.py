"""Finished-film project handoff contract (``pipeline.project_handoff``).

A finished film is a directory, not a chat transcript. Every run lives
under one project root with a fixed stage layout, and every stage
records what it consumed, what it produced, when it ran, and what it
checked. A later stage may only start from files the earlier stage
actually wrote to disk; it never reads an earlier result out of a
conversation.

Stage order is fixed. The directory names are the contract; a stage
that is missing, or whose recorded outputs no longer exist on disk,
blocks every stage after it, and the block names the missing stage
and the missing files instead of failing silently or guessing.

Failure contract: unknown stage, a missing project root, a record
that names an input or output file that does not exist, or a gate
check against a missing stage all raise CapabilityError. A gate
that finds a gap returns that gap as data (the render path still
writes the report); it never reports a ready project when a stage
is missing.
"""

from __future__ import annotations

import json
import time
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

STAGES: tuple[str, ...] = (
    "reference",
    "topic",
    "script",
    "edit",
    "broll",
    "subtitle",
    "cover",
    "review",
)

STAGE_DIRS: dict[str, str] = {
    "reference": "00_reference",
    "topic": "01_topic",
    "script": "02_script",
    "edit": "03_edit",
    "broll": "04_broll",
    "subtitle": "05_subtitle",
    "cover": "06_cover",
    "review": "07_review",
}

MANIFEST_NAME = "manifest.json"


def _check_stage(stage: str) -> None:
    if stage not in STAGES:
        raise CapabilityError(
            f"pipeline.project_handoff: unknown stage {stage!r}; known: {list(STAGES)}"
        )


def _manifest_path(project_root: Path) -> Path:
    return Path(project_root) / MANIFEST_NAME


def _load_manifest(project_root: Path) -> dict[str, Any]:
    path = _manifest_path(project_root)
    if not path.is_file():
        raise CapabilityError(
            f"pipeline.project_handoff: manifest not found: {path} "
            "(run create first)"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CapabilityError(
            f"pipeline.project_handoff: manifest is not valid JSON: {path}"
        ) from exc
    if not isinstance(data, dict) or "stages" not in data:
        raise CapabilityError(
            f"pipeline.project_handoff: manifest has no stages block: {path}"
        )
    return data


def _save_manifest(project_root: Path, data: dict[str, Any]) -> Path:
    path = _manifest_path(project_root)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _resolve(project_root: Path, name: str) -> Path:
    p = Path(name)
    return p if p.is_absolute() else project_root / p


def create_project(project_root: Path, title: str = "") -> dict[str, Any]:
    """Create the fixed stage directories and an empty manifest."""
    root = Path(project_root)
    root.mkdir(parents=True, exist_ok=True)
    for stage in STAGES:
        (root / STAGE_DIRS[stage]).mkdir(parents=True, exist_ok=True)
    data = {
        "capability": "pipeline.project_handoff",
        "title": title,
        "stages": {
            stage: {
                "dir": STAGE_DIRS[stage],
                "status": "pending",
                "inputs": [],
                "outputs": [],
                "checks": [],
                "finished_at": None,
            }
            for stage in STAGES
        },
        "steps": [],
    }
    _save_manifest(root, data)
    return data


def record_step(
    project_root: Path,
    stage: str,
    inputs: list[str],
    outputs: list[str],
    checks: list[dict[str, Any]] | None = None,
    tool: str = "",
) -> dict[str, Any]:
    """Record one finished stage, after verifying its files exist.

    ``inputs`` and ``outputs`` are paths relative to the project root
    (absolute paths are accepted as-is). A name that does not exist
    on disk raises instead of being recorded, so the manifest can
    never claim a file that is not there.
    """
    _check_stage(stage)
    root = Path(project_root)
    if not root.is_dir():
        raise CapabilityError(
            f"pipeline.project_handoff: project root not found: {root}"
        )
    data = _load_manifest(root)
    missing_inputs = [n for n in inputs if not _resolve(root, n).is_file()]
    missing_outputs = [n for n in outputs if not _resolve(root, n).is_file()]
    if missing_inputs or missing_outputs:
        raise CapabilityError(
            "pipeline.project_handoff: cannot record stage "
            f"{stage!r}: missing inputs={missing_inputs} "
            f"missing outputs={missing_outputs}"
        )
    step = {
        "stage": stage,
        "inputs": list(inputs),
        "outputs": list(outputs),
        "checks": list(checks or []),
        "tool": tool,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    data["stages"][stage].update(
        {
            "status": "done",
            "inputs": list(inputs),
            "outputs": list(outputs),
            "checks": list(checks or []),
            "finished_at": step["finished_at"],
        }
    )
    data["steps"].append(step)
    _save_manifest(root, data)
    return step


def gate_for_stage(project_root: Path, stage: str) -> dict[str, Any]:
    """Check whether ``stage`` may start.

    A stage may start only when every earlier stage is recorded as
    done and every recorded output still exists on disk. The result
    lists each blocking stage with the exact files that are missing
    (unrecorded stages are listed with their expected directory).
    """
    _check_stage(stage)
    root = Path(project_root)
    data = _load_manifest(root)
    idx = STAGES.index(stage)
    blockers: list[dict[str, Any]] = []
    for earlier in STAGES[:idx]:
        entry = data["stages"].get(earlier) or {}
        if entry.get("status") != "done":
            blockers.append(
                {
                    "stage": earlier,
                    "dir": STAGE_DIRS[earlier],
                    "reason": "stage not recorded as done",
                    "missing_files": [],
                }
            )
            continue
        gone = [
            n for n in entry.get("outputs", []) if not _resolve(root, n).is_file()
        ]
        if gone:
            blockers.append(
                {
                    "stage": earlier,
                    "dir": STAGE_DIRS[earlier],
                    "reason": "recorded output no longer on disk",
                    "missing_files": gone,
                }
            )
    return {
        "capability": "pipeline.project_handoff",
        "project_root": str(root),
        "stage": stage,
        "ready": not blockers,
        "blockers": blockers,
    }


def validate_manifest(project_root: Path) -> dict[str, Any]:
    """Re-check a whole manifest: every done stage's outputs on disk."""
    root = Path(project_root)
    data = _load_manifest(root)
    problems: list[dict[str, Any]] = []
    for stage in STAGES:
        entry = data["stages"].get(stage) or {}
        if entry.get("status") != "done":
            continue
        gone = [
            n for n in entry.get("outputs", []) if not _resolve(root, n).is_file()
        ]
        if gone:
            problems.append({"stage": stage, "missing_files": gone})
    return {
        "capability": "pipeline.project_handoff",
        "project_root": str(root),
        "valid": not problems,
        "problems": problems,
        "done_stages": [
            s for s in STAGES if data["stages"].get(s, {}).get("status") == "done"
        ],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    project_root = Path(params["project_root"])
    action = params.get("action", "gate")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if action == "create":
        result: dict[str, Any] = create_project(
            project_root, title=str(params.get("title", ""))
        )
    elif action == "record":
        stage = str(params["stage"])
        result = {
            "capability": "pipeline.project_handoff",
            "step": record_step(
                project_root,
                stage,
                list(params.get("inputs", [])),
                list(params.get("outputs", [])),
                checks=list(params.get("checks", [])),
                tool=str(params.get("tool", "")),
            ),
        }
    elif action == "gate":
        result = gate_for_stage(project_root, str(params["stage"]))
    elif action == "validate":
        result = validate_manifest(project_root)
    else:
        raise CapabilityError(
            f"pipeline.project_handoff: unknown action {action!r}; "
            "known: create, record, gate, validate"
        )
    report = out_dir / "project_handoff_report.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "result": result},
    )


def register_project_handoff_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.project_handoff",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["create", "record", "gate", "validate"],
                    },
                    "title": {"type": "string"},
                    "stage": {"type": "string", "enum": list(STAGES)},
                    "inputs": {"type": "array", "items": {"type": "string"}},
                    "outputs": {"type": "array", "items": {"type": "string"}},
                    "checks": {"type": "array", "items": {"type": "object"}},
                    "tool": {"type": "string"},
                },
                "required": ["project_root"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Finished-film project handoff contract: fixed stage "
                "directories (reference, topic, script, edit, broll, "
                "subtitle, cover, review) plus a manifest recording each "
                "stage's inputs, outputs, finish time and checks. A "
                "stage may not start until every earlier stage is "
                "recorded and its outputs still exist; the gate names "
                "the blocking stage and missing files."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.project_handoff"]


register_project_handoff_capabilities_once()
