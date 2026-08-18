"""工单 —— 选产线、填槽、跑配方、签发交接单。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.pipeline.manifest import run_with_checkpoint
from hevi.studio.recipes import Recipe, get_recipe


@dataclass
class Slate:
    line_id: str
    slots: dict[str, Any]
    execute: bool = False
    slate_id: str = ""

    def __post_init__(self) -> None:
        if not self.slate_id:
            self.slate_id = str(uuid.uuid4())


@dataclass
class SlateResult:
    status: str
    slate_id: str
    line_id: str
    product: str
    missing: list[str] = field(default_factory=list)
    production_order: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "slate_id": self.slate_id,
            "line_id": self.line_id,
            "product": self.product,
            "missing": self.missing,
            "production_order": self.production_order,
            "data": {
                k: self.data[k]
                for k in (
                    "topic",
                    "video_provider",
                    "script_lines",
                    "bound_assets",
                    "edit_plan",
                    "preview_gate",
                    "concepts",
                    "research",
                    "publish_results",
                    "mix",
                    "timeline",
                    "render_runtime",
                    "hyperframes",
                    "fulfill",
                )
                if k in self.data
            },
            "reason": self.reason,
        }


def _seed_data(slate: Slate, recipe: Recipe) -> dict[str, Any]:
    data = dict(slate.slots)
    data["line_id"] = recipe.id
    data["handoff"] = recipe.handoff
    data["slate_id"] = slate.slate_id
    data.setdefault("render_runtime", recipe.render_runtime)
    data["execute"] = slate.execute
    if "topic" not in data:
        for key in ("source_text", "manuscript", "source_name"):
            if data.get(key):
                data["topic"] = str(data[key])[:200]
                break
    return data


async def run_slate(slate: Slate, *, recipe: Recipe | None = None) -> SlateResult:
    rec = recipe or get_recipe(slate.line_id)
    if rec is None:
        return SlateResult(
            status="failed",
            slate_id=slate.slate_id,
            line_id=slate.line_id,
            product="",
            reason=f"unknown line: {slate.line_id}",
        )
    missing = rec.missing_slots(slate.slots)
    if missing:
        return SlateResult(
            status="blocked",
            slate_id=slate.slate_id,
            line_id=rec.id,
            product=rec.product,
            missing=missing,
            reason="required slots empty",
        )
    state = await run_with_checkpoint(rec.pipeline, _seed_data(slate, rec), run_id=slate.slate_id)
    data = dict(state.data or {})
    order = data.get("production_order") or {}
    pipe_state = getattr(state, "state", "completed")
    fulfill = data.get("fulfill") or {}
    status = "scheduled" if order.get("target") and order["target"] != "none" else "planned"
    if slate.execute and fulfill.get("status") == "dispatched":
        status = "dispatched"
    if pipe_state in {"failed", "paused"}:
        status = str(pipe_state)
    if fulfill.get("status") == "failed":
        status = "failed"
    return SlateResult(
        status=status,
        slate_id=slate.slate_id,
        line_id=rec.id,
        product=rec.product,
        production_order=order,
        data=data,
    )


async def execute_lot_task(task: dict[str, Any], pool: Any = None) -> dict[str, Any]:
    """TaskService adapter:config_json.line_id + slots → 跑产线工单。"""
    del pool
    cfg = task.get("config_json") or {}
    options = cfg.get("options") or cfg
    line_id = str(options.get("line_id") or cfg.get("line_id") or "")
    slots = dict(options.get("slots") or {})
    if "topic" not in slots and task.get("topic"):
        slots["topic"] = task["topic"]
    slate = Slate(line_id=line_id, slots=slots, slate_id=str(task.get("id") or ""))
    result = await run_slate(slate)
    video = ""
    if isinstance(result.data.get("edit_plan"), dict):
        video = str(result.data["edit_plan"].get("preview_path") or "")
    ok = result.status in {"scheduled", "planned", "dispatched"}
    return {
        "status": "completed" if ok else "failed",
        "error": result.reason or None,
        "result_video_path": video or None,
        "production_order": result.production_order,
        "slate": result.to_dict(),
    }


def write_order(order: dict[str, Any], dest: Path) -> Path:
    import json

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest
