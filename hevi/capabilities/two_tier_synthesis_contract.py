"""Two-tier synthesis contract (``video.two_tier_synthesis_contract``).

Clean-room rewrite of a *contract* only: a knowledge film is
synthesised in one of two code-composition tiers. The base tier
renders every shot as code. The enhanced tier replaces at most
three shots the code tier cannot do well, each with a recorded
reason, and the rest stays code. The tier switch is a code
composition mode — it is not a generation tier, not a frame grid,
and not a model档位 — and any plan that describes it as one is
refused. No text, code, or asset from any outside repository is
copied here. See VIBE_KNOWLEDGE_ATTRIBUTION.md.

This contract performs no rendering and contacts no generation
service: every plan must declare ``executed_here: false``.
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

MAX_ENHANCED_SHOTS = 3


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_synthesis_contract(plan: Any) -> dict[str, Any]:
    """Validate one two-tier synthesis contract. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "synthesis plan must be a JSON object")
            ],
            "synthesis_mode": "code_composition",
            "enhanced_shot_count": 0,
        }
    if plan.get("executed_here") is not False:
        issues.append(
            _issue(
                "executed_here_claimed",
                "this contract never synthesises anything; executed_here "
                "must be false",
            )
        )
    if plan.get("synthesis_mode") not in (None, "code_composition"):
        issues.append(
            _issue(
                "synthesis_mode_wrong",
                "synthesis_mode must be code_composition: the tier "
                "switch is a code composition mode, not a generation "
                "tier",
            )
        )
    for field in ("h3_tier", "generation_tier", "frame_grid", "model_tier"):
        if field in plan:
            issues.append(
                _issue(
                    "generation_tier_confusion",
                    f"field {field!r} confuses the code composition mode "
                    "with a generation tier or frame grid and must not "
                    "appear in this contract",
                )
            )
    mode = plan.get("mode")
    if mode not in ("base", "enhanced"):
        issues.append(
            _issue(
                "mode_unknown",
                "mode must be one of base, enhanced",
            )
        )
        mode = None
    enhanced = plan.get("enhanced_shots", [])
    if not isinstance(enhanced, list):
        issues.append(
            _issue(
                "enhanced_shots_invalid",
                "enhanced_shots must be a list",
            )
        )
        enhanced = []
    if mode == "base" and enhanced:
        issues.append(
            _issue(
                "base_with_enhanced_shots",
                "the base tier renders every shot as code; it must "
                "declare no enhanced shots",
            )
        )
    if mode == "enhanced":
        if not enhanced:
            issues.append(
                _issue(
                    "enhanced_without_shots",
                    "the enhanced tier must name at least one enhanced shot",
                )
            )
        if len(enhanced) > MAX_ENHANCED_SHOTS:
            issues.append(
                _issue(
                    "enhanced_too_many",
                    f"the enhanced tier replaces at most "
                    f"{MAX_ENHANCED_SHOTS} shots, got {len(enhanced)}",
                )
            )
        for index, shot in enumerate(enhanced):
            if not isinstance(shot, dict):
                issues.append(
                    _issue(
                        f"enhanced_shots[{index}]:not_object",
                        "each enhanced shot must be an object",
                    )
                )
                continue
            if not _is_nonempty_str(shot.get("shot_id")):
                issues.append(
                    _issue(
                        f"enhanced_shots[{index}]:shot_id_missing",
                        "each enhanced shot must name a shot_id",
                    )
                )
            if not _is_nonempty_str(shot.get("reason")):
                issues.append(
                    _issue(
                        f"enhanced_shots[{index}]:reason_missing",
                        "each enhanced shot must record why the code "
                        "tier cannot do it well",
                    )
                )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "synthesis_mode": "code_composition",
        "mode": mode,
        "enhanced_shot_count": len(enhanced),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_synthesis_contract(params.get("plan"))
    report_path = out_dir / "two_tier_synthesis.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_two_tier_synthesis_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.two_tier_synthesis_contract",
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
                "Two-tier synthesis contract: base tier renders every "
                "shot as code; enhanced tier replaces at most three "
                "shots with recorded reasons. The switch is a code "
                "composition mode, never a generation tier."
            ),
        )
    )
    return ["video.two_tier_synthesis_contract"]


__all__ = [
    "check_synthesis_contract",
    "register_two_tier_synthesis_contract_capabilities_once",
]
