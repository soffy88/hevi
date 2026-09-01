"""Veya → Hevi 成品合同。

Veya 只调能力、收成品:选产线、填槽、拿 job。不在 Veya 侧重写一条管线。
`produce` 默认只签发工单(不烧 GPU);`execute=True` 才走 HyperFrames/Manim 回退出片。
"""

from __future__ import annotations

import uuid
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
    publish: list[dict[str, Any]] = field(default_factory=list)
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
            "publish": self.publish,
            "reason": self.reason,
        }


def reset_veya() -> None:
    _JOBS.clear()


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


async def produce(
    *,
    line_id: str,
    slots: dict[str, Any] | None = None,
    render_runtime: str | None = None,
    execute: bool = False,
    publish: bool = False,
    platforms: list[str] | None = None,
    output_dir: str | Path | None = None,
) -> ProduceJob:
    filled = dict(slots or {})
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
    if publish and (platforms or []):
        from hevi.studio.packaging import pack_queue, write_pack_tickets
        from hevi.studio.tools import invoke_tool

        media = artifact or ""
        queue = pack_queue(
            str(filled.get("topic") or rec.product),
            list(platforms or []),
            media_path=media,
        )
        write_pack_tickets(queue, dest_root / "pack")
        for variant in queue.variants:
            res = await invoke_tool(
                "publish.matrix",
                {
                    "platform": variant.platform,
                    "media_path": media or "pending",
                    "title": variant.title,
                    "description": variant.description,
                    "tags": variant.tags,
                    "account": variant.account,
                    "cover_hint": variant.cover_hint,
                },
            )
            job.publish.append(res.to_dict())
    _JOBS[job.job_id] = job
    return job
