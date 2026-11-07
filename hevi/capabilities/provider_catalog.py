"""Supplier directory: ``model.provider_catalog``.

Pixelle-Video idea, hevi implementation (clean-room: no Pixelle-Video
code, text, or structure is copied). ``model.model_catalog`` already
holds the model ids and per-image prices; this module extends that
catalogue into a *supplier* directory without duplicating its price
table:

* each supplier entry carries a name, the three route identifiers
  (``direct_api`` / ``comfyui`` / ``runninghub``) with a per-route
  ``supported`` flag, its own model mapping, and its own config
  (auth/endpoint environment variable names only, never values);
* ``central_config()`` is the single centralized config entry point:
  it reports, per supplier, which credential env vars exist and
  whether each is set (boolean only -- values are never read out);
* the cost gate is the ``model.model_catalog`` gate, same rule:
  ``allow_paid`` defaults to False and a call that has not explicitly
  accepted paid billing is refused BEFORE any key is read and BEFORE
  any network call. An unknown price (``null`` in the source data, or
  a supplier whose pricing is not per-image at all, e.g. PixStag
  video credits) is never guessed: the estimate is ``None`` and the
  caller who passes ``allow_paid=True`` accepts billing at an
  unverified rate, flagged ``unknown_price_accepted``.

Data lives in ``model_catalog_data/providers.json`` next to
``models.json``; every helper below reads that file, so a supplier
change is a data edit, not a code edit. Per-image prices are resolved
through ``model_catalog`` -- this module keeps no price copy, and the
test suite checks the two agree for every Gemini model.

DashScope is deliberately absent from the directory: the account is
in arrears and hevi has no verified supplier mapping for it, so no
default route to it exists here. Adding it later means adding a
verified data entry, not flipping a default.

Mounting (item 4对照): this module mounts exactly the way
``talking_head.render`` mounts -- it registers on the unified
capability registry and is imported by
``hevi/capabilities/__init__.py`` (the G13 guard:
``tests/test_capability_catalogue_completeness.py`` fails if the
import is missing). The talking_head line itself has no plugin or
extension registry -- its pipeline stages (preflight / TTS /
lip-sync / gates / ledger) are direct imports, not pluggable mounts
-- so no second mounting mechanism is built here; the registry is
the one mount point, and it is reused.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities import model_catalog
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
_DATA_DIR = Path(__file__).resolve().parent / "model_catalog_data"
_DATA_FILE = _DATA_DIR / "providers.json"
ROUTES = ("direct_api", "comfyui", "runninghub")
IMAGE_SIZES = ("1K", "2K", "4K")


def _load_raw() -> dict[str, Any]:
    try:
        doc = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CapabilityError(
            f"model.provider_catalog: cannot load providers.json: {exc}"
        ) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("providers"), list):
        raise CapabilityError(
            "model.provider_catalog: providers.json must be an object "
            "with a 'providers' list"
        )
    return doc


def load_providers_doc() -> dict[str, Any]:
    """Whole supplier directory document, as stored."""
    return _load_raw()


def list_providers() -> list[dict[str, Any]]:
    """All supplier entries, in file order, without mutating the file."""
    return [dict(p) for p in _load_raw()["providers"]]


def get_provider(key: str) -> dict[str, Any]:
    """Resolve a supplier by key; unknown -> error, never a fallback."""
    wanted = str(key or "").strip()
    for provider in _load_raw()["providers"]:
        if provider["key"] == wanted:
            return dict(provider)
    known = [p["key"] for p in _load_raw()["providers"]]
    raise CapabilityError(
        f"model.provider_catalog: unknown supplier {wanted!r}; "
        f"known suppliers: {', '.join(known)}"
    )


def list_routes(provider_key: str) -> dict[str, Any]:
    """The three route entries for one supplier, keyed by route name."""
    provider = get_provider(provider_key)
    routes = provider.get("routes")
    if not isinstance(routes, dict):
        raise CapabilityError(
            f"model.provider_catalog: supplier {provider_key!r} has no routes"
        )
    missing = [r for r in ROUTES if r not in routes]
    if missing:
        raise CapabilityError(
            f"model.provider_catalog: supplier {provider_key!r} is missing "
            f"route entries {missing}; every supplier must declare all "
            f"three routes (supported or explicitly unsupported)"
        )
    return {route: dict(routes[route]) for route in ROUTES}


def get_route(provider_key: str, route: str) -> dict[str, Any]:
    """One route entry; unknown route or supplier -> error."""
    routes = list_routes(provider_key)
    if route not in routes:
        raise CapabilityError(
            f"model.provider_catalog: unknown route {route!r}; "
            f"want one of {', '.join(ROUTES)}"
        )
    return routes[route]


def central_config() -> dict[str, Any]:
    """Centralized config entry point: env var names + set/unset only.

    Returns, per supplier, the auth/endpoint env var names from the
    data file and a boolean per name for whether it is set in the
    environment. Credential *values* are never read, returned, or
    logged here -- only presence booleans.
    """
    out: dict[str, Any] = {}
    for provider in _load_raw()["providers"]:
        config = provider.get("config") or {}
        auth_env = list(config.get("auth_env") or [])
        endpoint_env = list(config.get("endpoint_env") or [])
        out[provider["key"]] = {
            "auth_env": auth_env,
            "endpoint_env": endpoint_env,
            "auth_configured": {name: bool(os.environ.get(name)) for name in auth_env},
            "endpoint_configured": {
                name: bool(os.environ.get(name)) for name in endpoint_env
            },
            "notes": config.get("notes", ""),
        }
    return out


def resolve_provider_model(provider_key: str, model_key_or_id: str) -> dict[str, Any]:
    """Map a supplier-local model key (or model id) to its model id."""
    provider = get_provider(provider_key)
    models = provider.get("models") or {}
    wanted = str(model_key_or_id or "").strip()
    for model_key, model_id in models.items():
        if wanted in (model_key, model_id):
            return {
                "provider": provider["key"],
                "model_key": model_key,
                "model_id": model_id,
            }
    raise CapabilityError(
        f"model.provider_catalog: supplier {provider_key!r} has no model "
        f"{wanted!r}; known models: {', '.join(sorted(models))}"
    )


def estimate_provider_cost(
    provider_key: str,
    model_key_or_id: str,
    image_size: str = "1K",
    n: int = 1,
) -> dict[str, Any]:
    """Pre-generation estimate for one supplier + model. No network.

    For suppliers whose prices live in ``model_catalog`` (Gemini API)
    the estimate is delegated to it, so the two can never drift apart.
    For every other supplier the per-image price is unverified or not
    per-image at all, so ``estimated_cost_usd`` is ``None`` and
    ``price_known`` is False -- never invented.
    """
    provider = get_provider(provider_key)
    resolved = resolve_provider_model(provider_key, model_key_or_id)
    if image_size not in IMAGE_SIZES:
        raise CapabilityError(
            f"model.provider_catalog: unsupported image_size {image_size!r}; "
            f"want one of {', '.join(IMAGE_SIZES)}"
        )
    if isinstance(n, bool) or not isinstance(n, int) or n < 1 or n > 4:
        raise CapabilityError("model.provider_catalog: n must be an integer 1..4")
    if provider.get("price_source") == "model_catalog":
        estimate = model_catalog.estimate_cost(resolved["model_id"], image_size, n)
        return {
            "provider": provider["key"],
            "model_key": resolved["model_key"],
            "model_id": resolved["model_id"],
            "paid": bool(provider.get("paid", True)),
            "price_source": "model_catalog",
            "image_size": image_size,
            "n": n,
            "per_image_usd": estimate["per_image_usd"],
            "price_known": estimate["price_known"],
            "estimated_cost_usd": estimate["estimated_cost_usd"],
            "cost_note": estimate["cost_note"],
        }
    note = provider.get("notes", "")
    if provider.get("price_source") == "per_second_credit_not_per_image":
        note = (
            "This supplier bills video by the second (credits), not "
            "images: no per-image estimate exists. " + note
        )
    else:
        note = (
            "Per-image price NOT verified for this supplier; actual "
            "billing is per the key's project. allow_paid=True accepts "
            "that unknown rate. " + note
        )
    return {
        "provider": provider["key"],
        "model_key": resolved["model_key"],
        "model_id": resolved["model_id"],
        "paid": bool(provider.get("paid", True)),
        "price_source": provider.get("price_source"),
        "image_size": image_size,
        "n": n,
        "per_image_usd": None,
        "price_known": False,
        "estimated_cost_usd": None,
        "cost_note": note,
    }


def check_provider_cost_gate(estimate: dict[str, Any], allow_paid: bool) -> dict[str, Any]:
    """Same gate as ``model_catalog.check_cost_gate``, supplier flavoured."""
    if not allow_paid:
        raise CapabilityError(
            "model.provider_catalog: refused -- generation against "
            f"{estimate['provider']}/{estimate['model_id']} would bill "
            "the key's project. Pass allow_paid=true to explicitly "
            "accept paid billing for this call."
        )
    out = dict(estimate)
    out["cost_gate"] = "allowed"
    out["unknown_price_accepted"] = not estimate["price_known"]
    return out


def estimate_and_gate(
    provider_key: str,
    model_key_or_id: str,
    image_size: str = "1K",
    n: int = 1,
    allow_paid: bool = False,
) -> dict[str, Any]:
    """One-call convenience: estimate, then enforce the gate."""
    return check_provider_cost_gate(
        estimate_provider_cost(provider_key, model_key_or_id, image_size, n),
        allow_paid,
    )


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = str(params.get("action") or "list")
    if action == "list":
        payload: dict[str, Any] = {"action": "list", "providers": list_providers()}
    elif action == "get":
        payload = {"action": "get", "provider": get_provider(str(params["provider"]))}
    elif action == "routes":
        payload = {
            "action": "routes",
            "provider": str(params["provider"]),
            "routes": list_routes(str(params["provider"])),
        }
    elif action == "central_config":
        payload = {"action": "central_config", "config": central_config()}
    elif action == "estimate":
        gated = params.get("allow_paid", False)
        estimate = estimate_provider_cost(
            str(params["provider"]),
            str(params["model"]),
            str(params.get("image_size", "1K")),
            int(params.get("n", 1)),
        )
        payload = {
            "action": "estimate",
            "estimate": estimate if not gated else check_provider_cost_gate(estimate, True),
            "cost_gate": "allowed" if gated else "refused",
        }
        if not gated:
            check_provider_cost_gate(estimate, False)
    else:
        raise CapabilityError(f"model.provider_catalog: unknown action {action!r}")
    report = Path(out_dir) / "provider_catalog.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_provider_catalog_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.provider_catalog",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "routes", "central_config", "estimate"],
                    },
                    "provider": {"type": "string"},
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
                "Supplier directory extending model.model_catalog: "
                "suppliers with direct_api / comfyui / runninghub route "
                "flags, per-supplier model mappings and centralized "
                "config (env var names + set/unset only, never values), "
                "plus the same allow_paid cost gate (default refuse; "
                "unknown prices reported as null, never invented). "
                "Per-image prices are resolved through model_catalog, "
                "never duplicated here."
            ),
            line="model_catalog",
        )
    )
    return ["model.provider_catalog"]


register_provider_catalog_capabilities_once()
