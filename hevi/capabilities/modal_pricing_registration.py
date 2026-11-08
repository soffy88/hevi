"""Modal compute pricing: REGISTRATION ONLY.

This module only records Modal's pricing tiers in a model directory
(``model.model_directory`` discipline): presence in the directory is
not verification, and nothing here registers an account, spends money,
stores a payment method or API key, connects to the Modal API, or
performs any generation. It makes no network calls and reads no
credentials.

Modal is recorded as a separate compute-provider record, kept strictly
apart from the Floyo hosted record (``model.floyo_h3_registration``)
and the local H3 record. A different provider, a different record;
listing it here only prevents the three compute routes from being
conflated.

The figures below are exactly the ones in the page text read on
2026-11-01 from https://modal.com/pricing. This module does not
re-fetch the pricing page, so nothing here is a live price check.

Per-unit GPU and CPU prices were NOT captured in that page text.
They are therefore recorded as ``"unverified"`` in every record, and
:func:`validate_modal_config` refuses any record that states a
per-unit GPU or CPU price. No A100/H100 unit price is ever invented
here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
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

MODAL_MODEL_ID = "modal-compute"
MODAL_PRICING_URL = "https://modal.com/pricing"
MODAL_PRICING_READ_DATE = "2026-11-01"


def modal_pricing_config() -> dict[str, Any]:
    """The Modal pricing record, as registered (unverified)."""
    return {
        "provider": "Modal",
        "kind": "compute_provider",
        "route": "hosted",
        "pricing_source": {
            "url": MODAL_PRICING_URL,
            "read_date": MODAL_PRICING_READ_DATE,
            "note": (
                "Page text read on 2026-11-01; not re-fetched by this "
                "module and not a live price check"
            ),
        },
        "billing": {
            "unit": "per-second compute",
            "per_second_billing": True,
            "keep_alive_billed": True,
            "keep_alive_seconds": 60,
            "sandbox_multiplier": 3,
            "sandbox_note": "Sandboxes are billed at 3x the container rate",
            "region_multiplier": {"min": 1.15, "max": 1.75},
            "region_note": "Region selection multiplies the rate by 1.15x-1.75x",
            "non_preemptible_multiplier": 3,
            "non_preemptible_note": (
                "Non-preemptible (non-spot) compute is billed at 3x"
            ),
        },
        "plans": {
            "Starter": {
                "monthly_fee_usd": 0,
                "monthly_fee_note": "$0/month + compute",
                "free_credit_usd": 30,
                "seats": 3,
                "concurrency": {"containers": 100, "gpus": 10},
                "free_egress": "1 TiB",
            },
            "Team": {
                "monthly_fee_usd": 250,
                "monthly_fee_note": "$250/month + compute",
                "free_credit_usd": 100,
                "seats": "unlimited",
                "concurrency": {"containers": 5000, "gpus": 50},
                "free_egress": "10 TiB",
            },
            "Enterprise": {
                "monthly_fee_usd": "custom",
                "free_credit_usd": "unverified",
                "seats": "unverified",
                "concurrency": "unverified",
                "free_egress": "unverified",
            },
        },
        "gpu_prices": "unverified",
        "cpu_prices": "unverified",
        "account_registered": False,
        "payment_method_on_file": False,
        "api_connected": False,
        "api_key_stored": False,
        "status": "unverified",
        "verified": False,
    }


def validate_modal_config(config: Any) -> dict[str, Any]:
    """Refuse any Modal record that overstates the pricing page text.

    Positive case: the exact config from :func:`modal_pricing_config`.
    Negative cases: a changed plan field, a changed multiplier, a
    per-unit GPU or CPU price stated as anything but ``"unverified"``,
    or any account / payment / API flag set to true.
    """
    if not isinstance(config, dict):
        raise CapabilityError("model.modal_pricing_registration: config must be a JSON object")
    if config.get("provider") != "Modal":
        raise CapabilityError(
            "model.modal_pricing_registration: provider must be "
            f"'Modal', got {config.get('provider')!r}"
        )
    billing = config.get("billing")
    if not isinstance(billing, dict):
        raise CapabilityError("model.modal_pricing_registration: billing must be a JSON object")
    if billing.get("per_second_billing") is not True:
        raise CapabilityError(
            "model.modal_pricing_registration: per_second_billing must be true "
            "(Modal bills per second)"
        )
    if billing.get("keep_alive_billed") is not True or billing.get("keep_alive_seconds") != 60:
        raise CapabilityError(
            "model.modal_pricing_registration: the 60-second keep-alive "
            "window must be recorded as billed"
        )
    if billing.get("sandbox_multiplier") != 3:
        raise CapabilityError(
            "model.modal_pricing_registration: sandbox_multiplier must be 3, "
            f"got {billing.get('sandbox_multiplier')!r}"
        )
    if billing.get("non_preemptible_multiplier") != 3:
        raise CapabilityError(
            "model.modal_pricing_registration: non_preemptible_multiplier "
            f"must be 3, got {billing.get('non_preemptible_multiplier')!r}"
        )
    region = billing.get("region_multiplier")
    if not isinstance(region, dict) or region.get("min") != 1.15 or region.get("max") != 1.75:
        raise CapabilityError(
            "model.modal_pricing_registration: region_multiplier must be "
            f"1.15-1.75, got {region!r}"
        )
    plans = config.get("plans")
    if not isinstance(plans, dict):
        raise CapabilityError("model.modal_pricing_registration: plans must be a JSON object")
    starter = plans.get("Starter")
    if not isinstance(starter, dict) or starter.get("monthly_fee_usd") != 0:
        raise CapabilityError(
            "model.modal_pricing_registration: Starter monthly_fee_usd must be 0"
        )
    if starter.get("free_credit_usd") != 30 or starter.get("seats") != 3:
        raise CapabilityError(
            "model.modal_pricing_registration: Starter must carry $30/month "
            "free credit and 3 seats"
        )
    if starter.get("concurrency") != {"containers": 100, "gpus": 10}:
        raise CapabilityError(
            "model.modal_pricing_registration: Starter concurrency must be "
            "100 containers + 10 GPUs"
        )
    if starter.get("free_egress") != "1 TiB":
        raise CapabilityError(
            "model.modal_pricing_registration: Starter free_egress must be '1 TiB'"
        )
    team = plans.get("Team")
    if not isinstance(team, dict) or team.get("monthly_fee_usd") != 250:
        raise CapabilityError(
            "model.modal_pricing_registration: Team monthly_fee_usd must be 250"
        )
    if team.get("free_credit_usd") != 100 or team.get("seats") != "unlimited":
        raise CapabilityError(
            "model.modal_pricing_registration: Team must carry $100/month "
            "free credit and unlimited seats"
        )
    if team.get("concurrency") != {"containers": 5000, "gpus": 50}:
        raise CapabilityError(
            "model.modal_pricing_registration: Team concurrency must be "
            "5000 containers + 50 GPUs"
        )
    if team.get("free_egress") != "10 TiB":
        raise CapabilityError(
            "model.modal_pricing_registration: Team free_egress must be '10 TiB'"
        )
    enterprise = plans.get("Enterprise")
    if not isinstance(enterprise, dict) or enterprise.get("monthly_fee_usd") != "custom":
        raise CapabilityError(
            "model.modal_pricing_registration: Enterprise monthly_fee_usd "
            "must be 'custom'"
        )
    for price_field in ("gpu_prices", "cpu_prices"):
        if config.get(price_field) != "unverified":
            raise CapabilityError(
                f"model.modal_pricing_registration: {price_field} must stay "
                "'unverified' (the captured page text states no per-unit "
                f"price), got {config.get(price_field)!r}"
            )
    for flag in ("account_registered", "payment_method_on_file",
                 "api_connected", "api_key_stored"):
        if config.get(flag) is not False:
            raise CapabilityError(
                f"model.modal_pricing_registration: {flag} must be false "
                "(registration only: no account, no payment method, "
                "no API connection, no stored key)"
            )
    if config.get("verified") is not False or config.get("status") != "unverified":
        raise CapabilityError(
            "model.modal_pricing_registration: the record must stay unverified"
        )
    return dict(config)


def record_in_directory(directory_path: Path) -> dict[str, dict[str, Any]]:
    """Record the Modal compute record (unverified) in a model-directory JSON file.

    Delegates to the single write path
    ``model.model_directory.record_in_directory``: the record lands
    with ``status: unverified`` and ``verified_at: null``. No account
    is created, no money moves, no network call is made, and no Modal
    API is connected.
    """
    config = validate_modal_config(modal_pricing_config())
    return record_models_in_directory(
        Path(directory_path), {MODAL_MODEL_ID: config}
    )


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = str(params.get("action") or "describe")
    if action == "describe":
        result: dict[str, Any] = {
            "capability": "model.modal_pricing_registration",
            "modal": modal_pricing_config(),
            "note": (
                "Registration only: the record is unverified, no account "
                "was registered, no payment method was stored, no API key "
                "was stored, no Modal API was connected, and no generation "
                "was performed. Per-unit GPU/CPU prices stay 'unverified'."
            ),
        }
    elif action == "record":
        directory_path = Path(params["directory_path"])
        records = record_in_directory(directory_path)
        result = {
            "capability": "model.modal_pricing_registration",
            "directory_path": str(directory_path),
            "records": records,
        }
    else:
        raise CapabilityError(
            f"model.modal_pricing_registration: unknown action {action!r}; "
            "known: describe, record"
        )
    report_path = out_dir / "modal_pricing_registration_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_modal_pricing_registration_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.modal_pricing_registration",
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
                "Modal compute pricing, registration only: records the "
                "Starter ($0/month + compute, $30 credit, 3 seats, "
                "100 containers + 10 GPUs, 1 TiB egress), Team "
                "($250/month + compute, $100 credit, unlimited seats, "
                "5000 containers + 50 GPUs, 10 TiB egress) and "
                "Enterprise (custom) tiers from the modal.com/pricing "
                "page text read 2026-11-01, with per-second billing, "
                "billed 60-second keep-alive, 3x sandbox and "
                "non-preemptible multipliers and 1.15x-1.75x region "
                "multipliers. Per-unit GPU/CPU prices stay 'unverified'. "
                "No account, no payment, no API key, no generation, "
                "no network."
            ),
            line="model",
        )
    )
    return ["model.modal_pricing_registration"]


register_modal_pricing_registration_capabilities_once()
