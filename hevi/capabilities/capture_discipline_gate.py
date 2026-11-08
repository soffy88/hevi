"""Capture discipline gate (``qa.capture_discipline_gate``).

Discipline gate only. Capturing a product page for film material
runs under hard discipline: the product must run locally, invented
but lifelike demonstration data must be seeded before capture, and
real customer data must never appear in a finished film. There is
no mechanism for pages behind a login or a paywall, so such pages
fail closed: no capture may be claimed for them. Capture is
automatic for screenshots only; the words are never extracted from
the page. Copy is written from the project brief and from words
the user supplies, so a claim of automatic copy extraction fails.
This gate judges the plan only and captures nothing. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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

# Admitted sources for film copy. Page extraction is not one of them.
COPY_SOURCES: tuple[str, ...] = ("project_brief", "user_supplied")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_capture_discipline(plan: Any) -> dict[str, Any]:
    """Validate a page-capture plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Capture requires a local
    run, declared seeding, and no real customer data; login and
    paywall pages fail closed; copy must come from the brief or
    from user-supplied words, never from page extraction.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "capture plan must be a JSON object")],
            "capture_allowed": False,
        }
    capture_claimed = plan.get("capture_claimed") is True
    if plan.get("runs_locally") is not True:
        issues.append(
            _issue(
                "not_local",
                "capture requires the product to run locally",
            )
        )
    if plan.get("seeding_declared") is not True:
        issues.append(
            _issue(
                "seeding_undeclared",
                "demonstration data seeding must be declared before capture",
            )
        )
    if plan.get("real_customer_data") is True:
        issues.append(
            _issue(
                "real_customer_data",
                "real customer data must never appear in a finished film",
            )
        )
    elif plan.get("real_customer_data") is not False:
        issues.append(
            _issue(
                "real_customer_data_undeclared",
                "plan must declare real_customer_data as true or false",
            )
        )
    copy_source = plan.get("copy_source")
    if copy_source not in COPY_SOURCES:
        issues.append(
            _issue(
                "copy_source_invalid",
                f"copy must come from {list(COPY_SOURCES)}; "
                "automatic extraction from the page is not admitted",
            )
        )
    auth_required = plan.get("auth_required")
    if auth_required is None:
        issues.append(
            _issue(
                "auth_requirement_undeclared",
                "plan must declare whether the page needs a login",
            )
        )
    elif auth_required is True:
        if plan.get("auth_handling") != "fail_closed":
            issues.append(
                _issue(
                    "auth_not_fail_closed",
                    "pages behind a login have no capture mechanism and must fail closed",
                )
            )
        if capture_claimed:
            issues.append(
                _issue(
                    "capture_behind_login",
                    "no capture may be claimed for a page behind a login",
                )
            )
    paywall = plan.get("paywall_present")
    if paywall is None:
        issues.append(
            _issue(
                "paywall_undeclared",
                "plan must declare whether a paywall stands in front of the content",
            )
        )
    elif paywall is True and capture_claimed:
        issues.append(
            _issue(
                "capture_behind_paywall",
                "no capture may be claimed for content behind a paywall",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "capture_allowed": not issues and capture_claimed,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_capture_discipline(params.get("plan"))
    report_path = out_dir / "capture_discipline.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_capture_discipline_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.capture_discipline_gate",
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
                "Capture discipline gate: local run, declared "
                "demonstration-data seeding, no real customer data, "
                "login and paywall pages fail closed, and copy comes "
                "from the brief or user-supplied words only."
            ),
        )
    )
    return ["qa.capture_discipline_gate"]


__all__ = [
    "COPY_SOURCES",
    "check_capture_discipline",
    "register_capture_discipline_gate_capabilities_once",
]
