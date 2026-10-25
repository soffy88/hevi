"""Server-side model catalogue + pre-generation cost estimate + cost gate.

This is the one configured source for generation-model ids and prices.
Data lives in ``model_catalog_data/models.json`` next to this module;
every helper below reads that file, so a price change is a data edit,
not a code edit in each capability. Written from scratch for hevi:
no code, text, or structure is taken from any external editor project.

Cost-gate rule (same rule as ``image.nano_banana_generate``):
``allow_paid`` defaults to False and a call that has not explicitly
accepted paid billing is refused BEFORE any key is read and BEFORE
any network call. There is no environment variable that silently
enables paid calls. An unknown price (``null`` in the data file) is
never guessed: the estimate is ``None`` and the caller who passes
``allow_paid=True`` accepts billing at an unverified rate; the
estimate dict says so in plain words.

Model lookup accepts either the short key (``nano_banana_2.1``) or
the official model id (``gemini-nano-banana-2.1``); anything else is
a CapabilityError, never a silent fallback to the default model.
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
_DATA_DIR = Path(__file__).resolve().parent / "model_catalog_data"
_DATA_FILE = _DATA_DIR / "models.json"
IMAGE_SIZES = ("1K", "2K", "4K")

_COST_NOTE = (
    "Gemini API image generation has NO free tier (official pricing: "
    "Free Tier = Not available). Every call bills the key's project; "
    "allow_paid=True is the caller's explicit per-call acceptance."
)


def _load_raw() -> dict[str, Any]:
    try:
        return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CapabilityError(
            f"model.model_catalog: cannot load models.json: {exc}"
        ) from exc


def load_catalog() -> dict[str, Any]:
    """Whole catalogue document, as stored (models + source note)."""
    return _load_raw()


def list_models() -> list[dict[str, Any]]:
    """All catalogue models, in file order, without mutating the file."""
    return [dict(m) for m in _load_raw()["models"]]


def get_model(key_or_id: str) -> dict[str, Any]:
    """Resolve a short key or an official model id; unknown -> error."""
    wanted = str(key_or_id or "").strip()
    for model in _load_raw()["models"]:
        if wanted in (model["key"], model["model_id"]):
            return dict(model)
    known = [m["key"] for m in _load_raw()["models"]]
    raise CapabilityError(
        f"model.model_catalog: unknown model {wanted!r}; known keys: "
        f"{', '.join(known)}"
    )


def default_model_id() -> str:
    for model in _load_raw()["models"]:
        if model.get("default"):
            return str(model["model_id"])
    raise CapabilityError("model.model_catalog: catalogue has no default model")


def per_image_prices() -> dict[str, dict[str, float | None]]:
    """model_id -> {size: USD per image or None when unverified}."""
    return {
        str(m["model_id"]): dict(m["prices_usd_per_image"])
        for m in _load_raw()["models"]
    }


def estimate_cost(
    key_or_id: str, image_size: str = "1K", n: int = 1
) -> dict[str, Any]:
    """Pre-generation estimate. No network, no key, no billing here.

    Returns ``estimated_cost_usd`` as a float, or ``None`` when the
    price for that model/size was not verified (never invented).
    ``n`` outside 1..4 and an unknown size are errors, not clamps.
    """
    model = get_model(key_or_id)
    if image_size not in IMAGE_SIZES:
        raise CapabilityError(
            f"model.model_catalog: unsupported image_size {image_size!r}; "
            f"want one of {', '.join(IMAGE_SIZES)}"
        )
    if isinstance(n, bool) or not isinstance(n, int) or n < 1 or n > 4:
        raise CapabilityError("model.model_catalog: n must be an integer 1..4")
    per_image = model["prices_usd_per_image"].get(image_size)
    estimated = round(per_image * n, 6) if per_image is not None else None
    return {
        "key": model["key"],
        "model_id": model["model_id"],
        "product_name": model["product_name"],
        "provider": model["provider"],
        "paid": bool(model["paid"]),
        "image_size": image_size,
        "n": n,
        "per_image_usd": per_image,
        "price_known": per_image is not None,
        "estimated_cost_usd": estimated,
        "cost_note": (
            _COST_NOTE
            if estimated is not None
            else (
                "Per-image price NOT verified for this model/size; "
                "actual billing is per the key's project. "
                "allow_paid=True accepts that unknown rate."
            )
        ),
    }


def check_cost_gate(estimate: dict[str, Any], allow_paid: bool) -> dict[str, Any]:
    """Enforce the cost gate on an estimate dict from ``estimate_cost``.

    * ``allow_paid`` False -> always refused, known price or not.
    * ``allow_paid`` True + known price -> allowed, estimate stands.
    * ``allow_paid`` True + unknown price -> allowed with an explicit
      ``unknown_price_accepted`` flag; the estimate stays ``None``.
    A refusal raises CapabilityError before any generation call.
    """
    if not allow_paid:
        raise CapabilityError(
            "model.model_catalog: refused -- generation against "
            f"{estimate['model_id']} would bill the key's project "
            "(no free tier). Pass allow_paid=true to explicitly accept "
            "paid billing for this call."
        )
    out = dict(estimate)
    out["cost_gate"] = "allowed"
    out["unknown_price_accepted"] = not estimate["price_known"]
    return out


def estimate_and_gate(
    key_or_id: str,
    image_size: str = "1K",
    n: int = 1,
    allow_paid: bool = False,
) -> dict[str, Any]:
    """One-call convenience: estimate, then enforce the gate."""
    return check_cost_gate(estimate_cost(key_or_id, image_size, n), allow_paid)


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = str(params.get("action") or "list")
    if action == "list":
        payload: dict[str, Any] = {"action": "list", "models": list_models()}
    elif action == "get":
        payload = {"action": "get", "model": get_model(str(params["model"]))}
    elif action == "estimate":
        gated = params.get("allow_paid", False)
        estimate = estimate_cost(
            str(params["model"]),
            str(params.get("image_size", "1K")),
            int(params.get("n", 1)),
        )
        payload = {
            "action": "estimate",
            "estimate": estimate if not gated else check_cost_gate(estimate, True),
            "cost_gate": "allowed" if gated else "refused",
        }
        if not gated:
            # Report the refusal honestly: the capability render itself
            # raises, exactly like the nano_banana cost gate does.
            check_cost_gate(estimate, False)
    else:
        raise CapabilityError(f"model.model_catalog: unknown action {action!r}")
    report = Path(out_dir) / "model_catalog.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_model_catalog_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.model_catalog",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "estimate"],
                    },
                    "model": {"type": "string"},
                    "image_size": {"type": "string", "enum": list(IMAGE_SIZES)},
                    "n": {"type": "integer", "minimum": 1, "maximum": 4},
                    "allow_paid": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Server-side model catalogue: model ids, per-image USD "
                "prices and paid flags from a configured data file, plus "
                "a pre-generation cost estimate and the allow_paid cost "
                "gate (default refuse, explicit allow_paid=true only). "
                "Unknown prices are reported as null, never invented."
            ),
            line="model_catalog",
        )
    )
    return ["model.model_catalog"]


register_model_catalog_capabilities_once()
