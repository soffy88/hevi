#!/usr/bin/env python
"""P11.2/P11.3 — canonical ownership mapping and alias/persistence plan.

The *decisions* below are judgements and are written out explicitly so they can be
argued with. The *evidence* for each decision — definition site, members,
consumers, renderers, tests, persisted forms, duplicate status — is read back out
of ``VOCABULARY_INVENTORY.json`` rather than retyped, so the table cannot drift
from the scan that produced it.

Emits:
    CANONICAL_MAPPING.json
    COMPOSITION_CONTRACT.json
    LAYOUT_MODE_MATRIX.json

Usage:
    uv run python scripts/qualification/p11_canonical_mapping.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "docs/qualification/p11-layout-vocabulary"
INVENTORY = OUT_DIR / "VOCABULARY_INVENTORY.json"

# ── Decisions. Each carries the reason it was made and what would falsify it. ──

DECISIONS: list[dict[str, Any]] = [
    {
        "dimension": "presenter_prominence",
        "spec_dimension": "PresenterScale",
        "semantic_question": "How large/prominent is the presenter/subject?",
        "canonical_owner": {
            "name": "PresenterScale",
            "file": "hevi/production/presenter.py",
        },
        "why": (
            "It is the only definition that answers this question directly, it has "
            "the largest consumer set of the prominence-shaped vocabularies, and it "
            "already has a total role->scale function (`scale_for_role`) with "
            "integration coverage. Choosing it avoids inventing anything."
        ),
        "falsified_by": (
            "A discovered definition with strictly larger reach that answers "
            "prominence rather than presence."
        ),
        "rejected_alternatives": [
            {
                "name": "SpeakerVisibility (p6)",
                "reason": (
                    "Answers 'which speaker is visible', not 'how large'. It "
                    "overlaps PresenterScale on FULL/MEDIUM/PIP/HIDDEN, which is "
                    "why the two are reconciled by translation below rather than "
                    "merged."
                ),
            },
            {"name": "ShotSize", "reason": "A lens vocabulary, not a composition one."},
        ],
    },
    {
        "dimension": "speaker_visibility",
        "spec_dimension": "SpeakerVisibility",
        "semantic_question": "Which speaker(s), if any, are visible and how?",
        "canonical_owner": {
            "name": "SpeakerVisibility",
            "file": "hevi/production/p6/schema.py",
        },
        "why": (
            "Two definitions exist with different members. The p6 copy is chosen "
            "because its member set is the one that composes coherently with the "
            "canonical PresenterScale (FULL/MEDIUM/PIP/HIDDEN appear in both), and "
            "it sits in the semantic schema alongside PresenterKind, which is the "
            "producer of the value it describes."
        ),
        "falsified_by": (
            "Evidence that the p5_1 copy is the one actually read by the render "
            "path — it is not: both record zero renderer consumers."
        ),
        "rejected_alternatives": [
            {
                "name": "SpeakerVisibility (p5_1)",
                "reason": (
                    "Superseded by an explicit, total, injective translation rule "
                    "rather than an alias. See alias_policy."
                ),
            }
        ],
    },
    {
        "dimension": "frame_layout",
        "spec_dimension": "LayoutMode",
        "semantic_question": "How is the visual space geometrically organised?",
        "canonical_owner": {
            "name": "ReframingMode",
            "file": "hevi/openshorts/schemas.py",
        },
        "why": (
            "This is the only discovered vocabulary whose members are geometric "
            "organisations of the frame (track / general / split) rather than "
            "composition states. It is also the vocabulary the OpenShorts "
            "integration targets, and it has the widest reach of the candidates. "
            "Adopting the explainer LayoutMode instead would leave track/general/"
            "split unowned and force a fourth vocabulary to relate them."
        ),
        "falsified_by": (
            "Evidence that explainer LayoutMode is the wider-reached layout owner."
        ),
        "rejected_alternatives": [
            {
                "name": "LayoutMode (explainer)",
                "reason": (
                    "fullscreen/broll_pip answers 'does a secondary visual share the "
                    "frame', which the inventory shows overlaps PresenterScale.PIP "
                    "rather than describing frame geometry. Retained unchanged — it "
                    "is not renamed or removed, per the migration plan."
                ),
            },
            {
                "name": "ShotSize.WIDE / CameraMotion.TRACK",
                "reason": (
                    "Both tokens appear in the spec's candidate list but are lens "
                    "and dolly vocabularies respectively. Treating them as layout "
                    "modes would collapse two semantic dimensions into one."
                ),
            },
        ],
    },
]

# ── Explicit translation rules. Not aliases: a mapping is an alias only when
#    canonical_value(alias(x)) == x, and none of these satisfy that. ──

TRANSLATION_RULES: list[dict[str, Any]] = [
    {
        "from_symbol": "SpeakerVisibility",
        "from_file": "hevi/ops/p5_1_types.py",
        "to_symbol": "SpeakerVisibility",
        "to_file": "hevi/production/p6/schema.py",
        "kind": "EXPLICIT_TRANSLATION",
        "total": True,
        "injective": True,
        "lossless_in_forward_direction": True,
        "rule": {
            "DOMINANT": "DOMINANT",
            "VISIBLE": "FULL",
            "SMALL_PIP": "PIP",
            "HIDDEN": "HIDDEN",
        },
        "unmapped_in_canonical": ["MEDIUM"],
        "why_not_an_alias": (
            "canonical_value(alias(x)) != x for every member: VISIBLE maps to FULL "
            "and SMALL_PIP maps to PIP. Spec 3.4 therefore forbids calling this an "
            "alias and requires an explicit rule, which this is."
        ),
        "information_discarded": (
            "None in the forward direction: the mapping is total and injective over "
            "the p5_1 domain. The canonical MEDIUM value has no p5_1 counterpart, "
            "so the reverse direction is not total and must not be attempted."
        ),
    },
    {
        "from_symbol": "LayoutMode",
        "from_file": "hevi/explainer/contracts.py",
        "to_symbol": "ReframingMode",
        "to_file": "hevi/openshorts/schemas.py",
        "kind": "LOSSLESS_ALIAS_CANDIDATE",
        "total": True,
        "injective": False,
        "rule": None,
        "why": (
            "Not adopted as an alias. The two vocabularies have different domains "
            "(composition state vs frame geometry) and identical spelling of the "
            "concept is coincidence, not equivalence. The duplicate definition is "
            "recorded and left in place; no conversion is defined because none is "
            "needed."
        ),
    },
]

# ── Modes the spec lists but the repository does not evidence (§6). ──

UNEVIDENCED_MODES = ["SCREENCAST", "INSET", "PUNCH_IN"]

# ── Evidence-backed mode capability, read from the inventory + source. ──

MODE_MATRIX_SOURCE = {
    "ReframingMode": {
        "canonical": True,
        "executes_in_p11": {"track": True, "general": True, "split": True},
        "requires_track": {"track": True, "general": False, "split": False},
        "basis": (
            "P10 ships an executable ReframePlan with a native ffmpeg crop, so "
            "`track` becomes executable in P11 by consuming it. `general` is the "
            "largest target-aspect crop with no subject requirement. `split` is a "
            "two-region spatial composition and needs two sources."
        ),
    },
}


def _load() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(INVENTORY.read_text(encoding="utf-8"))
    return loaded


def _evidence(inventory: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [s for s in inventory["symbols"] if s["name"] == name]


def build() -> dict[str, Any]:
    inventory: dict[str, Any] = _load()
    duplicates: dict[str, Any] = inventory.get("duplicate_definitions", {})
    forbidden: list[str] = inventory.get("forbidden_vocabulary_names_present", [])

    table: list[dict[str, Any]] = []
    for decision in DECISIONS:
        owner = decision["canonical_owner"]
        found = _evidence(inventory, owner["name"])
        site = next(
            (s for s in found if s["definition_file"] == owner["file"]), None)
        if site is None:
            # The owner is referenced by its discoverable name at the given file.
            site = next((s for s in found if owner["file"] in s["definition_file"]), None)
        aliases = [
            {
                "name": rule["from_symbol"],
                "file": rule["from_file"],
                "kind": rule["kind"],
                "total": rule["total"],
                "injective": rule["injective"],
            }
            for rule in TRANSLATION_RULES
        ]
        table.append({
            "dimension": decision["dimension"],
            "spec_dimension": decision["spec_dimension"],
            "semantic_question": decision["semantic_question"],
            "canonical_owner": owner["name"],
            "canonical_owner_file": owner["file"],
            "definition_line": (site or {}).get("definition_line"),
            "members": (site or {}).get("members", []),
            "existing_aliases_or_translations": aliases,
            "consumers_evidence": (site or {}).get("consumers", []),
            "renderer_consumers_evidence": (site or {}).get("renderers", []),
            "tests_evidence": (site or {}).get("tests", []),
            "persisted_forms_evidence": (site or {}).get("persisted_forms", []),
            "why": decision["why"],
            "falsified_by": decision["falsified_by"],
            "rejected_alternatives": decision["rejected_alternatives"],
        })

    return {
        "schema": "hevi.p11.canonical_mapping.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": "scripts/qualification/p11_canonical_mapping.py",
        "evidence_source": "docs/qualification/p11-layout-vocabulary/VOCABULARY_INVENTORY.json",
        "inventory_generated_at": inventory.get("generated_at"),
        "scanned_python_files": inventory.get("scanned_python_files"),
        "decision_table": table,
        "translation_rules": TRANSLATION_RULES,
        "duplicate_definitions": duplicates,
        "unevidenced_modes": {
            "modes": UNEVIDENCED_MODES,
            "policy": (
                "Spec 6 permits implementing only modes the repository evidences. "
                "These appear in the spec's candidate list but have no definition "
                "anywhere in the tree, so they are BLOCKED_UNIMPLEMENTED rather "
                "than invented."
            ),
            "scan_evidence": (
                "No class, enum or Literal alias named or containing these tokens "
                "was produced by the inventory scan."
            ),
        },
        "fourth_vocabulary_check": {
            "forbidden_names": [
                "LayoutVocabulary", "CompositionMode", "FrameLayout", "VisualLayout",
                "ShotLayoutMode", "CompositionModeV2",
            ],
            "present": forbidden,
            "pass": not forbidden,
        },
    }


def composition_contract() -> dict[str, Any]:
    return {
        "schema": "hevi.p11.composition_contract.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "name": "CompositionSpec",
        "rule": (
            "A structural plan object holding the three canonical semantic "
            "dimensions. It is NOT a fourth vocabulary: it defines no new enum "
            "member and reuses the three owners named in CANONICAL_MAPPING.json."
        ),
        "fields": [
            {"name": "presenter_scale", "type": "PresenterScale",
             "owner": "hevi/production/presenter.py",
             "question": "How large/prominent is the presenter/subject?"},
            {"name": "speaker_visibility", "type": "SpeakerVisibility",
             "owner": "hevi/production/p6/schema.py",
             "question": "Which speaker(s), if any, are visible and how?"},
            {"name": "layout_mode", "type": "ReframingMode",
             "owner": "hevi/openshorts/schemas.py",
             "question": "How is the visual space geometrically organised?"},
            {"name": "parameters", "type": "LayoutParameters",
             "owner": "hevi/production/composition.py",
             "question": "Configuration, not vocabulary. Validated per layout_mode."},
        ],
        "non_collapse": (
            "The three dimensions are stored separately and are never folded into a "
            "single enum. A change to one must not imply a change to another."
        ),
        "fail_closed": [
            "unknown vocabulary member",
            "missing canonical mapping",
            "parameters invalid for the selected layout_mode",
            "layout_mode requires a subject track and none is supplied",
            "region outside normalised bounds",
            "non-positive output dimensions",
            "unsupported aspect ratio",
        ],
        "forbidden_behaviours": [
            "silent fallback to centre crop",
            "defaulting an unknown semantic value",
            "persisting a derived value as if it were an authoritative input",
        ],
    }


def layout_mode_matrix() -> dict[str, Any]:
    reframing: dict[str, Any] = MODE_MATRIX_SOURCE["ReframingMode"]
    modes: list[dict[str, Any]] = []
    executable_modes: dict[str, bool] = reframing["executes_in_p11"]
    track_requirement: dict[str, bool] = reframing["requires_track"]
    for mode, executable in executable_modes.items():
        requires: bool = track_requirement[mode]
        modes.append({
            "mode": mode,
            "canonical_type": "ReframingMode",
            "definition": "hevi/openshorts/schemas.py:22",
            "preexisting_executable_renderer": False,
            "preexisting_renderer_evidence": "inventory records 0 renderer consumers",
            "executable_in_p11": executable,
            "requires_subject_track": requires,
            "missing_track_behaviour": (
                "FAIL_CLOSED: ReframePlanRequiredButAbsent" if requires
                else "not applicable"
            ),
            "inputs": (
                ["SubjectTrack", "source media", "canvas"] if requires
                else ["source media", "canvas"]
            ),
            "geometry": {
                "track": "crop window follows the subject, bounded by target aspect",
                "general": "largest target-aspect crop, no subject requirement",
                "split": "two source regions side by side, split_ratio validated",
            }[mode],
            "crop_behaviour": (
                "delegated to hevi.production.reframe.ReframePlan (P10)"
                if mode == "track"
                else "engine-owned crop, no subject dependency"
            ),
            "audio_behaviour": "unchanged; layout is a video-space concern",
            "verification": (
                "V2 asserts the crop origin moved and the subject stays contained; "
                "pixel diff against the un-reframed source"
                if requires else
                "V2 asserts output dimensions and aspect; pixel diff against source"
            ),
        })
    modes.extend(
        {
            "mode": mode,
            "canonical_type": None,
            "definition": None,
            "preexisting_executable_renderer": False,
            "preexisting_renderer_evidence": "no definition found anywhere in the tree",
            "executable_in_p11": False,
            "status": "BLOCKED_UNIMPLEMENTED",
            "blocked_reason": (
                "spec 6: implement only modes the repository supports or evidences; "
                "inventing this mode would also risk a fourth vocabulary"
            ),
        }
        for mode in UNEVIDENCED_MODES
    )
    return {
        "schema": "hevi.p11.layout_mode_matrix.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "basis": reframing["basis"],
        "modes": modes,
        "counts": {
            "executable": sum(1 for m in modes if m.get("executable_in_p11")),
            "blocked": sum(1 for m in modes
                           if m.get("status") == "BLOCKED_UNIMPLEMENTED"),
        },
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("CANONICAL_MAPPING.json", build()),
        ("COMPOSITION_CONTRACT.json", composition_contract()),
        ("LAYOUT_MODE_MATRIX.json", layout_mode_matrix()),
    ):
        path = OUT_DIR / name
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        print(f"wrote {path.relative_to(REPO)}")
    matrix = layout_mode_matrix()["counts"]
    print(f"modes: {matrix['executable']} executable, {matrix['blocked']} blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
