"""Dynastic Chinese costume gate (``qa.pose_dynasty_costume_gate``).

Shisei dynastic costume discipline: 57 sets over 227 views,
from Shang through Qing, in the ai-pose-gallery-zh costume
library. The gate judges dynastic costume declarations
only; it never downloads, copies, or generates an image.
This is the direct feed for the history-film line: a
Wang Yangming (Ming dynasty) figure must wear Ming
costume, so a declaration that names the Wang Yangming
history line with any other dynasty fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

DYNASTIES: tuple[str, ...] = (
    "商",
    "周",
    "秦",
    "汉",
    "魏晋",
    "隋",
    "唐",
    "宋",
    "元",
    "明",
    "清",
)
SETS = 57
VIEWS = 227


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_pose_dynasty_costume(item: Any) -> dict[str, Any]:
    """Validate one dynastic costume declaration.

    Verdicts are ``pass`` / ``fail`` only. A declaration fails
    when the dynasty is outside Shang-through-Qing, the set id
    is missing, the source is not Shisei when one is named, a
    Wang Yangming history-line declaration names a dynasty
    other than Ming, or a stated set/view count disagrees with
    the verified 57 sets / 227 views.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(item, dict):
        return fail("item_not_object", "dynastic costume declaration must be a JSON object")
    dynasty = item.get("dynasty")
    if dynasty not in DYNASTIES:
        return fail(
            "unknown_dynasty",
            f"dynasty must be one of {list(DYNASTIES)} (Shang through Qing), got {dynasty!r}",
        )
    set_id = item.get("set_id")
    if not isinstance(set_id, str) or not set_id.strip():
        return fail(
            "set_id_missing",
            "dynastic costume declaration must carry a non-empty set_id",
        )
    if item.get("source") is not None and item.get("source") != "shisei":
        return fail(
            "source_not_shisei",
            f"dynastic costumes come from the Shisei collection; got source {item.get('source')!r}",
        )
    views = item.get("views")
    if views is not None and (
        not isinstance(views, list)
        or not views
        or any(not isinstance(v, str) or not v.strip() for v in views)
    ):
        return fail(
            "views_invalid",
            "views must be a non-empty list of view names when given",
        )
    if item.get("history_line") == "wangyangming" and dynasty != "明":
        return fail(
            "wangyangming_dynasty_mismatch",
            "the Wang Yangming history line is Ming dynasty; a "
            f"{dynasty!r} costume does not belong to it",
        )
    counts = item.get("counts")
    if counts is not None:
        if not isinstance(counts, dict):
            return fail("counts_invalid", "dynastic counts must be an object")
        if "sets" in counts and (not _is_number(counts["sets"]) or int(counts["sets"]) != SETS):
            return fail(
                "sets_mismatch",
                f"the Shisei collection holds {SETS} sets, got {counts['sets']!r}",
            )
        if "views" in counts and (not _is_number(counts["views"]) or int(counts["views"]) != VIEWS):
            return fail(
                "views_mismatch",
                f"the Shisei collection holds {VIEWS} views, got {counts['views']!r}",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "dynasty": dynasty,
        "set_id": set_id,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_pose_dynasty_costume(params.get("costume"))
    report_path = out_dir / "pose_dynasty_costume_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_dynasty_costume_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_dynasty_costume_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "costume": {"type": "object"},
                },
                "required": ["costume"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pose-gallery dynastic costume gate: 57 Shisei sets "
                "over 227 views, Shang through Qing closed "
                "vocabulary, Wang Yangming history line requires "
                "Ming dynasty costume."
            ),
        )
    )
    return ["qa.pose_dynasty_costume_gate"]


__all__ = [
    "DYNASTIES",
    "SETS",
    "VIEWS",
    "check_pose_dynasty_costume",
    "register_pose_dynasty_costume_gate_capabilities_once",
]
