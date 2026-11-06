"""Dance MV pack-format gate (``qa.dance_mv_pack_format_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): one film, one
complete document. The pack opens with its title and
revision, then runs nine sections in order — revision
history, overall direction, picture responsibilities,
visual bible, audio index, copy-ready prompts,
transition map, pre-generation checklist, and
post-generation review. Every segment carries its own
frame: number, global time, local length, audio file,
and a complete prompt whose internal structure runs
from subject definitions through the action and camera
timeline to the end state and the two soundscape
declarations. The transition table covers every
boundary between neighbours. No segment may point back
with "same as above" — each one must be copyable on its
own. This gate judges the pack record only. It writes
nothing to disk beyond its report, renders nothing, and
spends nothing: ``executed_here`` is always false.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.scene_reference import H3_SECTIONS

_Registered = False

# The nine sections, in order. Title and revision sit
# above them as header metadata, not as sections.
NINE_SECTIONS: tuple[str, ...] = (
    "revision_history",
    "overall_direction",
    "picture_responsibilities",
    "visual_bible",
    "audio_index",
    "h3_prompts",
    "transition_map",
    "preflight_checklist",
    "post_review",
)

# The internal structure of one copy-ready H3 prompt.
PROMPT_INTERNAL: tuple[str, ...] = (
    "subject_definitions",
    "reference_roles",
    "global_continuity",
    "music_rules",
    "directing_concept",
    "action_camera_timeline",
    "end_state",
    "overall_soundscape",
    "non_diegetic_music",
)
TIMECODE_RE = re.compile(r"^\d{2}:\d{2}\.\d{3}$")
CROSS_REFERENCES: tuple[str, ...] = ("same as above", "as above", "同上")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _has_cross_reference(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CROSS_REFERENCES)


def check_dance_mv_pack(pack: Any) -> dict[str, Any]:
    """Validate one complete dance MV prompt pack.

    Verdicts are ``pass`` / ``fail`` only. The pack fails
    when its title or revision is missing, when its nine
    sections are missing or out of order, when any segment
    lacks its frame or its complete prompt, when any
    prompt points back at another segment, or when the
    transition table does not cover every boundary.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(pack, dict):
        return fail("pack_not_object", "prompt pack must be a JSON object")
    if not isinstance(pack.get("title"), str) or not pack["title"].strip():
        return fail("title_missing", "pack must carry its title")
    if not isinstance(pack.get("revision"), str) or not pack["revision"].strip():
        return fail("revision_missing", "pack must carry its revision")
    sections = pack.get("sections")
    if not isinstance(sections, list) or list(sections) != list(NINE_SECTIONS):
        return fail(
            "format_sections_wrong",
            "pack must carry the nine sections in order",
        )
    segments = pack.get("segments")
    if not isinstance(segments, list) or not segments:
        return fail("segments_missing", "pack must carry at least one segment")
    segment_ids: list[str] = []
    for position, segment in enumerate(segments):
        if not isinstance(segment, dict):
            return fail(
                "segment_not_object",
                f"segment {position} must be an object",
            )
        segment_id = segment.get("id")
        if not isinstance(segment_id, str) or not segment_id.strip():
            return fail(
                "segment_id_missing",
                f"segment {position} must carry its id",
            )
        segment_ids.append(segment_id)
        for field in ("global_start", "global_end"):
            value = segment.get(field)
            if not isinstance(value, str) or not TIMECODE_RE.match(value):
                return fail(
                    "segment_timecode_wrong",
                    f"segment {position} {field} must read MM:SS.mmm",
                )
        duration = segment.get("local_duration_s")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            return fail(
                "segment_duration_missing",
                f"segment {position} must state its local duration",
            )
        if duration <= 0:
            return fail(
                "segment_duration_not_positive",
                f"segment {position} duration must be positive",
            )
        if not isinstance(segment.get("audio_file"), str) or not segment["audio_file"].strip():
            return fail(
                "segment_audio_missing",
                f"segment {position} must name its audio file",
            )
        prompt = segment.get("h3_prompt")
        if not isinstance(prompt, dict):
            return fail(
                "segment_prompt_missing",
                f"segment {position} must carry its complete prompt",
            )
        prompt_sections = prompt.get("sections")
        if not isinstance(prompt_sections, dict):
            return fail(
                "prompt_sections_missing",
                f"segment {position} prompt must carry its six sections",
            )
        if set(prompt_sections) != set(H3_SECTIONS):
            return fail(
                "prompt_sections_not_six",
                f"segment {position} prompt sections must be exactly the six house sections",
            )
        internal = prompt.get("internal")
        if not isinstance(internal, dict):
            return fail(
                "prompt_internal_missing",
                f"segment {position} prompt must carry its internal structure",
            )
        for key in PROMPT_INTERNAL:
            value = internal.get(key)
            if not isinstance(value, str) or not value.strip():
                return fail(
                    "prompt_internal_missing",
                    f"segment {position} prompt is missing {key}",
                )
            if _has_cross_reference(value):
                return fail(
                    "cross_reference",
                    f"segment {position} prompt {key} points back at "
                    "another segment; each segment stands alone",
                )
        for value in prompt_sections.values():
            if isinstance(value, str) and _has_cross_reference(value):
                return fail(
                    "cross_reference",
                    f"segment {position} prompt section points back at another segment",
                )
    transitions = pack.get("transitions")
    if not isinstance(transitions, list):
        return fail(
            "transitions_missing",
            "pack must carry its transition table",
        )
    if len(transitions) != len(segments) - 1:
        return fail(
            "transition_count_mismatch",
            f"pack has {len(segments)} segments but "
            f"{len(transitions)} boundaries; every boundary needs "
            "one entry",
        )
    for position, boundary in enumerate(transitions):
        if not isinstance(boundary, dict):
            return fail(
                "boundary_not_object",
                f"boundary {position} must be an object",
            )
        if boundary.get("from_segment") != segment_ids[position]:
            return fail(
                "transition_mismatch",
                f"boundary {position} must cut from {segment_ids[position]}",
            )
        if boundary.get("to_segment") != segment_ids[position + 1]:
            return fail(
                "transition_mismatch",
                f"boundary {position} must cut to {segment_ids[position + 1]}",
            )
        if not isinstance(boundary.get("mechanism"), str) or not boundary["mechanism"].strip():
            return fail(
                "boundary_mechanism_missing",
                f"boundary {position} must name its mechanism",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_dance_mv_pack(params.get("pack"))
    report_path = out_dir / "dance_mv_pack_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_mv_pack_format_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_mv_pack_format_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "pack": {"type": "object"},
                },
                "required": ["pack"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Dance MV pack-format gate: one complete document, "
                "nine sections in order, every segment framed with "
                "its complete prompt, every boundary covered."
            ),
        )
    )
    return ["qa.dance_mv_pack_format_gate"]


__all__ = [
    "CROSS_REFERENCES",
    "NINE_SECTIONS",
    "PROMPT_INTERNAL",
    "check_dance_mv_pack",
    "register_dance_mv_pack_format_gate_capabilities_once",
]
