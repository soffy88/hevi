"""Character sheet structure contract (``qa.character_sheet_gate``).

Clean-room reimplementation of method ideas only; see
H3_CHARACTER_SHEET_ATTRIBUTION.md. No upstream code, prompt text or
artwork is copied here, and no image is generated: this module judges
JSON plans only.

The contract has three parts, each covering a gap the neighbouring
gates do not:

1. A fixed view catalogue. A character sheet names its views from a
   closed list of thirteen (six portraits, three full-body views, two
   clothing details, hands, feet). A view that is required but absent
   is reported ``pending`` -- never silently filled in, and never
   covered by a different view: a full-body view does not stand in
   for a hands, feet or clothing detail.
2. A body-part scope table. Each of eight parts applies only to the
   views where that part is actually visible from the assigned
   camera angle. Visibility is a camera/anatomy fact; it is never
   inferred from free-form wording. Directive text is treated as
   literal appearance wording only: it is never parsed as a layout
   or timing instruction.
3. A reference-role policy. Extra reference pictures are assigned
   one role each (same character, face, head, clothing, front/back
   clothing, hands, footwear). A role only governs the parts and
   views in its scope, a later reference with the same role wins
   over an earlier one, and an explicit part directive beats a
   role. Roles are text guidance only: exact identity transfer is
   never guaranteed by this gate.

Left and right are anatomical: in a left view the subject's left
side faces the camera and the nose points toward the right edge of
the sheet; in a right view the nose points toward the left edge.
Asymmetric features are never mirrored.

Failure contract: malformed plans (not a JSON object, missing ids,
non-string fields) raise CapabilityError. Gate failures (unknown
view, duplicate view, out-of-scope part directive, face wording
aimed at a rear view, detail substitution) are reported in the
result, not raised. A missing required view yields verdict
``pending``; a failed rule yields ``fail``; otherwise ``pass``.
"""

from __future__ import annotations

import json
import re
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

# ---------------------------------------------------------------- views

PORTRAIT_VIEWS = (
    "face_front",
    "face_left",
    "face_right",
    "face_3q_left",
    "face_3q_right",
    "face_back",
)
BODY_VIEWS = ("body_front", "body_left", "body_back")
CLOTHING_VIEWS = ("clothing_front", "clothing_back")
VIEW_IDS = (*PORTRAIT_VIEWS, *BODY_VIEWS, *CLOTHING_VIEWS, "hands", "feet")

# Views from behind: no face may be shown or described there.
REAR_VIEWS = frozenset({"face_back", "body_back", "clothing_back"})

# Detail views: a full-body view never substitutes for one of these.
DETAIL_VIEWS = frozenset({"clothing_front", "clothing_back", "hands", "feet"})

# Anatomical side convention: the edge the nose points toward.
LEFT_VIEWS = frozenset({"face_left", "face_3q_left", "body_left"})
RIGHT_VIEWS = frozenset({"face_right", "face_3q_right"})
NOSE_EDGE = {"left": "right", "right": "left"}

VIEW_LABELS = {
    "face_front": "front portrait",
    "face_left": "anatomical left-profile portrait",
    "face_right": "anatomical right-profile portrait",
    "face_3q_left": "anatomical left three-quarter portrait",
    "face_3q_right": "anatomical right three-quarter portrait",
    "face_back": "rear portrait",
    "body_front": "full-body front",
    "body_left": "anatomical left-profile full body",
    "body_back": "full-body back",
    "clothing_front": "clothing front detail",
    "clothing_back": "clothing back detail",
    "hands": "hands detail",
    "feet": "feet and footwear detail",
}

PRESETS = {
    "five": ("face_front", "face_left", "body_front", "body_left", "body_back"),
    "basic": ("face_front", "body_front", "body_left", "body_back"),
    "detail": VIEW_IDS,
    "turnaround": BODY_VIEWS,
    "single": ("body_front",),
    "head": PORTRAIT_VIEWS,
    "clothing": CLOTHING_VIEWS,
}

# ---------------------------------------------------------------- parts

# Priority is only a tie-breaker inside one view: a more specific
# directive wins over a generic one. The rear-clothing surface is
# more specific than upper clothing wherever both could apply.
PART_PRIORITY = {"back_clothing": 20, "other": 0}
_DEFAULT_PRIORITY = 10

# Applicable views per part, as a method default. Callers may pass
# their own table to check_part_directives; nothing here is a
# measured property of any model.
_FRONTAL_PORTRAITS = tuple(v for v in PORTRAIT_VIEWS if v != "face_back")
_FRONTAL_BODY = ("body_front", "body_left")
DEFAULT_PART_TABLE: dict[str, dict[str, Any]] = {
    "head_hair": {"views": (*PORTRAIT_VIEWS, *BODY_VIEWS)},
    "face": {"views": (*_FRONTAL_PORTRAITS, *_FRONTAL_BODY)},
    "upper_clothing": {"views": (*_FRONTAL_PORTRAITS, *_FRONTAL_BODY, "clothing_front")},
    "back_clothing": {"views": ("body_left", "body_back", "clothing_back")},
    "lower_body": {"views": (*BODY_VIEWS, "clothing_front", "clothing_back")},
    "hands": {"views": (*BODY_VIEWS, "hands")},
    "footwear": {"views": (*BODY_VIEWS, "feet")},
    "other": {"views": VIEW_IDS},
}
PART_IDS = tuple(DEFAULT_PART_TABLE)

# Wording that looks like a layout or timing instruction. Such text
# is kept verbatim as appearance wording and flagged; it is never
# executed as a placement or timing command.
_LAYOUT_TIME_PATTERNS = (
    re.compile(r"\d+\s*(?:秒|seconds?|frames?|帧|fps)"),
    re.compile(r"(?:左上|右上|左下|右下|top-left|top-right|bottom-left|bottom-right|坐标|position|layout|timeline|timecode)"),
    re.compile(r"(?:pan|zoom|推镜|拉镜|移动到|移到)"),
)


def part_priority(part: str) -> int:
    """Tie-break priority of a part directive (higher wins)."""
    return PART_PRIORITY.get(part, _DEFAULT_PRIORITY)


def _req_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"qa.character_sheet_gate: {what} must be a non-empty string")
    return value.strip()


def _view_records(views: Any) -> list[dict[str, Any]]:
    """Normalise a view list to records; plain strings count as current."""
    if not isinstance(views, list):
        raise CapabilityError("qa.character_sheet_gate: views must be a list")
    records: list[dict[str, Any]] = []
    for item in views:
        if isinstance(item, str):
            records.append({"view": _req_str(item, "view"), "status": "current"})
        elif isinstance(item, dict):
            records.append(
                {"view": _req_str(item.get("view"), "view"),
                 "status": item.get("status", "current")}
            )
        else:
            raise CapabilityError("qa.character_sheet_gate: every view must be a string or object")
    return records


def check_view_manifest(
    views: Any,
    required: list[str] | None = None,
    claimed_substitutions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Judge a sheet's view list against the catalogue.

    ``required`` defaults to the ``five`` preset. A required view
    that is absent is ``pending``; a view claimed to be covered by
    a full-body view is a failure, not a pass.
    """
    required = list(required) if required is not None else list(PRESETS["five"])
    for view in required:
        if view not in VIEW_IDS:
            raise CapabilityError(f"qa.character_sheet_gate: unknown required view {view!r}")
    issues: list[dict[str, Any]] = []
    records = _view_records(views)
    current: dict[str, dict[str, Any]] = {}
    for record in records:
        view = record["view"]
        if view not in VIEW_IDS:
            issues.append({"code": "UNKNOWN_VIEW", "severity": "fail",
                           "message": f"view {view!r} is not in the catalogue"})
            continue
        if record["status"] != "current":
            continue
        if view in current:
            issues.append({"code": "DUPLICATE_VIEW", "severity": "fail",
                           "message": f"view {view!r} appears more than once as current"})
        current[view] = record
    missing = [view for view in required if view not in current]
    for view in missing:
        issues.append({"code": "MISSING_VIEW", "severity": "pending",
                       "message": f"required view {view!r} is missing; marked pending, not filled in"})
    for missing_view, claimed in (claimed_substitutions or {}).items():
        if missing_view in DETAIL_VIEWS and claimed in BODY_VIEWS:
            issues.append({"code": "DETAIL_NOT_SUBSTITUTED", "severity": "fail",
                           "message": f"detail view {missing_view!r} cannot be covered "
                                      f"by full-body view {claimed!r}"})
    fatal = any(i["severity"] == "fail" for i in issues)
    verdict = "fail" if fatal else ("pending" if missing else "pass")
    return {"verdict": verdict, "issues": issues,
            "current_views": sorted(current), "missing_views": missing}


def check_anchor_sheet_views(sheet: dict[str, Any],
                             required: list[str] | None = None) -> dict[str, Any]:
    """Apply the view catalogue to an anchor-gate shaped sheet.

    Only ``current`` views count; stale and superseded records are
    ignored. The anchor discipline itself lives in
    qa.character_anchor_gate and is not re-implemented here.
    """
    if not isinstance(sheet, dict):
        raise CapabilityError("qa.character_sheet_gate: sheet must be a JSON object")
    return check_view_manifest(sheet.get("views", []), required)


# ---------------------------------------------------------------- parts

def _directive_records(directives: Any) -> list[dict[str, Any]]:
    if not isinstance(directives, list):
        raise CapabilityError("qa.character_sheet_gate: part_directives must be a list")
    records: list[dict[str, Any]] = []
    for item in directives:
        if not isinstance(item, dict):
            raise CapabilityError("qa.character_sheet_gate: every directive must be an object")
        records.append({"part": _req_str(item.get("part"), "directive.part"),
                        "view": _req_str(item.get("view"), "directive.view"),
                        "text": item.get("text", "")})
        if not isinstance(records[-1]["text"], str):
            raise CapabilityError("qa.character_sheet_gate: directive.text must be a string")
    return records


def _literal_only_flags(text: str) -> list[str]:
    return [p.pattern for p in _LAYOUT_TIME_PATTERNS if p.search(text)]


def check_part_directives(
    directives: Any,
    selected_views: list[str] | None = None,
    part_table: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Judge part directives against the scope table.

    A directive aimed at a view where its part is not visible
    fails. A ``face`` directive aimed at a rear view fails under
    its own code. Wording that reads like a layout/timing command
    is flagged literal-only and kept verbatim.
    """
    table = part_table if part_table is not None else DEFAULT_PART_TABLE
    issues: list[dict[str, Any]] = []
    records = _directive_records(directives)
    effective: list[dict[str, Any]] = []
    for record in records:
        part, view = record["part"], record["view"]
        if part not in table:
            issues.append({"code": "UNKNOWN_PART", "severity": "fail",
                           "message": f"unknown part {part!r}"})
            continue
        if view not in VIEW_IDS:
            issues.append({"code": "UNKNOWN_VIEW", "severity": "fail",
                           "message": f"unknown view {view!r}"})
            continue
        if part == "face" and view in REAR_VIEWS:
            issues.append({"code": "FACE_IN_REAR_VIEW", "severity": "fail",
                           "message": f"face directive must not target rear view {view!r}"})
            continue
        if view not in table[part]["views"]:
            issues.append({"code": "PART_VIEW_SCOPE", "severity": "fail",
                           "message": f"part {part!r} is not visible from view {view!r}"})
            continue
        if selected_views is not None and view not in selected_views:
            issues.append({"code": "DIRECTIVE_VIEW_NOT_SELECTED", "severity": "warn",
                           "message": f"directive targets unselected view {view!r}"})
        flags = _literal_only_flags(record["text"])
        entry = dict(record)
        entry["priority"] = part_priority(part)
        entry["literal_text"] = record["text"]
        if flags:
            entry["literal_only"] = True
            issues.append({"code": "LITERAL_ONLY", "severity": "warn",
                           "message": f"directive text for {part!r} on {view!r} reads like a "
                                      "layout/timing instruction; kept verbatim, never executed"})
        effective.append(entry)
    superseded: list[dict[str, Any]] = []
    for entry in effective:
        if entry["part"] == "upper_clothing" and entry["view"] in ("body_left", "body_back"):
            rival = next((e for e in effective
                          if e["part"] == "back_clothing" and e["view"] == entry["view"]), None)
            if rival is not None:
                entry["superseded_by"] = "back_clothing"
                superseded.append(entry)
    fatal = any(i["severity"] == "fail" for i in issues)
    return {"verdict": "fail" if fatal else "pass", "issues": issues,
            "effective_directives": [e for e in effective if "superseded_by" not in e],
            "superseded_directives": superseded}


# ---------------------------------------------------------------- roles

ROLES = (
    "same_character",
    "face",
    "head",
    "clothing",
    "clothing_front",
    "clothing_back",
    "hands",
    "footwear",
)
ROLE_PARTS: dict[str, tuple[str, ...]] = {
    "same_character": PART_IDS,
    "face": ("face",),
    "head": ("head_hair", "face"),
    "clothing": ("upper_clothing", "back_clothing", "lower_body"),
    "clothing_front": ("upper_clothing", "lower_body"),
    "clothing_back": ("upper_clothing", "back_clothing", "lower_body"),
    "hands": ("hands",),
    "footwear": ("footwear",),
}
# Views a role may never govern, beyond the per-part scopes.
ROLE_EXCLUDED_VIEWS: dict[str, frozenset] = {
    "face": REAR_VIEWS,
    "clothing_front": REAR_VIEWS,
    "clothing_back": frozenset(set(VIEW_IDS) - {"body_left", "body_back", "clothing_back"}),
}

REFERENCE_GUIDANCE_DISCLAIMER = (
    "Reference roles are text guidance only; exact transfer of "
    "identity or clothing is not guaranteed by this gate."
)


def resolve_reference_roles(
    references: Any,
    selected_views: list[str] | None = None,
    explicit_directives: Any = None,
) -> dict[str, Any]:
    """Resolve reference roles to part/view scopes.

    Later references with the same role win; an explicit part
    directive beats a role for the same part and view. Every
    resolved entry carries the guidance-only disclaimer.
    """
    if not isinstance(references, list):
        raise CapabilityError("qa.character_sheet_gate: references must be a list")
    issues: list[dict[str, Any]] = []
    explicit: set[tuple[str, str]] = set()
    if explicit_directives is not None:
        for directive in _directive_records(explicit_directives):
            explicit.add((directive["part"], directive["view"]))
    resolved: list[dict[str, Any]] = []
    superseded: list[dict[str, Any]] = []
    seen_roles: dict[str, dict[str, Any]] = {}
    for item in references:
        if not isinstance(item, dict):
            raise CapabilityError("qa.character_sheet_gate: every reference must be an object")
        role = _req_str(item.get("role"), "reference.role")
        ref_id = _req_str(item.get("ref_id"), "reference.ref_id")
        if role not in ROLES:
            issues.append({"code": "UNKNOWN_ROLE", "severity": "fail",
                           "message": f"unknown reference role {role!r}"})
            continue
        views: set[str] = set()
        for part in ROLE_PARTS[role]:
            views.update(DEFAULT_PART_TABLE[part]["views"])
        views -= set(ROLE_EXCLUDED_VIEWS.get(role, frozenset()))
        if selected_views is not None:
            views &= set(selected_views)
        entry = {"ref_id": ref_id, "role": role,
                 "parts": list(ROLE_PARTS[role]), "views": sorted(views),
                 "guidance_only": True,
                 "disclaimer": REFERENCE_GUIDANCE_DISCLAIMER}
        overridden = sorted(f"{part} on {view}" for part, view in explicit
                            if part in ROLE_PARTS[role] and view in views)
        if overridden:
            entry["overridden_by_explicit_directive"] = overridden
        if role in seen_roles:
            superseded.append(seen_roles[role])
            issues.append({"code": "ROLE_CONFLICT_SUPERSEDED", "severity": "warn",
                           "message": f"reference {seen_roles[role]['ref_id']!r} with role "
                                      f"{role!r} is superseded by later reference {ref_id!r}"})
        seen_roles[role] = entry
        resolved.append(entry)
    resolved = [entry for entry in resolved if entry not in superseded]
    fatal = any(i["severity"] == "fail" for i in issues)
    return {"verdict": "fail" if fatal else "pass", "issues": issues,
            "resolved_references": resolved, "superseded_references": superseded}


# ---------------------------------------------------------------- combined

def check_character_sheet(plan: dict[str, Any]) -> dict[str, Any]:
    """Judge one character-sheet plan: views, parts, roles together."""
    if not isinstance(plan, dict):
        raise CapabilityError("qa.character_sheet_gate: plan must be a JSON object")
    view_result = check_view_manifest(
        plan.get("views", []), plan.get("required_views"),
        plan.get("claimed_substitutions"))
    part_result = check_part_directives(
        plan.get("part_directives", []), plan.get("selected_views"))
    role_result = resolve_reference_roles(
        plan.get("references", []), plan.get("selected_views"),
        plan.get("part_directives", []))
    issues = view_result["issues"] + part_result["issues"] + role_result["issues"]
    fatal = any(i["severity"] == "fail" for i in issues)
    verdict = "fail" if fatal else ("pending" if view_result["verdict"] == "pending" else "pass")
    return {"verdict": verdict, "issues": issues,
            "view_manifest": view_result, "part_directives": part_result,
            "reference_roles": role_result,
            "disclaimer": REFERENCE_GUIDANCE_DISCLAIMER}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_character_sheet(params.get("plan", {}))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "character_sheet_gate.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"],
            "missing_views": result["view_manifest"]["missing_views"]},
    )


def register_character_sheet_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.character_sheet_gate",
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
            "Character sheet structure contract (clean-room): a fixed "
            "thirteen-view catalogue with a pending-not-fabricated "
            "missing-view rule, a body-part scope table, and a "
            "reference-role policy. Judges JSON plans only; no image "
            "is generated here."
        ),
        line="qa",
    ))
    return ["qa.character_sheet_gate"]


register_character_sheet_capabilities_once()
