"""Reference-map execution adapter (``video.reference_map_adapter``).

Fake execution adapter for the reference-map contract. The real
execution behaviour behind this adapter -- a generator that
refuses to run when a ``{{ref N}}`` has no binding -- lives in a
provider the caller supplies; this module only proves the
binding step, against a fake backend, so the contract can be
tested without a key, a model, or a GPU:

1. The prompt's ``{{ref N}}`` claims are checked by
   ``qa.reference_map_contract``. A missing mapping throws
   ``CapabilityError`` here, at bind time, instead of letting a
   generator silently substitute another asset.
2. A binding that passes is recorded: number, asset id, frame
   kind, and the sha of the bound asset when the caller supplies
   one. The record is the evidence the execution step consumed
   exactly the declared binding.
3. Frame references are bound only with a declared frame kind.
   A first-frame or last-frame role with no declared kind throws
   instead of binding as an ordinary reference.

No generator is called, no key is stored, nothing is spent.
Method ideas borrowed, text self-written, from
HBAI-Ltd/Toonflow-app (MIT, verified against the repository
LICENSE file; the MIT licence covers that repository only).
No Toonflow text, code or assets are copied here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.reference_map_contract import check_reference_map
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def bind_references(
    prompt: str,
    reference_order: Any,
    mapping: Any,
    *,
    numbering_convention: Any = None,
    identity_asset_id: Any = None,
    asset_shas: Any = None,
) -> dict[str, Any]:
    """Bind a prompt's {{ref N}} claims to declared assets (fake).

    Raises ``CapabilityError`` when any binding is missing, points
    at an undeclared asset, or contradicts the declared
    convention -- the execution-time throw. On success returns
    the binding record.
    """
    report = check_reference_map(
        prompt,
        reference_order,
        mapping,
        numbering_convention=numbering_convention,
        identity_asset_id=identity_asset_id,
    )
    if not report["ok"]:
        problems = "; ".join(
            f"{p['code']}: {p['detail']}" for p in report["problems"]
        )
        raise CapabilityError(
            "video.reference_map_adapter: reference binding failed; "
            f"execution refuses to guess: {problems}"
        )
    shas: dict[str, Any] = {}
    if asset_shas is not None:
        if not isinstance(asset_shas, dict):
            raise CapabilityError(
                "video.reference_map_adapter: asset_shas must be a dict "
                "of asset id -> sha256"
            )
        shas = dict(asset_shas)
    bindings = []
    for number in sorted(report["resolved"]):
        asset_id = report["resolved"][number]
        bindings.append(
            {
                "number": number,
                "asset_id": asset_id,
                "kind": report["frame_kinds"][number],
                "sha256": shas.get(asset_id),
            }
        )
    return {
        "ok": True,
        "bindings": bindings,
        "refs_bound": len(bindings),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    try:
        result = bind_references(
            params.get("prompt", ""),
            params.get("reference_order"),
            params.get("mapping"),
            numbering_convention=params.get("numbering_convention"),
            identity_asset_id=params.get("identity_asset_id"),
            asset_shas=params.get("asset_shas"),
        )
    except CapabilityError as exc:
        result = {"ok": False, "error": str(exc), "bindings": []}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / "reference_map_adapter_bindings.json"
    record_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(record_path),
        qa={
            "record_json": str(record_path),
            "ok": result["ok"],
        },
    )


def register_reference_map_adapter_capabilities_once() -> list[str]:
    """Register ``video.reference_map_adapter`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.reference_map_adapter",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "reference_order": {"type": "array"},
                    "mapping": {"type": ["object", "array"]},
                    "numbering_convention": {"type": "string"},
                    "identity_asset_id": {"type": "string"},
                    "asset_shas": {"type": "object"},
                },
                "required": ["prompt", "reference_order", "mapping"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Reference-map execution adapter (fake backend): binds "
                "every {{ref N}} to a declared asset before execution "
                "and throws instead of guessing when a binding is "
                "missing. No generator is called, no key is stored."
            ),
            line="video",
        )
    )
    return ["video.reference_map_adapter"]
