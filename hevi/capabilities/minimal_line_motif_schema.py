"""Minimal line motif schema, fake layer
(``video.minimal_line_motif_schema``).

Contract-only schema for the minimal black-and-white line
motif: one or two short lines of lowercase text, a staircase
of three to seven fine steps, one solid white dot hopping up
the steps, and at the top step a track ring with a spark as
the second line swaps in. The motif expresses steady
accumulation only (habit, compounding, patience); any other
meaning kind fails. Text rules are enforced: lowercase,
period-terminated, no exclamation, no emoji, no bold markup.
This module draws nothing: ``executed_here`` is always
false, ``rendered_here`` is always false, and
``output_file`` is always null. Real rendering is a
separate case. See ANIMATION_SKILLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
import unicodedata
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

MOTIF = "steps_dot_ring"
MEANING_KIND = "steady_accumulation"
MIN_STEPS = 3
MAX_STEPS = 7
MAX_LINE_CHARS = 30


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _check_line(line: Any, index: int) -> str:
    if not isinstance(line, str) or not line.strip():
        _fail(f"lines[{index}] must be a non-empty string")
    if len(line) > MAX_LINE_CHARS:
        _fail(
            f"lines[{index}] exceeds {MAX_LINE_CHARS} characters"
        )
    if any("A" <= ch <= "Z" for ch in line):
        _fail(f"lines[{index}] must be lowercase")
    if not line.endswith("."):
        _fail(f"lines[{index}] must end with a period")
    if "!" in line:
        _fail(f"lines[{index}] must not carry an exclamation mark")
    if "*" in line or "_" in line or "#" in line:
        _fail(f"lines[{index}] must not carry bold or heading markup")
    if any(unicodedata.category(ch) == "So" for ch in line):
        _fail(f"lines[{index}] must not carry emoji or symbols")
    return line


def compile_minimal_line_motif(plan: Any) -> dict[str, Any]:
    """Compile a minimal line motif contract from a plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``
    and ``output_file: null``: nothing is drawn here.
    """
    if not isinstance(plan, dict):
        _fail("minimal line motif plan must be a JSON object")
    if plan.get("motif", MOTIF) != MOTIF:
        _fail(f"motif must be {MOTIF!r}")
    if plan.get("meaning_kind") != MEANING_KIND:
        _fail(
            "this motif only expresses steady accumulation "
            "(habit, compounding, patience)"
        )
    lines = plan.get("lines")
    if not isinstance(lines, list) or not 1 <= len(lines) <= 2:
        _fail("motif plan must declare one or two lines")
    lines_out = [_check_line(line, index) for index, line in enumerate(lines)]
    steps = plan.get("steps")
    if (
        not isinstance(steps, int)
        or isinstance(steps, bool)
        or not MIN_STEPS <= steps <= MAX_STEPS
    ):
        _fail(
            f"steps must be an integer in [{MIN_STEPS}, {MAX_STEPS}]"
        )
    light = plan.get("light")
    if not isinstance(light, bool):
        _fail("motif plan must declare light as true/false")
    stages: list[dict[str, Any]] = []
    for stage in range(1, steps + 1):
        top = stage == steps
        stages.append(
            {
                "stage": stage,
                "dot_step": stage,
                "track_ring": top,
                "spark": top,
                "line_shown": (
                    lines_out[1]
                    if top and len(lines_out) == 2
                    else lines_out[0]
                ),
            }
        )
    return {
        "motif": MOTIF,
        "meaning_kind": MEANING_KIND,
        "lines": lines_out,
        "steps": steps,
        "light": light,
        "palette": "black_on_white" if light else "white_on_black",
        "dot": "one solid white dot",
        "stages": stages,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
        "render_required": "separate case; no rendering here",
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_minimal_line_motif(params.get("plan"))
    contract_path = out_dir / "minimal_line_motif_schema.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_minimal_line_motif_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.minimal_line_motif_schema",
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
                "Minimal line motif schema (contract only): "
                "steps, a white dot, and a track ring for steady "
                "accumulation; lowercase period-terminated lines "
                "only, nothing drawn here."
            ),
        )
    )
    return ["video.minimal_line_motif_schema"]


__all__ = [
    "compile_minimal_line_motif",
    "register_minimal_line_motif_schema_capabilities_once",
]
