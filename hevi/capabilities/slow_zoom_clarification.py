"""Slow-zoom clarification record (``qa.slow_zoom_clarification``).

Standing clarification, recorded in code so it cannot be
re-litigated by a later reader: ``slow_zoom_in`` and
``slow_zoom_out`` are LEGAL ids in hevi's own camera movement
vocabulary (``cinematic_data/camera_movements.json``, shared by
``shot.camera_movements`` and ``story.prompt_compiler``). The
wording that bans slow zooms comes from the H3 benchmark prompt
(the benchmark text itself forbids them); it is a benchmark
constraint, not a hevi vocabulary ban. No hevi banned-list,
validator, or gate may treat these two ids as forbidden: adding
either id to a banned list fails this check.

This module judges the record only and renders nothing. See
CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.cinematic_techniques import load_movements
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

SLOW_ZOOM_IDS: frozenset[str] = frozenset({"slow_zoom_in", "slow_zoom_out"})

CLARIFICATION = (
    "slow_zoom_in and slow_zoom_out are legal ids in hevi's camera "
    "movement vocabulary. The slow-zoom ban wording comes from the "
    "H3 benchmark prompt, not from hevi's vocabulary; never add "
    "these ids to a hevi banned list."
)


def slow_zoom_clarification_text() -> str:
    """Return the standing clarification text."""
    return CLARIFICATION


def check_slow_zoom_status(
    banned_ids: list[str] | None = None,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check the clarification against a vocabulary and a banned list.

    Returns a report; never raises. Fails when either slow-zoom id
    is absent from the vocabulary, or when either id appears in the
    supplied banned list.
    """
    issues: list[dict[str, Any]] = []
    rows = entries if entries is not None else load_movements()
    present = {str(r.get("id", "")) for r in rows if isinstance(r, dict)}
    status: dict[str, str] = {}
    for movement_id in sorted(SLOW_ZOOM_IDS):
        if movement_id not in present:
            status[movement_id] = "missing_from_vocabulary"
            issues.append(
                {
                    "code": f"slow_zoom_id_missing:{movement_id}",
                    "detail": f"{movement_id!r} is absent from the vocabulary",
                }
            )
        else:
            status[movement_id] = "legal_hevi_id"
    banned = set(banned_ids or [])
    for movement_id in sorted(SLOW_ZOOM_IDS & banned):
        status[movement_id] = "wrongly_banned"
        issues.append(
            {
                "code": f"slow_zoom_wrongly_banned:{movement_id}",
                "detail": (
                    f"{movement_id!r} is a legal hevi vocabulary id; "
                    "the slow-zoom ban belongs to the H3 benchmark "
                    "prompt, not to hevi's vocabulary"
                ),
            }
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "clarification": CLARIFICATION,
        "status": status,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    banned = params.get("banned_ids")
    report = check_slow_zoom_status(
        list(banned) if isinstance(banned, list) else None
    )
    report_path = out_dir / "slow_zoom_clarification.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_slow_zoom_clarification_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.slow_zoom_clarification",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "banned_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Slow-zoom clarification record: slow_zoom_in and "
                "slow_zoom_out are legal hevi vocabulary ids; the "
                "ban wording comes from the H3 benchmark prompt. "
                "Either id missing from the vocabulary, or present "
                "in a supplied banned list, fails."
            ),
        )
    )
    return ["qa.slow_zoom_clarification"]


__all__ = [
    "SLOW_ZOOM_IDS",
    "CLARIFICATION",
    "slow_zoom_clarification_text",
    "check_slow_zoom_status",
    "register_slow_zoom_clarification_capabilities_once",
]
