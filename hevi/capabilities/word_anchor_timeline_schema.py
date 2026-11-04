"""Word-anchor timeline schema, fake layer
(``video.word_anchor_timeline_schema``).

Contract-only schema for a word-anchored timeline: named
anchors bind word boundaries in the spoken lines, an
alignment pipeline turns those boundaries into positions on
the evidence audio, and a projection maps the semantic
boundaries onto the programme timeline. The four alignment
steps are stated in our own words: normalise the evidence
audio, align word boundaries, convert boundaries to the
sample domain, and project onto the timeline. Nothing is
aligned, no timing model is bundled or invoked, and nothing
is rendered: ``executed_here`` is always false,
``alignment_executed`` is always false, and ``output_file``
is always null. See HYPIT_ATTRIBUTION.md. Method restated
in our own words; no upstream DSL text is copied here.
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

_ALIGNMENT_STEPS = (
    "normalize_evidence_audio",
    "align_word_boundaries",
    "convert_to_sample_domain",
    "project_to_timeline",
)

_ATTACHMENT_KINDS = frozenset({"broll", "effect", "caption", "sound"})


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def compile_word_anchor_timeline_contract(plan: Any) -> dict[str, Any]:
    """Compile a word-anchor timeline contract (contract only).

    Raises ``CapabilityError`` for unknown anchor names,
    duplicate anchors, empty word lists, unknown attachment
    kinds, a wrong alignment step list, or word boundaries
    that are not monotonic sample positions. Never aligns
    audio and never renders.
    """
    if not isinstance(plan, dict):
        _fail("plan must be a JSON object")
    anchors = plan.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        _fail("plan must declare a non-empty anchors list")
    names: set[str] = set()
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            _fail(f"anchors[{index}] must be an object")
        name = anchor.get("name")
        if not isinstance(name, str) or not name.strip():
            _fail(f"anchors[{index}] needs a non-empty name")
        if name in names:
            _fail(f"duplicate anchor name: {name}")
        names.add(name)
        words = anchor.get("words")
        if (
            not isinstance(words, list)
            or not words
            or any(not isinstance(w, str) or not w.strip() for w in words)
        ):
            _fail(f"anchor {name} must bind a non-empty list of words")
        attachments = anchor.get("attachments")
        if not isinstance(attachments, list) or not attachments:
            _fail(f"anchor {name} needs at least one attachment")
        for attachment in attachments:
            if not isinstance(attachment, dict) or attachment.get("kind") not in _ATTACHMENT_KINDS:
                _fail(f"anchor {name} has an attachment with an unknown kind")
    alignment = plan.get("alignment")
    if not isinstance(alignment, dict):
        _fail("plan must declare an alignment object")
    steps = alignment.get("steps")
    if not isinstance(steps, list) or list(steps) != list(_ALIGNMENT_STEPS):
        _fail("alignment steps must be the four declared steps in order")
    sample_rate = alignment.get("sample_rate_hz")
    if not _is_int(sample_rate) or sample_rate <= 0:
        _fail("alignment must declare a positive integer sample_rate_hz")
    boundaries = alignment.get("word_boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        _fail("alignment must declare a non-empty word_boundaries list")
    previous_end = -1
    for index, boundary in enumerate(boundaries):
        if not isinstance(boundary, dict):
            _fail(f"word_boundaries[{index}] must be an object")
        start = boundary.get("start_sample")
        end = boundary.get("end_sample")
        if not _is_int(start) or not _is_int(end) or start < 0 or end <= start:
            _fail(f"word_boundaries[{index}] needs 0 <= start_sample < end_sample")
        if start < previous_end:
            _fail("word boundaries must be monotonic and non-overlapping")
        previous_end = end
    placements = plan.get("placements", [])
    if not isinstance(placements, list):
        _fail("placements must be a list")
    for placement in placements:
        if not isinstance(placement, dict) or placement.get("anchor") not in names:
            _fail("every placement must name a declared anchor")
    return {
        "anchors": [a["name"] for a in anchors],
        "alignment_steps": list(_ALIGNMENT_STEPS),
        "sample_rate_hz": sample_rate,
        "word_boundary_count": len(boundaries),
        "executed_here": False,
        "alignment_executed": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_word_anchor_timeline_contract(params.get("plan"))
    contract_path = out_dir / "word_anchor_timeline_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_word_anchor_timeline_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.word_anchor_timeline_schema",
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
                "Word-anchor timeline schema (contract only): named "
                "anchors, four-step alignment, and projection onto "
                "the programme timeline; nothing is aligned or rendered."
            ),
        )
    )
    return ["video.word_anchor_timeline_schema"]


__all__ = [
    "compile_word_anchor_timeline_contract",
    "register_word_anchor_timeline_schema_capabilities_once",
]
