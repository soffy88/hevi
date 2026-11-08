"""Review-signal vocabulary (``qa.review_signal_vocabulary``).

Clean-room restatement of the review-signal list described in
the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): fifteen closed
signal kinds a reviewer may raise against a take, each
labelled with how it is measured -- automatically by a
measurement, or manually by a human reviewer. Signals that
no measurement exists for must never be dressed up as
measured, and an automatic signal without a caller-declared
threshold is not a measurement at all: thresholds have no
defaults here.

This module judges vocabulary use only. It inspects no
frames, runs no measurement, and never touches a budget.
Nothing here executes a review; execution stays a separate
case.
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

# Closed vocabulary: kind -> (measurement method, plain-language meaning).
# Wording is a fresh restatement; no upstream text is copied.
SIGNALS: dict[str, dict[str, str]] = {
    "plastic_skin": {
        "method": "manual",
        "meaning": "skin looks unnaturally smooth or artificial",
    },
    "stiff_expression": {
        "method": "manual",
        "meaning": "facial expression looks frozen or unnatural",
    },
    "lighting_drift": {
        "method": "automatic",
        "meaning": "frame brightness drifts beyond the declared range",
    },
    "exposure_jump": {
        "method": "automatic",
        "meaning": "exposure changes abruptly between sampled frames",
    },
    "in_shot_jump": {
        "method": "automatic",
        "meaning": "content jumps within a single shot",
    },
    "seam_difference": {
        "method": "automatic",
        "meaning": "adjacent shots differ sharply at the seam",
    },
    "costume_jump": {
        "method": "manual",
        "meaning": "clothing changes between shots without cause",
    },
    "hairstyle_jump": {
        "method": "manual",
        "meaning": "hairstyle changes between shots without cause",
    },
    "identity_drift": {
        "method": "manual",
        "meaning": "the same person no longer reads as the same person",
    },
    "camera_jump_at_seam": {
        "method": "manual",
        "meaning": "camera position jumps at a cut without continuity",
    },
    "signage_garbled_text": {
        "method": "manual",
        "meaning": "signs or on-screen text are garbled or unreadable",
    },
    "prop_disappears": {
        "method": "manual",
        "meaning": "a tracked prop vanishes between shots",
    },
    "lip_sync_unclear": {
        "method": "manual",
        "meaning": "mouth movement does not read against the dialogue",
    },
    "background_flicker": {
        "method": "manual",
        "meaning": "the background shimmers or shifts unnaturally",
    },
    "wardrobe_colour_shift": {
        "method": "manual",
        "meaning": "wardrobe colour shifts between shots without cause",
    },
}


def list_review_signals() -> list[dict[str, str]]:
    """Return the closed review-signal vocabulary with method labels."""
    return [
        {"kind": kind, **info} for kind, info in SIGNALS.items()
    ]


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.review_signal_vocabulary: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_review_signals(plan: Any) -> dict[str, Any]:
    """Judge a review plan's use of the signal vocabulary.

    ``plan`` carries ``signals`` (each with ``kind`` and
    ``method``; automatic signals additionally carry a caller
    declared ``threshold``). Verdict ``pass`` means every
    signal kind is in the closed vocabulary, every declared
    method matches the vocabulary's method label, and every
    automatic signal carries a caller-declared threshold.
    A manual signal presented with measured evidence fails:
    unmeasured signals must stay labelled manual.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("review plan must be an object")
    signals = plan.get("signals")
    if not isinstance(signals, list):
        raise CapabilityError("review plan requires a signals list")
    issues: list[dict[str, Any]] = []
    seen: list[str] = []
    for index, signal in enumerate(signals):
        if not isinstance(signal, dict):
            issues.append(
                _issue("signal_not_object", f"signal {index} is not an object")
            )
            continue
        kind = signal.get("kind")
        entry = SIGNALS.get(kind) if isinstance(kind, str) else None
        if entry is None:
            issues.append(
                _issue(
                    "signal_kind_unknown",
                    f"signal {index} kind {kind!r} is outside the closed vocabulary",
                )
            )
            continue
        seen.append(kind)
        method = signal.get("method")
        if method != entry["method"]:
            issues.append(
                _issue(
                    "signal_method_mismatch",
                    f"signal {kind} is a {entry['method']} signal, "
                    f"not {method!r}",
                    kind=kind,
                )
            )
        if entry["method"] == "automatic":
            if not _is_number(signal.get("threshold")):
                issues.append(
                    _issue(
                        "threshold_missing",
                        f"automatic signal {kind} requires a caller-declared "
                        "threshold (no default is assumed)",
                        kind=kind,
                    )
                )
        elif signal.get("measured_value") is not None:
            issues.append(
                _issue(
                    "manual_signal_dressed_as_measured",
                    f"manual signal {kind} must not carry a measured value",
                    kind=kind,
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "signal_count": len(seen),
        "vocabulary_size": len(SIGNALS),
        "executed_here": False,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_review_signals(params.get("plan"))
    report_path = out_dir / "review_signal_vocabulary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_review_signal_vocabulary_capabilities_once() -> list[str]:
    """Register ``qa.review_signal_vocabulary`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.review_signal_vocabulary",
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
                "Review-signal vocabulary: fifteen closed signal kinds, "
                "each labelled automatic or manual; automatic signals "
                "require a caller-declared threshold."
            ),
        )
    )
    return ["qa.review_signal_vocabulary"]


__all__ = [
    "SIGNALS",
    "list_review_signals",
    "check_review_signals",
    "register_review_signal_vocabulary_capabilities_once",
]
