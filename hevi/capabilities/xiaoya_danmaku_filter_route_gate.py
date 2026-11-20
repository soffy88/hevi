"""Xiaoya danmaku filter and route gate (``qa.xiaoya_danmaku_filter_route_gate``).

The branch under review filters every incoming danmaku line
before routing it: five blocked categories, an allowlist of
phrases that must never be filtered (wardrobe words such as
change-clothes terms, so a request to change outfit is not
mistaken for a blocked line), a maximum line length of 40
characters, and a 60-second dedupe window. Routing then sends
each surviving line to exactly one of four destinations:
chat, wardrobe, action, or restore. A false-positive check
exists so a blocked verdict can be appealed against the
original text.

Clean-room restatement of the method found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``). This gate judges
the shape of a filter-and-route declaration only; it never
reads a live danmaku feed and never connects to any platform.
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

# The five blocked categories, as measured in the branch's
# moderation table (51 / 23 / 7 / 13 / 9 terms each).
FILTER_CATEGORIES: frozenset[str] = frozenset(
    {"低俗擦边", "引流广告", "敏感话题", "辱骂", "收益承诺"}
)

# The four routing destinations.
ROUTES: frozenset[str] = frozenset({"chat", "wardrobe", "action", "restore"})

# Measured caps from the branch's moderation table.
MEASURED_MAX_LENGTH = 40
MEASURED_DEDUPE_SECONDS = 60


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_xiaoya_danmaku_filter_route(plan: Any) -> dict[str, Any]:
    """Validate a danmaku filter-and-route declaration.

    Verdicts are ``pass`` / ``fail`` only. The plan fails when
    it is not an object, when any of the five filter
    categories is missing, when the allowlist is empty, when
    no maximum length is declared or it exceeds the measured
    40 characters, when no dedupe window is declared, when
    any of the four routes is missing, or when no
    false-positive check is declared.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail("plan_not_object", "plan must be a JSON object")
    categories = plan.get("filter_categories")
    if not isinstance(categories, list) or not set(categories) >= FILTER_CATEGORIES:
        missing = sorted(FILTER_CATEGORIES - set(categories or []))
        return fail(
            "filter_category_missing",
            f"all five filter categories are required; missing {missing}",
        )
    allow_phrases = plan.get("allow_phrases")
    if (
        not isinstance(allow_phrases, list)
        or not allow_phrases
        or any(not isinstance(p, str) or not p for p in allow_phrases)
    ):
        return fail(
            "allowlist_missing",
            "a non-empty allowlist is required so wardrobe words "
            "are never filtered as blocked lines",
        )
    max_length = plan.get("max_length")
    if not _is_int(max_length) or max_length <= 0:
        return fail(
            "max_length_missing",
            "a maximum danmaku length in characters must be declared",
        )
    if max_length > MEASURED_MAX_LENGTH:
        return fail(
            "max_length_exceeds_measured",
            "the only measured cap is 40 characters; longer lines were never measured",
        )
    dedupe_seconds = plan.get("dedupe_seconds")
    if not _is_int(dedupe_seconds) or dedupe_seconds < 0:
        return fail(
            "dedupe_missing",
            "a dedupe window in seconds must be declared (measured 60)",
        )
    routes = plan.get("routes")
    if not isinstance(routes, list) or not set(routes) >= ROUTES:
        missing = sorted(ROUTES - set(routes or []))
        return fail(
            "route_missing",
            f"all four routes are required (chat, wardrobe, action, restore); missing {missing}",
        )
    if plan.get("false_positive_check") is not True:
        return fail(
            "false_positive_check_missing",
            "a false-positive check against the original text must be declared",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_xiaoya_danmaku_filter_route(params.get("plan"))
    report_path = out_dir / "xiaoya_danmaku_filter_route_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_xiaoya_danmaku_filter_route_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.xiaoya_danmaku_filter_route_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "xiaoya danmaku filter and route gate: five blocked "
                "categories, non-empty allowlist, max length 40, "
                "dedupe window, four routes, false-positive check."
            ),
        )
    )
    return ["qa.xiaoya_danmaku_filter_route_gate"]


__all__ = [
    "FILTER_CATEGORIES",
    "MEASURED_DEDUPE_SECONDS",
    "MEASURED_MAX_LENGTH",
    "ROUTES",
    "check_xiaoya_danmaku_filter_route",
    "register_xiaoya_danmaku_filter_route_gate_capabilities_once",
]
