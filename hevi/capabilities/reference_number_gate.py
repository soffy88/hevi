"""Reference-number gate (``qa.reference_number_gate``).

A prompt that says {{ref 3}} is making a claim: the third
reference in the declared order is connected, and it is the
asset the prompt means. When that claim is wrong, the generator
does not fail; it quietly uses the wrong picture, and the film
drifts. This gate checks the claim before generation runs:

1. Every {{ref N}} in a prompt must resolve to an entry in the
   declared reference order. A number with no entry fails and
   names the number; the gate never guesses a substitute.
2. First-frame mode and multi-parameter mode are different
   modes, and a prompt must say which one it is. In first-frame
   mode the prompt's references must resolve to the one
   designated first-frame asset. A three-view sheet is a
   reference sheet, not a first frame, and fails in first-frame
   mode when it is presented as one.
3. Edges are real connections, not decoration. An edge whose
   endpoint is script text, or whose endpoints are not in the
   declared node set, fails and names the edge.
4. Reordering the reference list changes what every number
   means, so a prompt must be rechecked after any reorder. The
   gate returns the resolved mapping, so the caller can see
   exactly what changed.

This gate reads prompts and connection lists only. It calls no
generator, spends nothing, and never rewrites a prompt to make
it pass: a failing prompt is returned with its problems listed.

Method ideas borrowed, text self-written, from
HBAI-Ltd/Toonflow-app (MIT, verified against the repository
LICENSE file; the MIT licence covers that repository only, not
model services or generated material). No Toonflow text, code or
assets are copied here.
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
MODES = ("first_frame", "multi_param")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_numbered_refs(prompt: str) -> list[dict[str, Any]]:
    """List every {{ref N}} in a prompt, in order of appearance."""
    if not isinstance(prompt, str):
        raise CapabilityError(
            "qa.reference_number_gate: prompt must be a string"
        )
    refs = []
    for match in _REF_RE.finditer(prompt):
        refs.append({
            "raw": match.group(0),
            "number": int(match.group(1)),
            "position": match.start(),
        })
    return refs


def _check_order(reference_order: Any) -> list[str]:
    if not isinstance(reference_order, list) or not reference_order:
        raise CapabilityError(
            "qa.reference_number_gate: reference_order must be a "
            "non-empty list of asset ids, in declared order"
        )
    order = []
    for item in reference_order:
        if not isinstance(item, str) or not item:
            raise CapabilityError(
                "qa.reference_number_gate: every reference_order entry "
                "must be a non-empty asset id string"
            )
        if item in order:
            raise CapabilityError(
                f"qa.reference_number_gate: reference_order lists "
                f"asset {item!r} twice; numbers would be ambiguous"
            )
        order.append(item)
    return order


def check_references(
    prompt: str,
    reference_order: Any,
    *,
    mode: str,
    first_frame_asset_id: Any = None,
    three_view_asset_ids: Any = None,
) -> dict[str, Any]:
    """Check a prompt's {{ref N}} claims against the order.

    Returns a report with ``ok``, the resolved mapping and the
    problems. Use assert_references when a failure must stop
    generation instead of being listed.
    """
    order = _check_order(reference_order)
    if mode not in MODES:
        raise CapabilityError(
            f"qa.reference_number_gate: mode {mode!r} is unknown; "
            f"known modes: {list(MODES)}"
        )
    three_view = set(three_view_asset_ids or [])
    problems: list[str] = []
    resolved: list[dict[str, Any]] = []
    for ref in parse_numbered_refs(prompt):
        number = ref["number"]
        if number < 1 or number > len(order):
            problems.append(
                f"unconfirmed ref {number} ({ref['raw']}): no entry "
                f"at that position in the declared reference order; "
                f"the reference is not guessed and generation must "
                f"not run on it"
            )
            continue
        asset_id = order[number - 1]
        resolved.append({
            "raw": ref["raw"],
            "number": number,
            "asset_id": asset_id,
        })
        if mode == "first_frame":
            if first_frame_asset_id is not None and asset_id != first_frame_asset_id:
                problems.append(
                    f"first-frame mode: {ref['raw']} resolves to "
                    f"{asset_id!r}, not the designated first-frame "
                    f"asset {first_frame_asset_id!r}"
                )
            if asset_id in three_view:
                problems.append(
                    f"first-frame mode: {ref['raw']} resolves to "
                    f"{asset_id!r}, which is a three-view reference "
                    f"sheet, not a first frame"
                )
    distinct = {r["asset_id"] for r in resolved}
    if mode == "first_frame" and len(distinct) > 1:
        problems.append(
            f"first-frame mode: prompt references {len(distinct)} "
            f"different assets {sorted(distinct)}; a first-frame "
            f"prompt resolves to exactly one designated asset"
        )
    return {
        "ok": not problems,
        "mode": mode,
        "resolved": resolved,
        "problems": problems,
    }


def assert_references(
    prompt: str,
    reference_order: Any,
    *,
    mode: str,
    first_frame_asset_id: Any = None,
    three_view_asset_ids: Any = None,
) -> dict[str, Any]:
    """Check references, raising when generation must not run."""
    report = check_references(
        prompt, reference_order, mode=mode,
        first_frame_asset_id=first_frame_asset_id,
        three_view_asset_ids=three_view_asset_ids,
    )
    if not report["ok"]:
        raise CapabilityError(
            "qa.reference_number_gate: generation refused: "
            + "; ".join(report["problems"])
        )
    return report


def validate_edges(
    edges: Any, node_ids: Any
) -> dict[str, Any]:
    """Check that edges are real connections, not decoration.

    Every edge needs a ref number and two endpoints that are in
    the declared node set. An edge touching script text, or an
    edge marked decorative, fails and names the edge. Script
    text describes a film; it is never itself a connection.
    """
    if not isinstance(edges, list):
        raise CapabilityError(
            "qa.reference_number_gate: edges must be a list"
        )
    nodes = set(node_ids or [])
    problems: list[str] = []
    checked = 0
    for index, edge in enumerate(edges):
        checked += 1
        if not isinstance(edge, dict):
            problems.append(f"edge {index} is not an object")
            continue
        if edge.get("decorative") is True:
            problems.append(
                f"edge {index} is marked decorative; decoration is "
                f"not a connection"
            )
        ref = edge.get("ref")
        if not _is_int(ref) or ref < 1:
            problems.append(
                f"edge {index} has no positive ref number"
            )
        for endpoint in ("source", "target"):
            value = edge.get(endpoint)
            if value == "script" or value == "script_text":
                problems.append(
                    f"edge {index} touches script text at {endpoint}; "
                    f"script text is not a connection"
                )
            elif value not in nodes:
                problems.append(
                    f"edge {index} endpoint {endpoint} {value!r} is "
                    f"not in the declared node set"
                )
    return {"ok": not problems, "edges_checked": checked, "problems": problems}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_references(
        params.get("prompt", ""),
        params.get("reference_order"),
        mode=params.get("mode", "multi_param"),
        first_frame_asset_id=params.get("first_frame_asset_id"),
        three_view_asset_ids=params.get("three_view_asset_ids"),
    )
    edge_report = None
    if "edges" in params:
        edge_report = validate_edges(
            params.get("edges"), params.get("node_ids", [])
        )
        if not edge_report["ok"]:
            report = dict(report)
            report["ok"] = False
            report["problems"] = list(report["problems"]) + [
                f"edge: {p}" for p in edge_report["problems"]
            ]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    full = {"references": report, "edges": edge_report}
    report_path = out_dir / "reference_number_gate_report.json"
    report_path.write_text(
        json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_reference_number_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_number_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "reference_order": {"type": "array"},
                    "mode": {"type": "string"},
                    "first_frame_asset_id": {"type": "string"},
                    "three_view_asset_ids": {"type": "array"},
                    "edges": {"type": "array"},
                    "node_ids": {"type": "array"},
                },
                "required": ["prompt", "reference_order"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Reference-number gate: every {{ref N}} in a prompt "
                "must resolve to the declared reference order, "
                "unconfirmed numbers are never guessed and refuse "
                "generation, first-frame and multi-parameter modes "
                "are kept apart (a three-view sheet is not a first "
                "frame), and edges must be real connections, never "
                "script text or decoration. Prompts are checked, "
                "never rewritten to pass."
            ),
            line="qa",
        )
    )
    return ["qa.reference_number_gate"]


register_reference_number_gate_capabilities_once()
