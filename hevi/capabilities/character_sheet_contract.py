"""Deterministic compile contract, layout-guide discipline and
style-only-painting rule for character sheets
(``qa.character_sheet_contract``).

Clean-room reimplementation of method ideas only; see
H3_CHARACTER_SHEET_ATTRIBUTION.md. No upstream code, prompt text or
artwork is copied here, and no image is generated: this module judges
JSON plans only. It extends ``qa.character_sheet_gate`` without
changing that gate's behaviour: the view catalogue, part scope table
and reference-role policy live in ``character_sheet.py`` and are
reused here, never redefined.

Three checks, each covering a gap the neighbouring gates do not:

1. A deterministic compile contract. A sheet state carries a schema
   version and is strictly key-checked: unknown keys, missing
   required keys and wrong types fail. A state written under an older
   schema (1 or 2) is only accepted when it carries an explicit
   migration record; silently treating it as current-schema data
   fails. The canonical compilation of a state is byte-deterministic:
   the same input always serialises to the same bytes, and a golden
   fixture pins the exact output for one fixed input.
2. Layout-guide ON/OFF discipline. OFF is the baseline: pure text,
   no guide image, and the layout record must still state in words
   that it is semantic guidance, not a hard constraint. ON requires a
   guide image whose source is declared self-drawn; the upstream
   mannequin atlas is forbidden here and is never referenced, copied
   or recreated.
3. A style-only-painting rule. A style name comes from a closed list
   and may only change how the sheet is painted (line, shading,
   colour rendering, texture, brushwork, lighting rendering). Adding
   scenery, a new person or a new prop through the style field fails,
   as does changing identity, proportion or costume through it. This
   is the single "style adds nothing" constraint; style assembly
   itself already lives in lemo_styles / handraw and is not rebuilt.

Failure contract: malformed plans (not a JSON object) raise
CapabilityError. Gate failures are reported in the result, not
raised. Verdicts are ``pass`` / ``fail`` only; a missing view is a
``character_sheet_gate`` concern and is not re-judged here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.character_sheet import VIEW_IDS
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# ---------------------------------------------------------------- contract

CURRENT_SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = (1, 2, 3)

# Closed top-level key set for a sheet state. Anything else is
# rejected rather than silently ignored: an unrecognised key is
# either a typo or a newer field this contract does not understand.
STATE_KEYS = frozenset({
    "schema_version",
    "sheet_id",
    "character_id",
    "views",
    "part_directives",
    "references",
    "style",
    "layout",
    "migration",
})
REQUIRED_STATE_KEYS = ("schema_version", "sheet_id", "views")

# Method defaults taken from the upstream contract's stated limits:
# a state document is capped at 64 KiB and one part-directive field
# at 1000 UTF-16 code units. Callers may pass tighter limits; the
# defaults are recorded here so a failure names its threshold.
MAX_STATE_BYTES = 64 * 1024
MAX_DIRECTIVE_UTF16_UNITS = 1000


def _issue(severity: str, code: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message}


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def canonical_sheet_bytes(state: dict[str, Any]) -> bytes:
    """Serialise one sheet state to its canonical byte form.

    Keys sorted, no insignificant whitespace, UTF-8. The same input
    dict always produces the same bytes, whatever order the caller
    built it in.
    """
    return json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def validate_sheet_state(state: Any) -> dict[str, Any]:
    """Strict-check one sheet state document.

    Returns ``verdict`` plus an ``issues`` list. Unknown keys, a
    missing required key, an unsupported schema version, a state
    document over the byte cap, an over-long directive field, an
    unknown view id, or an older schema without an explicit
    migration record each fail the state.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(state, dict):
        raise CapabilityError(
            "qa.character_sheet_contract: state must be a JSON object")
    unknown = sorted(set(state) - STATE_KEYS)
    if unknown:
        issues.append(_issue(
            "fail", "UNKNOWN_STATE_KEY",
            f"unknown state key(s): {', '.join(unknown)}"))
    for key in REQUIRED_STATE_KEYS:
        if key not in state:
            issues.append(_issue(
                "fail", "MISSING_STATE_KEY", f"missing required key: {key}"))
    version = state.get("schema_version")
    if version is not None and version not in SUPPORTED_SCHEMA_VERSIONS:
        issues.append(_issue(
            "fail", "UNSUPPORTED_SCHEMA_VERSION",
            f"schema_version {version!r} is not one of "
            f"{list(SUPPORTED_SCHEMA_VERSIONS)}"))
    if isinstance(version, int) and version < CURRENT_SCHEMA_VERSION:
        migration = state.get("migration")
        if not isinstance(migration, dict) or migration.get(
                "from_version") != version or migration.get(
                "to_version") != CURRENT_SCHEMA_VERSION:
            issues.append(_issue(
                "fail", "SILENT_UPGRADE",
                "an older schema state must carry an explicit "
                "migration record (from_version/to_version); "
                "silent upgrade is refused"))
    try:
        size = len(canonical_sheet_bytes(state))
    except (TypeError, ValueError):
        issues.append(_issue(
            "fail", "UNENCODABLE_STATE", "state is not JSON-encodable"))
        size = 0
    if size > MAX_STATE_BYTES:
        issues.append(_issue(
            "fail", "STATE_TOO_LARGE",
            f"canonical state is {size} bytes, over the "
            f"{MAX_STATE_BYTES} byte cap"))
    views = state.get("views")
    if views is not None:
        if not isinstance(views, list) or not all(
                isinstance(v, str) for v in views):
            issues.append(_issue(
                "fail", "VIEWS_NOT_STRINGS", "views must be a list of strings"))
        else:
            bad = [v for v in views if v not in VIEW_IDS]
            if bad:
                issues.append(_issue(
                    "fail", "UNKNOWN_VIEW",
                    f"unknown view id(s): {', '.join(bad)}"))
    for directive in state.get("part_directives", []) or []:
        if isinstance(directive, dict):
            for field in ("text", "wording", "instruction"):
                value = directive.get(field)
                if isinstance(value, str) and _utf16_units(
                        value) > MAX_DIRECTIVE_UTF16_UNITS:
                    issues.append(_issue(
                        "fail", "DIRECTIVE_TOO_LONG",
                        f"part directive field {field!r} exceeds "
                        f"{MAX_DIRECTIVE_UTF16_UNITS} UTF-16 units"))
    fatal = any(i["severity"] == "fail" for i in issues)
    return {
        "verdict": "fail" if fatal else "pass",
        "issues": issues,
        "schema_version": version,
        "canonical_bytes": size,
    }


# ---------------------------------------------------------------- layout guide

# A layout record must state, in words, that it is semantic guidance
# and not a hard geometric constraint. Either language pair counts.
GUIDANCE_MARKERS = (
    ("语义指导", "不是硬约束"),
    ("semantic guidance", "not a hard constraint"),
)

FORBIDDEN_GUIDE_SOURCES = frozenset({
    "upstream_atlas",
    "mannequin_atlas",
    "mannequin-atlas",
    "atlas",
})


def check_layout_guide(plan: Any) -> dict[str, Any]:
    """Judge the layout-guide discipline of one sheet plan.

    ``layout`` is a record with ``mode`` ``"off"`` (baseline) or
    ``"on"``. OFF admits no guide image at all. ON requires a guide
    image declared as self-drawn, with a non-empty provenance
    declaration; the upstream atlas is forbidden. In both modes the
    layout record must carry the semantic-guidance marker.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        raise CapabilityError(
            "qa.character_sheet_contract: plan must be a JSON object")
    layout = plan.get("layout")
    if not isinstance(layout, dict):
        return {"verdict": "fail", "issues": [_issue(
            "fail", "MISSING_LAYOUT", "plan has no layout record")],
            "mode": None}
    mode = layout.get("mode")
    if mode not in ("off", "on"):
        issues.append(_issue(
            "fail", "UNKNOWN_LAYOUT_MODE",
            f"layout mode {mode!r} must be 'off' or 'on'"))
    note = layout.get("guidance_note", "")
    if not isinstance(note, str) or not any(
            a in note and b in note for a, b in GUIDANCE_MARKERS):
        issues.append(_issue(
            "fail", "MISSING_GUIDANCE_MARKER",
            "layout record must state it is semantic guidance, "
            "not a hard constraint"))
    guide = layout.get("guide_image")
    if mode == "off":
        if guide is not None:
            issues.append(_issue(
                "fail", "GUIDE_IMAGE_WHILE_OFF",
                "layout OFF is text-only; a guide image must not be present"))
    elif mode == "on":
        if not isinstance(guide, dict):
            issues.append(_issue(
                "fail", "MISSING_GUIDE_IMAGE",
                "layout ON requires a guide image record"))
        else:
            source = guide.get("source")
            if source in FORBIDDEN_GUIDE_SOURCES:
                issues.append(_issue(
                    "fail", "ATLAS_FORBIDDEN",
                    "the upstream mannequin atlas must not be used as "
                    "a guide image; only a self-drawn silhouette is allowed"))
            elif source != "self_drawn":
                issues.append(_issue(
                    "fail", "GUIDE_SOURCE_UNDECLARED",
                    "guide image source must be declared 'self_drawn'"))
            if not isinstance(guide.get("declaration"), str) or not guide[
                    "declaration"].strip():
                issues.append(_issue(
                    "fail", "GUIDE_DECLARATION_MISSING",
                    "a self-drawn guide image needs a non-empty "
                    "provenance declaration"))
    fatal = any(i["severity"] == "fail" for i in issues)
    return {"verdict": "fail" if fatal else "pass", "issues": issues,
            "mode": mode}


# ---------------------------------------------------------------- style

# Closed style list (nine effective styles plus explicit none). Style
# assembly lives elsewhere; this gate only polices what a style
# change is allowed to touch.
STYLE_IDS = (
    "none",
    "anime",
    "photo",
    "realistic_painting",
    "semi_realistic_anime",
    "oil_painting",
    "watercolor",
    "gouache",
    "colored_pencil",
    "3d",
)

# The only aspects a style change may touch: how the sheet is
# painted. Anything naming a subject, a place, a prop, identity,
# proportion or costume is not a painting technique.
PAINTING_ASPECTS = frozenset({
    "line", "shading", "color_rendering", "texture", "brushwork",
    "lighting_rendering",
})
NON_PAINTING_ASPECTS = frozenset({
    "scenery", "subject", "prop", "identity", "proportion", "costume",
    "background", "character", "setting",
})


def check_style_only(style: Any) -> dict[str, Any]:
    """Judge that a style change only changes how the sheet is painted.

    ``style`` is a record with ``name``, ``changed`` (aspects the
    style touches) and ``added_elements`` (things the style would
    introduce). Any added element fails; any changed aspect outside
    the painting set fails; an unknown style name fails. A style
    that drops a preserved feature (face, proportion, costume) is
    warned, not failed: preservation is the sheet gate's job.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(style, dict):
        raise CapabilityError(
            "qa.character_sheet_contract: style must be a JSON object")
    name = style.get("name")
    if name not in STYLE_IDS:
        issues.append(_issue(
            "fail", "UNKNOWN_STYLE", f"unknown style name: {name!r}"))
    added = style.get("added_elements", [])
    if added:
        issues.append(_issue(
            "fail", "STYLE_ADDS_OBJECT",
            "a style change must not add elements: "
            + ", ".join(str(a) for a in added)))
    changed = style.get("changed", [])
    bad = [c for c in changed if c in NON_PAINTING_ASPECTS]
    if bad:
        issues.append(_issue(
            "fail", "STYLE_CHANGES_SUBJECT",
            "a style change must only change painting technique, "
            f"not: {', '.join(str(c) for c in bad)}"))
    unknown_changed = [c for c in changed
                       if c not in PAINTING_ASPECTS and c not in NON_PAINTING_ASPECTS]
    if unknown_changed:
        issues.append(_issue(
            "warn", "UNKNOWN_CHANGED_ASPECT",
            "unrecognised changed aspect(s): "
            + ", ".join(str(c) for c in unknown_changed)))
    preserved = style.get("preserved", [])
    for feature in ("face", "proportion", "costume"):
        if name not in (None, "none") and feature not in preserved:
            issues.append(_issue(
                "warn", "PRESERVED_FEATURE_UNLISTED",
                f"preserved features should list {feature!r}"))
    fatal = any(i["severity"] == "fail" for i in issues)
    return {"verdict": "fail" if fatal else "pass", "issues": issues,
            "style": name}


# ---------------------------------------------------------------- combined

def check_sheet_contract(plan: dict[str, Any]) -> dict[str, Any]:
    """Judge one sheet plan: state contract, layout guide, style."""
    if not isinstance(plan, dict):
        raise CapabilityError(
            "qa.character_sheet_contract: plan must be a JSON object")
    state_result = validate_sheet_state(plan.get("state", {}))
    layout_result = check_layout_guide(plan)
    style_result = check_style_only(plan.get("style", {}))
    issues = (state_result["issues"] + layout_result["issues"]
              + style_result["issues"])
    fatal = any(i["severity"] == "fail" for i in issues)
    return {
        "verdict": "fail" if fatal else "pass",
        "issues": issues,
        "state": state_result,
        "layout": layout_result,
        "style": style_result,
        "disclaimer": (
            "This gate judges JSON plans only. It does not generate "
            "any image and does not measure whether a generated "
            "sheet keeps a character consistent."),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    result = check_sheet_contract(params.get("plan", {}))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "character_sheet_contract.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"]},
    )


def register_character_sheet_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.character_sheet_contract",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Character sheet compile contract (clean-room): a "
            "versioned, strictly key-checked, byte-deterministic "
            "state contract with explicit migration, layout-guide "
            "ON/OFF discipline (self-drawn guides only, atlas "
            "forbidden), and a style-only-painting rule. Judges "
            "JSON plans only; no image is generated here."
        ),
        line="qa",
    ))
    return ["qa.character_sheet_contract"]


register_character_sheet_contract_capabilities_once()
