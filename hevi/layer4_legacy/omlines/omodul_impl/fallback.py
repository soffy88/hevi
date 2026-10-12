"""Omlines free tier 3O wrappers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.omlines.omodul_impl.lines import LINES, MissingInput

_enabled_pillars = {"report", "cost", "decision_trail"}


def _result_path(rec: dict[str, Any]) -> str | None:
    final = rec.get("final")
    if final:
        return str(final)
    finals = rec.get("finals") or []
    return str(finals[0]) if finals else None


def omlines_fallback_workflow(config: dict[str, Any], input_data: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """Run the zero-cost line producer for ``input_data['line_id']``.

    The full ``input_data`` slot bag (topic / source / media_path / image_path /
    manuscript / source_text / transcript / ...) is forwarded to the line, which
    validates its own required inputs and raises ``MissingInput`` when one is
    absent.  No built-in sample is ever substituted for a missing input.
    """
    line = input_data.get("line_id")
    if not line or line not in LINES:
        return {"status": "failed", "reason": f"No omlines fallback for {line}"}

    slots = {k: v for k, v in input_data.items() if k != "line_id"}
    try:
        rec = LINES[line](slots=slots, output_dir=output_dir)
    except MissingInput as exc:
        return {"status": "failed", "reason": f"missing input: {exc}", "record": None}
    except Exception as exc:  # noqa: BLE001 - honest failure reporting
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}", "record": None}

    qa = rec.get("qa") or {}
    passed = bool(rec.get("pass")) if "pass" in rec else bool(qa.get("pass"))
    artifact = _result_path(rec)
    return {
        "status": "succeeded" if passed and artifact else "failed",
        "record": rec,
        "result_video_path": artifact,
        "reason": rec.get("notes") or "" if passed else "quality gate failed",
    }


async def omlines_fallback_workflow_async(config: dict[str, Any], input_data: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    return await asyncio.to_thread(omlines_fallback_workflow, config, input_data, output_dir)
