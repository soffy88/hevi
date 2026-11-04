"""Audacity effect-chain contract, fake layer
(``audio.audacity_effect_chain_contract``).

Contract-only schema for an Audacity effect chain on the 3.x
line only. Audacity is a desktop audio editor (GPLv3, with
some files under GPLv2, per the repository's own LICENSE
text); no Audacity code is copied here and no desktop
application is installed. The version line is the whole
point: the 4.x line currently offers no official scripting
entry point, so any scripting or effect-chain claim against
4.x fails closed, and a 3.x chain must name its interface
(``macro`` or ``mod_script_pipe``) and use the 3.x project
format (``aup3``). The effect names below are hevi's contract
vocabulary; the exact 3.x effect names and parameter ranges
are a real-machine case and are not asserted here. This
module processes no audio: ``executed_here`` is always
false, ``audio_rendered`` is always false, and
``output_file`` is always null. Real audio work is a
separate real-machine case. See
FIFTEEN_TOOLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.audacity_version_gate import (
    AUDACITY_LICENSE,
    LEGACY_SCRIPTING_INTERFACES,
    PROJECT_FORMAT_BY_MAJOR,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Contract vocabulary only. Exact 3.x effect names and
# parameter ranges are a real-machine case; nothing here
# asserts them.
EFFECT_KINDS: tuple[str, ...] = (
    "noise_reduction",
    "normalize",
    "compressor",
    "limiter",
    "fade_in",
    "fade_out",
    "amplify",
    "high_pass",
    "low_pass",
    "trim",
    "gain",
)

_OUTPUT_FORMATS: tuple[str, ...] = ("wav", "mp3", "flac", "ogg")


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_major(text: Any) -> int | None:
    if not isinstance(text, str) or not text.strip():
        return None
    match = re.match(r"v?(\d+)", text.strip())
    return int(match.group(1)) if match else None


def compile_audacity_effect_chain_contract(plan: Any) -> dict[str, Any]:
    """Compile an Audacity effect-chain contract from a plan.

    Raises :class:`CapabilityError` on a malformed plan, on
    any 4.x scripting claim, or on a project-format mismatch.
    The returned contract always carries
    ``executed_here: false`` and ``output_file: null``: no
    audio is processed here.
    """
    if not isinstance(plan, dict):
        _fail("audacity effect-chain plan must be a JSON object")
    major = _parse_major(plan.get("audacity_version"))
    if major is None:
        _fail("audacity effect-chain plan must declare audacity_version")
    if major != 3:
        _fail(
            f"Audacity {major}.x has no official scripting entry "
            "point for an effect chain; only the 3.x line keeps "
            "macro/script-pipe automation, so this contract is "
            "3.x-only and 4.x claims fail closed"
        )
    interface = plan.get("interface")
    if interface not in LEGACY_SCRIPTING_INTERFACES:
        _fail(
            "audacity 3.x chain must name its interface: one of "
            f"{list(LEGACY_SCRIPTING_INTERFACES)}"
        )
    project_format = plan.get("project_format")
    if project_format is not None and project_format != PROJECT_FORMAT_BY_MAJOR[3]:
        _fail(
            f"audacity 3.x project format must be "
            f"{PROJECT_FORMAT_BY_MAJOR[3]!r}, not {project_format!r}"
        )
    audio_in = plan.get("input")
    if not isinstance(audio_in, dict):
        _fail("effect-chain plan must declare an input object")
    source = audio_in.get("source")
    if not isinstance(source, str) or not source.strip():
        _fail("input must declare a source reference")
    duration_s = audio_in.get("duration_s")
    if duration_s is not None and (not _is_number(duration_s) or duration_s <= 0):
        _fail("input duration_s must be a positive number when declared")
    chain = plan.get("chain")
    if not isinstance(chain, list) or not chain:
        _fail("effect-chain plan must declare a non-empty chain list")
    steps_out: list[dict[str, Any]] = []
    for index, step in enumerate(chain):
        if not isinstance(step, dict):
            _fail(f"chain[{index}] must be an object")
        effect = step.get("effect")
        if effect not in EFFECT_KINDS:
            _fail(
                f"chain[{index}] effect must be one of the "
                f"contract vocabulary: {list(EFFECT_KINDS)}"
            )
        params = step.get("params")
        if not isinstance(params, dict):
            _fail(f"chain[{index}] must declare a params object")
        if effect in ("fade_in", "fade_out") and "duration_s" in params:
            if not _is_number(params["duration_s"]) or params["duration_s"] <= 0:
                _fail(
                    f"chain[{index}] fade duration_s must be a "
                    "positive number"
                )
        if effect in ("gain", "amplify") and "db" in params:
            if not _is_number(params["db"]):
                _fail(f"chain[{index}] db must be a number")
        steps_out.append(
            {"order": index + 1, "effect": effect, "params": dict(params)}
        )
    audio_out = plan.get("output")
    if not isinstance(audio_out, dict):
        _fail("effect-chain plan must declare an output object")
    out_format = audio_out.get("format")
    if out_format not in _OUTPUT_FORMATS:
        _fail(
            f"output format must be one of {list(_OUTPUT_FORMATS)}"
        )
    out_path = audio_out.get("path")
    if not isinstance(out_path, str) or not out_path.strip():
        _fail("output must declare a path")
    return {
        "license": AUDACITY_LICENSE,
        "audacity_version_major": 3,
        "interface": interface,
        "project_format": PROJECT_FORMAT_BY_MAJOR[3],
        "effect_vocabulary_note": (
            "contract vocabulary only; exact 3.x effect names "
            "and parameter ranges are a real-machine case"
        ),
        "input": {"source": source, "duration_s": duration_s},
        "chain": steps_out,
        "step_count": len(steps_out),
        "output": {"format": out_format, "path": out_path},
        "real_machine_required": (
            "Audacity desktop application plus a 3.x scripting "
            "session; no desktop application is installed here"
        ),
        "executed_here": False,
        "audio_rendered": False,
        "output_file": None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_audacity_effect_chain_contract(params.get("plan"))
    contract_path = out_dir / "audacity_effect_chain_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False,
            "audio_rendered": False},
    )


def register_audacity_effect_chain_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="audio.audacity_effect_chain_contract",
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
                "Audacity effect-chain contract (contract only, "
                "3.x-only): an ordered effect chain against the "
                "macro/script-pipe interface; 4.x scripting "
                "claims fail closed and no audio is processed here."
            ),
        )
    )
    return ["audio.audacity_effect_chain_contract"]


__all__ = [
    "EFFECT_KINDS",
    "compile_audacity_effect_chain_contract",
    "register_audacity_effect_chain_contract_capabilities_once",
]
