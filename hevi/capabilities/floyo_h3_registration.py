"""Floyo hosted MiniMax H3 image-to-video route: REGISTRATION ONLY.

This module only records the route in a model directory
(``model.model_directory`` discipline): presence in the directory is
not verification, and nothing here registers an account, spends money,
uses a promo code, stores a card, or performs any generation. It makes
no network calls and reads no credentials.

Two records are kept strictly separate and must never be confused:

* ``floyo-h3-i2v-openweight`` — the Floyo-hosted workflow
  ``Minimax_H3_Image_to_Video_OpenWeight`` (image-to-video: start frame
  + aspect ratio + duration + prompt; does not consume the API wallet;
  billed in FloTime GPU time). Recorded from the read-only check in the
  registration request (2026-10-31); this module does not re-fetch the
  pricing page.
* ``local-h3-fasth3`` — the local route (``video.fasth3_local``,
  ComfyUI on ubuntu26 with local FastH3 weights). A different backend,
  a different record; listing it here only prevents the two H3 routes
  from being conflated.

Claims the workflow page does not state ("no censorship", LoRA
support, adult performance, H100 speed) are recorded as
``"unverified"`` in every record. They must never be presented as
platform guarantees, and :func:`validate_floyo_config` refuses any
record that states them otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.h3_config_registration import config_record
from hevi.capabilities.model_directory import (
    record_in_directory as record_models_in_directory,
)
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

FLOYO_MODEL_ID = "floyo-h3-i2v-openweight"
LOCAL_H3_MODEL_ID = "local-h3-fasth3"
FLOYO_WORKFLOW_ID = "Minimax_H3_Image_to_Video_OpenWeight"

_FLOYO_INPUTS = ("start_frame", "aspect_ratio", "duration", "prompt")

# Claims that must stay "unverified": the workflow page does not state them.
_UNVERIFIED_CLAIMS = ("no_censorship", "lora", "adult_performance", "h100_speed")


def floyo_h3_config() -> dict[str, Any]:
    """The Floyo hosted H3 image-to-video record, as registered (unverified)."""
    return {
        "provider": "Floyo",
        "route": "hosted",
        "workflow": FLOYO_WORKFLOW_ID,
        "kind": "image_to_video",
        "inputs": list(_FLOYO_INPUTS),
        "billing": {
            "unit": "FloTime (GPU time)",
            "api_wallet_consumed": False,
            "plans": {
                "Explorer": "2 hours per month",
                "Flex": "$9/hour",
            },
            "source": (
                "Floyo pricing page wording as recorded in the "
                "registration request (2026-10-31); not re-fetched "
                "by this module and not a live price check"
            ),
        },
        "claims": {name: "unverified" for name in _UNVERIFIED_CLAIMS},
        "account_registered": False,
        "payment_method_on_file": False,
        "promo_code_used": False,
        "status": "unverified",
        "verified": False,
    }


def local_h3_config() -> dict[str, Any]:
    """The local H3 route record, kept separate from the Floyo record.

    The H3 configuration values are delegated to the single source
    ``qa.h3_config_registration.config_record`` (SPEC 1.4); only the
    Floyo-route fields below are local to this module.
    """
    canonical = config_record()
    return {
        "provider": "local",
        "route": "local",
        "capability": "video.fasth3_local",
        "backend": "ComfyUI on ubuntu26 with local FastH3 weights",
        "kind": "reference_to_video",
        "workflow": None,
        "h3_config": {
            "config_id": canonical["config_id"],
            "components": canonical["components"],
            "source": canonical["source"],
            "source_date": canonical["source_date"],
            "verification": canonical["verification"],
            "not_equivalent_to": canonical["not_equivalent_to"],
            "incompatible_lora_families": canonical["incompatible_lora_families"],
            "weight_license": canonical["weight_license"],
        },
        "billing": {
            "unit": "local GPU time (no Floyo billing)",
            "api_wallet_consumed": False,
            "floyo_workflow": False,
        },
        "claims": {name: "unverified" for name in _UNVERIFIED_CLAIMS},
        "account_registered": False,
        "payment_method_on_file": False,
        "promo_code_used": False,
        "status": "unverified",
        "verified": canonical["verified"],
    }


def validate_floyo_config(config: Any) -> dict[str, Any]:
    """Refuse any Floyo record that overstates the workflow page.

    Positive case: the exact config from :func:`floyo_h3_config`.
    Negative cases: a wrong workflow id, a missing input, a claim
    stated as anything but ``"unverified"``, API-wallet consumption,
    or any account / payment / promo flag set to true.
    """
    if not isinstance(config, dict):
        raise CapabilityError("model.floyo_h3_registration: config must be a JSON object")
    if config.get("workflow") != FLOYO_WORKFLOW_ID:
        raise CapabilityError(
            "model.floyo_h3_registration: workflow must be "
            f"{FLOYO_WORKFLOW_ID!r}, got {config.get('workflow')!r}"
        )
    inputs = config.get("inputs")
    if not isinstance(inputs, list) or [str(i) for i in inputs] != list(_FLOYO_INPUTS):
        raise CapabilityError(
            "model.floyo_h3_registration: inputs must be exactly "
            f"{list(_FLOYO_INPUTS)}, got {inputs!r}"
        )
    billing = config.get("billing")
    if not isinstance(billing, dict) or billing.get("api_wallet_consumed") is not False:
        raise CapabilityError(
            "model.floyo_h3_registration: api_wallet_consumed must be false "
            "(the workflow does not consume the API wallet)"
        )
    claims = config.get("claims")
    if not isinstance(claims, dict):
        raise CapabilityError("model.floyo_h3_registration: claims must be a JSON object")
    for name in _UNVERIFIED_CLAIMS:
        if claims.get(name) != "unverified":
            raise CapabilityError(
                "model.floyo_h3_registration: claim "
                f"{name!r} must stay 'unverified' (the workflow page does "
                f"not state it), got {claims.get(name)!r}"
            )
    for flag in ("account_registered", "payment_method_on_file", "promo_code_used"):
        if config.get(flag) is not False:
            raise CapabilityError(
                f"model.floyo_h3_registration: {flag} must be false "
                "(registration only: no account, no card, no promo code)"
            )
    if config.get("verified") is not False or config.get("status") != "unverified":
        raise CapabilityError(
            "model.floyo_h3_registration: the record must stay unverified"
        )
    return dict(config)


def record_in_directory(directory_path: Path) -> dict[str, dict[str, Any]]:
    """Record both H3 routes (unverified) in a model-directory JSON file.

    Delegates to the single write path
    ``model.model_directory.record_in_directory``: both records land
    with ``status: unverified`` and ``verified_at: null``. No account
    is created, no money moves, no network call is made.
    """
    floyo = validate_floyo_config(floyo_h3_config())
    local = dict(local_h3_config())
    return record_models_in_directory(
        Path(directory_path),
        {FLOYO_MODEL_ID: floyo, LOCAL_H3_MODEL_ID: local},
    )


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = str(params.get("action") or "describe")
    if action == "describe":
        result: dict[str, Any] = {
            "capability": "model.floyo_h3_registration",
            "floyo": floyo_h3_config(),
            "local_h3": local_h3_config(),
            "note": (
                "Registration only: both records are unverified, no "
                "account was registered, no payment was made, no promo "
                "code was used, and no generation was performed."
            ),
        }
    elif action == "record":
        directory_path = Path(params["directory_path"])
        records = record_in_directory(directory_path)
        result = {
            "capability": "model.floyo_h3_registration",
            "directory_path": str(directory_path),
            "records": records,
        }
    else:
        raise CapabilityError(
            f"model.floyo_h3_registration: unknown action {action!r}; "
            "known: describe, record"
        )
    report_path = out_dir / "floyo_h3_registration_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_floyo_h3_registration_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.floyo_h3_registration",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "directory_path": {"type": "string"},
                    "action": {"type": "string", "enum": ["describe", "record"]},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Floyo hosted MiniMax H3 image-to-video route, registration "
                "only: records the Minimax_H3_Image_to_Video_OpenWeight "
                "workflow (start frame + aspect ratio + duration + prompt, "
                "no API-wallet consumption, FloTime GPU-time billing) and "
                "the separate local H3 route in a model directory, both "
                "unverified. Unstated claims (no censorship / LoRA / adult "
                "performance / H100 speed) stay 'unverified'. No account, "
                "no payment, no promo code, no generation, no network."
            ),
            line="model",
        )
    )
    return ["model.floyo_h3_registration"]


register_floyo_h3_registration_capabilities_once()
