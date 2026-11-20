"""MiniMax H3 community license compliance gate (``qa.freevideo_h3_community_license_gate``).

The H3 weights are not open source: they ship under the
MiniMax H3 Community License. In the reviewer's own words,
a use fails when it runs in a barred region (the European
Union, the United Kingdom, South Korea, or the United
States), when a commercial product over 20 million US
dollars of annual revenue runs without MiniMax's prior
written authorization, when a commercial product neither
displays ``MiniMax H3`` prominently in its UI nor attaches
the license copy, when H3 output is used to improve any
other AI model, when a person is impersonated without
consent, when a minor is harmed, or when a public release
does not clearly disclose that the content is machine
generated. This gate judges use declarations only; it is
not legal advice.

Clean-room restatement of the FlashML-org/FreeVideo license
position (see ``FREEVIDEO_ATTRIBUTION.md``); no upstream
code appears here.
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

BARRED_REGIONS: frozenset[str] = frozenset({"EU", "GB", "KR", "US"})
REVENUE_AUTHORIZATION_THRESHOLD_USD = 20_000_000


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_freevideo_h3_license(use: Any) -> dict[str, Any]:
    """Validate a MiniMax H3 Community License use declaration.

    Verdicts are ``pass`` / ``fail`` only. A use fails when
    a required field is missing, when any region is barred,
    when H3 output is used to improve another model, when a
    person is impersonated without consent, when a minor is
    harmed, when a commercial product over the revenue
    threshold runs without written authorization, when a
    commercial product neither displays ``MiniMax H3`` nor
    attaches the license copy, or when a public release does
    not disclose machine generation.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(use, dict):
        return fail("use_not_object", "license use must be a JSON object")
    for field in (
        "regions",
        "commercial",
        "ui_displays_minimax_h3",
        "license_copy_attached",
        "improves_other_models_with_output",
        "impersonation_without_consent",
        "minors_harmed",
    ):
        if field not in use:
            return fail("use_field_missing", f"license use must carry {field!r}")
    regions = use["regions"]
    if not isinstance(regions, list) or not regions:
        return fail("regions_invalid", "regions must be a non-empty list")
    barred = sorted(set(regions) & BARRED_REGIONS)
    if barred:
        return fail(
            "region_barred",
            "the H3 Community License bars use in " + ", ".join(barred),
        )
    if use["improves_other_models_with_output"] is True:
        return fail(
            "output_improvement_banned",
            "H3 output must never be used to improve any other AI model",
        )
    if use["impersonation_without_consent"] is True:
        return fail(
            "impersonation_without_consent",
            "impersonating a person without consent is banned by the H3 acceptable use policy",
        )
    if use["minors_harmed"] is True:
        return fail(
            "minors_harmed",
            "harming minors is banned by the H3 acceptable use policy",
        )
    if use["commercial"] is True:
        revenue = use.get("annual_revenue_usd")
        if (
            isinstance(revenue, (int, float))
            and not isinstance(revenue, bool)
            and revenue > REVENUE_AUTHORIZATION_THRESHOLD_USD
            and use.get("written_authorization") is not True
        ):
            return fail(
                "written_authorization_required",
                "a commercial product over 20 million US dollars of "
                "annual revenue needs MiniMax's prior written authorization",
            )
        if use["ui_displays_minimax_h3"] is not True:
            return fail(
                "ui_display_missing",
                "a commercial product must display MiniMax H3 prominently in its UI",
            )
        if use["license_copy_attached"] is not True:
            return fail(
                "license_copy_missing",
                "distribution must attach a copy of the H3 Community License",
            )
    if (
        use.get("public_release") is True
        and use.get("public_release_discloses_ai_generated") is not True
    ):
        return fail(
            "ai_disclosure_missing",
            "a public release must clearly disclose that the content is machine generated",
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
    report = check_freevideo_h3_license(params.get("use"))
    report_path = out_dir / "freevideo_h3_community_license_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_h3_community_license_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_h3_community_license_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "use": {"type": "object"},
                },
                "required": ["use"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "FreeVideo H3 Community License gate: barred regions "
                "refused, revenue over 20M USD needs written "
                "authorization, commercial UI displays MiniMax H3 "
                "and attaches the license, no output-to-model "
                "improvement, no non-consensual impersonation, no "
                "harm to minors, public releases disclose AI generation."
            ),
        )
    )
    return ["qa.freevideo_h3_community_license_gate"]


__all__ = [
    "BARRED_REGIONS",
    "REVENUE_AUTHORIZATION_THRESHOLD_USD",
    "check_freevideo_h3_license",
    "register_freevideo_h3_community_license_gate_capabilities_once",
]
