"""Reference-use gate (``qa.reference_use_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-ai-manju-skills.md``
section 2 / A2, consolidated into one gate: a reference picture
may only be used for what its kind allows, and every reference
rides hevi's numbering discipline, never a foreign notation.

* A character reference supplies likeness only -- never the
  angle, composition, pose, or expression of the shot.
* A scene reference supplies structure only -- never the angle
  or a multi-character blocking.
* A prop reference must keep its front/back logic consistent.
* A multi-view set must not repeat the same view, and a mirrored
  scene is not a new view.

Numbering: the plan declares ``numbering_convention`` from
``qa.reference_numbering_gate`` (``identity-first`` /
``scene-first``); under ``identity-first`` reference 1 must be
the identity role. The ``{{Mixed N}}`` placeholder notation from
the source templates is not a hevi numbering and fails outright
wherever it appears. The full mounting check (picture -> role
order, audio registration) stays the job of
``qa.reference_numbering_gate``; this gate judges use, not
mounting.

This module judges plans only. It reads no image bytes and
calls no generator.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.reference_numbering_gate import (
    IDENTITY_FIRST_MAP,
    NUMBERING_CONVENTIONS,
    ROLES,
)
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

KINDS = ("character", "scene", "prop")

# What each kind may take from its reference picture. Anything
# outside the allowed set is a use the reference does not grant.
_CHARACTER_TAKES = {"likeness"}
_CHARACTER_FORBIDDEN = {"angle", "composition", "pose", "expression"}
_SCENE_TAKES = {"structure"}
_SCENE_FORBIDDEN = {"angle", "multi_character_blocking"}
_PROP_TAKES = {"form", "texture"}

_MIXED_RE = re.compile(r"mixed\s*\d+", re.IGNORECASE)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_reference_use(plan: Any) -> dict[str, Any]:
    """Judge one reference-use plan. Returns a report; never raises for a bad plan.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    references_out: list[dict[str, Any]] = []
    convention = None

    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "numbering_convention": None,
            "references": [],
            "issues": [
                _issue(
                    "plan_not_object",
                    "qa.reference_use_gate: reference plan must be an object",
                )
            ],
        }

    convention = plan.get("numbering_convention")
    if not _is_nonempty_str(convention):
        issues.append(
            _issue(
                "missing_numbering_convention",
                "qa.reference_use_gate: the plan declares no "
                "'numbering_convention' (identity-first or scene-first)",
            )
        )
        convention = None
    elif convention not in NUMBERING_CONVENTIONS:
        issues.append(
            _issue(
                "unsupported_numbering_convention",
                f"qa.reference_use_gate: numbering_convention "
                f"{convention!r} is not one of {list(NUMBERING_CONVENTIONS)}",
            )
        )

    references = plan.get("references")
    if not isinstance(references, list) or not references:
        issues.append(
            _issue(
                "references_missing",
                "qa.reference_use_gate: the plan needs a non-empty "
                "'references' list",
            )
        )
        references = []

    seen_views: set[tuple[str, str]] = set()
    for index, ref in enumerate(references):
        label = f"reference {index + 1}"
        if not isinstance(ref, dict):
            issues.append(
                _issue(
                    "reference_not_object",
                    f"qa.reference_use_gate: {label} must be an object",
                )
            )
            continue
        number = ref.get("ref_number")
        if isinstance(number, int) and not isinstance(number, bool):
            label = f"reference {number}"
        entry: dict[str, Any] = {"label": label}
        asset_id = ref.get("asset_id")
        if not _is_nonempty_str(asset_id):
            issues.append(
                _issue(
                    "asset_id_missing",
                    f"qa.reference_use_gate: {label} must declare an "
                    "'asset_id'",
                )
            )
        else:
            entry["asset_id"] = asset_id
            if _MIXED_RE.search(asset_id):
                issues.append(
                    _issue(
                        "mixed_n_notation",
                        f"qa.reference_use_gate: {label} uses the foreign "
                        "'Mixed N' placeholder notation; hevi references "
                        "ride the declared numbering convention, never "
                        "Mixed N",
                    )
                )
        role = ref.get("role")
        if role not in ROLES:
            issues.append(
                _issue(
                    "role_unknown",
                    f"qa.reference_use_gate: {label} role {role!r} is not "
                    f"one of {list(ROLES)}",
                )
            )
        else:
            entry["role"] = role
            if (
                convention == "identity-first"
                and isinstance(number, int)
                and number in IDENTITY_FIRST_MAP
                and role != IDENTITY_FIRST_MAP[number]
            ):
                issues.append(
                    _issue(
                        "numbering_role_mismatch",
                        f"qa.reference_use_gate: {label} under "
                        "identity-first must be role "
                        f"{IDENTITY_FIRST_MAP[number]!r}, got {role!r}",
                    )
                )
        kind = ref.get("kind")
        if kind not in KINDS:
            issues.append(
                _issue(
                    "kind_unknown",
                    f"qa.reference_use_gate: {label} kind {kind!r} is not "
                    f"one of {list(KINDS)}",
                )
            )
            references_out.append(entry)
            continue
        entry["kind"] = kind
        takes = ref.get("takes")
        if not isinstance(takes, list) or not takes:
            issues.append(
                _issue(
                    "takes_missing",
                    f"qa.reference_use_gate: {label} must declare a "
                    "non-empty 'takes' list naming what the shot takes "
                    "from the reference",
                )
            )
            takes = []
        takes_set = {t for t in takes if isinstance(t, str)}
        if kind == "character":
            bad = takes_set & _CHARACTER_FORBIDDEN
            if bad:
                issues.append(
                    _issue(
                        "character_reference_overreach",
                        f"qa.reference_use_gate: {label} is a character "
                        f"reference and supplies likeness only; it must "
                        f"not supply {sorted(bad)}",
                    )
                )
            if not takes_set <= _CHARACTER_TAKES:
                extra = takes_set - _CHARACTER_TAKES - _CHARACTER_FORBIDDEN
                if extra:
                    issues.append(
                        _issue(
                            "character_take_unknown",
                            f"qa.reference_use_gate: {label} takes "
                            f"{sorted(extra)}, which no character "
                            "reference grants",
                        )
                    )
        elif kind == "scene":
            bad = takes_set & _SCENE_FORBIDDEN
            if bad:
                issues.append(
                    _issue(
                        "scene_reference_overreach",
                        f"qa.reference_use_gate: {label} is a scene "
                        "reference and supplies structure only; it must "
                        f"not supply {sorted(bad)}",
                    )
                )
            if not takes_set <= _SCENE_TAKES:
                extra = takes_set - _SCENE_TAKES - _SCENE_FORBIDDEN
                if extra:
                    issues.append(
                        _issue(
                            "scene_take_unknown",
                            f"qa.reference_use_gate: {label} takes "
                            f"{sorted(extra)}, which no scene reference "
                            "grants",
                        )
                    )
            if ref.get("mirrored") is True:
                issues.append(
                    _issue(
                        "mirrored_scene_not_new_view",
                        f"qa.reference_use_gate: {label} is a mirrored "
                        "scene; a mirror is not a new view",
                    )
                )
        else:  # prop
            if not takes_set <= _PROP_TAKES:
                issues.append(
                    _issue(
                        "prop_take_unknown",
                        f"qa.reference_use_gate: {label} takes "
                        f"{sorted(takes_set - _PROP_TAKES)}, which no prop "
                        "reference grants",
                    )
                )
            if ref.get("front_back_consistent") is not True:
                issues.append(
                    _issue(
                        "prop_front_back_inconsistent",
                        f"qa.reference_use_gate: {label} must declare "
                        "'front_back_consistent: true'; a prop whose "
                        "front and back do not agree is unusable",
                    )
                )
        view = ref.get("view")
        if _is_nonempty_str(asset_id) and _is_nonempty_str(view):
            key = (asset_id, view)
            if key in seen_views:
                issues.append(
                    _issue(
                        "duplicate_view",
                        f"qa.reference_use_gate: asset {asset_id!r} repeats "
                        f"view {view!r}; a multi-view set must not repeat "
                        "a view",
                    )
                )
            seen_views.add(key)
        references_out.append(entry)

    verdict = "pass" if not issues else "fail"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "numbering_convention": convention,
        "references": references_out,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_reference_use(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "reference_use_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_reference_use_gate_capabilities_once() -> list[str]:
    """Register ``qa.reference_use_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_use_gate",
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
                "Reference-use gate: character references supply "
                "likeness only, scene references structure only, prop "
                "references must keep front/back logic consistent, and "
                "multi-view sets must not repeat a view; every reference "
                "rides the declared numbering convention, never Mixed N. "
                "Plans are judged, never rewritten to pass."
            ),
            line="qa",
        )
    )
    return ["qa.reference_use_gate"]


register_reference_use_gate_capabilities_once()
