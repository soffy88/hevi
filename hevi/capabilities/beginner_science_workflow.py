"""Beginner science-film workflow (``pipeline.beginner_science_workflow``).

Clean-room rewrite of a method only: a seven-column script table
that lets a beginner produce a short science explainer in one or
two hours by handing the table to code-rendered motion, checking
a short sample first, and only then running the rest. No wording,
prompt text, or table text was copied from the forwarded essay;
only the working method was taken: one spoken sentence per row,
timing filled in from measured narration, a source per science
claim, a real file path per material, pause marks in the
narration, a short sample before the full run, A-roll/B-roll
alternation, named motion templates, and music that lands on
section changes rather than inside sentences.

What this module is and is not:

* It is a method and gate layer only. It calls no text-to-speech
  service and no video model. Narration text with pause marks is
  produced for the existing LuxTTS route; a MiniMax voice route
  does not exist here (no key) and is recorded as pending, never
  claimed as connected.
* It does not generate people. A-roll transition styles (green
  screen keying, paper-cut parts, a virtual presenter) are
  recorded as method notes only; no face, voice, or footage is
  produced by this module.
* Timing discipline mirrors ``pipeline.code_studio_workflow``
  step 3 (rows tile the timeline, no overlap, no unnamed gap).
  This module only adds the seven columns and the source and
  material gates; it does not re-implement the shot-table gate.
* Sample confirmation reuses the strict-``True`` semantics of
  ``pipeline.spend_brake``: the string ``"true"``, ``1``, and a
  missing field are not confirmation.
* Music alignment reuses the planned beat grid of
  ``pipeline.code_studio_workflow`` (``build_beat_grid`` /
  ``check_beat_alignment``); a grid is planned, not measured
  from audio, unless the caller supplies measured beat points.
* Motion/transition checks reuse ``video.motion_beat_chart``
  (``gate_chart``) unchanged.
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

# Pause ranges, in seconds. Intra-sentence breaths are short;
# between-sentence breaths are longer. Out-of-range marks are
# warnings, not failures: a human ear decides the final breath.
INTRA_PAUSE_RANGE = (0.1, 0.2)
INTER_PAUSE_RANGE = (0.3, 0.4)

# A run of code-motion (B-roll) rows longer than this needs an
# A-roll transition prompt. Configurable by the caller.
DEFAULT_MAX_CONSECUTIVE_B = 3

# Inline pause marks accepted inside narration text, e.g.
# "[pause=0.15]". They are data, not prose: they are stripped
# from the sentence count but kept in the narration segment.
_PAUSE_MARK_RE = re.compile(r"\[pause\s*=\s*([0-9]*\.?[0-9]+)\]")
_SENTENCE_END_RE = re.compile(r"[。！？!?]+")
_EMOTION_SEPARATORS = (",", "、", "/", "＋", "+", "转", "->", "→")

# Motion templates. Only the two rows marked "integrated" are
# backed by a capability verified in this repository; the rest
# are selection references only and must never be reported as
# connected. Counts below are the counts measured in this
# session for the integrated rows; reference rows carry no count.
_TEMPLATE_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "name": "lemo-opuscar",
        "source": "lemomo-ai/lemo-opuscar",
        "hevi_capability": "image.lemo_styles",
        "status": "integrated",
        "note": "Style list is read live from STYLE.md files; 59 styles counted in this session.",
    },
    {
        "name": "handraw-style",
        "source": "yang0/handraw-style",
        "hevi_capability": "image.handraw_styles",
        "status": "integrated",
        "note": "Numbered prompt library; 365 styles per the library index.",
    },
    {
        "name": "eian-riso-broll",
        "source": "reference only",
        "hevi_capability": None,
        "status": "reference_only",
        "note": "Selection reference only; no capability in this repository is wired to it.",
    },
    {
        "name": "mg-styles-15",
        "source": "Vincentwei1021/mg-styles-15",
        "hevi_capability": None,
        "status": "reference_only",
        "note": "Selection reference only; not connected in this repository.",
    },
    {
        "name": "vox-director",
        "source": "Alisa0808/vox-director",
        "hevi_capability": None,
        "status": "reference_only",
        "note": "Selection reference only; not connected in this repository.",
    },
    {
        "name": "sweety-handdraw-video",
        "source": "threerocks/sweety-handdraw-video",
        "hevi_capability": None,
        "status": "reference_only",
        "note": "Selection reference only; not connected in this repository.",
    },
)

_A_ROLL_TRANSITIONS = (
    "green_screen_keying",
    "paper_cut_parts",
    "virtual_presenter",
)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _rows_of(table: Any) -> list[Any] | None:
    if isinstance(table, dict):
        rows = table.get("rows") or table.get("segments") or table.get("shots")
        return rows if isinstance(rows, list) else None
    if isinstance(table, list):
        return table
    return None


def parse_pause_marks(text: str) -> list[dict[str, Any]]:
    """Extract inline ``[pause=0.15]`` marks from narration text."""
    marks = []
    for match in _PAUSE_MARK_RE.finditer(text or ""):
        marks.append({"seconds": float(match.group(1)), "raw": match.group(0)})
    return marks


def _sentence_count(narration: str) -> int:
    stripped = _PAUSE_MARK_RE.sub("", narration)
    endings = _SENTENCE_END_RE.findall(stripped)
    if not stripped.strip():
        return 0
    # One sentence may end without a final mark; a second mark
    # means a second sentence is packed into the same row.
    return max(1, len(endings)) if endings else 1


def check_pause_marks(
    pauses: Any, narration: str = ""
) -> list[str]:
    """Warn on pause marks outside the intra/inter ranges.

    ``pauses`` is a list of ``{"kind": ..., "seconds": ...}`` with
    kind ``intra_sentence`` or ``between_sentences``. Inline
    ``[pause=...]`` marks in the narration are treated as
    intra-sentence breaths.
    """
    warnings: list[str] = []
    entries: list[dict[str, Any]] = []
    if isinstance(pauses, list):
        entries.extend(p for p in pauses if isinstance(p, dict))
    for mark in parse_pause_marks(narration or ""):
        entries.append({"kind": "intra_sentence", "seconds": mark["seconds"]})
    for entry in entries:
        kind = entry.get("kind")
        seconds = entry.get("seconds")
        if kind not in ("intra_sentence", "between_sentences"):
            warnings.append(f"pause kind {kind!r} is not intra_sentence or between_sentences")
            continue
        if not _is_num(seconds):
            warnings.append(f"pause {kind} needs numeric seconds, got {seconds!r}")
            continue
        low, high = INTRA_PAUSE_RANGE if kind == "intra_sentence" else INTER_PAUSE_RANGE
        if not low <= float(seconds) <= high:
            warnings.append(
                f"pause {kind} {seconds}s is outside {low}-{high}s; "
                "a human ear decides the final breath"
            )
    return warnings


def _material_paths(row: dict[str, Any]) -> list[str]:
    raw = row.get("material") or row.get("materials") or row.get("material_paths")
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(p) for p in raw if _nonempty_str(p)]
    return []


def _resolve_material(path_text: str, project_root: Path | None) -> Path:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path
    if project_root is not None:
        return Path(project_root) / path
    return path


def validate_seven_column_table(
    table: Any, *, project_root: Any = None
) -> dict[str, Any]:
    """Validate the seven-column script table.

    Columns per row: time (start/end), narration (one sentence),
    emotion/breath, picture, motion, source, material. Timing
    basis is table-wide: every row ``estimated`` (draft) or every
    row ``measured`` (filled in after real narration); mixing the
    two fails. A science row without a source is marked
    ``unverified`` and blocks broadcast. A material path that
    does not exist fails; without a project root, material
    existence is ``unchecked`` and the table fails loudly rather
    than pretending the files exist.
    """
    problems: list[str] = []
    warnings: list[str] = []
    rows = _rows_of(table)
    if not rows:
        return {
            "ok": False,
            "problems": ["seven_column_table: a non-empty rows list is required"],
            "warnings": [],
            "rows_checked": 0,
            "timing_basis": None,
            "unverified_rows": [],
            "missing_materials": [],
            "material_status": "unchecked",
            "broadcast_blocked": True,
            "rows": [],
        }
    root = Path(project_root) if project_root is not None else None
    bases: set[str] = set()
    unverified: list[dict[str, Any]] = []
    missing_materials: list[dict[str, Any]] = []
    material_status = "checked" if root is not None else "unchecked"
    checked_rows: list[dict[str, Any]] = []
    prev_end: float | None = None
    eps = 1e-6
    for index, row in enumerate(rows):
        label = f"rows[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label}: row must be an object")
            continue
        row_id = row.get("id") or row.get("row_id") or f"row_{index}"
        start = row.get("start_sec", row.get("start"))
        end = row.get("end_sec", row.get("end"))
        if not _is_num(start) or not _is_num(end):
            problems.append(f"{label} ({row_id}): start_sec and end_sec must be numbers")
            continue
        start_f, end_f = float(start), float(end)
        if not start_f < end_f:
            problems.append(f"{label} ({row_id}): start_sec must be before end_sec")
        if index == 0 and abs(start_f) > eps:
            problems.append(
                f"{label} ({row_id}): the first row must start at 0, got {start_f}"
            )
        if prev_end is not None:
            if start_f < prev_end - eps:
                problems.append(
                    f"{label} ({row_id}): overlaps the previous row "
                    f"(starts {start_f}, previous ends {prev_end})"
                )
            elif start_f > prev_end + eps:
                intent = row.get("gap_intent") or row.get("gap_reason")
                if not _nonempty_str(intent):
                    problems.append(
                        f"{label} ({row_id}): gap from {prev_end} to {start_f} "
                        "with no stated intent; name the intent or close the gap"
                    )
        prev_end = end_f

        basis = row.get("timing_basis") or row.get("time_basis")
        if basis in ("estimated", "measured"):
            bases.add(basis)
        else:
            problems.append(
                f"{label} ({row_id}): timing_basis must be 'estimated' or 'measured', "
                f"got {basis!r}"
            )

        narration = row.get("narration") or row.get("voiceover") or ""
        if not _nonempty_str(narration):
            problems.append(f"{label} ({row_id}): narration (one spoken sentence) is required")
        elif _sentence_count(str(narration)) > 1:
            problems.append(
                f"{label} ({row_id}): narration holds more than one sentence; "
                "one row is one spoken sentence"
            )

        emotion = row.get("emotion") or row.get("mood") or ""
        if _nonempty_str(emotion):
            if any(sep in str(emotion) for sep in _EMOTION_SEPARATORS):
                problems.append(
                    f"{label} ({row_id}): emotion must be a single label, "
                    f"got {emotion!r}; one segment keeps one emotion"
                )

        if not _nonempty_str(row.get("picture") or row.get("visual")):
            problems.append(f"{label} ({row_id}): picture is required")
        if not _nonempty_str(row.get("motion") or row.get("effect")):
            problems.append(f"{label} ({row_id}): motion is required")

        source = row.get("source") or row.get("information_source") or ""
        if not _nonempty_str(source):
            unverified.append({"row_id": row_id, "reason": "no information source"})
        roll = row.get("roll") or row.get("shot_type")
        if roll not in ("A", "B"):
            problems.append(
                f"{label} ({row_id}): roll must be 'A' (transition) or 'B' (code-motion explainer), "
                f"got {roll!r}"
            )

        for path_text in _material_paths(row):
            resolved = _resolve_material(path_text, root)
            if root is None:
                problems.append(
                    f"{label} ({row_id}): material existence is unchecked "
                    "(no project_root supplied); supply a project root so "
                    f"{path_text!r} can be verified"
                )
            elif not resolved.exists():
                missing_materials.append({"row_id": row_id, "path": path_text})
                problems.append(
                    f"{label} ({row_id}): material file does not exist: {path_text}"
                )

        warnings.extend(
            f"{label} ({row_id}): {w}"
            for w in check_pause_marks(row.get("pauses"), str(narration))
        )
        checked_rows.append({
            "row_id": row_id,
            "start_sec": start_f,
            "end_sec": end_f,
            "timing_basis": basis,
            "narration": narration,
            "emotion": emotion,
            "picture": row.get("picture") or row.get("visual"),
            "motion": row.get("motion") or row.get("effect"),
            "source": source,
            "material": _material_paths(row),
            "roll": roll,
            "status": "unverified" if not _nonempty_str(source) else "sourced",
        })

    timing_basis = None
    if len(bases) == 1:
        timing_basis = next(iter(bases))
    elif len(bases) > 1:
        problems.append(
            "timing_basis: estimated (draft) and measured (post-narration) "
            "rows are mixed in one table; fill every row from measured "
            "narration before production"
        )
    if unverified:
        problems.append(
            "source: rows without an information source are unverified "
            "and must not be broadcast as fact: "
            + ", ".join(r["row_id"] for r in unverified)
        )
    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "rows_checked": len(checked_rows),
        "timing_basis": timing_basis,
        "unverified_rows": unverified,
        "missing_materials": missing_materials,
        "material_status": material_status,
        "broadcast_blocked": bool(problems),
        "rows": checked_rows,
    }


def build_narration_segments(
    table: Any, *, max_rows_per_segment: int = 3, project_root: Any = None
) -> dict[str, Any]:
    """Group validated rows into 2-3 sentence narration segments.

    A segment never mixes emotions: an emotion change forces a
    segment break. Each segment lists its rows so a single row
    can be re-synthesised and replaced without re-running the
    rest. No audio is produced here; the segments are the
    pause-marked script for the existing LuxTTS route.
    """
    report = validate_seven_column_table(table, project_root=project_root)
    if not report["ok"]:
        return {
            "ok": False,
            "problems": report["problems"],
            "warnings": report["warnings"],
            "segments": [],
            "tts_status": "not_connected",
            "tts_note": (
                "No text-to-speech service is called here. Segments are "
                "pause-marked narration scripts for the existing LuxTTS "
                "route; a MiniMax voice route is pending a key and is "
                "not claimed as connected."
            ),
        }
    if not 1 <= int(max_rows_per_segment) <= 3:
        raise CapabilityError(
            "pipeline.beginner_science_workflow: max_rows_per_segment must be 1-3"
        )
    segments: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_emotion: str | None = None
    for row in report["rows"]:
        emotion = str(row.get("emotion") or "").strip()
        if current and emotion and current_emotion and emotion != current_emotion:
            segments.append(current)
            current, current_emotion = [], None
        if current and len(current) >= int(max_rows_per_segment):
            segments.append(current)
            current, current_emotion = [], None
        current.append(row)
        if emotion:
            current_emotion = emotion
    if current:
        segments.append(current)
    built = []
    for index, group in enumerate(segments):
        built.append({
            "segment_id": f"narration_seg_{index + 1}",
            "row_ids": [r["row_id"] for r in group],
            "emotion": group[0].get("emotion") or "",
            "text": " ".join(str(r["narration"]).strip() for r in group),
            "start_sec": group[0]["start_sec"],
            "end_sec": group[-1]["end_sec"],
            "single_row_replaceable": True,
        })
    return {
        "ok": True,
        "problems": [],
        "warnings": report["warnings"],
        "segments": built,
        "segment_count": len(built),
        "tts_status": "not_connected",
        "tts_note": (
            "No text-to-speech service is called here. Segments are "
            "pause-marked narration scripts for the existing LuxTTS "
            "route; a MiniMax voice route is pending a key and is "
            "not claimed as connected."
        ),
    }


def regenerate_row(
    table: Any, row_id: str, *, new_narration: str, project_root: Any = None
) -> dict[str, Any]:
    """Replace one row's narration and rebuild only its segment.

    Only the named row changes; every other row keeps its text,
    timing, and material. The rebuilt narration segments are
    returned so the caller can re-synthesise that segment alone.
    """
    rows = _rows_of(table)
    if not isinstance(rows, list):
        raise CapabilityError("pipeline.beginner_science_workflow: table rows are required")
    replaced = False
    new_rows = []
    for row in rows:
        if isinstance(row, dict) and (row.get("id") or row.get("row_id")) == row_id:
            updated = dict(row)
            updated["narration"] = new_narration
            new_rows.append(updated)
            replaced = True
        else:
            new_rows.append(row)
    if not replaced:
        raise CapabilityError(
            f"pipeline.beginner_science_workflow: no row with id {row_id!r}"
        )
    result = build_narration_segments(new_rows, project_root=project_root)
    result["replaced_row_id"] = row_id
    result["unchanged_row_ids"] = [
        r.get("id") or r.get("row_id")
        for r in rows
        if (r.get("id") or r.get("row_id")) != row_id
    ]
    return result


def gate_sample_first(
    table: Any, *, confirmed: Any, project_root: Any = None, sample_rows: int = 3
) -> dict[str, Any]:
    """Sample-first gate: the first 2-3 rows must pass and be confirmed.

    The full table must never start in one batch. The three
    human checks (picture/audio alignment, transitions, template
    style) are recorded as requiring human confirmation; this
    gate never claims a machine checked them.
    """
    blockers: list[str] = []
    rows = _rows_of(table)
    if not rows:
        blockers.append("sample: the table has no rows to sample")
        return {"allowed": False, "blockers": blockers, "sample": {}, "sample_checks": {}}
    count = max(1, min(int(sample_rows), len(rows), 3))
    sample = {"rows": list(rows[:count])}
    report = validate_seven_column_table(sample, project_root=project_root)
    if not report["ok"]:
        blockers.extend(report["problems"])
    if confirmed is not True:
        blockers.append(
            "confirmed: no machine-readable confirmation (confirmed=true "
            "required); a missing field, the string 'true', or 1 is not "
            "confirmation, so the rest of the table is refused"
        )
    sample_checks = {
        "picture_audio_alignment": "requires_human_confirmation",
        "transition_smoothness": "requires_human_confirmation",
        "template_style": "requires_human_confirmation",
    }
    return {
        "allowed": not blockers,
        "blockers": blockers,
        "sample": {
            "row_ids": [r["row_id"] for r in report["rows"]],
            "rows_checked": report["rows_checked"],
            "table_ok": report["ok"],
        },
        "sample_checks": sample_checks,
        "note": (
            "Sample checks are human checks. This gate records that "
            "they still need a person; it never reports them passed."
        ),
    }


def gate_full_production(
    table: Any, *, sample_confirmed: Any, project_root: Any = None
) -> dict[str, Any]:
    """Refuse the full run unless the sample was confirmed."""
    blockers: list[str] = []
    if sample_confirmed is not True:
        blockers.append(
            "sample_confirmed: the 2-3 row sample was not confirmed "
            "(confirmed=true required); the full table must not start"
        )
    report = validate_seven_column_table(table, project_root=project_root)
    if not report["ok"]:
        blockers.extend(report["problems"])
    return {
        "allowed": not blockers,
        "blockers": blockers,
        "table": {
            "rows_checked": report["rows_checked"],
            "ok": report["ok"],
            "timing_basis": report["timing_basis"],
        },
    }


def check_roll_pattern(
    table: Any, *, max_consecutive_b: int = DEFAULT_MAX_CONSECUTIVE_B
) -> dict[str, Any]:
    """Flag runs of B-roll rows that need an A-roll transition.

    Code-motion explainer rows (B) carry the film; A-roll rows
    are transitions only. A run longer than the threshold gets a
    transition prompt, not a failure: the human decides where
    the transition lands.
    """
    rows = _rows_of(table) or []
    rolls = [r.get("roll") if isinstance(r, dict) else None for r in rows]
    prompts: list[dict[str, Any]] = []
    run = 0
    for index, roll in enumerate(rolls):
        if roll == "B":
            run += 1
            if run > int(max_consecutive_b):
                prompts.append({
                    "after_row_index": index,
                    "after_row_id": rows[index].get("id") or rows[index].get("row_id"),
                    "consecutive_b": run,
                    "suggestion": "insert an A-roll transition here",
                })
        else:
            run = 0
    return {
        "rolls": rolls,
        "max_consecutive_b": int(max_consecutive_b),
        "transition_prompts": prompts,
        "needs_transition": bool(prompts),
    }


def check_motion_chart(chart: Any) -> dict[str, Any]:
    """Run transition/rhythm checks through video.motion_beat_chart."""
    from hevi.capabilities.motion_beat_chart import gate_chart

    report = gate_chart(chart)
    return {"ok": report["verdict"] == "pass", "chart_report": report}


def list_templates() -> list[dict[str, Any]]:
    """List motion templates with honest connection status."""
    entries = []
    lemo_count = None
    handraw_count = None
    try:
        from hevi.capabilities.lemo_styles import list_lemo_styles

        lemo_count = len(list_lemo_styles())
    except Exception:
        lemo_count = None
    try:
        from hevi.image import handraw_style

        index = handraw_style.load_index()
        counts = index.get("counts") or {}
        handraw_count = counts.get("styles")
    except Exception:
        handraw_count = None
    for entry in _TEMPLATE_REGISTRY:
        item = dict(entry)
        if entry["name"] == "lemo-opuscar":
            item["verified_count"] = lemo_count
            item["count_status"] = "verified" if lemo_count is not None else "unverified"
        elif entry["name"] == "handraw-style":
            item["verified_count"] = handraw_count
            item["count_status"] = "verified" if handraw_count is not None else "unverified"
        else:
            item["verified_count"] = None
            item["count_status"] = "not_connected"
        entries.append(item)
    return entries


def check_template_use(
    template_name: str, *, customized: Any = None, changes: Any = None
) -> dict[str, Any]:
    """Record a template choice; direct reuse without changes warns."""
    warnings: list[str] = []
    match = next((t for t in _TEMPLATE_REGISTRY if t["name"] == template_name), None)
    if match is None:
        return {
            "ok": False,
            "problems": [f"template {template_name!r} is not in the template registry"],
            "warnings": warnings,
            "template": None,
        }
    if match["status"] != "integrated":
        warnings.append(
            f"template {template_name!r} is reference_only in this repository; "
            "it is a selection reference, not a connected capability"
        )
    changed = bool(customized is True) or (
        isinstance(changes, list) and len(changes) > 0
    )
    if not changed:
        warnings.append(
            f"template {template_name!r} used without recorded changes "
            "(colour, transition, or small animation); direct reuse "
            "is recorded as a warning, not as a finished style"
        )
    return {
        "ok": True,
        "problems": [],
        "warnings": warnings,
        "template": dict(match),
        "customized": changed,
        "changes": changes if isinstance(changes, list) else [],
    }


def record_style_analysis(
    source_name: str, *, analysis_notes: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Record a style analysis as method notes only.

    Copying another creator's text, prompts, or material is
    refused here: any ``copied_text`` or ``copied_material``
    argument that is non-empty fails the record.
    """
    problems: list[str] = []
    if not _nonempty_str(source_name):
        problems.append("style_analysis: source_name is required")
    if not _nonempty_str(analysis_notes):
        problems.append("style_analysis: analysis_notes are required; name what was learned")
    for key in ("copied_text", "copied_material", "copied_prompt"):
        if _nonempty_str(kwargs.get(key)):
            problems.append(
                f"style_analysis: {key} must stay empty; analyse the style, "
                "then write your own skill and material"
            )
    return {
        "ok": not problems,
        "problems": problems,
        "record": {
            "source_name": source_name,
            "analysis_notes": analysis_notes,
            "method_only": True,
            "note": (
                "Method notes only. No text, prompt, or material from "
                "the source was copied into this record."
            ),
        },
    }


def check_music_alignment(
    events: Any, grid: Any, *, tolerance: float = 0.05
) -> dict[str, Any]:
    """Music must land on section changes, never inside a sentence.

    Events carry ``kind`` (``section_change`` / ``emotion_rise`` /
    ``cut``) and ``time_sec``. An event of kind ``mid_sentence``
    fails outright; the remaining events are checked against the
    planned beat grid by ``pipeline.code_studio_workflow``.
    """
    from hevi.capabilities.pure_helpers import check_beat_alignment

    problems: list[str] = []
    beat_events: list[dict[str, Any]] = []
    if not isinstance(events, list) or not events:
        problems.append("music_alignment: a non-empty events list is required")
        events = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            problems.append(f"events[{index}]: event must be an object")
            continue
        kind = event.get("kind")
        if kind == "mid_sentence":
            problems.append(
                f"events[{index}]: music must not land inside a sentence; "
                "move the cue to a section change or an emotion rise"
            )
            continue
        if kind not in ("section_change", "emotion_rise", "cut"):
            problems.append(
                f"events[{index}]: kind must be section_change, emotion_rise, or cut, "
                f"got {kind!r}"
            )
            continue
        beat_events.append(event)
    grid_report = check_beat_alignment(beat_events, grid, tolerance=tolerance)
    problems.extend(grid_report.get("problems", []))
    return {
        "ok": not problems,
        "problems": problems,
        "events_checked": len(beat_events),
        "beat_basis": grid_report.get("beat_basis", "planned_not_measured"),
        "grid_report": grid_report,
        "note": (
            "Beat points are planned from the declared BPM unless the "
            "caller supplies measured points; no audio was analysed here."
        ),
    }


def a_roll_transition_methods() -> list[dict[str, Any]]:
    """Method notes for the three A-roll transition styles.

    No person, footage, or keying is produced; these are records
    of how a transition may be made by the caller.
    """
    return [
        {
            "method": "green_screen_keying",
            "note": "Keyed presenter footage used as a transition; no footage is generated here.",
        },
        {
            "method": "paper_cut_parts",
            "note": "A character split into swappable parts, one frame at a time, as a short transition.",
        },
        {
            "method": "virtual_presenter",
            "note": "The creator's own virtual presenter used as a transition; only the creator's own likeness.",
        },
    ]


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    action = params.get("action", "validate_table")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if action == "validate_table":
        result: dict[str, Any] = {
            "action": action,
            "report": validate_seven_column_table(
                params.get("table"), project_root=params.get("project_root")
            ),
        }
    elif action == "narration_segments":
        result = {
            "action": action,
            "report": build_narration_segments(
                params.get("table"),
                max_rows_per_segment=int(params.get("max_rows_per_segment", 3)),
                project_root=params.get("project_root"),
            ),
        }
    elif action == "sample_gate":
        result = {
            "action": action,
            "report": gate_sample_first(
                params.get("table"),
                confirmed=params.get("confirmed"),
                project_root=params.get("project_root"),
            ),
        }
    elif action == "full_gate":
        result = {
            "action": action,
            "report": gate_full_production(
                params.get("table"),
                sample_confirmed=params.get("sample_confirmed"),
                project_root=params.get("project_root"),
            ),
        }
    elif action == "templates":
        result = {"action": action, "templates": list_templates()}
    elif action == "music_alignment":
        result = {
            "action": action,
            "report": check_music_alignment(
                params.get("events"), params.get("grid"),
                tolerance=float(params.get("tolerance", 0.05)),
            ),
        }
    else:
        raise CapabilityError(
            f"pipeline.beginner_science_workflow: unknown action {action!r}; "
            "known: validate_table, narration_segments, sample_gate, "
            "full_gate, templates, music_alignment"
        )
    report_path = out_dir / "beginner_science_workflow_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path)},
    )


def register_beginner_science_workflow_capabilities_once() -> list[str]:
    """Register pipeline.beginner_science_workflow exactly once."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.beginner_science_workflow",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "table": {"type": "object"},
                    "project_root": {"type": "string"},
                    "confirmed": {"type": "boolean"},
                    "sample_confirmed": {"type": "boolean"},
                    "max_rows_per_segment": {"type": "integer"},
                    "events": {"type": "array"},
                    "grid": {"type": "object"},
                    "tolerance": {"type": "number"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Beginner science-film workflow (method and gates only): "
                "seven-column script table with one sentence per row, "
                "timing filled in from measured narration, a source per "
                "claim, real material paths, pause-marked narration "
                "segments for the existing LuxTTS route, a 2-3 row "
                "sample gate before the full run, A/B roll discipline, "
                "a template registry that reports unconnected templates "
                "as reference-only, and music cues on section changes. "
                "No TTS or video service is called; MiniMax, green-"
                "screen footage, and video-model generation are not "
                "connected. Report only; never generates media."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.beginner_science_workflow"]


register_beginner_science_workflow_capabilities_once()
