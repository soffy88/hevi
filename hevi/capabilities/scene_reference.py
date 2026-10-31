"""Scene-reference assembly discipline (``pipeline.scene_reference``).

Clean-room reimplementation of method ideas only; see
SCENEREF_ATTRIBUTION.md. No upstream code, prompt text or artwork is
copied here, no ComfyUI node is adapted, no model is run and no
picture is generated: this module judges and assembles JSON plans
only.

This module is the single place in hevi that defines the six-section
reference-prompt format. The format is shared with the character
sheet gate: the same section names, subject/picture labels and
retention keyword are used there and here, and there must not be a
second, competing definition anywhere in ``hevi/capabilities``. The
six sections are, in order:

1. subject definitions -- the scene as Subject 1 and one subject
   per cast member, each bound to a picture reference;
2. a short summary of the shot;
3. a retention analysis, stating per subject what is preserved
   from its reference picture;
4. a detailed description of the shot, including rewritten
   dialogue;
5. the overall soundscape heard inside the scene;
6. the non-diegetic music, if any.

Picture 1 is a reference for the place and the framing. It is not
a first frame, and the generated picture is not required to
reproduce it pixel for pixel. That statement is written into every
assembled prompt, in words, so that no later step can mistake the
reference for a frame that must be matched exactly.

Three disciplines, each covering a gap the neighbouring gates do
not:

1. A six-section prompt builder. The builder assembles the six
   sections from a structured plan and nothing else: a missing
   required input is an error, never silently written in. Picture
   references are capped at nine and voice references at three;
   over either cap is an error.
2. A reference-assembly record with a slot budget. References
   must arrive in order -- the scene first (Picture 1), other
   angles next, cast last. Every picture must carry a stated role
   or purpose; one without is reported ``pending``, never assumed.
3. An intent/final separation gate. A short intent (the text
   behind a "write the prompt" button) never becomes the running
   prompt. Only the finished text counts; an empty finished text
   is refused, and a finished text that changed since it was last
   reviewed is marked ``stale`` and must be reviewed again.

Failure contract: malformed plans (not a JSON object, missing ids,
non-string fields) raise CapabilityError. Gate failures are
reported in the result, not raised.
"""

from __future__ import annotations

import hashlib
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

# ---------------------------------------------------------------- format

# The one canonical definition of the six-section format in hevi.
# Do not redefine these names in another capabilities module.
H3_SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)

MAX_PICTURE_REFS = 9
MAX_VOICES = 3

# Written into every assembled prompt, verbatim in meaning: the
# scene picture is a reference, not a frame to be matched.
PICTURE_1_NOTE = (
    "Picture 1 is a reference for the place and the framing, "
    "not a first frame; it need not be reproduced pixel for pixel."
)

_RETENTION_KEYWORD = "fully_preserved"


def _req_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"pipeline.scene_reference: {what} must be a non-empty string")
    return value.strip()


def _req_list(value: Any, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise CapabilityError(f"pipeline.scene_reference: {what} must be a list")
    return value


# ---------------------------------------------------------------- dialogue

# ``Name says: "..."`` -- the speaker name is one word of letters.
_DIALOGUE_RE = re.compile(r"([A-Za-z][A-Za-z\-']*)\s+says:\s*\"([^\"]*)\"")


def rewrite_dialogue(text: str, names: list[str] | None = None) -> tuple[str, list[str]]:
    """Rewrite spoken lines to speaker-numbered, tagged dialogue.

    Speakers are numbered by first appearance: ``Mei says: "..."``
    becomes ``Mei (S1) says, <d>...</d>``. Text that already
    carries a ``<d>`` tag is left alone. The tagged content is the
    caller's wording verbatim: no translation is performed here.
    Returns the rewritten text and the speaker list in order.
    """
    if not isinstance(text, str):
        raise CapabilityError("pipeline.scene_reference: dialogue text must be a string")
    speakers: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        name, spoken = match.group(1), match.group(2)
        if name not in speakers:
            speakers.append(name)
        number = speakers.index(name) + 1
        return f"{name} (S{number}) says, <d>{spoken}</d>"

    rewritten = _DIALOGUE_RE.sub(_replace, text)
    if names is not None:
        for name in names:
            if name not in speakers:
                speakers.append(name)
    return rewritten, speakers


# ---------------------------------------------------------------- builder

def build_h3_prompt(plan: dict[str, Any]) -> dict[str, Any]:
    """Assemble the six-section reference prompt from a plan.

    ``plan`` carries ``scene`` (description, optional framing),
    ``characters`` (name, description, picture reference), optional
    ``angles``, ``shots`` (description plus dialogue) or ``detail``,
    ``soundscape``, optional ``music`` and optional ``voices``
    (speaker names, at most three). Required inputs that are
    missing raise CapabilityError; nothing is invented to fill
    them. Picture references are numbered from 1: the scene is
    Picture 1, angles follow, cast follows.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("pipeline.scene_reference: plan must be a JSON object")
    scene = plan.get("scene")
    if not isinstance(scene, dict):
        raise CapabilityError("pipeline.scene_reference: scene must be an object")
    scene_description = _req_str(scene.get("description"), "scene.description")
    framing = scene.get("framing")
    if framing is not None and not isinstance(framing, str):
        raise CapabilityError("pipeline.scene_reference: scene.framing must be a string")

    characters = _req_list(plan.get("characters", []), "characters")
    subjects: list[dict[str, Any]] = []
    for item in characters:
        if not isinstance(item, dict):
            raise CapabilityError("pipeline.scene_reference: every character must be an object")
        subjects.append({
            "name": _req_str(item.get("name"), "character.name"),
            "description": _req_str(item.get("description"), "character.description"),
        })
    angles = _req_list(plan.get("angles", []), "angles")
    for angle in angles:
        _req_str(angle, "angle")

    shots = plan.get("shots")
    detail = plan.get("detail")
    if shots is not None:
        shot_list = _req_list(shots, "shots")
        if not shot_list:
            raise CapabilityError("pipeline.scene_reference: shots must not be empty")
        for shot in shot_list:
            if not isinstance(shot, dict):
                raise CapabilityError("pipeline.scene_reference: every shot must be an object")
            _req_str(shot.get("description"), "shot.description")
    elif detail is not None:
        shot_list = []
        _req_str(detail, "detail")
    else:
        raise CapabilityError(
            "pipeline.scene_reference: shots or detail is required; "
            "a missing description is never written in")

    soundscape = _req_str(plan.get("soundscape"), "soundscape")
    music = plan.get("music")
    if music is not None and not isinstance(music, str):
        raise CapabilityError("pipeline.scene_reference: music must be a string")

    voices = _req_list(plan.get("voices", []), "voices")
    voice_names = [_req_str(voice, "voice") for voice in voices]
    if len(voice_names) > MAX_VOICES:
        raise CapabilityError(
            f"pipeline.scene_reference: at most {MAX_VOICES} voice references; "
            f"got {len(voice_names)}")

    picture_count = 1 + len(angles) + len(subjects)
    if picture_count > MAX_PICTURE_REFS:
        raise CapabilityError(
            f"pipeline.scene_reference: at most {MAX_PICTURE_REFS} picture "
            f"references; got {picture_count}")

    # --- section 1: subject definitions, scene first as Subject 1.
    subject_lines = [
        f"<Subject 1> = <Picture 1>: {scene_description}"
        + (f" Framing: {framing.strip()}." if framing and framing.strip() else ""),
        PICTURE_1_NOTE,
    ]
    for index, subject in enumerate(subjects):
        picture = 2 + len(angles) + index
        subject_lines.append(
            f"<Subject {index + 2}> = <Picture {picture}>: "
            f"{subject['name']}, {subject['description']}")
    if angles:
        subject_lines.append(
            "Further angles of the same place: "
            + ", ".join(f"<Picture {2 + i}>" for i in range(len(angles))) + ".")

    # --- section 2: summary.
    summary = f"A shot in the place of Picture 1"
    if subjects:
        summary += " with " + ", ".join(s["name"] for s in subjects)
    summary += "."

    # --- section 3: retention analysis, one preserved line each.
    retention_lines = [
        f"Subject 1: {_RETENTION_KEYWORD} -- place, framing and "
        "furnishings follow Picture 1."
    ]
    for index, subject in enumerate(subjects):
        retention_lines.append(
            f"Subject {index + 2} ({subject['name']}): {_RETENTION_KEYWORD} "
            "-- identity, face and build follow its reference picture.")

    # --- section 4: detailed description, dialogue rewritten.
    detail_lines: list[str] = []
    dialogue_speakers: list[str] = []
    if shot_list:
        for number, shot in enumerate(shot_list, start=1):
            dialogue = shot.get("dialogue", "")
            if not isinstance(dialogue, str):
                raise CapabilityError("pipeline.scene_reference: shot.dialogue must be a string")
            rewritten, speakers = rewrite_dialogue(dialogue)
            for speaker in speakers:
                if speaker not in dialogue_speakers:
                    dialogue_speakers.append(speaker)
            line = f"[Shot {number}] {shot['description'].strip()}"
            if rewritten.strip():
                line += f" {rewritten.strip()}"
            detail_lines.append(line)
    else:
        detail_lines.append(str(detail).strip())
    for speaker in dialogue_speakers:
        if speaker not in voice_names:
            raise CapabilityError(
                f"pipeline.scene_reference: dialogue speaker {speaker!r} "
                "has no declared voice reference")

    sections = {
        "subject_definitions": "\n".join(subject_lines),
        "summary": summary,
        "retention_analysis": "\n".join(retention_lines),
        "detailed_description": "\n".join(detail_lines),
        "overall_soundscape": soundscape,
        "non_diegetic_music": (
            music.strip() if music and music.strip()
            else "No non-diegetic music requested."),
    }
    text = "\n\n".join(f"{name}:\n{sections[name]}" for name in H3_SECTIONS)
    return {
        "sections": sections,
        "text": text,
        "picture_refs": picture_count,
        "voices": voice_names,
        "dialogue_speakers": dialogue_speakers,
    }


def check_h3_prompt(prompt: Any) -> dict[str, Any]:
    """Judge an assembled six-section prompt text or section map.

    Sections must appear once, in the canonical order, with the
    Picture 1 reference note and a ``fully_preserved`` retention
    line present. Dialogue speakers are counted from ``(Sn)``
    tags and must stay within the voice cap.
    """
    issues: list[dict[str, Any]] = []
    ordered: list[str] = []
    if isinstance(prompt, dict):
        sections = prompt.get("sections")
        if not isinstance(sections, dict):
            raise CapabilityError("pipeline.scene_reference: prompt.sections must be an object")
        text = "\n\n".join(f"{name}:\n{sections[name]}" for name in H3_SECTIONS
                           if name in sections)
        present = [name for name in H3_SECTIONS if name in sections]
        ordered = [name for name in sections if name in H3_SECTIONS]
    elif isinstance(prompt, str):
        text = prompt
        positions = []
        for name in H3_SECTIONS:
            match = re.search(rf"(?m)^{re.escape(name)}:", text)
            if match:
                positions.append((match.start(), name))
        positions.sort()
        ordered = [name for _, name in positions]
        present = ordered
    else:
        raise CapabilityError("pipeline.scene_reference: prompt must be text or a section map")
    for name in H3_SECTIONS:
        if name not in present:
            issues.append({"code": "MISSING_SECTION", "severity": "fail",
                           "message": f"required section {name!r} is missing; it is never written in"})
    if ordered != [name for name in H3_SECTIONS if name in ordered]:
        issues.append({"code": "SECTION_ORDER", "severity": "fail",
                       "message": "sections are out of the canonical order"})
    if PICTURE_1_NOTE not in text:
        issues.append({"code": "MISSING_PICTURE_1_NOTE", "severity": "fail",
                       "message": "the Picture 1 reference note is missing from the prompt"})
    if _RETENTION_KEYWORD not in text:
        issues.append({"code": "MISSING_RETENTION", "severity": "fail",
                       "message": "retention analysis carries no fully_preserved line"})
    speaker_numbers = {int(n) for n in re.findall(r"\(S(\d+)\)", text)}
    if speaker_numbers and max(speaker_numbers) > MAX_VOICES:
        issues.append({"code": "VOICE_CAP", "severity": "fail",
                       "message": f"dialogue uses {max(speaker_numbers)} speakers; "
                                  f"at most {MAX_VOICES} voice references"})
    picture_numbers = {int(n) for n in re.findall(r"<Picture (\d+)>", text)}
    if picture_numbers and max(picture_numbers) > MAX_PICTURE_REFS:
        issues.append({"code": "PICTURE_CAP", "severity": "fail",
                       "message": f"prompt cites Picture {max(picture_numbers)}; "
                                  f"at most {MAX_PICTURE_REFS} picture references"})
    fatal = any(i["severity"] == "fail" for i in issues)
    return {"verdict": "fail" if fatal else "pass", "issues": issues,
            "sections_present": present}


# ---------------------------------------------------------------- assembly

REFERENCE_KINDS = ("scene", "angle", "cast")
_KIND_ORDER = {"scene": 0, "angle": 1, "cast": 2}


def check_reference_assembly(assembly: Any) -> dict[str, Any]:
    """Judge a reference-assembly record: order and slot budget.

    The scene reference (Picture 1) comes first, other angles
    next, cast last. At most nine pictures and three voice
    references. A picture with no stated role or purpose is
    ``pending``; order and budget violations fail.
    """
    if not isinstance(assembly, dict):
        raise CapabilityError("pipeline.scene_reference: assembly must be a JSON object")
    references = _req_list(assembly.get("references", []), "assembly.references")
    issues: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for item in references:
        if not isinstance(item, dict):
            raise CapabilityError("pipeline.scene_reference: every reference must be an object")
        kind = _req_str(item.get("kind"), "reference.kind")
        ref_id = _req_str(item.get("ref_id"), "reference.ref_id")
        if kind not in REFERENCE_KINDS:
            issues.append({"code": "UNKNOWN_KIND", "severity": "fail",
                           "message": f"unknown reference kind {kind!r}"})
            continue
        picture = item.get("picture")
        if not isinstance(picture, int) or picture < 1:
            raise CapabilityError("pipeline.scene_reference: reference.picture must be a positive integer")
        purpose = item.get("purpose", item.get("role", ""))
        if not isinstance(purpose, str):
            raise CapabilityError("pipeline.scene_reference: reference purpose must be a string")
        records.append({"ref_id": ref_id, "kind": kind, "picture": picture,
                        "purpose": purpose.strip(),
                        "voice": bool(item.get("voice", False))})
    kinds = [_KIND_ORDER[r["kind"]] for r in records]
    if kinds != sorted(kinds):
        issues.append({"code": "REFERENCE_ORDER", "severity": "fail",
                       "message": "references must arrive scene first, angles next, cast last"})
    scenes = [r for r in records if r["kind"] == "scene"]
    if len(scenes) != 1:
        issues.append({"code": "SCENE_COUNT", "severity": "fail",
                       "message": f"exactly one scene reference is required; got {len(scenes)}"})
    elif scenes[0]["picture"] != 1:
        issues.append({"code": "SCENE_NOT_PICTURE_1", "severity": "fail",
                       "message": "the scene reference must be Picture 1"})
    elif records and records[0] is not scenes[0]:
        issues.append({"code": "SCENE_NOT_FIRST", "severity": "fail",
                       "message": "the scene reference must come first"})
    if len(records) > MAX_PICTURE_REFS:
        issues.append({"code": "PICTURE_BUDGET", "severity": "fail",
                       "message": f"{len(records)} picture references exceed the budget of {MAX_PICTURE_REFS}"})
    voice_count = sum(1 for r in records if r["voice"])
    if voice_count > MAX_VOICES:
        issues.append({"code": "VOICE_BUDGET", "severity": "fail",
                       "message": f"{voice_count} voice references exceed the budget of {MAX_VOICES}"})
    for record in records:
        if not record["purpose"]:
            issues.append({"code": "UNDECLARED_REFERENCE", "severity": "pending",
                           "message": f"reference {record['ref_id']!r} states no role or purpose"})
    fatal = any(i["severity"] == "fail" for i in issues)
    pending = any(i["severity"] == "pending" for i in issues)
    verdict = "fail" if fatal else ("pending" if pending else "pass")
    return {"verdict": verdict, "issues": issues,
            "ordered_references": records,
            "picture_count": len(records), "voice_count": voice_count}


# ---------------------------------------------------------------- intent/final

def resolve_final_prompt(intent: Any, expanded: Any, action_text: Any) -> str:
    """Resolve the running prompt from finished text only.

    The finished text (``action_text`` first, else ``expanded``)
    wins. The short intent is never used: it only feeds the button
    that writes the prompt. Both finished fields blank is an
    error, not a fallback to the intent.
    """
    for field in (action_text, expanded):
        if isinstance(field, str) and field.strip():
            return field.strip()
    raise CapabilityError(
        "pipeline.scene_reference: the finished prompt text is empty; "
        "the intent is never used as the running prompt")


def _final_hash(final_text: str) -> str:
    return hashlib.sha256(final_text.encode("utf-8")).hexdigest()


def check_final_prompt(record: Any) -> dict[str, Any]:
    """Judge an intent/final separation record.

    An empty finished text fails; a finished text recorded as
    coming from the intent fails; a finished text that changed
    since its last review is ``stale`` and must be reviewed again.
    When intent and finished text disagree, the finished text
    governs; a finished text identical to the intent is warned
    about, since it usually means the prompt was never written.
    """
    if not isinstance(record, dict):
        raise CapabilityError("pipeline.scene_reference: final record must be a JSON object")
    issues: list[dict[str, Any]] = []
    final_text = record.get("final_text", "")
    if not isinstance(final_text, str):
        raise CapabilityError("pipeline.scene_reference: final_text must be a string")
    final_text = final_text.strip()
    if not final_text:
        issues.append({"code": "EMPTY_FINAL_PROMPT", "severity": "fail",
                       "message": "the finished prompt text is empty; the intent never stands in for it"})
    source = record.get("final_source", "")
    if source in ("action", "intent"):
        issues.append({"code": "INTENT_USED_AS_FINAL", "severity": "fail",
                       "message": "the running prompt must come from the finished text, not the intent"})
    intent = record.get("intent", "")
    if isinstance(intent, str) and intent.strip() and final_text == intent.strip():
        issues.append({"code": "FINAL_EQUALS_INTENT", "severity": "warn",
                       "message": "the finished text is identical to the intent; "
                                  "the prompt was probably never written"})
    stale = False
    previous = record.get("previous_final_hash")
    if previous is not None:
        if not isinstance(previous, str):
            raise CapabilityError("pipeline.scene_reference: previous_final_hash must be a string")
        if _final_hash(final_text) != previous:
            stale = True
            issues.append({"code": "STALE_FINAL_PROMPT", "severity": "stale",
                           "message": "the finished text changed since its last review; re-review is required"})
    fatal = any(i["severity"] == "fail" for i in issues)
    verdict = "fail" if fatal else ("stale" if stale else "pass")
    return {"verdict": verdict, "issues": issues,
            "final_hash": _final_hash(final_text) if final_text else None,
            "final_governs": True}


# ---------------------------------------------------------------- combined

def check_scene_reference(plan: dict[str, Any]) -> dict[str, Any]:
    """Judge one scene-reference plan: prompt, assembly, final text."""
    if not isinstance(plan, dict):
        raise CapabilityError("pipeline.scene_reference: plan must be a JSON object")
    issues: list[dict[str, Any]] = []
    prompt_result: dict[str, Any] | None = None
    if "prompt" in plan:
        prompt_result = check_h3_prompt(plan.get("prompt"))
        issues += prompt_result["issues"]
    elif "build" in plan:
        try:
            built = build_h3_prompt(plan.get("build"))
            prompt_result = check_h3_prompt(built)
            issues += prompt_result["issues"]
        except CapabilityError as exc:
            issues.append({"code": "BUILD_FAILED", "severity": "fail", "message": str(exc)})
            prompt_result = {"verdict": "fail", "issues": issues[-1:]}
    assembly_result = check_reference_assembly(plan.get("assembly", {}))
    issues += assembly_result["issues"]
    final_result = check_final_prompt(plan.get("final", {}))
    issues += final_result["issues"]
    fatal = any(i["severity"] == "fail" for i in issues)
    stale = any(i["severity"] == "stale" for i in issues)
    pending = any(i["severity"] == "pending" for i in issues)
    if fatal:
        verdict = "fail"
    elif stale:
        verdict = "stale"
    elif pending:
        verdict = "pending"
    else:
        verdict = "pass"
    return {"verdict": verdict, "issues": issues,
            "prompt": prompt_result, "assembly": assembly_result,
            "final": final_result}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_scene_reference(params.get("plan", {}))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "scene_reference.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"]},
    )


def register_scene_reference_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="pipeline.scene_reference",
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
            "Scene-reference assembly discipline (clean-room): the "
            "single six-section reference-prompt format shared with "
            "the character sheet gate, a scene-first reference "
            "assembly record with picture/voice slot budgets, and "
            "an intent/final separation gate. Judges and assembles "
            "JSON plans only; no image is generated here."
        ),
        line="pipeline",
    ))
    return ["pipeline.scene_reference"]


register_scene_reference_capabilities_once()
