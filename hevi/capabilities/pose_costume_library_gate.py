"""Costume reference library gate (``qa.pose_costume_library_gate``).

Index-only discipline for costume references from
anhao/ai-pose-gallery-zh: 3224 sets (giaa realistic 1407 +
Shisei dynastic 57 sets / 227 views + anime 1320 hotlinked +
CharaDB 440). The gate judges costume reference declarations
only; it never downloads, copies, or generates an image. Image
files always stay outside the repo and are resolved at runtime
under ``HEVI_POSE_GALLERY_HOME``; a declaration that bundles
images, or claims commercial use, fails.

Counts are the values verified in the 2026-11-20 read-only
check (see ``AI_POSE_GALLERY_ZH_ATTRIBUTION.md``): giaa
realistic categories sum to 1407 (春 215, 夏 254, 秋 244,
冬 253, 内衣睡衣 199, 性感 140, 泳装 54, 礼服 48).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

SOURCES: frozenset[str] = frozenset({"giaa-realistic", "shisei", "anime-hotlink", "charadb"})
GIAA_CATEGORY_SETS: dict[str, int] = {
    "春": 215,
    "夏": 254,
    "秋": 244,
    "冬": 253,
    "内衣睡衣": 199,
    "性感": 140,
    "泳装": 54,
    "礼服": 48,
}
GIAA_TOTAL_SETS = 1407
TOTAL_SETS = 3224


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_pose_costume(costume: Any) -> dict[str, Any]:
    """Validate one costume reference declaration.

    Verdicts are ``pass`` / ``fail`` only. A declaration fails
    when the source is unknown, the set id is missing, commercial
    use is claimed, images are bundled, a giaa category is
    outside the verified eight, a Shisei record has no dynasty,
    an anime record is not marked hotlinked (or claims offline
    availability), or a CharaDB record does not forbid
    redistribution and real-person/minor use.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(costume, dict):
        return fail("costume_not_object", "costume reference must be a JSON object")
    source = costume.get("source")
    if source not in SOURCES:
        return fail(
            "unknown_source",
            f"costume source must be one of {sorted(SOURCES)}, got {source!r}",
        )
    set_id = costume.get("set_id")
    if not isinstance(set_id, str) or not set_id.strip():
        return fail("set_id_missing", "costume reference must carry a non-empty set_id")
    if costume.get("commercial_use") is True:
        return fail(
            "commercial_use_refused",
            "costume images are non-commercial reference only; commercial use is refused",
        )
    if costume.get("images_bundled") is True:
        return fail(
            "images_must_stay_external",
            "costume images are never bundled into hevi; they stay "
            "under HEVI_POSE_GALLERY_HOME and are resolved at runtime",
        )
    if source == "giaa-realistic":
        category = costume.get("category")
        if category not in GIAA_CATEGORY_SETS:
            return fail(
                "unknown_giaa_category",
                f"giaa realistic category must be one of "
                f"{sorted(GIAA_CATEGORY_SETS)}, got {category!r}",
            )
        category_sets = costume.get("category_sets")
        if category_sets is not None and (
            not _is_number(category_sets) or int(category_sets) != GIAA_CATEGORY_SETS[category]
        ):
            return fail(
                "category_sets_mismatch",
                f"giaa category {category!r} holds "
                f"{GIAA_CATEGORY_SETS[category]} sets, got {category_sets!r}",
            )
        tags = costume.get("tags")
        if tags is not None and (
            not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() for t in tags)
        ):
            return fail(
                "tags_invalid",
                "costume tags must be a list of non-empty strings",
            )
    if source == "shisei" and (
        not isinstance(costume.get("dynasty"), str) or not costume["dynasty"].strip()
    ):
        return fail(
            "dynasty_missing",
            "a Shisei dynastic costume record must name its dynasty",
        )
    if source == "anime-hotlink":
        if costume.get("hotlink") is not True:
            return fail(
                "hotlink_not_marked",
                "anime costume images are hotlinked from the origin "
                "site, not shipped with the repo; the record must "
                "mark hotlink true",
            )
        if costume.get("offline_available") is True:
            return fail(
                "offline_claim_refused",
                "anime costume images are not available offline; "
                "offline availability must not be claimed",
            )
    if source == "charadb":
        if costume.get("no_redistribution") is not True:
            return fail(
                "redistribution_not_forbidden",
                "CharaDB images are reference only and must not be "
                "redistributed; the record must forbid it",
            )
        if costume.get("no_real_person_or_minor") is not True:
            return fail(
                "real_person_minor_not_forbidden",
                "CharaDB images must never be used for real people "
                "or minors; the record must forbid it",
            )
    total_sets = costume.get("total_sets")
    if total_sets is not None and (not _is_number(total_sets) or int(total_sets) != TOTAL_SETS):
        return fail(
            "total_sets_mismatch",
            f"the costume library holds {TOTAL_SETS} sets, got {total_sets!r}",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "source": source,
        "set_id": set_id,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_pose_costume(params.get("costume"))
    report_path = out_dir / "pose_costume_library_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_costume_library_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_costume_library_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "costume": {"type": "object"},
                },
                "required": ["costume"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pose-gallery costume reference gate: 3224 sets over "
                "four sources, giaa eight-category closed vocabulary, "
                "non-commercial reference only, images stay external "
                "under HEVI_POSE_GALLERY_HOME, hotlink and CharaDB "
                "restrictions enforced."
            ),
        )
    )
    return ["qa.pose_costume_library_gate"]


__all__ = [
    "GIAA_CATEGORY_SETS",
    "GIAA_TOTAL_SETS",
    "SOURCES",
    "TOTAL_SETS",
    "check_pose_costume",
    "register_pose_costume_library_gate_capabilities_once",
]
