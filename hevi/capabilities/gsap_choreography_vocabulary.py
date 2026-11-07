"""GSAP choreography vocabulary (``video.gsap_choreography_vocabulary``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 8 (BusyBee): choreography as a data vocabulary, not as
copied code. Four moves, each described in hevi's own words with its
parameter shape:

1. Weighted drop -- a body falls under weight and squashes on
   landing; squash amount carries the sense of heaviness.
2. Morph fuse -- one shape melts into another; the blend is the
   meaning, not decoration.
3. Forced collision -- an intended action fails against an obstacle
   and the consequence is shown; intention, failure, and consequence
   are three declared beats.
4. Quantity as character -- a counted amount is itself a character in
   the scene; the count is declared, not improvised.

Dependency discipline: no animation library is fetched from a
network at build or render time. A plan must declare how its motion
library is supplied -- vendored locally, or provided by the caller.
A missing vendor declaration fails, and no CDN address is ever
recorded as a default. This module never fetches, never renders in a
browser, and never plays audio; ``render_fake`` produces
deterministic frame records only, marked as fake.
"""

from __future__ import annotations

import hashlib
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

MOVES: dict[str, dict[str, Any]] = {
    "weighted_drop": {
        "description": (
            "A body falls under weight and squashes on landing; "
            "the squash amount carries the sense of heaviness."
        ),
        "params": ["drop_height", "squash_amount", "settle_duration_s"],
        "beats": ["fall", "impact", "settle"],
    },
    "morph_fuse": {
        "description": (
            "One shape melts into another; the blend itself is "
            "the meaning, not decoration."
        ),
        "params": ["source_shape", "target_shape", "blend_duration_s"],
        "beats": ["source", "blend", "target"],
    },
    "forced_collision": {
        "description": (
            "An intended action fails against an obstacle and the "
            "consequence is shown."
        ),
        "params": ["intention", "obstacle", "consequence"],
        "beats": ["intention", "failure", "consequence"],
    },
    "quantity_as_character": {
        "description": (
            "A counted amount is itself a character in the scene; "
            "the count is declared, not improvised."
        ),
        "params": ["count", "unit_label", "growth_duration_s"],
        "beats": ["establish", "grow", "rest"],
    },
}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def list_moves() -> list[str]:
    """Return the choreography move names in vocabulary order."""
    return list(MOVES)


def get_move(name: Any) -> dict[str, Any]:
    """Return one move's vocabulary entry, or raise for an unknown move."""
    if not _is_nonempty_str(name) or name not in MOVES:
        raise CapabilityError(
            "video.gsap_choreography_vocabulary: unknown choreography move "
            f"{name!r}; known moves are {', '.join(MOVES)}"
        )
    entry = dict(MOVES[name])
    entry["name"] = name
    return entry


def compile_choreography(plan: Any) -> dict[str, Any]:
    """Validate a choreography plan against the vocabulary.

    Returns a compilation report; raises ``CapabilityError`` for a
    malformed plan or a missing vendor declaration.
    """
    if not isinstance(plan, dict):
        raise CapabilityError(
            "video.gsap_choreography_vocabulary: plan must be a JSON object"
        )
    vendor = plan.get("motion_library")
    if not isinstance(vendor, dict) or vendor.get("supply") not in (
        "vendored",
        "caller_provided",
    ):
        raise CapabilityError(
            "video.gsap_choreography_vocabulary: plan must declare how the "
            "motion library is supplied (supply 'vendored' or "
            "'caller_provided'); no network fetch is ever a default"
        )
    if _is_nonempty_str(vendor.get("source_url")):
        raise CapabilityError(
            "video.gsap_choreography_vocabulary: a network source address "
            "must never be recorded as a default supply"
        )
    moves = plan.get("moves")
    if not isinstance(moves, list) or not moves:
        raise CapabilityError(
            "video.gsap_choreography_vocabulary: plan must declare a "
            "non-empty moves list"
        )
    compiled: list[dict[str, Any]] = []
    for index, move in enumerate(moves):
        if not isinstance(move, dict):
            raise CapabilityError(
                "video.gsap_choreography_vocabulary: "
                f"moves[{index}] must be an object"
            )
        entry = get_move(move.get("name"))
        params = move.get("params")
        if not isinstance(params, dict):
            raise CapabilityError(
                "video.gsap_choreography_vocabulary: "
                f"moves[{index}] must carry a params object"
            )
        missing = [key for key in entry["params"] if key not in params]
        if missing:
            raise CapabilityError(
                "video.gsap_choreography_vocabulary: move "
                f"{entry['name']!r} is missing params {missing}"
            )
        compiled.append(
            {"name": entry["name"], "beats": entry["beats"], "params": params}
        )
    return {
        "moves": compiled,
        "motion_library": {"supply": vendor["supply"]},
        "move_count": len(compiled),
    }


def render_fake(plan: Any, *, frames: int = 3) -> dict[str, Any]:
    """Produce deterministic fake frame records for a compiled plan.

    No browser runs and no library loads; each frame record is the
    sha256 of the canonical compiled plan plus the frame index.
    """
    compiled = compile_choreography(plan)
    canonical = json.dumps(compiled, ensure_ascii=False, sort_keys=True)
    frame_records = []
    for index in range(frames):
        digest = hashlib.sha256(f"{canonical}|frame:{index}".encode("utf-8")).hexdigest()
        frame_records.append({"frame": index, "sha256": digest, "backend": "fake"})
    return {
        "backend": "fake",
        "frames": frame_records,
        "move_count": compiled["move_count"],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    record = render_fake(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / "gsap_choreography_vocabulary_record.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(record_path),
        qa={
            "report_json": str(record_path),
            "ok": True,
            "backend": "fake",
        },
    )


def register_gsap_choreography_vocabulary_capabilities_once() -> list[str]:
    """Register the vocabulary on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.gsap_choreography_vocabulary",
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
            description=(
                "GSAP choreography vocabulary: four data-described moves "
                "(weighted drop, morph fuse, forced collision, quantity as "
                "character); the motion library must be declared vendored "
                "or caller-provided, never fetched by default. Fake frame "
                "records only; no browser, no network."
            ),
            line="video",
        )
    )
    return ["video.gsap_choreography_vocabulary"]


register_gsap_choreography_vocabulary_capabilities_once()
