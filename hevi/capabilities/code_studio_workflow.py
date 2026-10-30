"""Code-studio workflow (``pipeline.code_studio_workflow``).

A six-step, gated way to make a code-rendered explanatory film:
every step produces a checkable artefact on disk and stops at a
confirmation point. No step runs a generation model, spends money,
or renders a whole film; full-film assembly still belongs to
``pipeline.stable_film_assembly`` and frame rendering to
``video.code_render``. This module only plans, checks, and files.

Dedup table -- what each step reuses, what gap it fills, and what
it deliberately does not rewrite:

* Step 1 (brief) reuses ``pipeline.project_handoff`` for the project
  folder and its manifest (see ``run_workflow_step``). It adds the
  facts / creative-freedom split and the real-material refusal:
  project_handoff never judges whether the material is real.
* Step 2 (style note) reuses the strict-confirmation rule of
  ``pipeline.spend_brake`` (``confirmed`` must be exactly ``True``;
  the string ``"true"`` and ``1`` do not count) and the live style
  catalogue of ``image.lemo_styles`` (``list_lemo_styles`` /
  ``get_lemo_style``, which read STYLE.md essence text at call
  time). It adds the concrete style-note checks (colour codes,
  font sizes, texture, motion feel, originality declaration).
  It does not copy any style prompt text.
* Step 3 (shot table) adds only start/end state, existence reason,
  and narration alignment. It does NOT rewrite
  ``qa.storyboard_opening_gate`` (verbatim opening blocking) or
  ``qa.production_gates`` (segment location, cut range, keyframe
  timing, composition): see ``shot_table_dedup_notes``. Callers
  that need those gates should run them separately.
* Step 4 (beat grid) adds declared-beat timestamps and alignment
  checking. Loudness, ducking, and mixing stay with
  ``audio.mix_recipe``; measured beat analysis from an audio file
  is not done here and is labelled ``planned_not_measured``.
* Step 5 (code rendering) adds a deterministic per-time frame
  state, single-frame rendering, segment-only re-rendering, motion
  weight, eye landing, per-aspect layouts, and feasibility
  routing. The tier table and multi-frame rendering stay with
  ``video.code_render`` (see ``code_render_tier_status``: no
  vertical tier exists there). Manim has no public render entry
  point in ``video.manim_render`` (see ``manim_status``); it can
  only be injected by the caller.
* Step 6 (review board) adds the contact-sheet board, the five
  review checks, top-3 triage, folder finalisation, and resume.
  Colour contrast reuses ``design.cover_family.contrast_ratio``;
  caption measurement reuses the method of
  ``pipeline.stable_film_assembly.measure_caption_bbox`` only when
  a real frame is supplied, never as a guessed number. Final
  media QC stays with ``qa.final_qc_gate``; snapshots stay with
  ``pipeline.project_snapshot``.

ATTRIBUTION: the working method -- brief first, reference
teardown for feel rather than copying, a shot table with a reason
for every segment, music fixed to a beat grid, code as the
rendering source of truth with deterministic re-rendering, and a
contact-sheet review before filing -- follows the method ideas
of Eian's long essay on making video with code (the city-annals
piece rendered frame by frame from code) and of the Lemo Opuscar
skill (code-animation styles). Method ideas only: no wording,
no prompt text, and no phrasing from either source is copied
here, and Lemo styles are always read live through
``image.lemo_styles`` rather than pasted in. All code and
documentation wording in this module is newly written.

Failure contract: validators return reports (``ok: False`` with
named problems) instead of raising, so a gate can list every
problem at once; only genuinely unusable inputs (an empty frame
list, an unknown changed segment, a non-positive BPM, a step
number outside 1-6) raise ``CapabilityError``.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import time
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

# ---------------------------------------------------------------- constants

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX_FIND_RE = re.compile(r"#[0-9a-fA-F]{6}")

# Vague wording that may not stand in for a style decision. Scanned
# only in free-text description fields, never in the texture field
# (which has its own closed vocabulary).
_VAGUE_WORDS = (
    "高级感",
    "氛围感",
    "电影感",
    "精致感",
    "高级大气",
    "有感觉",
    "不明觉厉",
    "高级",
)

_TEXTURE_KINDS = {"颗粒", "纸张", "无质感", "grain", "paper", "none"}
_MOTION_FEELS = {"干脆", "慢滑", "回弹"}

_ASSET_KINDS = {"logo", "interface_screenshot", "data", "font", "color", "music"}
_ASSET_ALIASES = {
    "screenshot": "interface_screenshot",
    "interface": "interface_screenshot",
    "ui_screenshot": "interface_screenshot",
    "font_color": "color",
    "colour": "color",
    "typeface": "font",
    "dataset": "data",
}

# Motion-weight limits, stated in every report that uses them.
SMALL_MOVE_MAX_SEC = 0.35
READING_CHARS_PER_SEC = 8.0
MIN_HOLD_SEC = 1.0
MOTION_WEIGHT_FORMULA = (
    "required_hold_sec = max(1.0, chars / 8.0); "
    "small elements (button/switch/icon) move in at most 0.35s; "
    "large elements (panel/modal/block) must declare settle_ms > 0"
)

MIN_PHONE_FONT_PX = 14.0
DEFAULT_PHONE_WIDTH_PX = 390
TRANSITION_DELTA_LOW = 0.02
TRANSITION_DELTA_HIGH = 0.50
MIN_CONTRAST = 4.5

_FEASIBILITY_BLOCKERS = {
    "live_action",
    "live-action",
    "photoreal",
    "photorealistic",
    "complex_human_motion",
    "real_person_on_camera",
}

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_STEP_ARTIFACTS = {
    1: "brief.json",
    2: "style_note.json",
    3: "shot_table.json",
    4: "beat_grid.json",
    5: "frame_report.json",
    6: "checks/review.json",
}

_STEP_STAGES = {
    1: "topic",
    2: "reference",
    3: "script",
    4: "edit",
    5: "broll",
    6: "review",
}

_LAYOUT_SIZES = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


# ---------------------------------------------------------------- helpers


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if _nonempty_str(v)]
    return []


def _norm_asset_kind(kind: Any) -> str:
    key = str(kind or "").strip().lower()
    return _ASSET_ALIASES.get(key, key)


def _parse_hex(text: str) -> tuple[int, int, int]:
    value = text.strip().lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _contrast_fallback(foreground: str, background: str) -> float:
    def lum(hex_colour: str) -> float:
        r, g, b = _parse_hex(hex_colour)
        channels = []
        for channel in (r, g, b):
            c = channel / 255.0
            channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    lighter, darker = max(lum(foreground), lum(background)), min(
        lum(foreground), lum(background)
    )
    return (lighter + 0.05) / (darker + 0.05)


def _contrast_ratio(foreground: str, background: str) -> float:
    """Contrast via design.cover_family when importable, else exact fallback."""
    try:
        from hevi.capabilities.cover_family import contrast_ratio

        return float(contrast_ratio(foreground, background))
    except Exception:
        return _contrast_fallback(foreground, background)


def _strictly_confirmed(confirmation: Any) -> tuple[bool, str]:
    """Strict confirmation, spend_brake semantics.

    The rule is copied in meaning from
    ``pipeline.spend_brake.gate_spend`` (and restated by
    ``pipeline.stable_film_assembly.check_confirmation``):
    ``confirmed`` must be exactly ``True``. The string ``"true"``,
    ``1``, a missing field, and silence are all refusals.
    """
    if confirmation is True:
        return True, ""
    if isinstance(confirmation, dict):
        if confirmation.get("confirmed") is True:
            return True, ""
        return False, "confirmed is not exactly True"
    return False, "no confirmation supplied (confirmed must be exactly True)"


# ---------------------------------------------------------------- step 1: brief


def validate_brief(brief: Any) -> dict[str, Any]:
    """Validate a step-1 brief / project sheet.

    ``facts`` and ``creative_freedom`` must be two separate fields
    with no overlapping entries: a fact written into the freedom
    column (or the same content in both) is a mixed sheet and fails.
    A brief that declares a need for real material (logo, interface
    screenshot, data, music) without a listed file/reference for
    that kind refuses to start, naming the missing kind.
    """
    problems: list[str] = []
    if not isinstance(brief, dict):
        return {
            "ok": False,
            "problems": ["brief: brief must be a JSON object"],
            "missing_assets": [],
            "asset_kinds": [],
        }
    memory = brief.get("memory_point") or brief.get("one_sentence_memory")
    if not _nonempty_str(memory):
        problems.append("memory_point: a one-sentence memory point is required")
    platform = brief.get("platform")
    if not isinstance(platform, dict):
        platform = {
            "aspect": brief.get("aspect"),
            "duration_sec": brief.get("duration_sec"),
        }
    aspect = platform.get("aspect")
    if aspect not in _LAYOUT_SIZES:
        problems.append(
            f"platform.aspect: must be one of {sorted(_LAYOUT_SIZES)}, got {aspect!r}"
        )
    if not _is_num(platform.get("duration_sec")) or float(platform["duration_sec"]) <= 0:
        problems.append("platform.duration_sec: must be a positive number")

    raw_assets = brief.get("real_assets")
    if raw_assets is None:
        raw_assets = brief.get("assets") or brief.get("real_materials")
    assets: list[dict[str, Any]] = []
    if not isinstance(raw_assets, list) or not raw_assets:
        problems.append(
            "real_assets: the real-material list is empty; no real material, no start"
        )
    else:
        for index, asset in enumerate(raw_assets):
            if not isinstance(asset, dict):
                problems.append(f"real_assets[{index}]: asset must be an object")
                continue
            kind = _norm_asset_kind(asset.get("kind"))
            if kind not in _ASSET_KINDS:
                problems.append(
                    f"real_assets[{index}]: unknown kind {asset.get('kind')!r}; "
                    f"known: {sorted(_ASSET_KINDS)}"
                )
                continue
            locator = (
                asset.get("path")
                or asset.get("ref")
                or asset.get("reference")
                or asset.get("hash")
                or asset.get("file")
            )
            if not _nonempty_str(locator):
                problems.append(
                    f"real_assets[{index}]: kind {kind!r} has no file or "
                    "reference; a declared asset without a locator does not count"
                )
            assets.append({**asset, "kind": kind})
    asset_kinds = sorted({a["kind"] for a in assets})

    required: list[str] = []
    for key in ("requires_real_assets", "needs_real_assets", "needs"):
        value = brief.get(key)
        if isinstance(value, list):
            required.extend(_norm_asset_kind(v) for v in value)
    flag_kinds = {
        "uses_real_interface": ["interface_screenshot"],
        "uses_interface_data": ["interface_screenshot", "data"],
        "uses_real_data": ["data"],
        "uses_logo": ["logo"],
        "uses_music": ["music"],
    }
    for flag, kinds in flag_kinds.items():
        if brief.get(flag) is True:
            required.extend(kinds)
    required = sorted(set(required))
    missing_assets = [k for k in required if k not in asset_kinds]
    for kind in missing_assets:
        problems.append(
            f"real_assets: declared need for {kind!r} but no {kind} "
            "asset is listed with a file or reference; stop and ask, "
            "do not invent it"
        )

    if "unwanted" in brief or "not_wanted" in brief or "avoid" in brief:
        unwanted = brief.get("unwanted", brief.get("not_wanted", brief.get("avoid")))
        if not isinstance(unwanted, list):
            problems.append("unwanted: must be a list (empty is allowed)")
    else:
        problems.append("unwanted: the unwanted list must be present (empty is allowed)")

    red_text = " ".join(_as_strings(brief.get("red_lines") or brief.get("red_line")))
    if not red_text.strip():
        problems.append("red_lines: the red-line declaration is required")
    else:
        if "真实" not in red_text and "真的" not in red_text:
            problems.append(
                "red_lines: must state that interface data is always real"
            )
        if "停" not in red_text or "问" not in red_text:
            problems.append(
                "red_lines: must state that missing material stops the work "
                "and is asked about, not filled in"
            )
        if not any(
            marker in red_text
            for marker in ("不准", "不自", "不编", "不虚构", "不伪造", "禁止自")
        ):
            problems.append(
                "red_lines: must state that material is never drawn or "
                "invented by hand"
            )

    deliverables = brief.get("deliverables")
    if not isinstance(deliverables, list) or not deliverables:
        problems.append("deliverables: a non-empty deliverables list is required")

    facts = brief.get("facts")
    freedom = brief.get("creative_freedom")
    if facts is None or freedom is None:
        problems.append(
            "facts/creative_freedom: both fields must be present as "
            "separate fields; a combined field is a mixed sheet"
        )
    else:
        fact_entries = _as_strings(facts)
        freedom_entries = _as_strings(freedom)
        if not fact_entries:
            problems.append("facts: at least one fact is required")
        if not freedom_entries:
            problems.append(
                "creative_freedom: at least one freedom entry is required"
            )
        overlap = sorted(set(fact_entries) & set(freedom_entries))
        if overlap:
            problems.append(
                "facts/creative_freedom: mixed sheet; the same entries "
                f"appear in both columns: {overlap}"
            )
        if facts == freedom and fact_entries:
            problems.append(
                "facts/creative_freedom: the two columns are identical; "
                "facts and freedom must be kept apart"
            )

    return {
        "ok": not problems,
        "problems": problems,
        "missing_assets": missing_assets,
        "asset_kinds": asset_kinds,
        "platform": {"aspect": aspect, "duration_sec": platform.get("duration_sec")},
        "memory_point": memory if isinstance(memory, str) else None,
    }


# ---------------------------------------------------------------- step 2: style note


def _resolve_lemo_style(slug: str) -> dict[str, Any]:
    """Read one Lemo style live through image.lemo_styles; never fake it."""
    try:
        from hevi.capabilities.lemo_styles import get_lemo_style

        style = get_lemo_style(slug)
        return {"status": "resolved", "slug": style.get("slug"), "essence": style.get("essence")}
    except Exception as exc:
        return {
            "status": "unavailable",
            "slug": slug,
            "reason": f"image.lemo_styles could not resolve {slug!r}: {exc}",
        }


def validate_style_note(note: Any) -> dict[str, Any]:
    """Validate a step-2 style note: concrete, or it fails.

    Colour codes, font sizes, first glance, rhythm, motion feel,
    and texture must all be concrete. The originality declaration
    must state, in one field, that the feel is learned but people,
    logos, and wording are not copied.
    """
    problems: list[str] = []
    if not isinstance(note, dict):
        return {"ok": False, "problems": ["style_note: must be a JSON object"], "colors": []}

    colours: list[str] = []
    raw_colours = note.get("colors") or note.get("palette") or note.get("colour_hex")
    if isinstance(raw_colours, list):
        for value in raw_colours:
            if isinstance(value, str) and _HEX_RE.match(value.strip()):
                colours.append(value.strip().lower())
            else:
                problems.append(f"colors: {value!r} is not a #RRGGBB colour code")
    scanned: dict[str, Any] = {
        k: v for k, v in note.items() if k not in ("colors", "palette", "colour_hex")
    }
    for value in scanned.values():
        if isinstance(value, str):
            for found in _HEX_FIND_RE.findall(value):
                colours.append(found.lower())
    colours = sorted(set(colours))
    if len(colours) < 2:
        problems.append(
            f"colors: at least 2 concrete #RRGGBB codes are required, found {len(colours)}"
        )

    description_fields = [
        note.get("description"),
        note.get("feel"),
        note.get("mood"),
        note.get("overall"),
        note.get("summary"),
        note.get("notes"),
        note.get("impression"),
        note.get("style_description"),
    ]
    description_text = " ".join(str(v) for v in description_fields if isinstance(v, str))
    for word in _VAGUE_WORDS:
        if word in description_text:
            problems.append(
                f"description: vague wording {word!r} is not a style "
                "decision; name colours, sizes, and motion instead"
            )

    typography = note.get("typography") if isinstance(note.get("typography"), dict) else {}
    title_px = note.get("title_font_size_px", typography.get("title_px",
                       typography.get("title_size", typography.get("main_px"))))
    body_px = note.get("body_font_size_px", note.get("small_font_size_px",
                      typography.get("body_px", typography.get("small_px",
                      typography.get("sub_px")))))
    if not _is_num(title_px) or not _is_num(body_px):
        problems.append(
            "typography: title and small font sizes must both be numbers "
            "(title_font_size_px and body_font_size_px)"
        )
    elif float(title_px) <= float(body_px):
        problems.append(
            f"typography: title size {title_px} must be larger than small size {body_px}"
        )

    first_glance = (
        note.get("first_glance") or note.get("eye_landing")
        or note.get("first_eye") or note.get("first_look")
    )
    if not _nonempty_str(first_glance):
        problems.append("first_glance: the first-eye landing point is required")

    rhythm = (
        note.get("avg_shot_change_sec") or note.get("rhythm_sec")
        or note.get("pace_sec") or note.get("shot_change_sec")
    )
    if not _is_num(rhythm) or float(rhythm) <= 0:
        problems.append("rhythm: average shot-change seconds must be a positive number")

    motion = note.get("motion") or note.get("motion_feel")
    if motion is None:
        problems.append("motion: a motion feel is required")
    elif isinstance(motion, str):
        if motion.strip() in _MOTION_FEELS:
            pass
        elif len(motion.strip()) < 6:
            problems.append(
                "motion: a custom motion feel needs a concrete verb "
                "description of at least 6 characters, not a bare word"
            )
        elif any(word in motion for word in _VAGUE_WORDS):
            problems.append("motion: vague wording is not a motion description")
    elif isinstance(motion, dict):
        style = motion.get("style") or motion.get("feel")
        detail = motion.get("description") or motion.get("detail") or ""
        if style in _MOTION_FEELS or (_nonempty_str(detail) and len(detail.strip()) >= 6 and not any(
            word in detail for word in _VAGUE_WORDS
        )):
            pass
        else:
            problems.append(
                "motion: choose one of 干脆/慢滑/回弹, or write a concrete "
                "verb description of at least 6 characters"
            )
    else:
        problems.append("motion: must be a string or an object with style/description")

    texture = note.get("texture") or note.get("texture_kind")
    if isinstance(texture, dict):
        texture = texture.get("kind")
    if texture not in _TEXTURE_KINDS:
        problems.append(
            f"texture: must state one of {sorted(_TEXTURE_KINDS)} explicitly "
            f"(grain/paper/none); got {texture!r}"
        )

    declaration_found = False
    for value in note.values():
        if isinstance(value, str) and "学感觉" in value and "不照搬" in value:
            if any(marker in value for marker in ("人物", "Logo", "logo", "文案")):
                declaration_found = True
    if not declaration_found:
        problems.append(
            "originality_declaration: must state in one field that the "
            "feel is learned but people, logos, and wording are not copied"
        )

    lemo: dict[str, Any] | None = None
    slug = note.get("lemo_style_slug") or note.get("lemo_slug")
    if _nonempty_str(slug):
        lemo = _resolve_lemo_style(str(slug).strip())

    return {
        "ok": not problems,
        "problems": problems,
        "colors": colours,
        "title_font_size_px": title_px if _is_num(title_px) else None,
        "body_font_size_px": body_px if _is_num(body_px) else None,
        "texture": texture,
        "motion": motion,
        "lemo_style": lemo,
    }


def confirm_style_note(style_report: Any, confirmation: Any) -> dict[str, Any]:
    """Confirm a validated style note, under strict-True semantics.

    The confirmation rule is the ``pipeline.spend_brake`` rule (see
    ``_strictly_confirmed``): ``confirmed`` must be exactly ``True``.
    A style note that failed validation can never be confirmed.
    """
    if isinstance(style_report, dict) and style_report.get("ok") is False:
        return {
            "confirmed": False,
            "ok": False,
            "reason": "style note failed validation; fix it before confirming",
            "problems": style_report.get("problems", []),
        }
    allowed, reason = _strictly_confirmed(confirmation)
    return {
        "confirmed": allowed,
        "ok": allowed,
        "reason": reason,
        "note": (
            "Confirmation semantics follow pipeline.spend_brake: "
            "confirmed must be exactly True."
        ),
    }


# ---------------------------------------------------------------- step 3: shot table


def shot_table_dedup_notes() -> dict[str, Any]:
    """State what this shot-table check does not duplicate.

    ``qa.storyboard_opening_gate`` owns verbatim opening blocking
    and ``qa.production_gates`` owns segment location, cut range,
    keyframe timing, and composition. This module checks only the
    three things neither of them checks: start/end state per
    segment, an existence reason per segment, and narration
    alignment to the segment it belongs to. Run those gates
    separately when their coverage is needed.
    """
    return {
        "this_module": [
            "start/end state per segment",
            "existence reason per segment (cuttable marking)",
            "narration alignment to segment start/end",
        ],
        "owned_elsewhere": {
            "qa.storyboard_opening_gate": "verbatim opening blocking sentence",
            "qa.production_gates": (
                "segment location, cut range, keyframe timing, composition"
            ),
        },
        "not_duplicated": [
            "opening blocking",
            "cut duration range",
            "keyframe timing",
            "composition fields",
        ],
    }


_VAGUE_REASONS = {"好看", "丰富", "好看而已", "丰富画面", "为了好看", "丰富一下", "好看一点"}


def validate_shot_table(table: Any) -> dict[str, Any]:
    """Validate a step-3 shot table.

    Segments must tile the timeline from 0 with no overlap and no
    unnamed gap. A segment with no reason, or only a vague reason,
    is marked ``cuttable`` in the report but does not fail the
    whole table. Narration timing that disagrees with its segment
    does fail the table.
    """
    problems: list[str] = []
    cuttable: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    if isinstance(table, dict):
        segments = table.get("segments") or table.get("shots") or table.get("rows")
        total_supplied = table.get("total_duration_sec")
    elif isinstance(table, list):
        segments = table
        total_supplied = None
    else:
        segments = None
        total_supplied = None
    if not isinstance(segments, list) or not segments:
        return {
            "ok": False,
            "problems": ["shot_table: a non-empty segments list is required"],
            "cuttable": [],
            "segments_checked": 0,
            "total_duration_sec": None,
        }
    prev_end: float | None = None
    eps = 1e-6
    for index, seg in enumerate(segments):
        label = f"segments[{index}]"
        if not isinstance(seg, dict):
            problems.append(f"{label}: segment must be an object")
            continue
        seg_id = seg.get("id") or seg.get("segment_id") or seg.get("shot_id") or f"segment_{index}"
        start = seg.get("start_sec", seg.get("start"))
        end = seg.get("end_sec", seg.get("end"))
        if not _is_num(start) or not _is_num(end):
            problems.append(f"{label} ({seg_id}): start_sec and end_sec must be numbers")
            continue
        start_f, end_f = float(start), float(end)
        if not start_f < end_f:
            problems.append(f"{label} ({seg_id}): start_sec must be before end_sec")
        if index == 0 and abs(start_f) > eps:
            problems.append(
                f"{label} ({seg_id}): the first segment must start at 0, got {start_f}"
            )
        if prev_end is not None:
            if start_f < prev_end - eps:
                problems.append(
                    f"{label} ({seg_id}): overlaps the previous segment "
                    f"(starts {start_f}, previous ends {prev_end})"
                )
            elif start_f > prev_end + eps:
                intent = seg.get("gap_intent") or seg.get("gap_before_intent") or seg.get("gap_reason")
                if _nonempty_str(intent):
                    gaps.append({
                        "segment_id": seg_id, "from_sec": prev_end,
                        "to_sec": start_f, "intent": str(intent).strip(),
                    })
                else:
                    problems.append(
                        f"{label} ({seg_id}): gap from {prev_end} to {start_f} "
                        "with no stated intent; name the intent or close the gap"
                    )
        prev_end = end_f
        start_frame = seg.get("start_frame") or seg.get("start_image") or seg.get("start_visual")
        end_frame = seg.get("end_frame") or seg.get("end_image") or seg.get("end_visual")
        if not _nonempty_str(start_frame):
            problems.append(f"{label} ({seg_id}): start_frame (opening picture) is required")
        if not _nonempty_str(end_frame):
            problems.append(f"{label} ({seg_id}): end_frame (closing picture) is required")
        reason = seg.get("reason") or seg.get("existence_reason") or seg.get("purpose")
        if not _nonempty_str(reason):
            cuttable.append({
                "segment_id": seg_id, "reason": reason,
                "detail": "no existence reason given; a segment with no reason is cuttable",
            })
        elif str(reason).strip() in _VAGUE_REASONS:
            cuttable.append({
                "segment_id": seg_id, "reason": str(reason).strip(),
                "detail": "vague reason; a segment kept only for looks is cuttable",
            })
        narration = seg.get("narration")
        narration_text = seg.get("narration_text")
        if isinstance(narration, dict):
            n_start = narration.get("start_sec", narration.get("start"))
            n_end = narration.get("end_sec", narration.get("end"))
            if not _is_num(n_start) or not _is_num(n_end):
                problems.append(
                    f"{label} ({seg_id}): narration timing (start_sec/end_sec) "
                    "is required when narration is given as an object"
                )
            elif abs(float(n_start) - start_f) > 0.05 or abs(float(n_end) - end_f) > 0.05:
                problems.append(
                    f"{label} ({seg_id}): narration ({n_start}-{n_end}) does "
                    f"not align with its segment ({start_f}-{end_f}); "
                    "words belong to the segment they are timed to"
                )
        elif _nonempty_str(narration) or _nonempty_str(narration_text):
            n_start = seg.get("narration_start_sec", seg.get("narration_start"))
            n_end = seg.get("narration_end_sec", seg.get("narration_end"))
            if (_is_num(n_start) or _is_num(n_end)) and (
                not _is_num(n_start) or not _is_num(n_end)
                or abs(float(n_start) - start_f) > 0.05
                or abs(float(n_end) - end_f) > 0.05
            ):
                problems.append(
                    f"{label} ({seg_id}): narration timing does not align "
                    f"with its segment ({start_f}-{end_f})"
                )
    total = prev_end
    if _is_num(total_supplied) and total is not None and abs(float(total_supplied) - total) > 0.05:
        problems.append(
            f"total_duration_sec: supplied {total_supplied} does not match "
            f"the last segment end {total}"
        )
    return {
        "ok": not problems,
        "problems": problems,
        "cuttable": cuttable,
        "gaps": gaps,
        "segments_checked": len(segments),
        "total_duration_sec": total,
        "dedup": shot_table_dedup_notes(),
    }


# ---------------------------------------------------------------- step 4: beat grid


def build_beat_grid(
    bpm: Any,
    offset_sec: Any = 0.0,
    duration_sec: Any = None,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """Build a beat grid from a declared BPM.

    The grid is planned, not measured: no audio file is read here.
    Real beat analysis from audio is a separate, unbuilt step and
    must never be claimed from these numbers.
    """
    if not _is_num(bpm) or float(bpm) <= 0:
        raise CapabilityError("pipeline.code_studio_workflow: bpm must be a positive number")
    if duration_sec is None:
        raise CapabilityError(
            "pipeline.code_studio_workflow: duration_sec is required for a beat grid"
        )
    if not _is_num(duration_sec) or float(duration_sec) <= 0:
        raise CapabilityError("pipeline.code_studio_workflow: duration_sec must be > 0")
    if not _is_num(offset_sec) or float(offset_sec) < 0:
        raise CapabilityError("pipeline.code_studio_workflow: offset_sec must be >= 0")
    interval = 60.0 / float(bpm)
    beats: list[float] = []
    t = float(offset_sec)
    while t <= float(duration_sec) + 1e-9:
        beats.append(round(t, 4))
        t += interval
    return {
        "bpm": float(bpm),
        "beat_interval_sec": round(interval, 4),
        "offset_sec": float(offset_sec),
        "duration_sec": float(duration_sec),
        "beats": beats,
        "beat_count": len(beats),
        "mode": mode,
        "measured_from_audio": False,
        "beat_basis": "planned_not_measured",
        "note": (
            "Planned grid from the declared BPM only. No audio file was "
            "analysed; measured BPM/beat points require an audio file "
            "and are not claimed here."
        ),
    }


def check_beat_alignment(
    events: Any,
    grid: Any,
    tolerance: float = 0.05,
    mode: str | None = None,
) -> dict[str, Any]:
    """Check that cut / sound / picture-change events land on beats.

    Music-first and music-last pass through this same function:
    ``mode`` only records which order the music was fixed in, it
    never changes the tolerance or the check.
    """
    problems: list[str] = []
    if isinstance(grid, dict):
        beats = grid.get("beats") or []
        beat_basis = grid.get("beat_basis", "planned_not_measured")
        measured = bool(grid.get("measured_from_audio", False))
        grid_mode = grid.get("mode")
    elif isinstance(grid, list):
        beats = grid
        beat_basis = "planned_not_measured"
        measured = False
        grid_mode = None
    else:
        beats, beat_basis, measured, grid_mode = [], "planned_not_measured", False, None
    effective_mode = mode or grid_mode
    if effective_mode is not None and effective_mode not in ("music_first", "music_last"):
        problems.append(
            f"mode: must be music_first or music_last, got {effective_mode!r}"
        )
    if not beats:
        problems.append("grid: no beat points in the grid")
    if not _is_num(tolerance) or float(tolerance) < 0:
        problems.append("tolerance: must be a non-negative number")
        tolerance = 0.05
    if not isinstance(events, list) or not events:
        problems.append("events: a non-empty events list is required")
        events = []
    misaligned: list[dict[str, Any]] = []
    checked = 0
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            problems.append(f"events[{index}]: event must be an object")
            continue
        checked += 1
        event_id = event.get("id") or event.get("event_id") or f"event_{index}"
        when = event.get("time_sec", event.get("t_sec", event.get("t")))
        if not _is_num(when):
            problems.append(f"events[{index}] ({event_id}): time_sec is required")
            continue
        if not beats:
            continue
        nearest = min(beats, key=lambda b: abs(float(b) - float(when)))
        deviation = abs(float(when) - float(nearest))
        if deviation > float(tolerance) + 1e-9:
            misaligned.append({
                "event_id": event_id,
                "kind": event.get("kind") or event.get("type"),
                "time_sec": float(when),
                "nearest_beat_sec": float(nearest),
                "deviation_sec": round(deviation, 4),
            })
            problems.append(
                f"events[{index}] ({event_id}): at {when}s, "
                f"{deviation:.3f}s from the nearest beat {nearest}s "
                f"(tolerance {tolerance}s)"
            )
    return {
        "ok": not problems,
        "problems": problems,
        "checked": checked,
        "misaligned": misaligned,
        "tolerance_sec": float(tolerance),
        "mode": effective_mode,
        "beat_basis": beat_basis,
        "measured_from_audio": measured,
        "note": (
            "Beat basis is planned_not_measured unless the grid was "
            "measured from an audio file by a separate step."
        ),
    }


# ---------------------------------------------------------------- step 5: code rendering


def sample_layouts(title: str = "标题", subtitle: str = "副标题") -> dict[str, dict[str, Any]]:
    """Three independently laid-out aspect variants.

    Each aspect gets its own positions and font sizes, chosen for
    that canvas. Nothing here is a scaled copy of another aspect:
    ``check_no_hard_crop`` verifies that the normalised layouts
    differ.
    """
    return {
        "16:9": {
            "aspect": "16:9", "width": 1920, "height": 1080,
            "background": "#101418",
            "elements": [
                {"id": "title", "kind": "text", "x": 120, "y": 140, "w": 900,
                 "h": 120, "color": "#F5F2EA", "font_size": 72, "text": title},
                {"id": "panel", "kind": "panel", "x": 120, "y": 320, "w": 760,
                 "h": 420, "color": "#2A7FFF", "font_size": 28, "text": subtitle},
                {"id": "button", "kind": "button", "x": 120, "y": 800, "w": 200,
                 "h": 64, "color": "#FFC53D", "font_size": 28, "text": "开始"},
            ],
        },
        "9:16": {
            "aspect": "9:16", "width": 1080, "height": 1920,
            "background": "#101418",
            "elements": [
                {"id": "title", "kind": "text", "x": 80, "y": 220, "w": 920,
                 "h": 180, "color": "#F5F2EA", "font_size": 84, "text": title},
                {"id": "panel", "kind": "panel", "x": 80, "y": 480, "w": 920,
                 "h": 640, "color": "#2A7FFF", "font_size": 32, "text": subtitle},
                {"id": "button", "kind": "button", "x": 80, "y": 1200, "w": 360,
                 "h": 88, "color": "#FFC53D", "font_size": 36, "text": "开始"},
            ],
        },
        "1:1": {
            "aspect": "1:1", "width": 1080, "height": 1080,
            "background": "#101418",
            "elements": [
                {"id": "title", "kind": "text", "x": 90, "y": 110, "w": 900,
                 "h": 110, "color": "#F5F2EA", "font_size": 64, "text": title},
                {"id": "panel", "kind": "panel", "x": 90, "y": 280, "w": 900,
                 "h": 460, "color": "#2A7FFF", "font_size": 26, "text": subtitle},
                {"id": "button", "kind": "button", "x": 90, "y": 820, "w": 220,
                 "h": 60, "color": "#FFC53D", "font_size": 26, "text": "开始"},
            ],
        },
    }


def check_no_hard_crop(layouts: Any) -> dict[str, Any]:
    """Check that aspect layouts are not one layout scaled to fit.

    Layouts that share the same normalised positions, sizes, and
    font sizes in every aspect are a hard crop of one another and
    fail. Independently arranged layouts pass.
    """
    problems: list[str] = []
    if isinstance(layouts, dict):
        items = list(layouts.items())
    elif isinstance(layouts, list):
        items = [(lay.get("aspect", f"layout_{i}"), lay) for i, lay in enumerate(layouts)]
    else:
        return {"ok": False, "problems": ["layouts: must be a dict or list of layouts"],
                "aspects": [], "signatures_equal": None}
    if len(items) < 2:
        problems.append("layouts: at least 2 aspect layouts are required to compare")
        return {"ok": False, "problems": problems,
                "aspects": [a for a, _ in items], "signatures_equal": None}
    signatures: dict[str, tuple] = {}
    for aspect, layout in items:
        if not isinstance(layout, dict):
            problems.append(f"layouts[{aspect}]: layout must be an object")
            continue
        width, height = layout.get("width"), layout.get("height")
        if not _is_num(width) or not _is_num(height) or width <= 0 or height <= 0:
            problems.append(f"layouts[{aspect}]: width/height must be positive numbers")
            continue
        sig = []
        for element in layout.get("elements") or []:
            if not isinstance(element, dict):
                continue
            sig.append((
                element.get("id"),
                round(float(element.get("x", 0)) / float(width), 6),
                round(float(element.get("y", 0)) / float(height), 6),
                round(float(element.get("w", 0)) / float(width), 6),
                round(float(element.get("h", 0)) / float(height), 6),
                round(float(element.get("font_size", 0)) / float(height), 6),
            ))
        signatures[aspect] = tuple(sorted(sig, key=lambda row: str(row[0])))
    values = list(signatures.values())
    equal = len(values) > 1 and all(v == values[0] for v in values[1:])
    if equal:
        problems.append(
            "layouts: all aspects share the same normalised layout; "
            "that is a hard crop, not separate per-aspect arrangement"
        )
    return {
        "ok": not problems,
        "problems": problems,
        "aspects": [a for a, _ in items],
        "signatures_equal": equal,
    }


def _interp(moves: list[dict[str, Any]], t: float, base: dict[str, Any]) -> dict[str, Any]:
    state = dict(base)
    for move in moves:
        if not isinstance(move, dict):
            continue
        from_t, to_t = move.get("from_t", 0.0), move.get("to_t", 0.0)
        if not _is_num(from_t) or not _is_num(to_t):
            continue
        if t < float(from_t):
            continue
        if float(to_t) <= float(from_t) or t >= float(to_t):
            frac = 1.0
        else:
            frac = (t - float(from_t)) / (float(to_t) - float(from_t))
        for key, from_key, to_key in (
            ("x", "from_x", "to_x"), ("y", "from_y", "to_y"),
            ("w", "from_w", "to_w"), ("h", "from_h", "to_h"),
            ("opacity", "from_opacity", "to_opacity"),
            ("font_size", "from_font_size", "to_font_size"),
        ):
            if from_key in move and to_key in move:
                state[key] = float(move[from_key]) + (
                    float(move[to_key]) - float(move[from_key])) * frac
    return state


def frame_state(t: Any, layout: Any) -> dict[str, Any]:
    """Return every element's state at time ``t`` (pure, deterministic).

    The same ``t`` and layout always return the same values: state
    is a pure function of time, so a frame can be re-rendered
    exactly. No file is written and no model is called.
    """
    if not _is_num(t) or float(t) < 0:
        raise CapabilityError("pipeline.code_studio_workflow: t must be >= 0")
    if not isinstance(layout, dict):
        raise CapabilityError("pipeline.code_studio_workflow: layout must be an object")
    width, height = layout.get("width"), layout.get("height")
    if not _is_num(width) or not _is_num(height):
        raise CapabilityError("pipeline.code_studio_workflow: layout needs width/height")
    elements: list[dict[str, Any]] = []
    for element in layout.get("elements") or []:
        if not isinstance(element, dict):
            continue
        base = {
            "x": float(element.get("x", 0)),
            "y": float(element.get("y", 0)),
            "w": float(element.get("w", 0)),
            "h": float(element.get("h", 0)),
            "opacity": float(element.get("opacity", 1.0)),
            "font_size": float(element.get("font_size", 0)),
        }
        state = _interp(element.get("moves") or [], float(t), base)
        visible_from = element.get("visible_from", 0.0)
        visible_to = element.get("visible_to")
        visible = True
        if _is_num(visible_from) and float(t) < float(visible_from):
            visible = False
        if _is_num(visible_to) and float(t) >= float(visible_to):
            visible = False
        elements.append({
            "id": element.get("id"),
            "kind": element.get("kind"),
            "x": round(state["x"], 6),
            "y": round(state["y"], 6),
            "w": round(state["w"], 6),
            "h": round(state["h"], 6),
            "color": element.get("color"),
            "font_size": round(state["font_size"], 6),
            "text": element.get("text"),
            "visible": visible,
            "opacity": round(state["opacity"], 6),
        })
    return {
        "t": round(float(t), 4),
        "aspect": layout.get("aspect"),
        "width": int(width),
        "height": int(height),
        "background": layout.get("background", "#000000"),
        "elements": elements,
    }


def render_single_frame(t: Any, layout: Any, out_path: Any = None) -> dict[str, Any]:
    """Draw one frame with PIL from ``frame_state`` and hash the PNG bytes.

    This is the workflow's own deterministic frame function for
    single-frame checks. It is not a ``video.code_render`` tier
    render: code_render owns multi-frame tier rendering (see
    ``code_render_tier_status``), and this function carries its
    own width/height per aspect instead of claiming a tier.
    """
    from PIL import Image, ImageDraw, ImageFont

    state = frame_state(t, layout)
    width, height = state["width"], state["height"]
    try:
        background = _parse_hex(state["background"])
    except (ValueError, TypeError) as exc:
        raise CapabilityError(
            f"pipeline.code_studio_workflow: bad background colour: {state['background']!r}"
        ) from exc
    image = Image.new("RGB", (width, height), background)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for element in state["elements"]:
        if not element["visible"]:
            continue
        try:
            fill = _parse_hex(str(element["color"] or "#FFFFFF"))
        except (ValueError, TypeError) as exc:
            raise CapabilityError(
                f"pipeline.code_studio_workflow: bad element colour for "
                f"{element['id']!r}: {element['color']!r}"
            ) from exc
        alpha = max(0, min(255, int(round(element["opacity"] * 255))))
        draw.rectangle(
            [element["x"], element["y"], element["x"] + element["w"], element["y"] + element["h"]],
            fill=(*fill, alpha),
        )
        text = element.get("text")
        if _nonempty_str(text) and element["font_size"] > 0:
            try:
                font = ImageFont.load_default(size=max(8, int(element["font_size"])))
            except Exception:
                font = ImageFont.load_default()
            draw.text(
                (element["x"] + 4, element["y"] + 4), str(text),
                fill=(255, 255, 255, alpha), font=font,
            )
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    digest = hashlib.sha256(buffer.getvalue()).hexdigest()
    path: str | None = None
    if out_path is not None:
        path_obj = Path(out_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_bytes(buffer.getvalue())
        path = str(path_obj)
    return {
        "t": state["t"],
        "width": width,
        "height": height,
        "sha256": digest,
        "size": (width, height),
        "image": image,
        "path": path,
        "code_render_relation": (
            "Own deterministic frame function for single-frame checks; "
            "full multi-frame rendering stays with video.code_render."
        ),
    }


def rerender_segments(
    changed_ids: Any,
    previous_manifest: Any,
    render_fn: Any,
) -> dict[str, Any]:
    """Re-render only changed segments; reuse old hashes for the rest.

    ``previous_manifest`` is a list of ``{id, hash}`` segment rows
    or a dict with a ``segments`` list (or an id->hash mapping).
    ``render_fn`` is a caller-supplied callable taking one segment
    row and returning a hash string or a dict with ``sha256``/``hash``.
    """
    if not callable(render_fn):
        raise CapabilityError("pipeline.code_studio_workflow: render_fn must be callable")
    if isinstance(previous_manifest, dict) and "segments" in previous_manifest:
        rows = previous_manifest["segments"]
    elif isinstance(previous_manifest, dict):
        rows = [{"id": key, "hash": value} for key, value in previous_manifest.items()]
    elif isinstance(previous_manifest, list):
        rows = previous_manifest
    else:
        raise CapabilityError(
            "pipeline.code_studio_workflow: previous_manifest must be a segment list or mapping"
        )
    changed = set(changed_ids or [])
    known = {str(row.get("id")) for row in rows if isinstance(row, dict)}
    unknown = sorted(changed - known)
    if unknown:
        raise CapabilityError(
            f"pipeline.code_studio_workflow: changed segment(s) not in the "
            f"previous manifest: {unknown}"
        )
    out_rows: list[dict[str, Any]] = []
    rerendered: list[str] = []
    reused: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        seg_id = str(row.get("id"))
        old_hash = row.get("hash") or row.get("sha256")
        if seg_id in changed:
            result = render_fn(row)
            new_hash = result.get("sha256") or result.get("hash") if isinstance(result, dict) else result
            if not _nonempty_str(new_hash):
                raise CapabilityError(
                    f"pipeline.code_studio_workflow: render_fn returned no hash for {seg_id!r}"
                )
            out_rows.append({"id": seg_id, "hash": str(new_hash), "status": "rerendered"})
            rerendered.append(seg_id)
        else:
            if not _nonempty_str(old_hash):
                raise CapabilityError(
                    f"pipeline.code_studio_workflow: previous manifest has no "
                    f"hash for unchanged segment {seg_id!r}; cannot reuse it"
                )
            out_rows.append({"id": seg_id, "hash": str(old_hash), "status": "reused"})
            reused.append(seg_id)
    return {
        "ok": True,
        "segments": out_rows,
        "rerendered": rerendered,
        "reused": reused,
        "note": "Unchanged segments reuse their previous hash; only changed segments were re-rendered.",
    }


def check_motion_weight(moves: Any) -> dict[str, Any]:
    """Check motion weight: small moves fast, large moves settle, text readable.

    Limits (also written into the report): small elements move in
    at most 0.35s; large elements must declare ``settle_ms > 0``;
    text must stay on screen for at least
    ``max(1.0, chars / 8.0)`` seconds, counting characters at 8
    characters per second of reading speed.
    """
    problems: list[str] = []
    checks: list[dict[str, Any]] = []
    if not isinstance(moves, list):
        return {
            "ok": False,
            "problems": ["moves: a list of move records is required"],
            "checks": [],
            "limits": {"small_max_sec": SMALL_MOVE_MAX_SEC,
                       "reading_chars_per_sec": READING_CHARS_PER_SEC,
                       "min_hold_sec": MIN_HOLD_SEC, "formula": MOTION_WEIGHT_FORMULA},
        }
    small_kinds = {"button", "switch", "icon", "small", "small_element"}
    large_kinds = {"panel", "modal", "dialog", "block", "large", "large_element", "section"}
    for index, move in enumerate(moves):
        if not isinstance(move, dict):
            problems.append(f"moves[{index}]: move must be an object")
            continue
        move_id = move.get("element_id") or move.get("id") or f"move_{index}"
        kind = str(move.get("kind") or move.get("element_kind") or move.get("type") or "").strip().lower()
        duration = move.get("duration_sec", move.get("duration"))
        if kind in small_kinds:
            if not _is_num(duration) or float(duration) > SMALL_MOVE_MAX_SEC:
                problems.append(
                    f"moves[{index}] ({move_id}): small element must move in "
                    f"at most {SMALL_MOVE_MAX_SEC}s, got {duration!r}"
                )
                checks.append({"element_id": move_id, "rule": "small_fast", "pass": False})
            else:
                checks.append({"element_id": move_id, "rule": "small_fast", "pass": True})
        if kind in large_kinds:
            settle = move.get("settle_ms", move.get("settle"))
            if not _is_num(settle) or float(settle) <= 0:
                problems.append(
                    f"moves[{index}] ({move_id}): large element must declare "
                    f"settle_ms > 0 so it lands and rests, got {settle!r}"
                )
                checks.append({"element_id": move_id, "rule": "large_settle", "pass": False})
            else:
                checks.append({"element_id": move_id, "rule": "large_settle", "pass": True})
        text = move.get("text")
        if _nonempty_str(text):
            chars = len(str(text))
            required = max(MIN_HOLD_SEC, chars / READING_CHARS_PER_SEC)
            hold = move.get("hold_sec", move.get("hold"))
            if not _is_num(hold) or float(hold) < required - 1e-9:
                problems.append(
                    f"moves[{index}] ({move_id}): text of {chars} chars must "
                    f"stay readable for at least {required:.2f}s "
                    f"(max(1.0, chars / 8.0)), got hold_sec={hold!r}"
                )
                checks.append({"element_id": move_id, "rule": "text_hold",
                               "pass": False, "required_hold_sec": round(required, 2)})
            else:
                checks.append({"element_id": move_id, "rule": "text_hold",
                               "pass": True, "required_hold_sec": round(required, 2)})
    return {
        "ok": not problems,
        "problems": problems,
        "checks": checks,
        "limits": {"small_max_sec": SMALL_MOVE_MAX_SEC,
                   "reading_chars_per_sec": READING_CHARS_PER_SEC,
                   "min_hold_sec": MIN_HOLD_SEC, "formula": MOTION_WEIGHT_FORMULA},
    }


def check_eye_landing(items: Any) -> dict[str, Any]:
    """Every segment, after its move, must declare a gaze target."""
    problems: list[str] = []
    missing: list[str] = []
    if not isinstance(items, list) or not items:
        return {"ok": False, "problems": ["eye_landing: a non-empty items list is required"],
                "missing": [], "checked": 0}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"items[{index}]: item must be an object")
            continue
        item_id = item.get("id") or item.get("segment_id") or item.get("shot_id") or f"item_{index}"
        target = item.get("gaze_target") or item.get("eye_target") or item.get("landing")
        if not _nonempty_str(target):
            missing.append(str(item_id))
            problems.append(
                f"items[{index}] ({item_id}): no gaze_target declared after the move"
            )
    return {"ok": not problems, "problems": problems, "missing": missing, "checked": len(items)}


def classify_shot_feasibility(shot: Any) -> dict[str, Any]:
    """Route a shot: code rendering, or live / video-model work.

    Shots that need a real person on camera, photoreal picture, or
    complex human motion are routed away from code rendering and
    labelled as such. Code is never asked to fake them.
    """
    if not isinstance(shot, dict):
        raise CapabilityError("pipeline.code_studio_workflow: shot must be an object")
    values: list[str] = []
    for key in ("kind", "type", "shot_kind", "category", "route_hint"):
        if _nonempty_str(shot.get(key)):
            values.append(str(shot[key]).strip().lower())
    requires = shot.get("requires") or shot.get("needs") or []
    if isinstance(requires, list):
        values.extend(str(v).strip().lower() for v in requires if _nonempty_str(v))
    for flag in ("live_action", "photoreal", "complex_human_motion"):
        if shot.get(flag) is True:
            values.append(flag)
    matched = sorted(set(values) & _FEASIBILITY_BLOCKERS)
    shot_id = shot.get("id") or shot.get("segment_id") or shot.get("shot_id")
    if matched:
        return {
            "shot_id": shot_id,
            "route": "live_or_video_model",
            "code_render_ok": False,
            "matched": matched,
            "reason": (
                f"Shot needs {', '.join(matched)}; code rendering cannot "
                "do it honestly, so it is routed to live footage or a "
                "video model instead of being forced through code."
            ),
        }
    return {
        "shot_id": shot_id,
        "route": "code_render",
        "code_render_ok": True,
        "matched": [],
        "reason": "No live-action, photoreal, or complex human-motion requirement declared.",
    }


def code_render_tier_status() -> dict[str, Any]:
    """Report the video.code_render tier table honestly, including the gap.

    This module does not add tiers to code_render. The vertical
    gap is stated here so no caller can claim a code_render
    vertical tier exists.
    """
    try:
        from hevi.capabilities.code_render import TIERS

        tiers = sorted(TIERS.keys())
    except Exception as exc:
        return {
            "tiers": [],
            "vertical_tier": None,
            "gap": f"video.code_render tier table could not be read: {exc}",
            "relation": (
                "Workflow frame functions carry their own width/height "
                "per aspect; they do not claim a code_render tier."
            ),
        }
    vertical = [name for name in tiers if "vertical" in name or "9x16" in name or "portrait" in name]
    return {
        "tiers": tiers,
        "vertical_tier": vertical[0] if vertical else None,
        "gap": (
            None if vertical else
            "video.code_render has landscape tiers only "
            "(draft_720p30/hd_1080p30/hd_1080p60/uhd_2160p30/uhd_2160p60); "
            "there is no vertical tier. Vertical work in this workflow "
            "uses its own per-aspect frame functions and must not be "
            "reported as a code_render vertical tier."
        ),
        "relation": (
            "Workflow frame functions carry their own width/height per "
            "aspect; full multi-frame rendering stays with video.code_render."
        ),
    }


def manim_status() -> dict[str, Any]:
    """State the Manim connection honestly: registry-only, not connected.

    ``video.manim_render`` exposes no public render function: its
    render entry point is the registry-private ``_render_manim``
    and its interpreter resolver ``manim_python()``. Until a
    caller injects a renderer (see ``request_manim_render``),
    Manim is not connected here.
    """
    try:
        from hevi.capabilities.manim_render import manim_python

        interpreter = manim_python()
        exists = Path(interpreter).is_file()
        detail = str(interpreter)
    except Exception as exc:
        return {
            "connected": False, "status": "not_connected",
            "manim_render_entry": "registry-only (_render_manim); no public render function",
            "manim_python": None, "interpreter_exists": False,
            "reason": f"video.manim_render could not be inspected: {exc}",
        }
    return {
        "connected": False,
        "status": "not_connected",
        "manim_render_entry": "registry-only (_render_manim); no public render function",
        "manim_python": detail,
        "interpreter_exists": exists,
        "reason": (
            "Manim is not connected to this workflow: video.manim_render "
            "has no public render entry point to call. Pass a "
            "manim_renderer callable to request_manim_render to inject one."
        ),
    }


def request_manim_render(payload: Any, manim_renderer: Any = None) -> dict[str, Any]:
    """Render with Manim only through an injected renderer, or report the gap."""
    status = manim_status()
    if manim_renderer is None:
        return {**status, "rendered": False, "payload": payload}
    if not callable(manim_renderer):
        raise CapabilityError("pipeline.code_studio_workflow: manim_renderer must be callable")
    result = manim_renderer(payload)
    return {**status, "rendered": True, "result": result}


# ---------------------------------------------------------------- step 6: review board


def build_contact_sheet(
    frames: Any,
    *,
    columns: int = 3,
    thumb_width: int = 360,
    out_path: Any = None,
    times: Any = None,
) -> dict[str, Any]:
    """Assemble key frames into one labelled contact-sheet board (PIL).

    ``frames`` may be dicts with ``image`` (PIL) or ``path`` plus
    ``t_sec``, ``(t_sec, image)`` pairs, or bare PIL images (with
    ``times`` giving their timestamps). Every thumb carries its
    timestamp label, so the board can be read without its caption.
    """
    from PIL import Image, ImageDraw, ImageFont

    entries: list[tuple[float, Any]] = []
    if isinstance(frames, list):
        for index, item in enumerate(frames):
            if isinstance(item, dict):
                image = item.get("image")
                path = item.get("path") or item.get("file")
                when = item.get("t_sec", item.get("time_sec", item.get("t")))
                if image is None and path is not None:
                    image = Image.open(path)
                if image is None:
                    raise CapabilityError(
                        f"pipeline.code_studio_workflow: frame {index} has no image or path"
                    )
                if not _is_num(when):
                    raise CapabilityError(
                        f"pipeline.code_studio_workflow: frame {index} has no t_sec"
                    )
                entries.append((float(when), image))
            elif isinstance(item, tuple) and len(item) == 2:
                entries.append((float(item[0]), item[1]))
            else:
                when = None
                if isinstance(times, list) and index < len(times):
                    when = float(times[index])
                elif _is_num(getattr(item, "_t_sec", None)):
                    when = float(item._t_sec)
                if when is None:
                    raise CapabilityError(
                        "pipeline.code_studio_workflow: bare frame images need "
                        "a times list with one timestamp per frame"
                    )
                entries.append((when, item))
    if not entries:
        raise CapabilityError("pipeline.code_studio_workflow: no frames supplied for a contact sheet")
    if not isinstance(columns, int) or columns < 1:
        raise CapabilityError("pipeline.code_studio_workflow: columns must be a positive integer")
    thumbs: list[tuple[float, Any]] = []
    for when, image in entries:
        image = image.convert("RGB")
        thumb_height = max(1, round(image.height * thumb_width / image.width))
        thumbs.append((when, image.resize((thumb_width, thumb_height))))
    rows = math.ceil(len(thumbs) / columns)
    row_heights = []
    for row in range(rows):
        row_heights.append(max(t.height for _, t in thumbs[row * columns:(row + 1) * columns]))
    label_h = 24
    sheet_width = columns * thumb_width
    sheet_height = sum(h + label_h for h in row_heights)
    sheet = Image.new("RGB", (sheet_width, sheet_height), (17, 20, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=16)
    except Exception:
        font = ImageFont.load_default()
    y = 0
    for row in range(rows):
        for col in range(columns):
            index = row * columns + col
            if index >= len(thumbs):
                break
            when, thumb = thumbs[index]
            x = col * thumb_width
            sheet.paste(thumb, (x, y))
            draw.rectangle([x, y + thumb.height, x + thumb_width, y + thumb.height + label_h],
                           fill=(0, 0, 0))
            draw.text((x + 6, y + thumb.height + 3), f"{when:.1f}s",
                      fill=(255, 255, 255), font=font)
        y += row_heights[row] + label_h
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    digest = hashlib.sha256(buffer.getvalue()).hexdigest()
    path: str | None = None
    if out_path is not None:
        path_obj = Path(out_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_bytes(buffer.getvalue())
        path = str(path_obj)
    return {
        "image": sheet,
        "sha256": digest,
        "width": sheet.width,
        "height": sheet.height,
        "frame_count": len(entries),
        "times": [when for when, _ in entries],
        "columns": columns,
        "path": path,
    }


def review_contact_sheet(checks: Any) -> dict[str, Any]:
    """Run the five contact-sheet review checks.

    Phone legibility is an arithmetic projection (title size scaled
    to a phone-width frame), stated as such: it is not a real-device
    viewing. Transition deltas that were never measured stay
    ``undetermined``, never a pass. A missing cover element fails.
    """
    if not isinstance(checks, dict):
        return {"ok": False, "checks": {}, "failures": ["checks"],
                "undetermined": [], "verdict": "fail",
                "problems": ["checks: must be a JSON object"]}
    results: dict[str, dict[str, Any]] = {}

    phone = checks.get("phone_projection") or checks.get("phone") or {}
    if isinstance(phone, dict) and _is_num(phone.get("title_font_size_px")) and _is_num(phone.get("frame_width_px")):
        phone_width = float(phone.get("phone_width_px", DEFAULT_PHONE_WIDTH_PX))
        minimum = float(phone.get("min_phone_font_px", MIN_PHONE_FONT_PX))
        projected = float(phone["title_font_size_px"]) * phone_width / float(phone["frame_width_px"])
        passed = projected >= minimum
        results["phone_legibility"] = {
            "verdict": "pass" if passed else "fail", "pass": passed,
            "projected_phone_font_px": round(projected, 2),
            "phone_width_px": phone_width, "threshold_px": minimum,
            "detail": (
                f"title {phone['title_font_size_px']}px on a "
                f"{phone['frame_width_px']}px frame projects to {projected:.1f}px "
                f"at {phone_width:.0f}px phone width (threshold {minimum}px)"
            ),
            "method": (
                "Arithmetic projection only: title size scaled by "
                "phone_width / frame_width. Not a real-device viewing."
            ),
        }
    else:
        results["phone_legibility"] = {
            "verdict": "undetermined", "pass": None,
            "detail": "phone projection inputs missing (title_font_size_px, frame_width_px)",
            "method": "Arithmetic projection only; no numbers supplied.",
        }

    real = checks.get("real_data") or {}
    if isinstance(real, dict) and isinstance(real.get("used_refs"), list):
        brief_assets = real.get("brief_assets") or real.get("assets") or []
        known = {str(a.get("ref") or a.get("path") or a.get("hash") or a.get("name") or a)
                 for a in brief_assets} if isinstance(brief_assets, list) else set()
        used = [str(u) for u in real["used_refs"]]
        missing_refs = [u for u in used if u not in known]
        if not used:
            results["real_data"] = {
                "verdict": "undetermined", "pass": None,
                "detail": "no interface-data refs declared as used",
                "method": "Used refs checked against the brief's real-material list.",
            }
        elif missing_refs:
            results["real_data"] = {
                "verdict": "fail", "pass": False,
                "missing_refs": missing_refs,
                "detail": f"used refs not in the brief's real-material list: {missing_refs}",
                "method": "Used refs checked against the brief's real-material list.",
            }
        else:
            results["real_data"] = {
                "verdict": "pass", "pass": True,
                "detail": f"all {len(used)} used refs are in the brief's real-material list",
                "method": "Used refs checked against the brief's real-material list.",
            }
    else:
        results["real_data"] = {
            "verdict": "undetermined", "pass": None,
            "detail": "real-data check inputs missing (used_refs, brief_assets)",
            "method": "Used refs checked against the brief's real-material list.",
        }

    transition = checks.get("transition") or {}
    deltas = transition.get("frame_deltas") if isinstance(transition, dict) else None
    if isinstance(deltas, list) and deltas and all(_is_num(d) for d in deltas):
        low = float(transition.get("low", TRANSITION_DELTA_LOW))
        high = float(transition.get("high", TRANSITION_DELTA_HIGH))
        bad = []
        for i, delta in enumerate(deltas):
            if float(delta) < low:
                bad.append(f"delta[{i}]={delta} below {low} (blurry / no change)")
            elif float(delta) > high:
                bad.append(f"delta[{i}]={delta} above {high} (jump cut)")
        passed = not bad
        results["transition"] = {
            "verdict": "pass" if passed else "fail", "pass": passed,
            "deltas": [float(d) for d in deltas], "low": low, "high": high,
            "detail": "; ".join(bad) if bad else (
                f"all {len(deltas)} adjacent key-frame deltas within [{low}, {high}]"
            ),
            "method": (
                "Delta = mean absolute per-pixel difference / 255 between "
                "adjacent key frames, as supplied by the caller."
            ),
        }
    else:
        results["transition"] = {
            "verdict": "undetermined", "pass": None,
            "detail": "no measured frame deltas supplied; transition sharpness unmeasured",
            "method": "Adjacent key-frame deltas, as supplied by the caller.",
        }

    hook = checks.get("hook") or {}
    if isinstance(hook, dict):
        declared = hook.get("hook_declared")
        declared_ok = bool(declared) if not isinstance(declared, str) else bool(declared.strip())
        first_change = hook.get("first_change_sec", hook.get("first_visual_change_sec"))
        if not declared_ok:
            results["hook"] = {
                "verdict": "fail", "pass": False,
                "detail": "no hook declared for the first segment",
                "method": "First segment must declare a hook; the first visual change must fall within 2s.",
            }
        elif not _is_num(first_change):
            results["hook"] = {
                "verdict": "undetermined", "pass": None,
                "detail": "hook declared but the first visual-change time was not measured",
                "method": "First segment must declare a hook; the first visual change must fall within 2s.",
            }
        elif float(first_change) <= 2.0:
            results["hook"] = {
                "verdict": "pass", "pass": True,
                "first_change_sec": float(first_change),
                "detail": f"hook declared; first visual change at {first_change}s (within 2s)",
                "method": "First segment must declare a hook; the first visual change must fall within 2s.",
            }
        else:
            results["hook"] = {
                "verdict": "fail", "pass": False,
                "first_change_sec": float(first_change),
                "detail": f"first visual change at {first_change}s, after the 2s hook window",
                "method": "First segment must declare a hook; the first visual change must fall within 2s.",
            }
    else:
        results["hook"] = {"verdict": "fail", "pass": False, "detail": "hook check missing"}

    cover = checks.get("cover") or {}
    if isinstance(cover, dict):
        title_present = bool(cover.get("title_present") or cover.get("title_text"))
        ratio: float | None = None
        if _is_num(cover.get("contrast_ratio")):
            ratio = float(cover["contrast_ratio"])
        elif _nonempty_str(cover.get("title_color")) and _nonempty_str(cover.get("background_color")):
            ratio = _contrast_ratio(str(cover["title_color"]), str(cover["background_color"]))
        if not title_present:
            results["cover"] = {
                "verdict": "fail", "pass": False,
                "detail": "last frame has no cover element (no title); it cannot serve as a cover",
                "method": "Cover-family contrast via design.cover_family.contrast_ratio; title presence declared by the caller.",
            }
        elif ratio is None:
            results["cover"] = {
                "verdict": "undetermined", "pass": None,
                "detail": "title present but no contrast figure supplied",
                "method": "Cover-family contrast via design.cover_family.contrast_ratio.",
            }
        elif ratio >= MIN_CONTRAST:
            results["cover"] = {
                "verdict": "pass", "pass": True, "contrast_ratio": round(ratio, 2),
                "detail": f"title present; contrast {ratio:.2f} >= {MIN_CONTRAST}",
                "method": "Cover-family contrast via design.cover_family.contrast_ratio.",
            }
        else:
            results["cover"] = {
                "verdict": "fail", "pass": False, "contrast_ratio": round(ratio, 2),
                "detail": f"title present but contrast {ratio:.2f} < {MIN_CONTRAST}",
                "method": "Cover-family contrast via design.cover_family.contrast_ratio.",
            }
    else:
        results["cover"] = {"verdict": "fail", "pass": False, "detail": "cover check missing"}

    failures = [name for name, item in results.items() if item["verdict"] == "fail"]
    undetermined = [name for name, item in results.items() if item["verdict"] == "undetermined"]
    verdict = "pass" if not failures and not undetermined else "fail"
    return {
        "ok": verdict == "pass",
        "checks": results,
        "failures": failures,
        "undetermined": undetermined,
        "verdict": verdict,
        "note": (
            "Undetermined checks are not passes. Phone legibility is an "
            "arithmetic projection, not a real-device viewing."
        ),
    }


def triage_top3(issues: Any) -> dict[str, Any]:
    """Keep only the 3 most severe issues on top; defer the rest, never drop them."""
    if not isinstance(issues, list):
        raise CapabilityError("pipeline.code_studio_workflow: issues must be a list")
    ranked: list[tuple[tuple, int, dict[str, Any]]] = []
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity", "low")).strip().lower()
        rank = _SEVERITY_RANK.get(severity, 4)
        when = issue.get("time_sec", issue.get("t_sec"))
        sort_time = float(when) if _is_num(when) else math.inf
        ranked.append(((rank, sort_time), index, issue))
    ranked.sort(key=lambda row: (row[0], row[1]))

    def _normalise(issue: dict[str, Any]) -> dict[str, Any]:
        when = issue.get("time_sec", issue.get("t_sec"))
        return {
            "severity": str(issue.get("severity", "low")),
            "time_sec": float(when) if _is_num(when) else None,
            "fix": issue.get("fix") or issue.get("action") or "",
            "description": issue.get("description") or issue.get("detail") or "",
            "issue": issue,
        }

    ordered = [_normalise(issue) for _, _, issue in ranked]
    return {
        "top3": ordered[:3],
        "deferred": ordered[3:],
        "total": len(ordered),
        "note": "Deferred issues are listed, not discarded; fix the top 3 first.",
    }


_FINALIZE_CATEGORIES: dict[str, dict[str, Any]] = {
    "brief": {"files": ["brief.json", "01_topic/brief.json"], "dirs": []},
    "style_note": {"files": ["style_note.json", "01_topic/style_note.json"], "dirs": []},
    "shot_table": {"files": ["shot_table.json", "02_script/shot_table.json"], "dirs": []},
    "assets": {"files": [], "dirs": ["assets", "00_reference"]},
    "source": {"files": [], "dirs": ["source", "03_edit"]},
    "checks": {"files": [], "dirs": ["checks", "07_review"]},
    "film": {"files": ["film.mp4", "output.mp4", "film/film.mp4"], "dirs": ["film"]},
}


def finalize_project_folder(root: Any) -> dict[str, Any]:
    """Check that a project folder holds all seven artefact kinds.

    The seven kinds are: brief, style note, shot table, real
    material, source code, check records, and the finished film.
    A missing kind is named; the folder is not called finalised
    while any kind is missing.
    """
    root_path = Path(root)
    present: dict[str, bool] = {}
    missing: list[str] = []
    for kind, spec in _FINALIZE_CATEGORIES.items():
        found = False
        for rel in spec["files"]:
            if (root_path / rel).is_file():
                found = True
                break
        if not found:
            for rel in spec["dirs"]:
                directory = root_path / rel
                if directory.is_dir() and any(p.is_file() for p in directory.rglob("*")):
                    found = True
                    break
        present[kind] = found
        if not found:
            missing.append(kind)
    return {
        "ok": not missing,
        "root": str(root_path),
        "present": present,
        "missing": missing,
        "categories": list(_FINALIZE_CATEGORIES.keys()),
    }


def resume_project(root: Any) -> dict[str, Any]:
    """Resume from a project folder: what is done, what is next, what is missing.

    The project_handoff manifest is read first when it exists; when
    there is no manifest, the folder structure itself is read and
    the report says the inference came from the folder, with
    confirmation status unknown.
    """
    root_path = Path(root)
    manifest_path = root_path / "manifest.json"
    steps: dict[int, dict[str, Any]] = {}
    manifest_present = manifest_path.is_file()
    handoff_done: list[str] = []
    if manifest_present:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {
                "ok": False, "root": str(root_path), "source": "manifest",
                "manifest_present": True, "steps": {},
                "completed_steps": [], "current_step": 1, "pending_step": 1,
                "missing": ["manifest.json is not readable JSON"],
                "reason": str(exc),
            }
        source = "manifest"
        workflow = data.get("code_studio_workflow") or {}
        recorded = workflow.get("steps") or {}
        if isinstance(data.get("stages"), dict):
            handoff_done = [s for s, entry in data["stages"].items()
                            if isinstance(entry, dict) and entry.get("status") == "done"]
        for step in range(1, 7):
            entry = recorded.get(str(step)) or recorded.get(step) or {}
            if isinstance(entry, dict) and entry:
                steps[step] = {
                    "status": entry.get("status", "pending"),
                    "confirmed": bool(entry.get("confirmed", False)),
                    "report_file": entry.get("report_file"),
                }
            else:
                steps[step] = {"status": "pending", "confirmed": False, "report_file": None}
    else:
        source = "folder_inference"
        inferred = {
            1: (root_path / "brief.json").is_file(),
            2: (root_path / "style_note.json").is_file(),
            3: (root_path / "shot_table.json").is_file(),
            4: (root_path / "beat_grid.json").is_file(),
            5: (root_path / "frame_report.json").is_file(),
            6: (root_path / "checks" / "review.json").is_file() or (root_path / "review.json").is_file(),
        }
        for step in range(1, 7):
            steps[step] = {
                "status": "inferred_present" if inferred[step] else "pending",
                "confirmed": False,
                "report_file": _STEP_ARTIFACTS[step] if inferred[step] else None,
                "note": "inferred from folder contents; confirmation status unknown",
            }
    completed = [s for s in range(1, 7)
                 if steps[s]["status"] in ("done", "inferred_present")]
    current = next((s for s in range(1, 7) if steps[s]["status"] != "done"), None)
    missing: list[str] = []
    if current is not None:
        artifact = _STEP_ARTIFACTS[current]
        if not (root_path / artifact).is_file():
            missing.append(artifact)
        if current == 6:
            missing.extend(f for f in finalize_project_folder(root_path)["missing"])
            missing = sorted(set(missing))
    return {
        "ok": True,
        "root": str(root_path),
        "source": source,
        "manifest_present": manifest_present,
        "handoff_stages_done": handoff_done,
        "steps": {str(k): v for k, v in steps.items()},
        "completed_steps": completed,
        "current_step": current,
        "pending_step": current,
        "missing": missing,
    }


# ---------------------------------------------------------------- orchestrator


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CapabilityError("pipeline.code_studio_workflow: manifest is not a JSON object")
    return data


def _save_manifest(root: Path, data: dict[str, Any]) -> None:
    (root / "manifest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_project(root: Path, title: str = "") -> dict[str, Any]:
    if not (root / "manifest.json").is_file():
        from hevi.capabilities.project_handoff import create_project

        data = create_project(root, title=title)
    else:
        data = _load_manifest(root)
    if "code_studio_workflow" not in data:
        data["code_studio_workflow"] = {"steps": {}}
        _save_manifest(root, data)
    return data


def _workflow_steps(root: Path) -> dict[str, Any]:
    data = _load_manifest(root)
    workflow = data.get("code_studio_workflow") or {}
    steps = workflow.get("steps") or {}
    return steps if isinstance(steps, dict) else {}


def _record_workflow_step(
    root: Path, step: int, status: str, confirmed: bool,
    report_file: str, problems: list[str],
) -> None:
    data = _load_manifest(root)
    workflow = data.setdefault("code_studio_workflow", {"steps": {}})
    steps = workflow.setdefault("steps", {})
    steps[str(step)] = {
        "status": status,
        "confirmed": confirmed,
        "report_file": report_file,
        "problems": list(problems),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_manifest(root, data)


def _step_confirmation(confirmation: Any, step: int) -> tuple[bool, str]:
    if isinstance(confirmation, dict) and "stage" in confirmation:
        try:
            from hevi.capabilities.stable_film_pipeline import check_confirmation

            result = check_confirmation(confirmation, f"step{step}")
            return bool(result["allowed"]), str(result["reason"])
        except Exception:
            pass
    return _strictly_confirmed(confirmation)


def _write_json(root: Path, rel: str, payload: dict[str, Any]) -> str:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return rel


def run_workflow_step(
    project_root: Any,
    step: Any,
    payload: Any = None,
    confirmation: Any = None,
) -> dict[str, Any]:
    """Run one workflow step, write its artefact, and stop at its gate.

    The previous step must be confirmed (strict ``True``) before
    this step runs; otherwise the call is refused and names the
    blocking step. A step whose validation passes but whose
    confirmation is not strictly ``True`` is recorded as
    ``awaiting_confirmation``, never as done. The single manifest
    is the ``pipeline.project_handoff`` manifest: this module
    appends its steps under ``code_studio_workflow.steps`` and,
    for completed steps only, records the mapped handoff stage
    with ``record_step``. No separate manifest is invented.
    """
    if not _is_num(step) or int(step) not in range(1, 7):
        raise CapabilityError(
            f"pipeline.code_studio_workflow: step must be 1-6, got {step!r}"
        )
    step = int(step)
    root = Path(project_root)
    root.mkdir(parents=True, exist_ok=True)
    payload = payload if isinstance(payload, dict) else {}
    title = ""
    brief_candidate = payload.get("brief") if isinstance(payload.get("brief"), dict) else payload
    if isinstance(brief_candidate, dict) and _nonempty_str(brief_candidate.get("title")):
        title = str(brief_candidate["title"])
    _ensure_project(root, title=title)

    recorded = _workflow_steps(root)
    for prev in range(1, step):
        entry = recorded.get(str(prev)) or {}
        if entry.get("status") != "done" or entry.get("confirmed") is not True:
            return {
                "ok": False, "step": step, "status": "blocked",
                "blocked_by": prev, "confirmed": False,
                "reason": (
                    f"step {prev} is not confirmed; confirm step {prev} "
                    "before step {step} may start"
                ),
                "report_file": None,
            }

    artifact_rel = _STEP_ARTIFACTS[step]
    report: dict[str, Any] = {}
    ok = False
    problems: list[str] = []
    extra_outputs: list[str] = []

    if step == 1:
        brief = payload.get("brief", payload)
        report = validate_brief(brief)
        ok, problems = report["ok"], report["problems"]
        _write_json(root, artifact_rel, {"brief": brief, "validation": report})
    elif step == 2:
        note = payload.get("style_note", payload)
        report = validate_style_note(note)
        ok, problems = report["ok"], report["problems"]
        _write_json(root, artifact_rel, {"style_note": note, "validation": report})
    elif step == 3:
        table = payload.get("shot_table") or payload.get("segments") or payload
        report = validate_shot_table(table)
        ok, problems = report["ok"], report["problems"]
        _write_json(root, artifact_rel, {"shot_table": table, "validation": report})
    elif step == 4:
        if not _is_num(payload.get("bpm")) or not _is_num(payload.get("duration_sec")):
            report = {"ok": False, "problems": ["bpm and duration_sec are required"],
                      "grid": None, "alignment": None}
            ok, problems = False, report["problems"]
        else:
            grid = build_beat_grid(
                payload["bpm"], payload.get("offset_sec", payload.get("offset", 0.0)),
                payload["duration_sec"], mode=payload.get("mode"))
            alignment = check_beat_alignment(
                payload.get("events", []), grid,
                tolerance=payload.get("tolerance", 0.05), mode=payload.get("mode"))
            report = {"grid": grid, "alignment": alignment, "ok": alignment["ok"],
                      "problems": alignment["problems"], "beat_basis": grid["beat_basis"]}
            ok, problems = alignment["ok"], alignment["problems"]
        _write_json(root, artifact_rel, report)
    elif step == 5:
        sub_reports: dict[str, Any] = {}
        layouts = payload.get("layouts")
        layout = payload.get("layout")
        if layouts is not None:
            sub_reports["no_hard_crop"] = check_no_hard_crop(layouts)
            if layout is None and isinstance(layouts, dict):
                layout = next(iter(layouts.values()), None)
        if layout is None:
            report = {"ok": False, "problems": ["layout or layouts is required"],
                      "checks": sub_reports}
            ok, problems = False, report["problems"]
        else:
            t_value = payload.get("t", payload.get("t_sec", 0.0))
            state = frame_state(t_value, layout)
            frame_rel = f"frames/frame_{float(t_value):.2f}.png"
            frame = render_single_frame(t_value, layout, out_path=root / frame_rel)
            extra_outputs.append(frame_rel)
            sub_reports["frame_state"] = state
            sub_reports["frame"] = {"sha256": frame["sha256"], "path": frame_rel,
                                    "size": frame["size"]}
            sub_reports["code_render_tiers"] = code_render_tier_status()
            if payload.get("moves") is not None:
                sub_reports["motion_weight"] = check_motion_weight(payload["moves"])
            if payload.get("eye_items") is not None or payload.get("segments") is not None:
                sub_reports["eye_landing"] = check_eye_landing(
                    payload.get("eye_items") or payload.get("segments"))
            feasibility = [classify_shot_feasibility(shot)
                           for shot in payload.get("shots", [])]
            sub_reports["feasibility"] = feasibility
            if payload.get("manim") is not None:
                sub_reports["manim"] = request_manim_render(
                    payload["manim"], payload.get("manim_renderer"))
                if isinstance(payload.get("manim"), dict) and payload["manim"].get("required") is True \
                        and not sub_reports["manim"]["rendered"]:
                    problems.append("manim: required but no manim_renderer was injected")
            rerender = payload.get("rerender")
            if isinstance(rerender, dict) and payload.get("rerender_render_fn") is not None:
                sub_reports["rerender"] = rerender_segments(
                    rerender.get("changed_ids", []),
                    rerender.get("previous_manifest"),
                    payload["rerender_render_fn"])
            if _nonempty_str(payload.get("source_code")):
                source_rel = "source/code_studio.py"
                source_path = root / source_rel
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(str(payload["source_code"]), encoding="utf-8")
                extra_outputs.append(source_rel)
            problems = list(sub_reports["no_hard_crop"]["problems"]) if "no_hard_crop" in sub_reports and not sub_reports["no_hard_crop"]["ok"] else []
            if "motion_weight" in sub_reports and not sub_reports["motion_weight"]["ok"]:
                problems.extend(sub_reports["motion_weight"]["problems"])
            if "eye_landing" in sub_reports and not sub_reports["eye_landing"]["ok"]:
                problems.extend(sub_reports["eye_landing"]["problems"])
            if any(not item["code_render_ok"] for item in feasibility):
                problems.append(
                    "feasibility: a shot is routed to live_or_video_model; "
                    "code rendering cannot cover it"
                )
            ok = not problems
            report = {"ok": ok, "problems": problems, "checks": sub_reports,
                      "frame_sha256": frame["sha256"]}
        _write_json(root, artifact_rel, report)
    else:  # step 6
        checks_payload = payload.get("checks") or payload.get("review") or payload
        review = review_contact_sheet(checks_payload)
        triage = triage_top3(payload.get("issues", []))
        sheet_info: dict[str, Any] | None = None
        if payload.get("frames") is not None:
            sheet = build_contact_sheet(
                payload["frames"], out_path=root / "checks" / "contact_sheet.png")
            sheet_info = {"sha256": sheet["sha256"], "path": "checks/contact_sheet.png",
                          "frame_count": sheet["frame_count"]}
            extra_outputs.append("checks/contact_sheet.png")
        _write_json(root, artifact_rel,
                    {"review": review, "triage": triage, "contact_sheet": sheet_info,
                     "finalize": None})
        finalize = finalize_project_folder(root)
        report = {"ok": review["ok"] and finalize["ok"],
                  "problems": (["review: " + f for f in review["failures"]]
                               + (["review undetermined: " + u for u in review["undetermined"]]
                                  if review["undetermined"] else [])
                               + (["finalize missing: " + m for m in finalize["missing"]]
                                  if finalize["missing"] else [])),
                  "review": review, "triage": triage,
                  "contact_sheet": sheet_info, "finalize": finalize}
        ok, problems = report["ok"], report["problems"]
        _write_json(root, artifact_rel, report)

    confirmed, conf_reason = _step_confirmation(confirmation, step)
    if ok and confirmed:
        status = "done"
    elif ok:
        status = "awaiting_confirmation"
    else:
        status = "failed"
    _record_workflow_step(root, step, status, bool(ok and confirmed), artifact_rel, problems)
    if status == "done":
        try:
            from hevi.capabilities.project_handoff import record_step

            outputs = [artifact_rel] + extra_outputs
            record_step(root, _STEP_STAGES[step], inputs=[], outputs=outputs,
                        checks=[{"step": step, "ok": True}], tool="pipeline.code_studio_workflow")
        except Exception:
            # The workflow manifest above is the record of truth; a
            # handoff-stage recording failure must not rewrite the
            # step's own confirmed status.
            pass
    return {
        "ok": bool(ok and confirmed),
        "step": step,
        "status": status,
        "confirmed": bool(ok and confirmed),
        "confirmation_reason": conf_reason if not confirmed else "",
        "report": report,
        "report_file": artifact_rel,
        "blocked_by": None,
    }


def workflow_status(project_root: Any) -> dict[str, Any]:
    """Return the status of all six steps for a project root."""
    root = Path(project_root)
    steps: dict[str, dict[str, Any]] = {}
    source = "none"
    if (root / "manifest.json").is_file():
        try:
            recorded = _workflow_steps(root)
            source = "manifest"
        except Exception:
            recorded = {}
            source = "manifest_unreadable"
        for step in range(1, 7):
            entry = recorded.get(str(step)) or {}
            steps[str(step)] = {
                "status": entry.get("status", "pending"),
                "confirmed": bool(entry.get("confirmed", False)),
                "report_file": entry.get("report_file"),
            }
    else:
        for step in range(1, 7):
            steps[str(step)] = {"status": "pending", "confirmed": False, "report_file": None}
    done = [int(s) for s, entry in steps.items() if entry["status"] == "done"]
    current = next((s for s in range(1, 7) if steps[str(s)]["status"] != "done"), None)
    return {
        "project_root": str(root),
        "source": source,
        "steps": steps,
        "done_steps": done,
        "current_step": current,
        "pending_step": current,
    }


# ---------------------------------------------------------------- registry


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = params.get("action", "step")
    if action == "status":
        result = workflow_status(params["project_root"])
    else:
        result = run_workflow_step(
            params["project_root"], params["step"],
            payload=params.get("payload", {}),
            confirmation=params.get("confirmation"),
        )
    report_path = out_dir / "code_studio_workflow.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "ok": bool(result.get("ok")),
            "step": result.get("step")},
    )


def register_code_studio_workflow_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.code_studio_workflow",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "step": {"type": "integer", "minimum": 1, "maximum": 6},
                    "payload": {"type": "object"},
                    "confirmation": {},
                    "action": {"type": "string"},
                },
                "required": ["project_root", "step"],
                "additionalProperties": True,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Code-studio workflow: six gated steps (brief, style "
                "note, shot table, beat grid, code rendering checks, "
                "contact-sheet review and filing), each stopping at a "
                "strict confirmation point. Plans and checks only; no "
                "generation model is called and no whole film is rendered."
            ),
            line="pipeline",
            has_media_output=False,
        )
    )
    return ["pipeline.code_studio_workflow"]


register_code_studio_workflow_capabilities_once()
