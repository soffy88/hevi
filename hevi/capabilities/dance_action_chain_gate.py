"""Dance action-chain gate (``qa.dance_action_chain_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): a dance phrase
is designed, not named. Every phrase carries three
layers — a steady groove underneath, one main chain of
movement, and small accents on the off-beats — and every
main chain carries ten facts: where the body starts,
where the force comes from, how it enters, how the power
changes beat by beat, the one visible peak, how the
cloth and hair keep moving after, how it brakes, how the
body and cloth behave, how the camera sees it, and what
in the music triggers it. Five steps link the chain
together — set the support and preload, pass the power
along, arrive at the peak, brake and recover, and leave
an entry for the next chain — and the end of one chain
must be the natural start of the next. A bare action
name with an adjective is not a chain. This gate judges
the chain record only. It dances nothing, renders
nothing, and spends nothing: ``executed_here`` is always
false.

No internal library code is accepted here at all: the
source action-chain library was never supplied, so any
record carrying a library code — as a key or as a bare
code-shaped value — fails outright, and the chain must
be written out in plain language instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# The ten facts every main chain must carry, each written
# out in plain language. A bare action name is too short
# to count as a fact.
CHAIN_ELEMENTS: tuple[str, ...] = (
    "start_state",
    "power_source",
    "entry_path",
    "beat_progression",
    "peak",
    "inertia",
    "recovery",
    "body_cloth_physics",
    "camera_geometry",
    "music_trigger",
)
MIN_ELEMENT_LENGTH = 6
# A bare internal library code looks like one letter
# followed by one or two digits. Such codes are refused
# wherever they appear; chains are written in plain words.
_CODE_SHAPE = re.compile(r"^[A-Za-z]\d{1,2}$")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _has_library_code(value: Any) -> bool:
    """True when any key or bare code-shaped value is present."""
    if isinstance(value, dict):
        return any(
            key == "library_code" or _has_library_code(item) for key, item in value.items()
        ) or any(isinstance(key, str) and bool(_CODE_SHAPE.match(key)) for key in value)
    if isinstance(value, list):
        return any(_has_library_code(item) for item in value)
    return isinstance(value, str) and bool(_CODE_SHAPE.match(value))


def check_dance_action_chain(chain: Any) -> dict[str, Any]:
    """Validate an action-chain design for one dance phrase.

    Verdicts are ``pass`` / ``fail`` only. The chain fails
    when a layer is missing, when any of the ten chain
    facts is missing or too short to be a real description,
    when the five steps are incomplete, when the entry or
    exit state names no support foot or direction, when a
    micro accent is incomplete, or when any internal
    library code appears anywhere in the record.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(chain, dict):
        return fail("chain_not_object", "action chain must be a JSON object")
    if _has_library_code(chain):
        return fail(
            "library_code_refused",
            "internal library codes are refused here; the source "
            "library was never supplied, so chains are written "
            "out in plain language",
        )
    layers = chain.get("layers")
    if not isinstance(layers, dict):
        return fail(
            "layers_missing",
            "chain must carry its three layers: groove, main chain and micro accents",
        )
    groove = layers.get("groove")
    if not isinstance(groove, str) or not groove.strip():
        return fail(
            "groove_missing",
            "chain must state its steady groove underneath",
        )
    main = layers.get("main_chain")
    if not isinstance(main, dict):
        return fail(
            "main_chain_missing",
            "chain must carry its main chain of movement",
        )
    for element in CHAIN_ELEMENTS:
        value = main.get(element)
        if not isinstance(value, str) or not value.strip():
            return fail(
                "chain_element_missing",
                f"main chain is missing {element}",
            )
        if len(value.strip()) < MIN_ELEMENT_LENGTH:
            return fail(
                "chain_element_too_short",
                f"main chain {element} is a bare name, not a description of how the body moves",
            )
    micro = layers.get("micro_accents")
    if not isinstance(micro, list):
        return fail(
            "micro_accents_missing",
            "chain must carry a micro-accent list, empty when none",
        )
    for position, accent in enumerate(micro):
        if not isinstance(accent, dict):
            return fail(
                "micro_accent_not_object",
                f"micro accent {position} must be an object",
            )
        if not isinstance(accent.get("beat"), str) or not accent["beat"].strip():
            return fail(
                "micro_accent_beat_missing",
                f"micro accent {position} must name its beat",
            )
        if not isinstance(accent.get("detail"), str) or not accent["detail"].strip():
            return fail(
                "micro_accent_detail_missing",
                f"micro accent {position} must describe the accent",
            )
    steps = chain.get("steps")
    if not isinstance(steps, list) or len(steps) != 5:
        return fail(
            "steps_incomplete",
            "chain must carry exactly five steps: support and "
            "preload, power transfer, peak, brake and recovery, "
            "and the next entry",
        )
    for position, step in enumerate(steps):
        if not isinstance(step, str) or not step.strip():
            return fail(
                "step_missing",
                f"chain step {position} must be written out",
            )
    for state_name in ("entry_state", "exit_state"):
        state = chain.get(state_name)
        if not isinstance(state, dict):
            return fail(
                "entry_exit_missing",
                f"chain must carry its {state_name}",
            )
        if not isinstance(state.get("support_foot"), str) or not state["support_foot"].strip():
            return fail(
                "support_foot_missing",
                f"{state_name} must name the supporting foot",
            )
        if not isinstance(state.get("direction"), str) or not state["direction"].strip():
            return fail(
                "direction_missing",
                f"{state_name} must name the body direction",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_dance_action_chain(params.get("chain"))
    report_path = out_dir / "dance_action_chain_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_action_chain_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_action_chain_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "chain": {"type": "object"},
                },
                "required": ["chain"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Dance action-chain gate: three layers, ten chain "
                "facts, five linking steps, and entry and exit "
                "states; bare action names and internal library "
                "codes are refused."
            ),
        )
    )
    return ["qa.dance_action_chain_gate"]


__all__ = [
    "CHAIN_ELEMENTS",
    "MIN_ELEMENT_LENGTH",
    "check_dance_action_chain",
    "register_dance_action_chain_gate_capabilities_once",
]
