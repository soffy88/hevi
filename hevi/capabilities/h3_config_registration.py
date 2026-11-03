"""H3 single-segment configuration registration (``qa.h3_config_registration``).

Clean-room restatement of the configuration discipline behind the
pixelaigc single-segment H3 workflow (see
``PIXELAIGC_H3_WORKFLOW_ATTRIBUTION.md``): one named configuration
is registered -- a pruned INT8 diffusion model of the fl2va family,
an NVFP4 AWQ text encoder, fp16 video / fp32 audio VAEs, and the
ckpt850 4-step turbo LoRA at strength 1.0 -- with
``verified=false`` until a real GPU run measures it. The record
states plainly that this configuration is **not equivalent** to
the weights already installed for hevi's FastH3 route (the omniref
INT8 diffusion model plus INT8 encoder, with an empty LoRA
directory): file names must never be swapped between the two, and
the two turbo LoRA families (this one and the Pika family) must
never be mixed in one plan.

This module judges configuration records only. It never
downloads weights, never calls a model, never stores a key, and
never asserts a weight licence: the licence of the weights is
unverified and is recorded as such, never defaulted.
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

CONFIG_ID = "h3-fl2va-int8-awq-ckpt850"
INSTALLED_CONFIG_ID = "fasth3-omniref-int8"
SOURCE = "pixelaigc/ComfyUI-MiniMax-H3-Workflow (public workflow description, read-only review)"
SOURCE_DATE = "2026-11-03"

# Component file names are factual identifiers read from the public
# workflow description. They are not hevi defaults and must never be
# treated as interchangeable with the installed FastH3 file names.
COMPONENTS = {
    "diffusion_model": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "text_encoder": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "video_vae": "minimax_h3_video_vae_fp16.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
    "turbo_lora": "minimax_h3_turbo_4step_ema_ckpt850.safetensors",
    "lora_strength": 1.0,
    "sampler_steps_saved": 8,
}

# The other turbo LoRA family known to hevi. Declaring both families
# in one plan is a failure, not a fallback.
INCOMPATIBLE_LORA_FAMILIES = ("pika-h3-flex-turbo",)


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.h3_config_registration: {detail}"}
    issue.update(extra)
    return issue


def config_record() -> dict[str, Any]:
    """The registered single-segment H3 configuration record."""
    return {
        "config_id": CONFIG_ID,
        "components": dict(COMPONENTS),
        "source": SOURCE,
        "source_date": SOURCE_DATE,
        "verified": False,
        "verification": "not_run",
        "not_equivalent_to": INSTALLED_CONFIG_ID,
        "equivalence_note": (
            "Frame counts sharing a grid do not make weights "
            "equivalent; file-name substitution between this "
            "configuration and the installed FastH3 configuration "
            "is unverified and must not be assumed."
        ),
        "incompatible_lora_families": list(INCOMPATIBLE_LORA_FAMILIES),
        "weight_license": "unverified",
    }


def check_h3_config(plan: Any) -> dict[str, Any]:
    """Judge one plan's declared H3 configuration.

    ``plan`` is an object with ``config_id``, ``components`` (a
    mapping), ``lora_families`` (a list, may be empty), and the
    record fields ``source`` / ``source_date``. Claims of
    verification or of equivalence with the installed
    configuration fail without run evidence, which this gate
    never accepts on a plan's word alone. Returns ``ok`` /
    ``issues`` / ``config``.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "issues": [_issue("plan_not_object", "configuration plan must be an object")],
            "config": None,
        }
    if not plan.get("source") or not plan.get("source_date"):
        issues.append(
            _issue(
                "source_undeclared",
                "configuration record requires source and source_date",
            )
        )
    config_id = plan.get("config_id")
    if config_id != CONFIG_ID:
        issues.append(
            _issue(
                "unknown_config",
                f"config_id must be {CONFIG_ID!r}, got {config_id!r}; "
                "unknown configurations are not judged",
            )
        )
        return {"ok": False, "issues": issues, "config": None}
    components = plan.get("components")
    if not isinstance(components, dict):
        issues.append(_issue("components_undeclared", "components mapping is required"))
    else:
        for key, wanted in COMPONENTS.items():
            if components.get(key) != wanted:
                issues.append(
                    _issue(
                        "component_mismatch",
                        f"component {key!r} must be {wanted!r}, "
                        f"got {components.get(key)!r}",
                        component=key,
                    )
                )
    families = plan.get("lora_families") or []
    if not isinstance(families, list):
        issues.append(_issue("lora_families_not_list", "lora_families must be a list"))
        families = []
    for family in families:
        if family in INCOMPATIBLE_LORA_FAMILIES:
            issues.append(
                _issue(
                    "lora_mix",
                    f"turbo LoRA family {family!r} must never be mixed "
                    f"with the {CONFIG_ID} LoRA",
                    family=family,
                )
            )
    if plan.get("verified"):
        issues.append(
            _issue(
                "verified_claim_without_run",
                "verified=true requires a measured GPU run record; "
                "a plan may not self-certify",
            )
        )
    if plan.get("equivalent_to") == INSTALLED_CONFIG_ID:
        issues.append(
            _issue(
                "equivalence_claim_without_evidence",
                "equivalence with the installed FastH3 configuration "
                "requires a completed equivalence protocol run; "
                "frame-grid sharing alone is not evidence",
            )
        )
    if plan.get("weight_license") not in (None, "unverified"):
        issues.append(
            _issue(
                "weight_license_defaulted",
                "weight licence is unverified; no licence value may "
                "be asserted in a configuration record",
            )
        )
    return {"ok": not issues, "issues": issues, "config": config_record()}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_h3_config(params.get("plan"))
    report_path = out_dir / "h3_config_registration.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_h3_config_registration_capabilities_once() -> list[str]:
    """Register ``qa.h3_config_registration`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.h3_config_registration",
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
                "H3 configuration registration gate: judge a plan's "
                "declared single-segment configuration (fl2va INT8 + "
                "NVFP4 AWQ + ckpt850 turbo LoRA) as verified=false, "
                "not equivalent to the installed FastH3 weights, and "
                "never mixed with the other turbo LoRA family. "
                "Judges records only; no weights, no keys."
            ),
            line="qa",
        )
    )
    return ["qa.h3_config_registration"]


register_h3_config_registration_capabilities_once()
