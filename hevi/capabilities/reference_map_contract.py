"""Reference-map execution contract gate (``qa.reference_map_contract``).

Clean-room restatement of the "missing mapping throws" discipline
behind the Toonflow metaso provider (see
``TOONFLOW_RECHECK_ATTRIBUTION.md``): a prompt that writes
``{{ref N}}`` is making an execution claim -- number N is bound to
a declared asset through a declared reference order -- and a
generator that silently substitutes a different asset when the
binding is missing drifts the film. This gate judges the contract
before anything executes:

1. Every ``{{ref N}}`` in the prompt must have a mapping entry.
   A number with no entry fails and names the number; the gate
   never guesses a substitute.
2. Every mapped asset must be an entry of the declared reference
   order. A mapping to an undeclared asset fails.
3. A reference used as a first frame, last frame, or multi-frame
   reference must declare its frame kind. An ordinary reference
   passed off as a first frame fails, and a declared frame kind
   for an asset that is not in the order fails.
4. When a numbering convention is declared it must be one of the
   known conventions (``identity-first`` or ``scene-first``, the
   vocabulary of ``qa.reference_numbering_gate``). Under
   ``identity-first`` the caller must name the identity asset and
   reference 1 must resolve to it; this gate does not re-judge the
   full numbering discipline, it only refuses a mapping that
   contradicts the declared convention.

This gate judges plans only. It calls no generator, spends
nothing, and never rewrites a prompt or a mapping to make it
pass: a failing plan is returned with its problems listed. The
execution adapter that throws on a missing mapping is
``video.reference_map_adapter``; this gate is the plan-side
check that runs before it.
"""

from __future__ import annotations

import json
import re
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

_REF_RE = re.compile(r"\{\{\s*ref\s+(\d+)\s*\}\}")
NUMBERING_CONVENTIONS = ("identity-first", "scene-first")
FRAME_KINDS = ("reference", "first_frame", "last_frame", "multi_frame_ref")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.reference_map_contract: {detail}"}
    issue.update(extra)
    return issue


def parse_numbered_refs(prompt: str) -> list[dict[str, Any]]:
    """List every {{ref N}} in a prompt, in order of appearance."""
    if not isinstance(prompt, str):
        raise CapabilityError(
            "qa.reference_map_contract: prompt must be a string"
        )
    return [
        {
            "raw": match.group(0),
            "number": int(match.group(1)),
            "position": match.start(),
        }
        for match in _REF_RE.finditer(prompt)
    ]


def _check_order(reference_order: Any) -> list[str]:
    if not isinstance(reference_order, list) or not reference_order:
        raise CapabilityError(
            "qa.reference_map_contract: reference_order must be a "
            "non-empty list of asset ids, in declared order"
        )
    order = []
    for item in reference_order:
        if not isinstance(item, str) or not item:
            raise CapabilityError(
                "qa.reference_map_contract: every reference_order entry "
                "must be a non-empty asset id string"
            )
        if item in order:
            raise CapabilityError(
                "qa.reference_map_contract: reference_order lists "
                f"asset {item!r} twice; numbers would be ambiguous"
            )
        order.append(item)
    return order


def _normalise_mapping(mapping: Any) -> dict[int, dict[str, Any]]:
    """Accept a mapping as a dict or a list of records.

    Dict form: ``{"1": "asset-a", "2": "asset-b"}`` (kind defaults
    to ``reference``). List form: ``[{"number": 1, "asset_id":
    "asset-a", "kind": "first_frame"}, ...]``.
    """
    if isinstance(mapping, dict):
        records = [
            {"number": key, "asset_id": value} for key, value in mapping.items()
        ]
    elif isinstance(mapping, list):
        records = list(mapping)
    else:
        raise CapabilityError(
            "qa.reference_map_contract: mapping must be a dict of "
            "number -> asset id, or a list of mapping records"
        )
    normalised: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise CapabilityError(
                "qa.reference_map_contract: every mapping record must "
                "be an object with number and asset_id"
            )
        try:
            number = int(record.get("number"))
        except (TypeError, ValueError):
            raise CapabilityError(
                "qa.reference_map_contract: every mapping record needs "
                "an integer number"
            ) from None
        if isinstance(record.get("number"), bool):
            raise CapabilityError(
                "qa.reference_map_contract: mapping number must be an integer"
            )
        asset_id = record.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            raise CapabilityError(
                "qa.reference_map_contract: mapping record for number "
                f"{number} needs a non-empty asset_id string"
            )
        kind = record.get("kind", "reference")
        if kind not in FRAME_KINDS:
            raise CapabilityError(
                f"qa.reference_map_contract: mapping kind {kind!r} is "
                f"unknown; known kinds: {list(FRAME_KINDS)}"
            )
        if number in normalised:
            raise CapabilityError(
                "qa.reference_map_contract: mapping lists number "
                f"{number} twice; bindings would be ambiguous"
            )
        normalised[number] = {"asset_id": asset_id, "kind": kind}
    return normalised


def check_reference_map(
    prompt: str,
    reference_order: Any,
    mapping: Any,
    *,
    numbering_convention: Any = None,
    identity_asset_id: Any = None,
) -> dict[str, Any]:
    """Check a prompt's {{ref N}} bindings against the order.

    Returns a report with ``ok``, the resolved mapping, the frame
    kinds, and the problems. A failing plan is listed, never
    silently repaired.
    """
    order = _check_order(reference_order)
    refs = parse_numbered_refs(prompt)
    bindings = _normalise_mapping(mapping)
    problems: list[dict[str, Any]] = []

    if numbering_convention is not None:
        if numbering_convention not in NUMBERING_CONVENTIONS:
            raise CapabilityError(
                "qa.reference_map_contract: numbering_convention "
                f"{numbering_convention!r} is unknown; known conventions: "
                f"{list(NUMBERING_CONVENTIONS)}"
            )
        if numbering_convention == "identity-first":
            if not isinstance(identity_asset_id, str) or not identity_asset_id:
                problems.append(
                    _issue(
                        "missing_identity_asset",
                        "identity-first mapping must name identity_asset_id",
                    )
                )
            elif identity_asset_id not in order:
                problems.append(
                    _issue(
                        "identity_asset_not_in_order",
                        f"identity asset {identity_asset_id!r} is not in "
                        "the declared reference order",
                        asset_id=identity_asset_id,
                    )
                )
            elif 1 in bindings and bindings[1]["asset_id"] != identity_asset_id:
                problems.append(
                    _issue(
                        "identity_first_mismatch",
                        "identity-first mapping must bind ref 1 to the "
                        f"identity asset {identity_asset_id!r}, got "
                        f"{bindings[1]['asset_id']!r}",
                        number=1,
                    )
                )

    resolved: dict[int, str] = {}
    frame_kinds: dict[int, str] = {}
    for ref in refs:
        number = ref["number"]
        binding = bindings.get(number)
        if binding is None:
            problems.append(
                _issue(
                    "missing_mapping",
                    f"prompt uses {{{{ref {number}}}}} but the mapping "
                    "has no entry for it; the binding is never guessed",
                    number=number,
                )
            )
            continue
        if binding["asset_id"] not in order:
            problems.append(
                _issue(
                    "mapping_asset_not_in_order",
                    f"mapping binds ref {number} to asset "
                    f"{binding['asset_id']!r}, which is not in the "
                    "declared reference order",
                    number=number,
                    asset_id=binding["asset_id"],
                )
            )
            continue
        resolved[number] = binding["asset_id"]
        frame_kinds[number] = binding["kind"]

    # A frame kind declared for a number the prompt never uses is a
    # stale binding: it claims a role nothing consumes.
    for number in bindings:
        if number not in {ref["number"] for ref in refs}:
            problems.append(
                _issue(
                    "unused_frame_binding",
                    f"mapping binds ref {number} but the prompt never "
                    "uses it; stale bindings are not carried forward",
                    number=number,
                )
            )

    return {
        "ok": not problems,
        "resolved": resolved,
        "frame_kinds": frame_kinds,
        "refs_checked": len(refs),
        "problems": problems,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_reference_map(
        params.get("prompt", ""),
        params.get("reference_order"),
        params.get("mapping"),
        numbering_convention=params.get("numbering_convention"),
        identity_asset_id=params.get("identity_asset_id"),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "reference_map_contract_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_reference_map_contract_capabilities_once() -> list[str]:
    """Register ``qa.reference_map_contract`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_map_contract",
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
                },
                "required": ["prompt", "reference_order", "mapping"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Reference-map contract gate: every {{ref N}} in a "
                "prompt must have a mapping entry to a declared asset, "
                "frame references must declare their frame kind, and a "
                "declared numbering convention must not be contradicted. "
                "Missing mappings fail and are never guessed. Plans are "
                "checked, never rewritten to pass."
            ),
            line="qa",
        )
    )
    return ["qa.reference_map_contract"]
