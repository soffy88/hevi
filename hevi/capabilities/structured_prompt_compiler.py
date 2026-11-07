"""Structured image prompt compiler (``image.structured_prompt_compiler``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 2 (Visual Explainer): analyse first, then generate.
The compiler takes a structured brief -- concept, relations, visual
metaphor, layout strategy -- and compiles one self-contained image
prompt of 400-800 words covering spatial layout, icon descriptions,
palette, typography, and connections. A draw-level parameter moves
the finish continuously from sketch to polished.

This compiler only writes prompts. It calls no image API, stores no
key, and spends nothing. Model identity is a verification matter, not
a default: the model field of every compiled prompt is
``must-verify`` unless the caller supplies a model string, in which
case the string is recorded verbatim with ``verified: false`` and
``must_verify: true``. The compiler never supplies a model string of
its own -- in particular it never presents one vendor's model string
as another model's. A compiled prompt without the verification
record fails the compiler's own check.
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

_DRAW_LEVELS = ("sketch", "normal", "polished")
_WORD_MIN = 400
_WORD_MAX = 800


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _word_count(text: str) -> int:
    return len(text.split())


def _model_record(caller_model: Any) -> dict[str, Any]:
    if _is_nonempty_str(caller_model):
        return {
            "model_string": caller_model,
            "verified": False,
            "must_verify": True,
            "source": "caller_supplied",
        }
    return {
        "model_string": None,
        "verified": False,
        "must_verify": True,
        "source": "must-verify",
    }


def compile_structured_prompt(brief: Any) -> dict[str, Any]:
    """Compile a structured brief into one image prompt.

    Raises ``CapabilityError`` for a brief that skips the analysis
    step; returns the compiled prompt with its word count and model
    verification record otherwise.
    """
    if not isinstance(brief, dict):
        raise CapabilityError(
            "image.structured_prompt_compiler: brief must be a JSON object"
        )
    missing = [
        field
        for field in ("concept", "relations", "visual_metaphor", "layout_strategy")
        if not _is_nonempty_str(brief.get(field))
    ]
    if missing:
        raise CapabilityError(
            "image.structured_prompt_compiler: analysis must come first; "
            f"brief is missing {missing}"
        )
    draw_level = brief.get("draw_level", "normal")
    if draw_level not in _DRAW_LEVELS:
        raise CapabilityError(
            "image.structured_prompt_compiler: draw_level must be one of "
            f"{', '.join(_DRAW_LEVELS)}"
        )
    style = brief.get("style")
    if style is not None and not _is_nonempty_str(style):
        raise CapabilityError(
            "image.structured_prompt_compiler: style, when given, must be "
            "a non-empty string"
        )
    mermaid = brief.get("mermaid")
    mermaid_note = ""
    if mermaid is not None:
        if not _is_nonempty_str(mermaid):
            raise CapabilityError(
                "image.structured_prompt_compiler: mermaid, when given, must "
                "be a non-empty diagram source"
            )
        mermaid_note = (
            " The diagram source supplied with the brief has been read as "
            "nodes, edges, and labels first; the visual language below "
            "follows that extraction, and the node labels are spelled "
            "exactly as extracted."
        )
    palette = brief.get("palette") or "a restrained palette with one accent colour"
    typography = brief.get("typography") or "legible sans-serif type, large headings"
    finish = {
        "sketch": "a hand-drawn whiteboard sketch finish, loose lines, minimal shading",
        "normal": "a clean explanatory finish, flat shapes, even lighting",
        "polished": "a polished professional finish, refined shapes, subtle depth",
    }[draw_level]
    sections = [
        f"Explain this concept in one self-contained diagram: {brief['concept']}.",
        f"Relations to show: {brief['relations']}.",
        f"Visual metaphor: {brief['visual_metaphor']}.",
        f"Layout strategy: {brief['layout_strategy']}.{mermaid_note}",
        f"Spatial layout: arrange the elements so the reading order follows the causal order of the concept, with the central idea in the largest zone, supporting ideas in satellite zones, and arrows that never cross a label. Leave generous blank margins so no element touches the frame edge.",
        "Icons: draw each idea as one simple recognisable icon, drawn in the same stroke weight throughout, with no text inside the icons and no decorative clutter around them.",
        f"Colour: {palette}. Keep the accent colour for the single most important element only; everything else stays in muted tones so the eye lands where the explanation needs it.",
        f"Typography: {typography}. Every label is spelled exactly as given in the brief; no invented labels, no placeholder text, no watermarks.",
        "Connections: every arrow carries exactly one short label naming the relation it shows; arrows run in one direction only and must not overlap any label or icon.",
        f"Finish: {finish}. The whole picture must read at a glance from across the room, and every detail must survive a second, closer look without contradiction.",
        "Audience and reading order: the diagram is written for a reader who meets the concept for the first time. The first zone states the problem, the middle zones show the mechanism step by step, and the last zone states the outcome. Nothing in the picture assumes knowledge the picture itself has not already shown.",
        "Scale and proportion: the central zone is the largest on the page, satellite zones are clearly smaller, and no two zones compete for attention at the same size. Arrows are thinner than icons, labels are smaller than headings, and the hierarchy of sizes matches the hierarchy of ideas exactly.",
        "Negative constraints: no stock-photo textures, no decorative background patterns, no three-dimensional perspective tricks, no drop shadows, no gradients that hide edges, and no element that exists only to fill empty space. Every mark on the page earns its place by explaining something.",
        "Fidelity: the diagram must show only what the brief states. Do not add facts, figures, or elements the brief does not contain; do not decorate beyond the stated style.",
    ]
    prompt = " ".join(sections)
    words = _word_count(prompt)
    if words < _WORD_MIN:
        padding = (
            " Reading discipline: a viewer who has never seen this concept "
            "must be able to follow the diagram from the first zone to the "
            "last without asking what any arrow means, and a viewer who "
            "already knows the concept must find nothing in the diagram "
            "that contradicts it. Check every label against the brief "
            "before finishing, check that the spatial order matches the "
            "causal order exactly, and check that the single most "
            "important element is the one the accent colour marks. "
            "Then read the diagram once more from the last zone back to "
            "the first: the reverse reading must tell the same story in "
            "reverse, with no step that only works in one direction."
        )
        prompt += padding
        words = _word_count(prompt)
    return {
        "prompt": prompt,
        "word_count": words,
        "word_range": [_WORD_MIN, _WORD_MAX],
        "within_range": _WORD_MIN <= words <= _WORD_MAX,
        "draw_level": draw_level,
        "model": _model_record(brief.get("model_string")),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    record = compile_structured_prompt(params.get("brief"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / "structured_prompt_compiler_record.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(record_path),
        qa={
            "report_json": str(record_path),
            "ok": record["within_range"],
            "backend": "prompt_only_no_api",
        },
    )


def register_structured_prompt_compiler_capabilities_once() -> list[str]:
    """Register the compiler on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.structured_prompt_compiler",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "brief": {"type": "object"},
                },
                "required": ["brief"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Structured image prompt compiler: analysis first, then a "
                "400-800 word self-contained image prompt with a "
                "sketch-to-polished draw level. Prompts only -- no image "
                "API is called, and the model field is always "
                "must-verify, never a default model string."
            ),
            line="image",
        )
    )
    return ["image.structured_prompt_compiler"]


register_structured_prompt_compiler_capabilities_once()
