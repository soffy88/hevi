"""Wardrobe and age-variant asset gate (``qa.wardrobe_age_variant_gate``).

Clean-room restatement of the wardrobe/age-variant asset
discipline described in the Infinite Creation review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a character may own
several wardrobes and several age appearances, but a variant is
never a free-floating asset. Every variant hangs from its parent
character by ``parent_id``, declares the story event that first
introduces it, and may only be used at or after that event, in a
scene where its parent character is present. A variant used
before its introduction, or without its parent, is a continuity
error, not a styling choice.

This module judges asset records only. It never generates, never
calls a model, and it holds no image or voice data: variant
identity is a record-level discipline, and likeness or voice
consent is a separate, caller-owned concern that this gate does
not certify.
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

_VARIANT_KINDS = ("wardrobe", "age")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.wardrobe_age_variant_gate: {detail}"}
    issue.update(extra)
    return issue


def check_wardrobe_age_variants(record: Any) -> dict[str, Any]:
    """Judge one wardrobe/age-variant asset record.

    ``record`` carries ``characters`` (asset ids), ``events`` (an
    ordered list of event ids), ``variants`` (each with ``id``,
    ``parent_id``, ``kind`` and ``first_use_event``) and
    ``usages`` (each with ``variant_id`` and ``event``, and
    optional ``scene_characters_present``). Verdict ``pass`` means
    every variant hangs from a known character, is introduced by
    a known event, and is only used at or after that event with
    its parent present.
    """
    if not isinstance(record, dict):
        raise CapabilityError("asset record must be an object")
    issues: list[dict[str, Any]] = []
    characters = record.get("characters")
    events = record.get("events")
    variants = record.get("variants")
    if not isinstance(characters, list) or not characters:
        raise CapabilityError("asset record requires a non-empty characters list")
    if not isinstance(events, list) or not events:
        raise CapabilityError("asset record requires a non-empty ordered events list")
    if not isinstance(variants, list):
        raise CapabilityError("asset record requires a variants list")
    character_ids = set()
    for character in characters:
        if isinstance(character, dict):
            character_ids.add(character.get("id"))
        else:
            character_ids.add(character)
    event_index = {event: index for index, event in enumerate(events)}
    variant_by_id: dict[str, dict[str, Any]] = {}
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict):
            issues.append(_issue("variant_not_object", f"variant {index} is not an object"))
            continue
        variant_id = variant.get("id")
        if not variant_id:
            issues.append(_issue("variant_id_missing", f"variant {index} lacks an id"))
            continue
        if variant_id in variant_by_id:
            issues.append(_issue("variant_id_duplicate", f"variant id {variant_id} is duplicated"))
        variant_by_id[variant_id] = variant
        if variant.get("parent_id") not in character_ids:
            issues.append(
                _issue(
                    "variant_parent_unknown",
                    f"variant {variant_id} parent_id is not a known character",
                    variant=variant_id,
                )
            )
        if variant.get("kind") not in _VARIANT_KINDS:
            issues.append(
                _issue(
                    "variant_kind_invalid",
                    f"variant {variant_id} kind must be one of {_VARIANT_KINDS}",
                    variant=variant_id,
                )
            )
        if variant.get("first_use_event") not in event_index:
            issues.append(
                _issue(
                    "variant_introduction_unknown",
                    f"variant {variant_id} first_use_event is not a known event",
                    variant=variant_id,
                )
            )
    usages = record.get("usages", [])
    if not isinstance(usages, list):
        raise CapabilityError("usages must be a list when present")
    for index, usage in enumerate(usages):
        if not isinstance(usage, dict):
            issues.append(_issue("usage_not_object", f"usage {index} is not an object"))
            continue
        variant = variant_by_id.get(usage.get("variant_id"))
        if variant is None:
            issues.append(
                _issue("usage_variant_unknown", f"usage {index} names an unknown variant", usage=index)
            )
            continue
        event = usage.get("event")
        if event not in event_index:
            issues.append(
                _issue("usage_event_unknown", f"usage {index} names an unknown event", usage=index)
            )
            continue
        first_use = variant.get("first_use_event")
        if first_use in event_index and event_index[event] < event_index[first_use]:
            issues.append(
                _issue(
                    "variant_used_before_introduction",
                    f"variant {variant.get('id')} used at {event}, introduced at {first_use}",
                    usage=index,
                )
            )
        present = usage.get("scene_characters_present")
        if present is not None:
            if not isinstance(present, list):
                raise CapabilityError("scene_characters_present must be a list when present")
            if variant.get("parent_id") not in present:
                issues.append(
                    _issue(
                        "variant_used_without_parent",
                        f"variant {variant.get('id')} used in a scene without its parent character",
                        usage=index,
                    )
                )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "character_count": len(character_ids),
        "variant_count": len(variant_by_id),
        "usage_count": len(usages),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_wardrobe_age_variants(params.get("record"))
    report_path = out_dir / "wardrobe_age_variants.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_wardrobe_age_variant_gate_capabilities_once() -> list[str]:
    """Register ``qa.wardrobe_age_variant_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.wardrobe_age_variant_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                },
                "required": ["record"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Wardrobe/age-variant asset gate: every variant hangs from "
                "its parent character, is introduced by a known event, and "
                "is only used at or after that event with its parent present."
            ),
        )
    )
    return ["qa.wardrobe_age_variant_gate"]


__all__ = ["check_wardrobe_age_variants", "register_wardrobe_age_variant_gate_capabilities_once"]
