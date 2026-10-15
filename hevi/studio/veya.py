"""Veya → Hevi 成品合同。

Veya 只调能力、收成品:选产线、填槽、拿 job。不在 Veya 侧重写一条管线。
`produce` 默认只签发工单(不烧 GPU);`execute=True` 才走 HyperFrames/Manim 回退出片。
"""

from __future__ import annotations

import os
import uuid
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.studio.recipes import get_recipe, list_recipes
from hevi.studio.runtime import select_runtime
from hevi.studio.slate import Slate, run_slate
from hevi.studio.tools import list_tools

_JOBS: dict[str, ProduceJob] = {}


@dataclass
class ProduceJob:
    job_id: str
    line_id: str
    status: str
    render_runtime: str
    product: str = ""
    artifact: str = ""
    production_order: dict[str, Any] = field(default_factory=dict)
    fulfill: dict[str, Any] = field(default_factory=dict)
    slate: dict[str, Any] = field(default_factory=dict)
    pack: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "line_id": self.line_id,
            "product": self.product,
            "status": self.status,
            "render_runtime": self.render_runtime,
            "artifact": self.artifact,
            "production_order": self.production_order,
            "fulfill": self.fulfill,
            "slate": self.slate,
            "pack": self.pack,
            "reason": self.reason,
        }


def reset_veya() -> None:
    _JOBS.clear()


def _fallback_fulfill(fb: dict[str, Any], line_id: str, artifact: str, product: str) -> tuple[dict[str, Any], str]:
    """Build fulfill data from the *measured* fallback record (never hardcoded)."""
    rec = fb.get("record") or {}
    qa = rec.get("qa") or {}
    verified = bool(artifact and Path(artifact).is_file() and qa.get("pass"))
    if not product:
        recipe = get_recipe(line_id)
        product = recipe.product if recipe else line_id
    return {
        "artifact_verification": {
            "verified": verified,
            "sha256": qa.get("sha256"),
            "duration": qa.get("duration"),
            "resolution": qa.get("resolution"),
        },
        "quality": qa,
        "provenance": {"fallback_used": True, "line": rec.get("provenance")},
    }, product


def list_capabilities() -> dict[str, Any]:
    lines = [
        {
            "id": r.id,
            "product": r.product,
            "handoff": r.handoff,
            "render_runtime": r.render_runtime,
            "slots": [s.model_dump() for s in r.slots],
        }
        for r in list_recipes()
    ]
    return {
        "lines": lines,
        "tools": [t.tool_id for t in list_tools()],
        "runtimes": ["remotion", "hyperframes", "manim", "ffmpeg"],
        "daily_lines": ["explainer", "history_scene"],
    }


def get_job(job_id: str) -> ProduceJob | None:
    return _JOBS.get(job_id)


def list_jobs() -> list[ProduceJob]:
    return list(_JOBS.values())


def _zero_engine_requested(line_id: str, slots: dict[str, Any]) -> bool:
    """The zero-cost engine was explicitly chosen (slot ``engine`` or HEVI_LINE_ENGINE)."""
    from hevi.layer4_legacy.zerolines.oprim_impl.specs import resolve_engine

    try:
        return resolve_engine(line_id=line_id, slot_engine=slots.get("engine"), env_engine=os.getenv("HEVI_LINE_ENGINE")) == "zero"
    except ValueError:
        return False  # unknown engine: the Studio renderer reports it as blocked


def _auto_mode(line_id: str, requested_mode: str, slots: dict[str, Any]) -> str:
    """``auto`` -> low_cost for its two recipes, unless the zero engine was chosen
    (zero is a separate CPU engine routed by Studio fulfil, not the low_cost path)."""
    if requested_mode == "auto" and line_id in {"emotional_reading", "history_scene"} and not _zero_engine_requested(line_id, slots):
        return "low_cost"
    return requested_mode


async def produce(
    *,
    line_id: str,
    slots: dict[str, Any] | None = None,
    render_runtime: str | None = None,
    execute: bool = False,
    platforms: list[str] | None = None,
    output_dir: str | Path | None = None,
    production_mode: str | None = None,
) -> ProduceJob:
    filled = dict(slots or {})
    from hevi.production.low_cost import policy_for

    requested_mode = production_mode or filled.get("production_mode") or "auto"
    # ``auto`` defaults compatible, CPU-first behavior for the two currently
    # supported low-cost recipes. Existing canonical lines retain their
    # established standard renderer until their low-cost strategy is declared.
    mode = _auto_mode(line_id, str(requested_mode), filled)
    if mode == "auto":
        mode = "production"
    policy = policy_for(str(mode))
    if policy.mode == "low_cost":
        # Low-cost is an explicit strategy.  It must never silently fall back
        # to the standard GPU/provider renderer when its own prerequisites are
        # unavailable.
        supported = {"emotional_reading", "history_scene"}
        job_id = str(uuid.uuid4())
        dest_root = Path(output_dir or "output/veya")
        if line_id not in supported:
            job = ProduceJob(
                job_id=job_id,
                line_id=line_id,
                status="blocked",
                render_runtime="ffmpeg",
                production_order={"target": line_id, "requested_mode": requested_mode, "production_mode": "low_cost", "policy": policy.__dict__},
                reason="LOW_COST_RECIPE_NOT_SUPPORTED",
            )
            _JOBS[job.job_id] = job
            return job
        if not execute:
            job = ProduceJob(
                job_id=job_id,
                line_id=line_id,
                status="planned",
                render_runtime="ffmpeg",
                production_order={"target": line_id, "requested_mode": requested_mode, "production_mode": "low_cost", "policy": policy.__dict__},
                reason="LOW_COST_REQUIRES_EXECUTE_TRUE",
            )
            _JOBS[job.job_id] = job
            return job
        from hevi.production.low_cost import LowCostBlocked, execute_low_cost

        filled["production_mode"] = "low_cost"
        try:
            result = await execute_low_cost(line_id=line_id, slots=filled, output_dir=dest_root / job_id)
        except LowCostBlocked as exc:
            if execute:
                from hevi.layer4_legacy.omlines.omodul_impl.fallback import omlines_fallback_workflow
                filled["line_id"] = line_id
                fb = await asyncio.to_thread(omlines_fallback_workflow, {}, filled, dest_root / job_id)
                if fb.get("status") == "succeeded":
                    artifact = str(fb.get("result_video_path") or "")
                    fulfill, product = _fallback_fulfill(fb, line_id, artifact, "")
                    job = ProduceJob(
                        job_id=job_id,
                        line_id=line_id,
                        status="ready" if artifact else "failed",
                        render_runtime="omlines_free_tier",
                        product=product,
                        artifact=artifact,
                        production_order={"fallback": "omlines_free_tier"},
                        fulfill=fulfill,
                        slate={"status": "completed"},
                        reason=fb.get("reason", "")
                    )
                    _JOBS[job.job_id] = job
                    return job
            result = {
                "status": "blocked",
                "line_id": line_id,
                "result_video_path": None,
                "artifact_manifest": {},
                "reason": str(exc),
                "policy": policy.__dict__,
            }
        artifact = str(result.get("result_video_path") or "")
        job = ProduceJob(
            job_id=job_id,
            line_id=line_id,
            status="ready" if result.get("status") == "completed" and artifact else result.get("status", "blocked"),
            render_runtime="ffmpeg",
            product="情绪读书视频" if line_id == "emotional_reading" else "历史场景",
            artifact=artifact,
            production_order={"target": line_id, "requested_mode": requested_mode, "production_mode": "low_cost", "policy": policy.__dict__},
            fulfill=result,
            slate={"slate_id": job_id, "line_id": line_id, "status": result.get("status", "blocked"), "production_mode": "low_cost"},
            reason=str(result.get("reason") or ""),
        )
        _JOBS[job.job_id] = job
        return job
    rec = get_recipe(line_id)
    if rec is None:
        job = ProduceJob(
            job_id=str(uuid.uuid4()),
            line_id=line_id,
            status="failed",
            render_runtime=render_runtime or "remotion",
            reason=f"unknown line: {line_id}",
        )
        _JOBS[job.job_id] = job
        return job
    picked = select_runtime(
        locked=render_runtime or rec.render_runtime,
        intent=str(filled.get("topic") or filled.get("source_name") or ""),
        line_id=rec.id,
    )
    runtime = str(picked["runtime"])
    filled.setdefault("render_runtime", runtime)
    dest_root = Path(output_dir or "output/veya")
    filled.setdefault("output_dir", str(dest_root))
    slate = await run_slate(Slate(line_id=rec.id, slots=filled, execute=execute))
    artifact = str(slate.data.get("result_video_path") or "")
    job = ProduceJob(
        job_id=slate.slate_id,
        line_id=rec.id,
        status="ready" if artifact and slate.status == "completed" else slate.status,
        render_runtime=runtime,
        product=rec.product,
        artifact=artifact,
        production_order=slate.production_order,
        fulfill=slate.data.get("fulfill") or {},
        slate=slate.to_dict(),
        reason=slate.reason,
    )
    if platforms:
        # 只做分平台打包(标题/封面/标签交接单);平台发布已迁至 Easel。
        from hevi.studio.packaging import pack_queue, write_pack_tickets

        queue = pack_queue(
            str(filled.get("topic") or rec.product),
            list(platforms),
            media_path=artifact or "",
        )
        write_pack_tickets(queue, dest_root / "pack")
        job.pack = [variant.to_dict() for variant in queue.variants]
    _JOBS[job.job_id] = job
    return job
