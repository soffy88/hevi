"""消费 production_order:配方阶段继续跑产品工具,不是停在交接单。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.studio.kit import explainer_cues_from_text, storygraph_extract, tongjian_l0

TARGETS = ("explainer", "tongjian", "shortdrama")


def _texts_from_order(order: dict[str, Any]) -> list[str]:
    lines = order.get("script_lines") or []
    texts: list[str] = []
    for item in lines:
        if isinstance(item, str) and item.strip():
            texts.append(item.strip())
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("line") or "").strip()
            if text:
                texts.append(text)
    topic = str(order.get("topic") or "").strip()
    if not texts and topic:
        texts = [topic]
    return texts


def _write_job(dest: Path, body: dict[str, Any]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


async def fulfill_explainer(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    cues = await explainer_cues_from_text({"texts": _texts_from_order(order)})
    job = {
        "target": "explainer",
        "topic": order.get("topic"),
        "cues": cues.get("cues") or [],
        "render_runtime": order.get("render_runtime"),
        "bound_assets": order.get("bound_assets") or [],
        "timeline_id": order.get("timeline_id"),
        "compose_after_qc": True,
        "next": "hevi.explainer.service.ExplainerMasterService.assemble",
    }
    path = _write_job(output_dir / "explainer.dispatch.json", job)
    return {
        "status": "dispatched",
        "target": "explainer",
        "dispatch_path": str(path),
        "cue_count": len(job["cues"]),
        "next": job["next"],
    }


async def fulfill_tongjian(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    raw = str(order.get("topic") or order.get("source_text") or "")
    ir = await tongjian_l0(
        {
            "raw_text": raw,
            "source_name": order.get("source_name") or "studio",
        }
    )
    job = {
        "target": "tongjian",
        "topic": order.get("topic"),
        "chapter_ir": ir.get("chapter_ir") or {},
        "mix": order.get("mix"),
        "compose_after_qc": True,
        "defer_avatar": True,
        "next": "hevi.tongjian.script.build_script",
    }
    path = _write_job(output_dir / "tongjian.dispatch.json", job)
    return {
        "status": "dispatched" if ir.get("status") != "failed" else "failed",
        "target": "tongjian",
        "dispatch_path": str(path),
        "quote_count": ir.get("quote_count") or 0,
        "reason": ir.get("reason") or "",
        "next": job["next"],
    }


async def fulfill_shortdrama(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    raw = str(order.get("manuscript") or order.get("topic") or "")
    extracted = await storygraph_extract(
        {"raw_text": raw, "source_name": order.get("source_name") or "studio"}
    )
    job = {
        "target": "shortdrama",
        "story_graph": extracted.get("story_graph") or {},
        "bound_assets": order.get("bound_assets") or [],
        "compose_after_qc": True,
        "next": "hevi.season_planner.planner.build_season_plan",
    }
    path = _write_job(output_dir / "shortdrama.dispatch.json", job)
    return {
        "status": "dispatched" if extracted.get("status") != "failed" else "failed",
        "target": "shortdrama",
        "dispatch_path": str(path),
        "characters": extracted.get("characters") or 0,
        "events": extracted.get("events") or 0,
        "reason": extracted.get("reason") or "",
        "next": job["next"],
    }


_ADAPTERS = {
    "explainer": fulfill_explainer,
    "tongjian": fulfill_tongjian,
    "shortdrama": fulfill_shortdrama,
}


async def fulfill_order(
    order: dict[str, Any],
    *,
    execute: bool = False,
    output_dir: Path | str | None = None,
    adapters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """execute=False 只签发;True 则按 target 跑产品适配器(L0/cues/故事图)。"""
    target = str(order.get("target") or "none")
    if target == "none":
        return {"status": "planned", "target": target}
    if not execute:
        return {"status": "issued", "target": target, "order": order}
    dest = Path(output_dir or f"output/studio/{order.get('slate_id') or 'order'}")
    table = adapters or _ADAPTERS
    fn = table.get(target)
    if fn is None:
        return {"status": "failed", "target": target, "reason": f"no adapter: {target}"}
    return await fn(order, dest)
