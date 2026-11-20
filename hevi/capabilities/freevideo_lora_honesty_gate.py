"""Community LoRA honesty gate (``qa.freevideo_lora_honesty_gate``).

A community LoRA is only usable when its source and its
license are written down. In the reviewer's own words, a
LoRA list fails when any entry lacks a source or a license,
when a license is recorded as unknown, or when an adult
LoRA does not record a subject age of 24 or above — adult
material in hevi is for adults only, never for minors, and
an unaged adult claim is not a pass. The gate judges LoRA
descriptions only; it never downloads or applies a LoRA.

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here.
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

ADULT_MIN_AGE_YEARS = 24


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_freevideo_lora(loras: Any) -> dict[str, Any]:
    """Validate a FreeVideo-style community LoRA list.

    Verdicts are ``pass`` / ``fail`` only. A list fails when
    it is not a non-empty list, when any entry is not an
    object, when any entry lacks a LoRA id, a source, or a
    license, when a license is unknown, or when an adult
    LoRA does not record a subject age of 24 or above.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(loras, list) or not loras:
        return fail("loras_missing", "LoRA list must be a non-empty list")
    for position, entry in enumerate(loras):
        if not isinstance(entry, dict):
            return fail("lora_not_object", f"LoRA {position} must be an object")
        lora_id = entry.get("lora_id")
        if not isinstance(lora_id, str) or not lora_id:
            return fail("lora_id_missing", f"LoRA {position} must carry a lora_id")
        source = entry.get("source")
        if not isinstance(source, str) or not source:
            return fail(
                "lora_source_missing",
                f"LoRA {lora_id!r} must record its source",
            )
        license_text = entry.get("license")
        if not isinstance(license_text, str) or not license_text:
            return fail(
                "lora_license_missing",
                f"LoRA {lora_id!r} must record its license",
            )
        if license_text.strip().lower() == "unknown":
            return fail(
                "lora_license_unknown",
                f"LoRA {lora_id!r} has an unknown license and must not be used",
            )
        if entry.get("adult") is True:
            age = entry.get("subject_age_years")
            if not _is_number(age) or age < ADULT_MIN_AGE_YEARS:
                return fail(
                    "adult_lora_age_unproven",
                    f"adult LoRA {lora_id!r} must record a subject age of "
                    f"{ADULT_MIN_AGE_YEARS} or above",
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
    report = check_freevideo_lora(params.get("loras"))
    report_path = out_dir / "freevideo_lora_honesty_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_lora_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_lora_honesty_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "loras": {"type": "array"},
                },
                "required": ["loras"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "FreeVideo community LoRA honesty gate: every LoRA "
                "records its source and license, unknown licenses "
                "fail, adult LoRAs record a subject age of 24 or above."
            ),
        )
    )
    return ["qa.freevideo_lora_honesty_gate"]


__all__ = [
    "ADULT_MIN_AGE_YEARS",
    "check_freevideo_lora",
    "register_freevideo_lora_honesty_gate_capabilities_once",
]
