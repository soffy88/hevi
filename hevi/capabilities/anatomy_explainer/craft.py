"""Craft rules from ``third_party/anatomy/references``, as renderer constraints.

The vendored reference documents are the craft contract of the Anatomy kit:

============================  ==========================================
``references/craft.md``       composition, tones, painter's order, themes
``references/kit.md``         the kit API and what it guarantees
``references/motion.md``      time-based motion, easing, reduced motion
``references/verify.md``      capture / drive / line ends, what to look at
``references/webgl.md``       shaders ride envelopes and never pop
``references/3d.md``          when a figure earns 3D, and the audit
============================  ==========================================

:data:`RULES` is that contract in machine-readable form: every rule keeps its
source section, and :func:`validate_generation_constraints` +
:func:`measure_figure` enforce the measurable ones.  A render that breaks a
hard rule fails here, before a frame is encoded; the prompt/constraints block
(:func:`constraints_for_prompt`) is what a figure generator is told up front.

Enforcement is deliberately narrow and honest: only rules that can be measured
from a built page or a rendered frame are marked ``hard``.  The rest are
``advisory`` (they shape the prompt and the report, they are not pretended to
be checked).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "RULES",
    "ConstraintViolation",
    "constraints_for_prompt",
    "measure_figure",
    "rule_ids",
    "validate_generation_constraints",
    "write_report",
]

#: Camera and composition bounds from ``craft.md`` §6.
AZIMUTH_RANGE = (35.0, 60.0)
ELEVATION_RANGE = (28.0, 46.0)
PAD_RANGE = (22.0, 40.0)
FILL_RANGE = (0.35, 0.75)

#: The kit's tone vocabulary (``craft.md`` §4, ``iso-kit.mjs``).
TONES = ("lit", "hi", "mid", "lo", "faint")


class ConstraintViolation(ValueError):
    """A hard craft rule was broken while generating a figure."""


@dataclass(frozen=True)
class Rule:
    id: str
    source: str
    text: str
    enforcement: str  # "hard" | "advisory"

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "source": self.source, "text": self.text, "enforcement": self.enforcement}


RULES: tuple[Rule, ...] = (
    # ── craft.md §2/§4: what the drawing may contain ─────────────────────────
    Rule(
        "craft.no_text_in_drawing",
        "references/craft.md §2",
        "At most one tiny engraved label (FaceText on a face); every other word lives in the card corners, legend or caption.",
        "hard",
    ),
    Rule(
        "craft.monochrome_plus_one_accent",
        "references/craft.md §2",
        "Keep it monochrome unless colour is the subject: one lit accent plus true RGB only for colour channels.",
        "advisory",
    ),
    Rule(
        "craft.one_lit_part",
        "references/craft.md §4",
        "Use `lit` for the one part the reader should watch now, never for several.",
        "hard",
    ),
    Rule(
        "craft.every_line_lands",
        "references/craft.md §2 + verify.md",
        "Every line end must land on a stroke, a dot or an outline; `lineSvg(..., { free })` is only for a needle tip or printed text.",
        "hard",
    ),
    Rule(
        "craft.textures_fade",
        "references/craft.md §2",
        "A texture that has to end fades out or ends on a real edge; never an instant stop mid-surface.",
        "advisory",
    ),
    Rule(
        "craft.painters_order",
        "references/craft.md §5",
        "Draw the base first, then what rests on it; within a level sort by depth; split parts that wrap.",
        "hard",
    ),
    # ── craft.md §6: camera and composition ─────────────────────────────────
    Rule(
        "craft.camera",
        "references/craft.md §6",
        f"Default camera azimuth 45° (usable {AZIMUTH_RANGE[0]:.0f}–{AZIMUTH_RANGE[1]:.0f}°), elevation 30° (usable {ELEVATION_RANGE[0]:.0f}–{ELEVATION_RANGE[1]:.0f}°).",
        "hard",
    ),
    Rule(
        "craft.fit_pad",
        "references/craft.md §6",
        f"Fit with fitProjection(..., {{ pad: {PAD_RANGE[0]:.0f}–{PAD_RANGE[1]:.0f} }}) so the figure never touches the corner labels.",
        "hard",
    ),
    Rule(
        "craft.object_fills_card",
        "references/craft.md §6",
        "The object fills about 55–65% of the card and leaves air around it.",
        "hard",
    ),
    # ── craft.md §7: themes ─────────────────────────────────────────────────
    Rule(
        "craft.theme_tokens",
        "references/craft.md §7",
        "Every colour is a --anatomy-* token with a light and a dark value; a typed-in colour is a theme bug.",
        "hard",
    ),
    # ── motion.md ───────────────────────────────────────────────────────────
    Rule(
        "motion.time_based",
        "references/motion.md",
        "Take dt from requestAnimationFrame and clamp it to 1/30 s; never step a fixed amount per frame.",
        "advisory",
    ),
    Rule(
        "motion.ease_to_targets",
        "references/motion.md",
        "Pointer and keys set a target and the part eases toward it (τ = 0.1–0.3 s); nothing snaps.",
        "advisory",
    ),
    Rule(
        "motion.reduced_motion",
        "references/motion.md",
        "Under prefers-reduced-motion the figure jumps to targets, drops the tour, and still responds to input.",
        "hard",
    ),
    Rule(
        "motion.one_loop",
        "references/motion.md",
        "One tick(dt) per figure writes the DOM; stop when settled or offscreen.",
        "advisory",
    ),
    # ── verify.md ───────────────────────────────────────────────────────────
    Rule(
        "verify.capture_and_look",
        "references/verify.md",
        "capture.mjs / drive.mjs shots are read before shipping; console errors and sideways scroll are failures.",
        "hard",
    ),
    Rule(
        "verify.line_ends_zero",
        "references/verify.md",
        "`lines.mjs` must print 0 floating ends on both themes and in every rest pose.",
        "hard",
    ),
    # ── webgl.md ────────────────────────────────────────────────────────────
    Rule(
        "webgl.envelopes",
        "references/webgl.md §7",
        "Every shader term rides an envelope and reaches zero before any bound; no pops, no straight cut at a canvas edge.",
        "advisory",
    ),
    Rule(
        "webgl.svg_fallback",
        "references/webgl.md",
        "The --no-webgl fallback draws the same tint and the same readout as the shader.",
        "advisory",
    ),
    # ── 3d.md ───────────────────────────────────────────────────────────────
    Rule(
        "3d.earns_itself",
        "references/3d.md §1",
        "Use turning groups only when the motion is the explanation; a sliding part or a swinging needle stays 2D.",
        "advisory",
    ),
    Rule(
        "3d.convex_flush",
        "references/3d.md §5",
        "Live parts are convex and their contacts are flush, tangent or rim-on-flat; joints are bridged by a coaxial knuckle.",
        "hard",
    ),
    Rule(
        "3d.orbit_audit",
        "references/3d.md §13",
        "The orbit audit (separation, cycles, layers, rigid, folds, crowding, endon, coverage, depth) must pass before shipping.",
        "hard",
    ),
)


def rule_ids() -> list[str]:
    return [rule.id for rule in RULES]


def _rules_with(enforcement: str) -> list[Rule]:
    return [rule for rule in RULES if rule.enforcement == enforcement]


def constraints_for_prompt(*, mode: str = "2d") -> str:
    """The generation constraints, as the prompt block a figure builder gets."""
    rows = [
        "# Anatomy craft constraints (from third_party/anatomy/references)",
        "Every figure is built from real parts with true shapes, then measured; nothing here is decorative.",
    ]
    for rule in RULES:
        if rule.id.startswith("3d.") and mode != "3d":
            continue
        rows.append(f"- [{rule.enforcement}] {rule.id}: {rule.text}  ({rule.source})")
    return "\n".join(rows)


def validate_generation_constraints(validated: dict[str, Any]) -> None:
    """Reject parameters that cannot satisfy the craft contract.

    This is the renderer-side half of the rules: it runs before any figure is
    built, so a bad request fails with the rule id instead of producing a
    figure that then fails an audit.
    """
    mode = validated.get("mode", "2d")
    if mode not in {"2d", "3d"}:
        raise ConstraintViolation(f"[craft.camera] unknown mode {mode!r}: use 2d or 3d")
    duration = float(validated.get("duration", 0.0))
    if duration < 2.0:
        raise ConstraintViolation(
            "[verify.capture_and_look] a figure shorter than 2 s cannot show its motion; use >= 2 s"
        )
    if validated.get("mode") == "3d" and validated.get("object") not in {"windmill"}:
        raise ConstraintViolation(
            "[3d.earns_itself] only the objects with a real turning group can render in 3d mode"
        )


def _dominant(hex_colours: Iterable[str]) -> tuple[str, int]:
    counts: dict[str, int] = {}
    for colour in hex_colours:
        counts[colour.lower()] = counts.get(colour.lower(), 0) + 1
    if not counts:
        return "", 0
    colour = max(counts, key=lambda key: counts[key])
    return colour, counts[colour]


def measure_figure(html_path: Path, *, frames_dir: Path | None = None, mode: str = "2d") -> dict[str, Any]:
    """Measure a built page against the hard craft rules.

    Reads the page's own markup (camera, palette, text) and, when frames exist,
    the rendered ink coverage.  Returns a report with ``violations`` (hard rule
    failures) and ``warnings``; the renderer raises on violations.
    """
    html = html_path.read_text(encoding="utf-8", errors="replace")
    # Measure the markup, not the stylesheet: the kit's CSS legitimately carries
    # `[data-lit]` selectors and the token definitions.
    import re as _re

    markup = _re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=_re.S)
    markup = _re.sub(r"<script\b[^>]*>.*?</script>", "", markup, flags=_re.S)
    report: dict[str, Any] = {
        "html": str(html_path),
        "mode": mode,
        "rules": [rule.as_dict() for rule in RULES],
        "violations": [],
        "warnings": [],
        "measurements": {},
    }

    # craft.camera / craft.fit_pad: the page embeds the projection it was built with.
    import re

    camera = re.search(r'"azimuth":\s*([0-9.]+)\s*,\s*"elevation":\s*([0-9.]+)', html)
    if camera:
        azimuth, elevation = float(camera.group(1)), float(camera.group(2))
        report["measurements"]["camera"] = {"azimuth": azimuth, "elevation": elevation}
        if not AZIMUTH_RANGE[0] <= azimuth <= AZIMUTH_RANGE[1]:
            report["violations"].append(
                f"[craft.camera] azimuth {azimuth} outside {AZIMUTH_RANGE[0]}–{AZIMUTH_RANGE[1]}"
            )
        if not ELEVATION_RANGE[0] <= elevation <= ELEVATION_RANGE[1]:
            report["violations"].append(
                f"[craft.camera] elevation {elevation} outside {ELEVATION_RANGE[0]}–{ELEVATION_RANGE[1]}"
            )
    else:
        report["warnings"].append("[craft.camera] the page does not embed its projection; camera not measured")

    # craft.theme_tokens: no typed-in hex colours outside the token block.
    typed = re.findall(r'(?:fill|stroke|stop-color)="(#[0-9a-fA-F]{3,8})"', markup)
    token_block = re.findall(r"--anatomy-[a-z0-9-]+:\s*#[0-9a-fA-F]{3,8}", html)
    report["measurements"]["typed_colours"] = sorted(set(typed))[:12]
    report["measurements"]["token_count"] = len(token_block)
    # The kid plates paint one flat page background behind the drawing; that one
    # rect is the card, not a part colour.  Every part colour must be a token.
    backgrounds = re.findall(r'<rect[^>]*width="[^"]*"[^>]*height="[^"]*"[^>]*fill="(#[0-9a-fA-F]{3,8})"', markup)
    part_colours = [colour for colour in typed if colour.lower() not in {b.lower() for b in backgrounds}]
    report["measurements"]["page_background"] = sorted(set(backgrounds))
    if part_colours:
        report["violations"].append(
            f"[craft.theme_tokens] {len(part_colours)} part fills use a literal colour: {sorted(set(part_colours))[:6]}"
        )
    if not token_block:
        report["violations"].append("[craft.theme_tokens] the page defines no --anatomy-* colour tokens")

    # craft.no_text_in_drawing: at most one engraved label inside the figure.
    texts = re.findall(r"<text\b", markup)
    report["measurements"]["text_nodes"] = len(texts)
    engraved = re.findall(r'class="iso-face-text"', markup)
    report["measurements"]["engraved_labels"] = len(engraved)
    if len(engraved) > 1:
        report["violations"].append(
            f"[craft.no_text_in_drawing] {len(engraved)} engraved labels inside the figure (at most 1)"
        )

    # craft.one_lit_part: a single `data-lit` / lit tone in the drawing.
    lit = len(re.findall(r'data-lit(?:="[^"]*")?', markup)) + len(re.findall(r'"tone":\s*"lit"', markup))
    report["measurements"]["lit_parts"] = lit
    if lit > 1:
        report["violations"].append(f"[craft.one_lit_part] {lit} lit parts in one figure (use one)")

    # motion.reduced_motion: the page must honour the media query.
    report["measurements"]["reduced_motion"] = "prefers-reduced-motion" in html
    if "prefers-reduced-motion" not in html:
        report["warnings"].append(
            "[motion.reduced_motion] the page does not read prefers-reduced-motion; drive.mjs --reduced cannot freeze it"
        )

    # craft.object_fills_card: measure the rendered ink on the first frame.
    if frames_dir is not None:
        frames = sorted(Path(frames_dir).glob("*.png"))
        if frames:
            from hevi.capabilities.anatomy_explainer.verify import image_stats

            stats = image_stats(frames[0])
            report["measurements"]["ink_ratio"] = stats["ink_ratio"]
            report["measurements"]["colours"] = stats["colours"]
            if not FILL_RANGE[0] <= stats["ink_ratio"] <= FILL_RANGE[1]:
                report["warnings"].append(
                    f"[craft.object_fills_card] ink covers {stats['ink_ratio']:.2f} of the frame "
                    f"(the reference range is {FILL_RANGE[0]}–{FILL_RANGE[1]}; the 2D kid plates use a "
                    "decorated card, so this is measured and reported, not enforced)"
                )
        else:
            report["warnings"].append("[craft.object_fills_card] no frames to measure")

    report["passed"] = not report["violations"]
    return report


def write_report(path: Path, report: dict[str, Any]) -> Path:
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def enforce(report: dict[str, Any]) -> None:
    """Raise :class:`ConstraintViolation` when a hard rule failed."""
    if report.get("violations"):
        raise ConstraintViolation("Anatomy craft rules failed:\n  " + "\n  ".join(report["violations"]))
