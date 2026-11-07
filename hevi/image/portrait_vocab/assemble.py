"""Assemble a portrait prompt from vocabulary picks.

Method (from the source pages): pick at most one entry per category,
write the person first and the scene second, expand every pick with its
``how`` text (the concrete, executable description) instead of stacking
bare terms, and never combine conflicting picks.

Two outputs:

* ``prompt_zh`` -- identity sentence (optional), subject sentence
  (optional), then the ``how`` expansion of every pick in canonical
  category order, then the scene sentence and the framing line.
* ``prompt_en`` -- the English phrases of the picks, comma-joined, in
  the same order.

With ``mode="motion"`` the result also carries ``motion_prompt``: the
English phrases with the video_micro pick first -- the text a PixStag
shot package consumes for one shot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hevi.image.portrait_vocab.vocab import (
    CATEGORIES,
    PortraitVocabError,
    get_entry,
)

# Canonical assembly order: pose before detail, gaze before micro-motion.
CATEGORY_ORDER = (
    "posture",
    "sitting",
    "standing",
    "motion",
    "hair_head",
    "hands",
    "gaze",
    "video_micro",
)

# Entry-pair conflicts, each grounded in the source text or plain
# physical fact.  Kept deliberately small:宁少勿造.
CONFLICT_PAIRS: tuple[tuple[str, str, str], ...] = (
    # Source, gaze page: eyes / face / body are controlled separately;
    # with the eyes closed no gaze direction can be performed.
    ("GA-08", "GA-01", "闭眼与看向镜头冲突：双眼轻合时目光无法落在镜头"),
    ("GA-08", "GA-02", "闭眼与直视镜头冲突：双眼轻合时无法稳定看着镜头"),
    ("GA-08", "GA-10", "闭眼与侧目一瞥冲突：侧目需要睁眼移向一侧"),
)

# Whole-category conflicts: one body cannot hold both at the same moment.
_CATEGORY_CONFLICTS: tuple[tuple[str, str, str], ...] = (
    ("sitting", "standing", "坐姿与站姿互斥：同一时刻不能既坐又站"),
)

# Category x entry conflicts: a seated body cannot perform these.
_SEATED_BLOCKED_MOTION = {
    "MO-01": "坐姿下不能行走：行走要选迈步的一瞬、双腿承重",
    "MO-04": "坐姿下不能舞动：舞动需要支撑脚站立",
    "MO-08": "坐姿下不能奔跑：奔跑要选支撑或腾空阶段",
}


def find_conflicts(picked: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    """Return every conflict among the picked entries (possibly empty)."""
    by_id = {e["id"]: e for e in picked}
    by_category = {e["category"]: e for e in picked}
    conflicts: list[dict[str, str]] = []
    for id_a, id_b, reason in CONFLICT_PAIRS:
        if id_a in by_id and id_b in by_id:
            conflicts.append(
                {"a": id_a, "b": id_b, "reason": reason}
            )
    for cat_a, cat_b, reason in _CATEGORY_CONFLICTS:
        if cat_a in by_category and cat_b in by_category:
            conflicts.append(
                {
                    "a": by_category[cat_a]["id"],
                    "b": by_category[cat_b]["id"],
                    "reason": reason,
                }
            )
    if "sitting" in by_category:
        for entry in picked:
            if entry["id"] in _SEATED_BLOCKED_MOTION:
                conflicts.append(
                    {
                        "a": by_category["sitting"]["id"],
                        "b": entry["id"],
                        "reason": _SEATED_BLOCKED_MOTION[entry["id"]],
                    }
                )
    return conflicts


def _resolve_selection(
    selection: Mapping[str, Any],
) -> list[dict[str, Any]]:
    picked: dict[str, dict[str, Any]] = {}
    for category, raw in selection.items():
        if category not in CATEGORIES:
            raise PortraitVocabError(
                f"unknown portrait vocab category: {category!r} "
                f"(want one of {', '.join(CATEGORIES)})"
            )
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            values = [v for v in raw if str(v).strip()]
            if len(values) > 1:
                raise PortraitVocabError(
                    f"category {category!r} takes at most one entry "
                    f"(source rule: 从每组挑一个), got {list(raw)!r}"
                )
            if not values:
                continue
            raw = values[0]
        if raw is None or not str(raw).strip():
            continue
        entry = get_entry(str(raw))
        if entry["category"] != category:
            raise PortraitVocabError(
                f"entry {entry['id']} ({entry['zh']}) belongs to category "
                f"{entry['category']!r}, not {category!r}"
            )
        picked[category] = entry
    return [picked[c] for c in CATEGORY_ORDER if c in picked]


def _sentence(text: str) -> str:
    text = text.strip()
    if text and text[-1] not in "。！？":
        text += "。"
    return text


def assemble(
    selection: Mapping[str, Any],
    *,
    mode: str = "image",
    identity: str | None = None,
    subject: str | None = None,
    scene: str | None = None,
    framing: str | None = None,
    on_conflict: str = "error",
) -> dict[str, Any]:
    """Assemble a bilingual portrait prompt from per-category picks.

    ``selection`` maps a category key to one entry (id, Chinese name or
    English phrase); more than one entry for a category is rejected.
    ``on_conflict`` is ``"error"`` (raise on conflicting picks) or
    ``"warn"`` (assemble anyway and report them under ``conflicts``).
    """
    if mode not in ("image", "motion"):
        raise PortraitVocabError(
            f"unknown portrait assemble mode {mode!r} (want image|motion)"
        )
    if on_conflict not in ("error", "warn"):
        raise PortraitVocabError(
            f"unknown on_conflict {on_conflict!r} (want error|warn)"
        )
    picked = _resolve_selection(selection)
    if not picked:
        raise PortraitVocabError(
            "empty selection: pick at least one vocabulary entry"
        )
    conflicts = find_conflicts(picked)
    if conflicts and on_conflict == "error":
        detail = "; ".join(
            f"{c['a']} x {c['b']}: {c['reason']}" for c in conflicts
        )
        raise PortraitVocabError(f"conflicting portrait picks: {detail}")

    zh_parts: list[str] = []
    if identity:
        zh_parts.append(_sentence(identity))
    if subject:
        zh_parts.append(_sentence(subject))
    zh_parts.append("；".join(e["how"] for e in picked) + "。")
    if scene:
        zh_parts.append(_sentence(scene))
    if framing:
        zh_parts.append(_sentence(framing))
    prompt_zh = "".join(zh_parts)

    prompt_en = ", ".join(e["en"] for e in picked)

    motion_prompt: str | None = None
    if mode == "motion":
        micro = [e for e in picked if e["category"] == "video_micro"]
        rest = [e for e in picked if e["category"] != "video_micro"]
        motion_prompt = ", ".join(e["en"] for e in micro + rest)

    return {
        "mode": mode,
        "entries": picked,
        "detail_zh": [f"{e['zh']}：{e['how']}" for e in picked],
        "prompt_zh": prompt_zh,
        "prompt_en": prompt_en,
        "motion_prompt": motion_prompt,
        "conflicts": conflicts,
        "warnings": [c["reason"] for c in conflicts] if conflicts else [],
    }
