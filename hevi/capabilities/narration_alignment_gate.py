"""Narration alignment gate (``qa.narration_alignment_gate``).

Clean-room rewrite of a *method* only: narration leads the picture,
so the spoken track is measured first and every beat is aligned to
it; gaps and lead-ins stay within caller-set limits; a read-back
below a caller-set threshold sends the narration back for a new
recording; and a cloned voice is allowed only for the speaker
themselves or an explicitly authorised voice, with the authorisation
on record. No text, code, or asset from any outside repository is
copied here. See VIBE_KNOWLEDGE_ATTRIBUTION.md.

This gate judges alignment plans only. It performs no voice
cloning, no recording, and no audio analysis of any kind. The
narration rate, the gap and lead limits, and the read-back
threshold are all required caller parameters; no fallback values
are baked in.
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

AUTHORISED_ORIGINS = ("self", "authorised", "authorized")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_narration_alignment(plan: Any) -> dict[str, Any]:
    """Judge one narration alignment plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. A missing clone
    authorisation is a hard failure, never a warning.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "plan_not_object",
                    "narration alignment plan must be a JSON object",
                )
            ],
            "measured_chars_per_second": None,
            "thresholds_applied": {},
        }
    rate = plan.get("chars_per_second")
    if not _is_number(rate) or rate <= 0:
        issues.append(
            _issue(
                "chars_per_second_missing",
                "chars_per_second is a required caller parameter; the "
                "gate never assumes a narration rate",
            )
        )
        rate = None
    max_gap_s = plan.get("max_gap_s")
    if not _is_number(max_gap_s) or max_gap_s < 0:
        issues.append(
            _issue(
                "max_gap_s_missing",
                "max_gap_s is a required caller parameter",
            )
        )
        max_gap_s = None
    max_lead_s = plan.get("max_lead_s")
    if not _is_number(max_lead_s) or max_lead_s < 0:
        issues.append(
            _issue(
                "max_lead_s_missing",
                "max_lead_s is a required caller parameter",
            )
        )
        max_lead_s = None
    readback_threshold = plan.get("readback_threshold")
    if (
        not _is_number(readback_threshold)
        or readback_threshold < 0
        or readback_threshold > 1
    ):
        issues.append(
            _issue(
                "readback_threshold_missing",
                "readback_threshold is a required caller parameter "
                "between 0 and 1",
            )
        )
        readback_threshold = None
    thresholds = {
        "chars_per_second": rate,
        "max_gap_s": max_gap_s,
        "max_lead_s": max_lead_s,
        "readback_threshold": readback_threshold,
    }
    narration = plan.get("narration")
    measured_rate = None
    if not isinstance(narration, dict):
        issues.append(
            _issue(
                "narration_missing",
                "plan must carry a narration evidence record",
            )
        )
    else:
        duration = narration.get("measured_duration_s")
        if "estimated_duration_s" in narration:
            issues.append(
                _issue(
                    "estimated_timing",
                    "an estimated narration duration is not measured evidence",
                )
            )
        if not _is_number(duration) or duration <= 0:
            issues.append(
                _issue(
                    "measured_duration_missing",
                    "narration must declare a positive measured_duration_s",
                )
            )
        if not _is_nonempty_str(narration.get("evidence_id")):
            issues.append(
                _issue(
                    "narration_evidence_missing",
                    "narration must carry an evidence_id",
                )
            )
        text = narration.get("text")
        if (
            _is_nonempty_str(text)
            and _is_number(duration)
            and duration > 0
        ):
            measured_rate = len(text) / float(duration)
            if rate is not None and measured_rate > float(rate) * 1.1:
                issues.append(
                    _issue(
                        "rate_exceeded",
                        f"measured narration rate {measured_rate:.2f} "
                        f"chars/s exceeds the caller rate {rate} chars/s "
                        "by more than 10%",
                    )
                )
    beats = plan.get("beats")
    if not isinstance(beats, list) or not beats:
        issues.append(
            _issue("beats_missing", "plan must declare a non-empty beats list")
        )
        beats = beats if isinstance(beats, list) else []
    for index, beat in enumerate(beats):
        label = f"beats[{index}]"
        if not isinstance(beat, dict):
            issues.append(
                _issue(f"{label}:not_object", "each beat must be an object")
            )
            continue
        gap = beat.get("gap_s")
        if gap is not None and max_gap_s is not None:
            if not _is_number(gap) or gap < 0:
                issues.append(
                    _issue(
                        f"{label}:gap_invalid",
                        "gap_s must be a non-negative number",
                    )
                )
            elif gap > max_gap_s:
                issues.append(
                    _issue(
                        f"{label}:gap_too_long",
                        f"gap of {gap}s exceeds the {max_gap_s}s limit",
                    )
                )
        lead = beat.get("lead_s")
        if lead is not None and max_lead_s is not None:
            if not _is_number(lead) or lead < 0:
                issues.append(
                    _issue(
                        f"{label}:lead_invalid",
                        "lead_s must be a non-negative number",
                    )
                )
            elif lead > max_lead_s:
                issues.append(
                    _issue(
                        f"{label}:lead_too_long",
                        f"lead-in of {lead}s exceeds the {max_lead_s}s limit",
                    )
                )
    readback = plan.get("readback_ratio")
    if readback is not None:
        if not _is_number(readback) or readback < 0 or readback > 1:
            issues.append(
                _issue(
                    "readback_ratio_invalid",
                    "readback_ratio must be a number between 0 and 1",
                )
            )
        elif readback_threshold is not None and readback < readback_threshold:
            issues.append(
                _issue(
                    "readback_below_threshold",
                    f"read-back ratio {readback} is below the "
                    f"{readback_threshold} threshold; re-record the "
                    "narration",
                )
            )
    voice = plan.get("voice")
    if isinstance(voice, dict) and voice.get("clone") is True:
        origin = voice.get("voice_origin")
        authorisation = voice.get("authorization")
        if origin not in AUTHORISED_ORIGINS:
            issues.append(
                _issue(
                    "clone_origin_unauthorised",
                    "a cloned voice is allowed only for the speaker "
                    "themselves or an explicitly authorised voice; "
                    "voice_origin must be self or authorised",
                )
            )
        if not _is_nonempty_str(authorisation):
            issues.append(
                _issue(
                    "clone_authorization_missing",
                    "a cloned voice needs a non-empty authorisation "
                    "record; cloning without one is refused",
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "measured_chars_per_second": measured_rate,
        "thresholds_applied": thresholds,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_narration_alignment(params.get("plan"))
    report_path = out_dir / "narration_alignment.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_narration_alignment_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.narration_alignment_gate",
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
                "Narration alignment gate: measured narration leads, "
                "beats align within caller-set gap and lead limits, "
                "read-back below a caller-set threshold re-records, "
                "and cloned voices need an authorisation record."
            ),
        )
    )
    return ["qa.narration_alignment_gate"]


__all__ = [
    "check_narration_alignment",
    "register_narration_alignment_gate_capabilities_once",
]
