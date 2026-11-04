"""three.quarks particle contract, fake layer (``video.quarks_particle_contract``).

Contract-only adapter. Given a particle plan it compiles the
contract for a three.quarks particle/VFX pass: each emitter
declares an emission rate, a particle lifetime, and a behaviour
name, and the plan declares the pinned library version and
acknowledges that real rendering needs a GPU. This module
executes nothing: ``executed_here`` is always false,
``rendered_here`` is always false, and ``output_file`` is
always null. No particle is simulated and no frame is rendered
here; the library itself is not installed, probed, or invoked,
and its maintenance-slowed status is recorded honestly (the
caller pins the version by declaration). Real particle
rendering is a separate GPU case whose effect is unverified.
See OPEN_SKILLS_ATTRIBUTION.md.
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

LIBRARY_REPO = "Alchemist0823/three.quarks"
LIBRARY_LICENSE = "MIT"
# Maintenance has slowed; the version is pinned by caller
# declaration, never assumed here.
VERSION_STATUS = "maintenance slowed; version pinned by declaration"


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compile_quarks_particle_contract(plan: Any) -> dict[str, Any]:
    """Compile a particle contract from a particle plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``,
    ``rendered_here: false``, and ``output_file: null``: nothing
    is simulated or rendered here.
    """
    if not isinstance(plan, dict):
        _fail("particle plan must be a JSON object")
    library_version = plan.get("library_version")
    if not isinstance(library_version, str) or not library_version:
        _fail(
            "particle plan must declare library_version: the "
            "slow-maintenance library is pinned by declaration"
        )
    if plan.get("gpu_required") is not True:
        _fail(
            "particle plan must declare gpu_required true: real "
            "particle rendering needs a GPU and is not done here"
        )
    emitters = plan.get("emitters")
    if not isinstance(emitters, list) or not emitters:
        _fail("particle plan must declare a non-empty emitters list")
    compiled: list[dict[str, Any]] = []
    for index, emitter in enumerate(emitters):
        if not isinstance(emitter, dict):
            _fail(f"emitters[{index}] must be an object")
        emitter_id = emitter.get("id")
        if not isinstance(emitter_id, str) or not emitter_id:
            _fail(f"emitters[{index}] must declare an id")
        rate = emitter.get("emission_rate_per_second")
        if not _is_number(rate) or rate <= 0:
            _fail(
                f"emitters[{index}] must declare a positive "
                "emission_rate_per_second"
            )
        lifetime = emitter.get("lifetime_seconds")
        if not _is_number(lifetime) or lifetime <= 0:
            _fail(
                f"emitters[{index}] must declare a positive "
                "lifetime_seconds"
            )
        behavior = emitter.get("behavior")
        if not isinstance(behavior, str) or not behavior:
            _fail(f"emitters[{index}] must declare a behavior name")
        compiled.append(
            {
                "index": index,
                "id": emitter_id,
                "emission_rate_per_second": rate,
                "lifetime_seconds": lifetime,
                "behavior": behavior,
            }
        )
    return {
        "contract": "quarks_particle",
        "library": {
            "repo": LIBRARY_REPO,
            "license": LIBRARY_LICENSE,
            "version_declared": library_version,
            "version_status": VERSION_STATUS,
            "installed_here": False,
        },
        "emitters": compiled,
        "gpu_required": True,
        "renderer": (
            "not executed here; real rendering is a separate GPU "
            "case and its effect is unverified"
        ),
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_quarks_particle_contract(params.get("plan"))
    contract_path = out_dir / "quarks_particle_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_quarks_particle_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.quarks_particle_contract",
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
                "three.quarks particle contract, fake layer: "
                "compiles an emitter contract (rate, lifetime, "
                "behaviour, pinned library version, GPU "
                "acknowledgement); nothing is simulated or rendered "
                "here and the library is not installed."
            ),
        )
    )
    return ["video.quarks_particle_contract"]


__all__ = [
    "LIBRARY_REPO",
    "compile_quarks_particle_contract",
    "register_quarks_particle_contract_capabilities_once",
]
