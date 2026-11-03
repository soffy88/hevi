"""AI-disclosure dual-track gate (``qa.ai_disclosure_dual_track_gate``).

Clean-room restatement of the two-track disclosure discipline
described in the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): the picture itself
carries no burned-in watermark, subtitle, or text, while the
accompanying copy outside the picture states in fixed wording
that the picture is AI-generated and not real footage. The two
tracks are judged separately: a correct caption never excuses
a burned-in mark, and a clean picture never excuses a missing
caption.

This module judges plans only. It never renders, never
publishes, and never touches a budget.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_BURNIN_KINDS = ("watermark", "subtitle", "text", "caption", "logo")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.ai_disclosure_dual_track_gate: {detail}"}
    issue.update(extra)
    return issue


def _states_ai_generated(text: str) -> bool:
    lowered = text.lower()
    has_ai = "ai" in lowered or "人工智能" in text
    has_generated = (
        "generated" in lowered or "生成" in text or "合成" in text
    )
    return has_ai and has_generated


def _claims_real_footage(text: str) -> bool:
    lowered = text.lower()
    # Negated denials ("not real footage", "并非实拍") are the required
    # disclosure wording, not a claim of real footage: strip them first.
    cleaned = lowered
    for negation in ("not real footage", "not real-footage"):
        cleaned = cleaned.replace(negation, "")
    cleaned_text = text
    for negation in ("并非实拍", "不是实拍", "非实拍"):
        cleaned_text = cleaned_text.replace(negation, "")
    return (
        "real footage" in cleaned
        or "not ai" in cleaned
        or "非ai" in cleaned_text
        or "实拍" in cleaned_text
    )


def check_ai_disclosure(plan: Any) -> dict[str, Any]:
    """Judge one plan's AI disclosure on the two-track discipline.

    ``plan`` carries ``on_screen_burnins`` (a list of burned-in
    elements, each with ``kind``) and ``external_disclosure``
    (the accompanying copy text). Verdict ``pass`` means no
    burned-in watermark, subtitle, text, caption, or logo is
    declared, and the external copy is present, states that the
    picture is AI-generated, and never claims real footage.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("disclosure plan must be an object")
    issues: list[dict[str, Any]] = []
    burnins = plan.get("on_screen_burnins", [])
    if not isinstance(burnins, list):
        raise CapabilityError("on_screen_burnins must be a list when present")
    for index, element in enumerate(burnins):
        if not isinstance(element, dict):
            issues.append(
                _issue("burnin_not_object", f"burn-in element {index} is not an object")
            )
            continue
        kind = element.get("kind")
        if kind in _BURNIN_KINDS:
            issues.append(
                _issue(
                    "on_screen_burnin_present",
                    f"burned-in {kind} is declared on screen; the picture "
                    "track must carry no watermark, subtitle, or text",
                    kind=kind,
                )
            )
    disclosure = plan.get("external_disclosure")
    if not isinstance(disclosure, str) or not disclosure.strip():
        issues.append(
            _issue(
                "external_disclosure_missing",
                "external copy stating the picture is AI-generated is required",
            )
        )
    else:
        if not _states_ai_generated(disclosure):
            issues.append(
                _issue(
                    "disclosure_does_not_state_ai_generated",
                    "external copy must state the picture is AI-generated",
                )
            )
        if _claims_real_footage(disclosure):
            issues.append(
                _issue(
                    "disclosure_claims_real_footage",
                    "external copy must never claim real footage",
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "burnin_count": len(burnins),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_ai_disclosure(params.get("plan"))
    report_path = out_dir / "ai_disclosure.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_ai_disclosure_dual_track_gate_capabilities_once() -> list[str]:
    """Register ``qa.ai_disclosure_dual_track_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.ai_disclosure_dual_track_gate",
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
            description=(
                "AI-disclosure dual-track gate: the picture carries no "
                "burned-in mark while the external copy states the "
                "picture is AI-generated and never claims real footage."
            ),
        )
    )
    return ["qa.ai_disclosure_dual_track_gate"]


__all__ = [
    "check_ai_disclosure",
    "register_ai_disclosure_dual_track_gate_capabilities_once",
]
