"""Capture kit schema (``video.capture_kit_schema``).

Contract-only schema for a page-capture kit: the three artifacts
a capture run produces, and the discipline the run must satisfy.
The kit is a full-page screenshot at double scale, a transparent
cutout per captured element, and a layout table of element
bounding boxes. Capture runs locally against a locally running
product, with demonstration data seeded first; real customer data
never enters the kit, and pages behind a login or a paywall are
not captured at all. Copy is written from the project brief or
from user-supplied words; nothing in this schema extracts words
from a page. This module captures nothing: ``executed_here`` is
always false and ``output_file`` is always null. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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

# The three capture artifacts, in production order.
CAPTURE_ARTIFACTS: tuple[str, ...] = (
    "full_page_screenshot",
    "element_cutout",
    "layout_table",
)

# Full-page screenshot geometry, restated from the capture method:
# a 1920 by 1080 viewport at double scale.
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080
DEVICE_SCALE_FACTOR = 2


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _check_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        _fail("capture kit request must be a JSON object")
    if request.get("runs_locally") is not True:
        _fail("capture requires the product to run locally")
    if request.get("seeding_declared") is not True:
        _fail("demonstration data seeding must be declared before capture")
    if request.get("real_customer_data") is not False:
        _fail("real customer data must never enter a capture kit")
    if request.get("auth_required") is True:
        _fail("pages behind a login are not captured; fail closed")
    if request.get("paywall_present") is True:
        _fail("content behind a paywall is not captured; fail closed")
    artifacts = request.get("artifacts")
    if artifacts is None:
        artifacts_out = list(CAPTURE_ARTIFACTS)
    elif isinstance(artifacts, list):
        unknown = [a for a in artifacts if a not in CAPTURE_ARTIFACTS]
        if unknown:
            _fail(f"artifacts outside the capture kit: {unknown}")
        artifacts_out = list(artifacts)
    else:
        _fail("artifacts must be a list when present")
    return {
        "artifacts": artifacts_out,
        "viewport": {
            "width": VIEWPORT_WIDTH,
            "height": VIEWPORT_HEIGHT,
            "device_scale_factor": DEVICE_SCALE_FACTOR,
        },
        "cutout_background": "transparent",
        "layout_table_fields": ["element", "x", "y", "width", "height"],
        "copy_source": "brief_or_user_supplied",
        "copy_extracted_from_page": False,
    }


def compile_capture_kit_contract(request: Any = None) -> dict[str, Any]:
    """Compile a capture kit contract from a capture request.

    ``request`` may be null (kit shape only) or a capture request
    object. Discipline violations raise :class:`CapabilityError`.
    Nothing is captured here.
    """
    if request is None:
        checked = {
            "artifacts": list(CAPTURE_ARTIFACTS),
            "viewport": {
                "width": VIEWPORT_WIDTH,
                "height": VIEWPORT_HEIGHT,
                "device_scale_factor": DEVICE_SCALE_FACTOR,
            },
            "cutout_background": "transparent",
            "layout_table_fields": ["element", "x", "y", "width", "height"],
            "copy_source": "brief_or_user_supplied",
            "copy_extracted_from_page": False,
        }
    elif isinstance(request, dict):
        checked = _check_request(request)
    else:
        _fail("capture kit request must be a JSON object or null")
    return {
        "kit": checked,
        "captured_here": False,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_capture_kit_contract(params.get("request"))
    contract_path = out_dir / "capture_kit_schema.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_capture_kit_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.capture_kit_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "request": {"type": ["object", "null"]},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Capture kit schema (contract only): full-page "
                "screenshot, per-element transparent cutout, and "
                "layout table, under local-run, seeding, and "
                "no-login/no-paywall discipline; nothing is "
                "captured here."
            ),
        )
    )
    return ["video.capture_kit_schema"]


__all__ = [
    "CAPTURE_ARTIFACTS",
    "DEVICE_SCALE_FACTOR",
    "VIEWPORT_HEIGHT",
    "VIEWPORT_WIDTH",
    "compile_capture_kit_contract",
    "register_capture_kit_schema_capabilities_once",
]
