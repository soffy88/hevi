"""Qwen Image 2.1 licence-compliance gate (``model.qwen_image_license_gate``).

Plan/licence layer only. This module bundles no weights, downloads no
model files, performs no generation and files no commercial-licence
application. It judges a *plan* against the Qwen Research License
Agreement (2026-09-20, Hangzhou Tongyi Laboratory Technology Co.,
Ltd.) as read from the Hugging Face ``Qwen/Qwen-Image-2.1`` LICENSE
text, plus the 24 GB deployment thresholds recorded in
``~/workspace/qwen-image-2-1-license-deploy-check.md``.

Licence rules enforced (clause references are to that agreement):

* Non-commercial means research or evaluation only (section 1(i)).
  Any commercial purpose needs a separate commercial licence
  (section 2(b)); the only application route recorded is
  ``model-business@notice.qwencloud.com`` and no price, self-serve
  path or grant promise exists in the agreement text.
* Redistribution of the Materials or derivatives must ship a copy of
  the agreement, carry a prominent modification notice on modified
  files, and retain the specified Notice text (section 3).
* The "Built with Qwen" / "Improved using Qwen" attribution duty is
  triggered ONLY when Materials or their outputs are used to create,
  train, fine-tune or improve an AI model that is distributed or
  provided (section 4(b)). Ordinary image generation does not
  trigger it, and this gate must never expand the duty to every
  generated image.
* "Qwen" must not be used as the primary name or mark of a
  derivative work or product (section 4(c)).
* The Turbo variant's licence text was NOT read in the source
  check; its licence status is always reported ``unverified`` and
  must never be assumed identical to the base model's.
* A Floyo hosted plan's commercial-use claim is a separate
  contractual regime from the self-hosted Research License. A
  Floyo record never satisfies a self-hosted commercial licence.

Deployment thresholds recorded (caller-measured values govern;
sizes below are registry values from the check report, in bytes):

* DiT 7B: bf16 14,230,280,616 B; int8 7,256,783,064 B.
* Qwen3-VL 8B encoder: bf16 17,534,334,616 B; int8
  9,350,798,360 B; w4a8 6,312,105,364 B (third-party file table).
* VAE: 675,509,688 B. bf16 three-piece total ~32.44 GB; int8
  three-piece total ~17.28 GB (decimal GB, bytes / 1e9).
* A 24 GB card only clears the int8 route for evaluation. A bf16
  resident plan on a 24 GB card fails unless CPU offload is
  explicitly declared. No speed figure is ever registered: every
  report marks speed ``unmeasured`` and any numeric speed claim in
  a plan fails.
* ComfyUI native templates: 4 (base text-to-image, base edit,
  Turbo text-to-image, Turbo edit), default int8. Turbo uses a
  fixed 8-step ManualSigmas schedule; changing only the step count
  fails.
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

LICENSE_NOTICE = (
    "Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, "
    "Copyright (c) 2026 Hangzhou Tongyi Laboratory Technology Co., Ltd. "
    "All Rights Reserved."
)
LICENSOR = "Hangzhou Tongyi Laboratory Technology Co., Ltd."
COMMERCIAL_LICENSE_CONTACT = "model-business@notice.qwencloud.com"
LICENSE_SOURCE = "Hugging Face Qwen/Qwen-Image-2.1 LICENSE (Qwen Research License Agreement, 2026-09-20)"
REPORT_PATH = "~/workspace/qwen-image-2-1-license-deploy-check.md"

# Component file sizes in bytes (registry values from the check report).
COMPONENT_SIZES_BYTES: dict[str, int] = {
    "dit_bf16": 14230280616,
    "dit_int8": 7256783064,
    "encoder_bf16": 17534334616,
    "encoder_int8": 9350798360,
    "encoder_w4a8": 6312105364,
    "vae_bf16": 675509688,
}

BASE_MODELS = ("qwen-image-2.1", "qwen-image-2.1-turbo")
NON_COMMERCIAL_PURPOSES = ("research", "evaluation")
COMMERCIAL_PURPOSES = (
    "commercial",
    "paid_generation",
    "commercial_delivery",
    "bundled_distribution",
    "commercial_finetune_distribution",
    "commercial_finetune",
    "monetised_publication",
)
SPEED_CLAIM_KEYS = (
    "seconds_per_image",
    "images_per_minute",
    "seconds_per_iteration",
    "it_per_sec",
    "images_per_hour",
)


def _fail(message: str) -> None:
    raise CapabilityError(f"model.qwen_image_license_gate: {message}")


def _gb(nbytes: int) -> float:
    return round(nbytes / 1e9, 2)


def component_sizes_gb() -> dict[str, float]:
    """Registry component sizes in decimal GB (bytes / 1e9)."""
    return {name: _gb(size) for name, size in COMPONENT_SIZES_BYTES.items()}


def three_piece_total_gb(quantization: str) -> float:
    """Total file size of the three-piece set for a quantization."""
    if quantization == "bf16":
        total = (
            COMPONENT_SIZES_BYTES["dit_bf16"]
            + COMPONENT_SIZES_BYTES["encoder_bf16"]
            + COMPONENT_SIZES_BYTES["vae_bf16"]
        )
    elif quantization == "int8":
        total = (
            COMPONENT_SIZES_BYTES["dit_int8"]
            + COMPONENT_SIZES_BYTES["encoder_int8"]
            + COMPONENT_SIZES_BYTES["vae_bf16"]
        )
    elif quantization == "w4a8":
        total = (
            COMPONENT_SIZES_BYTES["dit_int8"]
            + COMPONENT_SIZES_BYTES["encoder_w4a8"]
            + COMPONENT_SIZES_BYTES["vae_bf16"]
        )
    else:
        _fail(f"unknown quantization: {quantization!r}")
    return _gb(total)


def _is_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_license_use(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge the licence use of a plan. Returns a report dict."""
    if not isinstance(plan, dict):
        _fail("plan must be a dict")
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    model = plan.get("model")
    if model not in BASE_MODELS:
        failures.append(
            {
                "code": "unknown_model",
                "clause": "n/a",
                "message": f"model must be one of {list(BASE_MODELS)}; got {model!r}",
            }
        )
        model = None
    license_status = "qwen_research_non_commercial"
    if model == "qwen-image-2.1-turbo":
        license_status = "unverified"
        warnings.append(
            {
                "code": "turbo_license_unverified",
                "clause": "n/a",
                "message": (
                    "Turbo variant LICENSE text was not read in the source "
                    "check; its licence must not be assumed identical to "
                    "the base model's."
                ),
            }
        )
    purpose = plan.get("purpose")
    commercial_record = plan.get("commercial_license")
    if purpose in NON_COMMERCIAL_PURPOSES:
        pass
    elif purpose == "commercial_licensed":
        if not isinstance(commercial_record, dict) or not all(
            _is_str(commercial_record.get(key))
            for key in ("licensor", "date", "scope")
        ):
            failures.append(
                {
                    "code": "commercial_license_record_missing",
                    "clause": "2(b)",
                    "message": (
                        "commercial_licensed use requires a written "
                        "commercial licence record with licensor, date "
                        "and scope; apply at "
                        + COMMERCIAL_LICENSE_CONTACT
                    ),
                }
            )
    elif purpose in COMMERCIAL_PURPOSES:
        if isinstance(commercial_record, dict) and all(
            _is_str(commercial_record.get(key))
            for key in ("licensor", "date", "scope")
        ):
            warnings.append(
                {
                    "code": "commercial_scope_must_be_checked",
                    "clause": "2(b)",
                    "message": (
                        "A commercial licence record was supplied; the "
                        "caller must confirm its scope covers this use. "
                        "This gate does not verify the licence itself."
                    ),
                }
            )
        else:
            failures.append(
                {
                    "code": "commercial_use_without_license",
                    "clause": "2(b)",
                    "message": (
                        f"purpose {purpose!r} is a commercial purpose "
                        "under the Qwen Research License and requires a "
                        "separate commercial licence; apply at "
                        + COMMERCIAL_LICENSE_CONTACT
                    ),
                }
            )
    else:
        failures.append(
            {
                "code": "unknown_purpose",
                "clause": "1(i)/2(b)",
                "message": (
                    "purpose must be research, evaluation, or "
                    f"commercial_licensed; got {purpose!r}"
                ),
            }
        )
    # Floyo hosted regime must not be confused with self-hosted licence.
    if plan.get("hosting") == "floyo_hosted" and plan.get(
        "floyo_commercial_license_claimed"
    ):
        warnings.append(
            {
                "code": "floyo_regime_separate",
                "clause": "n/a",
                "message": (
                    "A Floyo hosted commercial-use claim is a separate "
                    "contractual regime from the self-hosted Qwen "
                    "Research License and never satisfies a self-hosted "
                    "commercial licence record."
                ),
            }
        )
        if purpose in COMMERCIAL_PURPOSES and not isinstance(
            commercial_record, dict
        ):
            failures.append(
                {
                    "code": "floyo_license_does_not_cover_self_hosted",
                    "clause": "2(b)",
                    "message": (
                        "Floyo hosted commercial-use status does not "
                        "cover self-hosted commercial use; a separate "
                        "commercial licence record is required."
                    ),
                }
            )
    # Redistribution conditions (section 3).
    redistribution = plan.get("redistribution")
    if redistribution:
        if not isinstance(redistribution, dict):
            failures.append(
                {
                    "code": "redistribution_plan_malformed",
                    "clause": "3",
                    "message": "redistribution must be a dict of conditions",
                }
            )
        else:
            if not redistribution.get("includes_license_copy"):
                failures.append(
                    {
                        "code": "redistribution_missing_license_copy",
                        "clause": "3(a)",
                        "message": "redistribution must ship a copy of the agreement",
                    }
                )
            if redistribution.get("modified") and not redistribution.get(
                "modification_notice"
            ):
                failures.append(
                    {
                        "code": "redistribution_missing_modification_notice",
                        "clause": "3(b)",
                        "message": (
                            "modified files in a redistribution must carry "
                            "a prominent modification notice"
                        ),
                    }
                )
            notice = redistribution.get("notice_text")
            if not redistribution.get("notice_retained") or notice != LICENSE_NOTICE:
                failures.append(
                    {
                        "code": "redistribution_notice_not_retained",
                        "clause": "3(c)",
                        "message": (
                            "redistribution must retain the specified "
                            "Notice text verbatim"
                        ),
                    }
                )
    derivative_name = plan.get("derivative_name")
    if _is_str(derivative_name) and derivative_name.strip().lower().startswith(
        "qwen"
    ):
        failures.append(
            {
                "code": "qwen_primary_name_forbidden",
                "clause": "4(c)",
                "message": (
                    "'Qwen' must not be used as the primary name or mark "
                    "of a derivative work or product"
                ),
            }
        )
    # Attribution duty, section 4(b): only for distributed AI models.
    attribution_required = bool(
        plan.get("derivative_model") and plan.get("derivative_distributed")
    )
    attribution_shown = bool(plan.get("attribution_shown"))
    if attribution_required and not attribution_shown:
        failures.append(
            {
                "code": "attribution_required_not_shown",
                "clause": "4(b)",
                "message": (
                    "Using Materials or their outputs to create, train, "
                    "fine-tune or improve a distributed AI model requires "
                    "a prominent 'Built with Qwen' or 'Improved using "
                    "Qwen' notice in the product documentation"
                ),
            }
        )
    return {
        "verdict": "fail" if failures else "pass",
        "failures": failures,
        "warnings": warnings,
        "license_status": license_status,
        "license_source": LICENSE_SOURCE,
        "licensor": LICENSOR,
        "attribution_required": attribution_required,
        "attribution_shown": attribution_shown,
    }


def check_redistribution(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge only the redistribution conditions of a plan."""
    if not isinstance(plan, dict):
        _fail("plan must be a dict")
    if not plan.get("redistribution"):
        return {
            "verdict": "pass",
            "failures": [],
            "warnings": [
                {
                    "code": "no_redistribution",
                    "clause": "3",
                    "message": "plan declares no redistribution",
                }
            ],
            "license_notice": LICENSE_NOTICE,
        }
    report = check_license_use(plan)
    redistribution_failures = [
        f for f in report["failures"] if f["clause"].startswith("3")
    ]
    return {
        "verdict": "fail" if redistribution_failures else "pass",
        "failures": redistribution_failures,
        "warnings": report["warnings"],
        "license_notice": LICENSE_NOTICE,
    }


def check_deployment(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge the recorded 24 GB deployment thresholds of a plan."""
    if not isinstance(plan, dict):
        _fail("plan must be a dict")
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    quantization = plan.get("quantization", "int8")
    if quantization not in ("bf16", "int8", "w4a8", "gguf-q4"):
        failures.append(
            {
                "code": "unknown_quantization",
                "clause": "deployment",
                "message": f"quantization must be bf16, int8, w4a8 or gguf-q4; got {quantization!r}",
            }
        )
        quantization = "int8"
    vram_gb = plan.get("vram_gb")
    if vram_gb is not None and (not isinstance(vram_gb, (int, float)) or vram_gb <= 0):
        failures.append(
            {
                "code": "invalid_vram_gb",
                "clause": "deployment",
                "message": "vram_gb must be a positive number when supplied",
            }
        )
        vram_gb = None
    if quantization == "bf16" and vram_gb is not None and vram_gb <= 24:
        if not plan.get("offload_declared"):
            failures.append(
                {
                    "code": "bf16_resident_not_permitted_without_offload",
                    "clause": "deployment",
                    "message": (
                        "bf16 three-piece set (~32.44 GB) cannot reside "
                        "on a 24 GB card without an explicit CPU offload "
                        "declaration; use the int8 route or declare offload"
                    ),
                }
            )
        else:
            warnings.append(
                {
                    "code": "bf16_offload_speed_cost",
                    "clause": "deployment",
                    "message": (
                        "bf16 with CPU offload declared; speed is "
                        "unmeasured and paging cost is expected"
                    ),
                }
            )
    if quantization == "w4a8":
        warnings.append(
            {
                "code": "w4a8_third_party_table",
                "clause": "deployment",
                "message": (
                    "w4a8 encoder size comes from a third-party file "
                    "table; verify sha256 before use"
                ),
            }
        )
    if quantization == "gguf-q4":
        warnings.append(
            {
                "code": "gguf_requires_custom_nodes",
                "clause": "deployment",
                "message": "GGUF route requires ComfyUI-GGUF nodes",
            }
        )
    templates = plan.get("comfyui_templates")
    if templates is not None and templates != 4:
        warnings.append(
            {
                "code": "comfyui_template_count",
                "clause": "deployment",
                "message": (
                    "ComfyUI native templates recorded as 4; plan "
                    f"declares {templates!r}"
                ),
            }
        )
    if plan.get("default_quantization") not in (None, "int8"):
        warnings.append(
            {
                "code": "default_quantization_not_int8",
                "clause": "deployment",
                "message": "ComfyUI native templates default to int8",
            }
        )
    # Turbo: fixed 8-step schedule; changing only the step count fails.
    if plan.get("model") == "qwen-image-2.1-turbo":
        steps = plan.get("turbo_steps")
        schedule = plan.get("turbo_schedule")
        if steps is not None and steps != 8:
            failures.append(
                {
                    "code": "turbo_steps_only_changed",
                    "clause": "deployment",
                    "message": (
                        "Turbo uses a fixed 8-step ManualSigmas schedule; "
                        "changing only the step count is not permitted"
                    ),
                }
            )
        if schedule is not None and schedule != "manual_sigmas":
            failures.append(
                {
                    "code": "turbo_schedule_not_fixed",
                    "clause": "deployment",
                    "message": "Turbo schedule must be the fixed ManualSigmas plan",
                }
            )
    for key in SPEED_CLAIM_KEYS:
        if plan.get(key) is not None:
            failures.append(
                {
                    "code": "speed_unmeasured",
                    "clause": "deployment",
                    "message": (
                        f"speed claim {key!r} must not be registered; "
                        "speed is unmeasured for this model"
                    ),
                }
            )
    totals = {
        "bf16_total_gb": three_piece_total_gb("bf16"),
        "int8_total_gb": three_piece_total_gb("int8"),
        "w4a8_total_gb": three_piece_total_gb("w4a8"),
    }
    return {
        "verdict": "fail" if failures else "pass",
        "failures": failures,
        "warnings": warnings,
        "quantization": quantization,
        "vram_gb": vram_gb,
        "component_sizes_gb": component_sizes_gb(),
        "three_piece_totals_gb": totals,
        "speed_status": "unmeasured",
    }


def check_qwen_image_license(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Combined licence + deployment report for a plan."""
    license_report = check_license_use(plan)
    deployment_report = check_deployment(plan)
    failures = license_report["failures"] + deployment_report["failures"]
    warnings = license_report["warnings"] + deployment_report["warnings"]
    return {
        "verdict": "fail" if failures else "pass",
        "failures": failures,
        "warnings": warnings,
        "license": license_report,
        "deployment": deployment_report,
        "speed_status": "unmeasured",
        "weights_bundled": False,
        "generation_performed": False,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = params.get("plan", {})
    report = check_qwen_image_license(plan)
    report_path = out_dir / "qwen_image_license_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "failures": report["failures"],
            "warnings": report["warnings"],
        },
    )


def register_qwen_image_license_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.qwen_image_license_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Qwen Image 2.1 licence-compliance gate: research and "
                "evaluation only under the Qwen Research License; any "
                "commercial purpose needs a separate written commercial "
                "licence record; redistribution needs the agreement copy, "
                "modification notice and verbatim Notice text; the "
                "'Built with Qwen' duty applies only when Materials or "
                "their outputs create, train, fine-tune or improve a "
                "distributed AI model; Turbo licence status is unverified; "
                "24 GB deployment only clears the int8 route and speed is "
                "always unmeasured. Plan and gate only: no weights are "
                "bundled, no generation is performed, no commercial "
                "licence is applied for."
            ),
            line="model",
        )
    )
    return ["model.qwen_image_license_gate"]
