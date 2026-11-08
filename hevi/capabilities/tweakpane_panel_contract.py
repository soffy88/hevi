"""Tweakpane panel contract, fake layer (``video.tweakpane_panel_contract``).

Contract-only schema for a Tweakpane parameter panel
(``cocopon/tweakpane``, MIT): a titled panel whose parameters
declare a kind, a range or option set, and a default, with
optional bindings from parameter keys to caller-declared
target paths. The panel is a debugging and tuning tool only,
never a finished-film pipeline step, and this module creates
no DOM, binds nothing, and renders nothing: ``executed_here``
is always false, ``dom_created`` is always false, and
``output_file`` is always null. Maintenance has slowed, so
the library version is pinned by caller declaration only and
never assumed here. Real panel use is a separate case. See
OPEN_SKILLS_ATTRIBUTION.md.
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

LIBRARY_REPO = "cocopon/tweakpane"
LIBRARY_LICENSE = "MIT"
VERSION_STATUS = "maintenance slowed; version pinned by declaration"
PURPOSE = "debugging and tuning only; not a finished-film pipeline step"

_PARAMETER_KINDS: tuple[str, ...] = ("number", "boolean", "string", "choice")


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_parameter(parameter: Any, index: int) -> dict[str, Any]:
    if not isinstance(parameter, dict):
        _fail(f"parameters[{index}] must be an object")
    key = parameter.get("key")
    if not isinstance(key, str) or not key.strip():
        _fail(f"parameters[{index}] must declare a key")
    kind = parameter.get("kind")
    if kind not in _PARAMETER_KINDS:
        _fail(
            f"parameters[{index}] kind must be one of "
            f"{list(_PARAMETER_KINDS)}"
        )
    default = parameter.get("default")
    out: dict[str, Any] = {"key": key, "kind": kind}
    if kind == "number":
        minimum = parameter.get("min")
        maximum = parameter.get("max")
        if not _is_number(minimum) or not _is_number(maximum):
            _fail(f"parameters[{index}] number needs numeric min and max")
        if not minimum < maximum:
            _fail(f"parameters[{index}] min must be below max")
        if not _is_number(default) or not minimum <= default <= maximum:
            _fail(
                f"parameters[{index}] default must be a number "
                "inside [min, max]"
            )
        step = parameter.get("step")
        if step is not None and (not _is_number(step) or step <= 0):
            _fail(f"parameters[{index}] step must be a positive number")
        out.update(
            {"min": float(minimum), "max": float(maximum),
             "step": step, "default": float(default)}
        )
    elif kind == "boolean":
        if not isinstance(default, bool):
            _fail(f"parameters[{index}] boolean default must be true/false")
        out["default"] = default
    elif kind == "string":
        if not isinstance(default, str):
            _fail(f"parameters[{index}] string default must be a string")
        out["default"] = default
    else:  # choice
        options = parameter.get("options")
        if (
            not isinstance(options, list)
            or not options
            or not all(isinstance(o, str) and o for o in options)
        ):
            _fail(
                f"parameters[{index}] choice needs a non-empty "
                "list of string options"
            )
        if default not in options:
            _fail(
                f"parameters[{index}] choice default must be one "
                "of its options"
            )
        out.update({"options": list(options), "default": default})
    return out


def compile_tweakpane_panel_contract(plan: Any) -> dict[str, Any]:
    """Compile a Tweakpane panel contract from a plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``
    and ``dom_created: false``: no panel is created here.
    """
    if not isinstance(plan, dict):
        _fail("tweakpane panel plan must be a JSON object")
    panel = plan.get("panel")
    if not isinstance(panel, dict):
        _fail("tweakpane plan must declare a panel object")
    title = panel.get("title")
    if not isinstance(title, str) or not title.strip():
        _fail("panel must declare a title")
    parameters = plan.get("parameters")
    if not isinstance(parameters, list) or not parameters:
        _fail("tweakpane plan must declare a non-empty parameters list")
    seen: set[str] = set()
    parameters_out: list[dict[str, Any]] = []
    for index, parameter in enumerate(parameters):
        checked = _check_parameter(parameter, index)
        if checked["key"] in seen:
            _fail(f"duplicate parameter key {checked['key']!r}")
        seen.add(checked["key"])
        parameters_out.append(checked)
    bindings: list[dict[str, Any]] = []
    raw_bindings = plan.get("bindings", [])
    if not isinstance(raw_bindings, list):
        _fail("bindings must be a list")
    for index, binding in enumerate(raw_bindings):
        if not isinstance(binding, dict):
            _fail(f"bindings[{index}] must be an object")
        if binding.get("parameter_key") not in seen:
            _fail(
                f"bindings[{index}] parameter_key must name a "
                "declared parameter"
            )
        target = binding.get("target")
        if not isinstance(target, str) or not target.strip():
            _fail(f"bindings[{index}] must declare a target path")
        bindings.append(
            {"parameter_key": binding["parameter_key"], "target": target}
        )
    version = plan.get("tweakpane_version")
    if version is not None and (
        not isinstance(version, str) or not version.strip()
    ):
        _fail("tweakpane_version must be a non-empty string when declared")
    return {
        "library": {"repo": LIBRARY_REPO, "license": LIBRARY_LICENSE},
        "version_status": VERSION_STATUS,
        "version_declared": version,
        "purpose": PURPOSE,
        "panel": {"title": title},
        "parameters": parameters_out,
        "parameter_count": len(parameters_out),
        "bindings": bindings,
        "executed_here": False,
        "dom_created": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_tweakpane_panel_contract(params.get("plan"))
    contract_path = out_dir / "tweakpane_panel_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False,
            "dom_created": False},
    )


def register_tweakpane_panel_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.tweakpane_panel_contract",
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
            layer="obase",
            description=(
                "Tweakpane panel contract (contract only): a "
                "debugging parameter panel schema with ranged and "
                "optioned parameters; no DOM is created here."
            ),
        )
    )
    return ["video.tweakpane_panel_contract"]


__all__ = [
    "compile_tweakpane_panel_contract",
    "register_tweakpane_panel_contract_capabilities_once",
]
