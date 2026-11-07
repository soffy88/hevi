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
   Generation-ready (``strict``) builds also carry the execution
   fields (duration, camera movement, shot size, lighting, style,
   negative prompts, aspect ratio); a strict build without
   ``duration_s`` fails, and the frame count is written into the
   prompt text from :func:`canonical_frame_count` only.
3. An intent/final separation gate. A short intent (the text
   behind a "write the prompt" button) never becomes the running
   prompt. Only the finished text counts; an empty finished text
   is refused, a finished text identical to the intent fails, and
   a finished text that changed since it was last reviewed is
   marked ``stale`` and must be reviewed again.

Three further disciplines (P1), on the same plan-only terms:

4. A photo-scene record. Exactly one main view sets the camera;
   other angles of the same place are extra references. Angles
   are for the movie branch by default: in the picture branch
   they are not applied unless the record says so explicitly,
   and asking for them there is warned about, because a picture
   model has been seen to take an angle's camera instead of the
   main view's. An angle with no description is ``pending``. The
   place description is plain wording about the place only: it
   must not describe people in the scene or comment on the
   photographs or their quality.
5. A blocking record. Each standing marker is bound to a cast
   member or role and to a screen zone, a depth and a camera
   relation, and carries an explicit declaration that the marker
   itself does not appear in the finished film. A marker with no
   binding is recorded as a person distinct from the cast. A
   marker's view and visible parts are checked against the
   character sheet gate's view catalogue and part-scope table,
   reusing that gate's tables rather than restating them; a
   conflict fails and names the marker, the person and the part
   or view.
6. An output precheck. Durations snap to the H3 frame lattice
   (see ``h3_frame_count``), sizes snap to the patch grid (see
   ``h3_output_size``), and any crop -- of the frame to a
   different aspect, or of the delivered frames below the
   snapped count -- must be declared in the plan; an undeclared
   crop fails. This is arithmetic on a plan only: nothing is
   generated, cropped or resized here, and no other capability's
   locked execution values are changed by it.

Failure contract: malformed plans (not a JSON object, missing ids,
non-string fields) raise CapabilityError. Gate failures are
reported in the result, not raised.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.character_sheet import (
    DEFAULT_PART_TABLE,
    PART_IDS,
    REAR_VIEWS,
    VIEW_IDS,
)
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

# Execution fields a generation-ready (strict) build must be able
# to state (2026-10-31 prompt audit, fix 6). Only ``duration_s``
# is required: a strict build without it fails. The other fields
# are validated when present and written into the prompt text
# when present; a missing one is recorded as absent, never
# invented. ``frame_route`` names the route whose frame lattice
# :func:`canonical_frame_count` used; it is not itself an
# execution field, it only labels the frame count.
EXECUTION_FIELDS = (
    "duration_s",
    "camera_movement",
    "shot_size",
    "lighting",
    "style",
    "negative_prompts",
    "aspect_ratio",
)


def _opt_execution_str(plan: dict[str, Any], field: str) -> str | None:
    value = plan.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(
            f"pipeline.scene_reference: {field} must be a non-empty string")
    return value.strip()


def _parse_execution_fields(plan: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    """Parse the plan's execution fields; strict builds need a duration.

    Returns the execution record (empty when the plan states no
    execution field at all). Frame counts come only from
    :func:`canonical_frame_count`, on the plan's named
    ``frame_route`` (default ``"h3"``). Angle and character
    bindings are untouched by this parse: strict binding checks
    in :func:`build_h3_prompt` run exactly as before.
    """
    execution: dict[str, Any] = {}
    duration = plan.get("duration_s")
    if duration is None:
        if strict:
            raise CapabilityError(
                "pipeline.scene_reference: strict build: duration_s is "
                "required; a prompt without a duration cannot be "
                "executed and is never written in")
    else:
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) \
                or not math.isfinite(duration) or duration <= 0:
            raise CapabilityError(
                "pipeline.scene_reference: duration_s must be a positive number")
        fps = plan.get("fps", H3_FPS)
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) \
                or not math.isfinite(fps) or fps <= 0:
            raise CapabilityError("pipeline.scene_reference: fps must be a positive number")
        route = plan.get("frame_route", "h3")
        if not isinstance(route, str) or not route.strip():
            raise CapabilityError(
                "pipeline.scene_reference: frame_route must be a non-empty string")
        route = route.strip()
        frames = canonical_frame_count(float(duration), float(fps), route=route)
        execution["duration_s"] = float(duration)
        execution["fps"] = float(fps)
        execution["frame_route"] = route
        execution["frames"] = frames
        execution["frame_seconds"] = frames / float(fps)
    for field in ("camera_movement", "shot_size", "lighting", "style"):
        value = _opt_execution_str(plan, field)
        if value is not None:
            execution[field] = value
    aspect = _opt_execution_str(plan, "aspect_ratio")
    if aspect is not None:
        _parse_ratio(aspect)  # rejects unparseable aspects; never invents one
        execution["aspect_ratio"] = aspect
    negatives = plan.get("negative_prompts")
    if negatives is not None:
        if isinstance(negatives, str):
            negatives = [negatives]
        if not isinstance(negatives, list) or any(
                not isinstance(item, str) or not item.strip() for item in negatives):
            raise CapabilityError(
                "pipeline.scene_reference: negative_prompts must be a list "
                "of non-empty strings")
        execution["negative_prompts"] = [str(item).strip() for item in negatives]
    return execution


def _execution_sentence(execution: dict[str, Any]) -> str:
    """One English execution sentence for the summary section.

    Written exactly once, in the summary, so the frame count and
    the execution parameters live in the prompt text itself and
    cannot drift from the plan's numbers.
    """
    parts: list[str] = []
    if "duration_s" in execution:
        parts.append(
            f"Duration: {execution['duration_s']:g}s "
            f"({execution['frames']} frames at {execution['fps']:g} fps, "
            f"route {execution['frame_route']}).")
    if "camera_movement" in execution:
        parts.append(f"Camera movement: {execution['camera_movement']}.")
    if "shot_size" in execution:
        parts.append(f"Shot size: {execution['shot_size']}.")
    if "lighting" in execution:
        parts.append(f"Lighting: {execution['lighting']}.")
    if "style" in execution:
        parts.append(f"Style: {execution['style']}.")
    if "aspect_ratio" in execution:
        parts.append(f"Aspect ratio: {execution['aspect_ratio']}.")
    if "negative_prompts" in execution:
        parts.append(
            "Negative prompts: " + "; ".join(execution["negative_prompts"]) + ".")
    return " ".join(parts)


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

# Chinese dialogue: ``守仁说："..."`` / ``守仁道："..."`` / ``守仁：“...”``.
# The name is 1-8 CJK characters (optionally with a middle dot), the verb is
# one of the common speech verbs, and the line is quoted with straight or
# curly quotes after a fullwidth/halfwidth colon. Text already rewritten
# to ``守仁 (S1) 说，<d>...</d>`` does not match: the ``(S1)`` marker sits
# between the name and the verb, so a second pass leaves it alone.
_CN_SPEECH_VERBS = r"说|说道|道|问|答|喊|叫|笑道|叹道|应道|回道"
_CN_DIALOGUE_RE = re.compile(
    r"([\u4e00-\u9fff]{1,8}(?:·[\u4e00-\u9fff]{1,8})?)"
    rf"\s*(?:{_CN_SPEECH_VERBS})\s*[：:]\s*[\"“]([^\"”]*)[\"”]"
)


def rewrite_dialogue(text: str, names: list[str] | None = None) -> tuple[str, list[str]]:
    """Rewrite spoken lines to speaker-numbered, tagged dialogue.

    Speakers are numbered by first appearance: ``Mei says: "..."``
    becomes ``Mei (S1) says, <d>...</d>``; ``守仁说："..."`` becomes
    ``守仁 (S1) 说，<d>...</d>``. Text that already carries a ``<d>``
    tag is left alone. The tagged content is the caller's wording
    verbatim: no translation is performed here. Returns the rewritten
    text and the speaker list in order.
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

    def _replace_cn(match: re.Match[str]) -> str:
        name, spoken = match.group(1), match.group(2)
        if name not in speakers:
            speakers.append(name)
        number = speakers.index(name) + 1
        return f"{name} (S{number}) 说，<d>{spoken}</d>"

    rewritten = _DIALOGUE_RE.sub(_replace, text)
    rewritten = _CN_DIALOGUE_RE.sub(_replace_cn, rewritten)
    if names is not None:
        for name in names:
            if name not in speakers:
                speakers.append(name)
    return rewritten, speakers


# ------------------------------------------------------- reference bindings
#
# A Picture number is not a binding until it names a file that exists
# (local path) or carries a verified hash. These validators are the
# single implementation used by both this module and
# story.prompt_compiler (which imports them lazily); do not copy them
# into a second module.

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def resolve_picture_binding(binding: Any, what: str = "reference binding") -> dict[str, Any]:
    """Validate one Picture -> file binding. Returns ``{file, sha256}``.

    ``file`` must be a non-empty string and ``sha256`` a 64-hex digest
    of the file's bytes. A local filesystem path (no URL scheme) must
    exist on disk; a URL is accepted on its hash alone, because the
    file lives elsewhere -- the hash is what the executor checks.
    """
    if not isinstance(binding, dict):
        raise CapabilityError(
            f"pipeline.scene_reference: {what} must be an object with 'file' and 'sha256'")
    file = binding.get("file")
    sha = binding.get("sha256")
    if not isinstance(file, str) or not file.strip():
        raise CapabilityError(f"pipeline.scene_reference: {what} needs a non-empty 'file'")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha.strip()):
        raise CapabilityError(
            f"pipeline.scene_reference: {what} needs a 64-hex 'sha256' for {file!r}")
    file = file.strip()
    if "://" not in file:
        path = Path(file)
        if not path.exists():
            raise CapabilityError(
                f"pipeline.scene_reference: {what} file does not exist: {file!r}")
    return {"file": file, "sha256": sha.strip()}


def resolve_picture_bindings(bindings: Any, *, what: str = "reference bindings") -> dict[int, dict[str, Any]]:
    """Validate a Picture-number -> binding map. Keys are ints or digit strings."""
    if not isinstance(bindings, dict):
        raise CapabilityError(f"pipeline.scene_reference: {what} must be an object")
    out: dict[int, dict[str, Any]] = {}
    for key, value in bindings.items():
        try:
            number = int(key)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise CapabilityError(
                f"pipeline.scene_reference: {what} key {key!r} is not a picture number") from None
        if number < 1:
            raise CapabilityError(
                f"pipeline.scene_reference: {what} picture number must be >= 1, got {number}")
        out[number] = resolve_picture_binding(value, f"{what} picture {number}")
    return out


def resolve_character_anchor(name: str, anchors: Any) -> dict[str, Any]:
    """Resolve one character's confirmed anchor from an anchors map.

    Accepted shapes (both must be confirmed by a human -- an
    unconfirmed or missing anchor fails, it never falls back to a
    bare name):
    * a ``qa.character_anchor_gate`` sheet: ``{"anchor": {"file",
      "sha256", "look_snapshot", "confirmed": true, ...}}``;
    * a plain record: ``{"look_snapshot"|"look"|"description",
      "file", "sha256", "confirmed": true}`` with optional
      ``"wardrobe"``.
    Returns ``{name, look, wardrobe, file, sha256}``.
    """
    if not isinstance(anchors, dict) or name not in anchors:
        raise CapabilityError(
            f"pipeline.scene_reference: character {name!r} has no confirmed anchor; "
            "a bare name is not a prompt-ready character")
    record = anchors[name]
    if not isinstance(record, dict):
        raise CapabilityError(
            f"pipeline.scene_reference: anchor for {name!r} must be an object")
    anchor = record.get("anchor") if isinstance(record.get("anchor"), dict) else record
    if anchor.get("confirmed") is not True:
        raise CapabilityError(
            f"pipeline.scene_reference: anchor for {name!r} is not confirmed; "
            "unconfirmed anchors never reach generation")
    look = anchor.get("look_snapshot") or anchor.get("look") or anchor.get("description")
    if not isinstance(look, str) or not look.strip():
        raise CapabilityError(
            f"pipeline.scene_reference: anchor for {name!r} carries no look description")
    binding = resolve_picture_binding(
        {"file": anchor.get("file"), "sha256": anchor.get("sha256")},
        f"anchor for {name!r}")
    wardrobe = anchor.get("wardrobe")
    if wardrobe is not None and (not isinstance(wardrobe, str) or not wardrobe.strip()):
        raise CapabilityError(
            f"pipeline.scene_reference: anchor wardrobe for {name!r} must be a non-empty string")
    return {"name": name, "look": look.strip(),
            "wardrobe": wardrobe.strip() if isinstance(wardrobe, str) else None,
            "file": binding["file"], "sha256": binding["sha256"]}


# ---------------------------------------------------------------- builder

def build_h3_prompt(
    plan: dict[str, Any],
    *,
    strict: bool = False,
    reference_files: Any = None,
    anchors: Any = None,
) -> dict[str, Any]:
    """Assemble the six-section reference prompt from a plan.

    ``plan`` carries ``scene`` (description, optional framing),
    ``characters`` (name, description, picture reference), optional
    ``angles``, ``shots`` (description plus dialogue) or ``detail``,
    ``soundscape``, optional ``music`` and optional ``voices``
    (speaker names, at most three). Required inputs that are
    missing raise CapabilityError; nothing is invented to fill
    them. Picture references are numbered from 1: the scene is
    Picture 1, angles follow, cast follows.

    ``angles`` entries may be bare strings (legacy) or objects
    ``{"description": ..., "file": ..., "sha256": ...}``. Dialogue
    in a shot's ``description`` is rewritten the same way as its
    ``dialogue`` field, so Chinese speech written inline is
    numbered and tagged instead of passing through unbound.

    With ``strict=True`` the prompt must be generation-ready:
    every Picture number needs a validated file binding
    (``reference_files`` or the plan's own ``reference_files``),
    every angle needs a description plus a file binding (a bare
    string fails), and every character needs a confirmed anchor
    (``anchors`` or the character's own ``anchor`` record). A
    spoken line that carries no speaker number after rewriting
    fails instead of passing through unbound. A strict build
    also needs ``duration_s`` (see ``EXECUTION_FIELDS``): without
    it the build fails, and with it the frame count from
    :func:`canonical_frame_count` on the plan's ``frame_route``
    is written into the summary section of the prompt text.
    Execution fields stated in a non-strict build are validated
    and written the same way; a non-strict build without a
    duration keeps its old behaviour and reports no frames.
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
            "anchor_record": item.get("anchor"),
            "reference_file": item.get("reference_file"),
        })
    raw_angles = _req_list(plan.get("angles", []), "angles")
    angles: list[dict[str, Any]] = []
    for angle in raw_angles:
        if isinstance(angle, str):
            angles.append({"description": _req_str(angle, "angle"), "file": None, "sha256": None})
        elif isinstance(angle, dict):
            angles.append({
                "description": _req_str(angle.get("description"), "angle.description"),
                "file": angle.get("file"),
                "sha256": angle.get("sha256"),
            })
        else:
            raise CapabilityError(
                "pipeline.scene_reference: every angle must be a string or an object")

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

    # Execution fields: parsed before any binding check, and the
    # binding checks below are unchanged -- execution fields never
    # relax an angle or anchor requirement.
    execution = _parse_execution_fields(plan, strict=strict)

    # --- strict bindings: every picture number names a real file.
    supplied_files = reference_files if reference_files is not None else plan.get("reference_files")
    bindings: dict[int, dict[str, Any]] = {}
    if supplied_files is not None:
        if isinstance(supplied_files, dict):
            bindings = resolve_picture_bindings(supplied_files)
        elif isinstance(supplied_files, list):
            by_number: dict[Any, Any] = {}
            for row in supplied_files:
                if not isinstance(row, dict) or "picture" not in row:
                    raise CapabilityError(
                        "pipeline.scene_reference: every reference_files row needs 'picture'")
                by_number[row["picture"]] = row
            bindings = resolve_picture_bindings(by_number)
        else:
            raise CapabilityError(
                "pipeline.scene_reference: reference_files must be an object or a list")
    if strict:
        if not bindings:
            raise CapabilityError(
                "pipeline.scene_reference: strict build needs reference_files; "
                "a Picture number without a file binding never reaches generation")
        for index, angle in enumerate(angles):
            if not angle["file"]:
                raise CapabilityError(
                    f"pipeline.scene_reference: strict build: angle Picture {2 + index} "
                    "is a bare string with no file binding")
        missing = [n for n in range(1, picture_count + 1) if n not in bindings]
        if missing:
            raise CapabilityError(
                f"pipeline.scene_reference: strict build: pictures without a file "
                f"binding: {', '.join(str(n) for n in missing)}")
        for index, angle in enumerate(angles):
            resolve_picture_binding(
                {"file": angle["file"], "sha256": angle["sha256"]},
                f"angle Picture {2 + index}")
            if bindings[2 + index]["file"] != str(angle["file"]).strip():
                raise CapabilityError(
                    f"pipeline.scene_reference: strict build: angle Picture {2 + index} "
                    "binding does not match its reference_files entry")
    # Resolved anchors (strict only; legacy builds keep bare names).
    resolved_anchors: dict[str, dict[str, Any]] = {}
    if strict:
        for subject in subjects:
            record = subject["anchor_record"]
            if record is not None:
                resolved = resolve_character_anchor(
                    subject["name"], {subject["name"]: record})
            elif anchors is not None:
                resolved = resolve_character_anchor(subject["name"], anchors)
            elif subject["reference_file"] is not None:
                binding = resolve_picture_binding(
                    subject["reference_file"], f"reference file for {subject['name']!r}")
                resolved = {"name": subject["name"], "look": subject["description"],
                            "wardrobe": None, "file": binding["file"],
                            "sha256": binding["sha256"]}
            else:
                raise CapabilityError(
                    f"pipeline.scene_reference: strict build: character "
                    f"{subject['name']!r} has no confirmed anchor")
            resolved_anchors[subject["name"]] = resolved
            picture = 2 + len(angles) + [s["name"] for s in subjects].index(subject["name"])
            if bindings and bindings[picture]["file"] != resolved["file"]:
                raise CapabilityError(
                    f"pipeline.scene_reference: strict build: anchor file for "
                    f"{subject['name']!r} does not match its Picture {picture} binding")

    # --- section 1: subject definitions, scene first as Subject 1.
    subject_lines = [
        f"<Subject 1> = <Picture 1>: {scene_description}"
        + (f" Framing: {framing.strip()}." if framing and framing.strip() else ""),
        PICTURE_1_NOTE,
    ]
    for index, subject in enumerate(subjects):
        picture = 2 + len(angles) + index
        line = (
            f"<Subject {index + 2}> = <Picture {picture}>: "
            f"{subject['name']}, {subject['description']}")
        if subject["name"] in resolved_anchors:
            anchor = resolved_anchors[subject["name"]]
            line += (f" Confirmed anchor: {anchor['look']}; "
                     f"reference file {anchor['file']} (sha256 {anchor['sha256'][:8]}).")
        subject_lines.append(line)
    if angles:
        angle_parts = []
        for i, angle in enumerate(angles):
            part = f"<Picture {2 + i}>: {angle['description']}"
            if angle["file"]:
                part += f" (file {angle['file']})"
            angle_parts.append(part)
        subject_lines.append(
            "Further angles of the same place: " + "; ".join(angle_parts) + ".")

    # --- section 2: summary, with the execution sentence when
    # the plan states any execution field (exactly once).
    summary = f"A shot in the place of Picture 1"
    if subjects:
        summary += " with " + ", ".join(s["name"] for s in subjects)
    summary += "."
    if execution:
        summary += " " + _execution_sentence(execution)

    # --- section 3: retention analysis, one preserved line each.
    retention_lines = [
        f"Subject 1: {_RETENTION_KEYWORD} -- place, framing and "
        "furnishings follow Picture 1."
    ]
    for index, subject in enumerate(subjects):
        if subject["name"] in resolved_anchors:
            anchor = resolved_anchors[subject["name"]]
            retention_lines.append(
                f"Subject {index + 2} ({subject['name']}): {_RETENTION_KEYWORD} "
                f"-- {anchor['look']} follow its reference picture.")
        else:
            retention_lines.append(
                f"Subject {index + 2} ({subject['name']}): {_RETENTION_KEYWORD} "
                "-- identity, face and build follow its reference picture.")

    # --- section 4: detailed description, dialogue rewritten.
    # Dialogue written inline in a shot description is rewritten
    # too: otherwise Chinese speech in the description passes
    # through with no speaker number and no voice binding.
    detail_lines: list[str] = []
    dialogue_speakers: list[str] = []
    for number, shot in enumerate(shot_list, start=1):
        dialogue = shot.get("dialogue", "")
        if not isinstance(dialogue, str):
            raise CapabilityError("pipeline.scene_reference: shot.dialogue must be a string")
        rewritten_desc, desc_speakers = rewrite_dialogue(shot["description"].strip())
        rewritten, speakers = rewrite_dialogue(dialogue)
        for speaker in (*desc_speakers, *speakers):
            if speaker not in dialogue_speakers:
                dialogue_speakers.append(speaker)
        line = f"[Shot {number}] {rewritten_desc}"
        if rewritten.strip():
            line += f" {rewritten.strip()}"
        if strict and re.search(r"[\"“]", line) and "(S" not in line:
            raise CapabilityError(
                f"pipeline.scene_reference: strict build: shot {number} carries "
                "quoted speech with no numbered speaker; the dialogue was "
                "not rewritten and no voice can be bound to it")
        detail_lines.append(line)
    if not shot_list:
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
    result: dict[str, Any] = {
        "sections": sections,
        "text": text,
        "picture_refs": picture_count,
        "voices": voice_names,
        "dialogue_speakers": dialogue_speakers,
        "strict": strict,
    }
    if bindings:
        result["picture_files"] = {
            number: binding["file"] for number, binding in sorted(bindings.items())}
    if execution:
        result["execution"] = execution
    if "duration_s" in execution:
        # Single frame-count source: canonical_frame_count, named
        # route only. The same numbers are already in the prompt
        # text (summary), via _execution_sentence.
        result["duration_s"] = execution["duration_s"]
        result["frames"] = execution["frames"]
        result["frame_seconds"] = execution["frame_seconds"]
        result["frame_route"] = execution["frame_route"]
    return result


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
    if isinstance(prompt, dict):
        execution_meta = prompt.get("execution")
        if isinstance(execution_meta, dict) and execution_meta.get("frames") is not None:
            frames = execution_meta["frames"]
            if "Duration:" not in text or f"{frames} frames" not in text:
                issues.append({"code": "EXECUTION_FRAMES_MISSING", "severity": "fail",
                               "message": f"the prompt states {frames} frames in its "
                                          "execution record but the frame count is not "
                                          "written into the prompt text"})
    if isinstance(prompt, dict) and isinstance(prompt.get("sections"), dict):
        detail_text = str(prompt["sections"].get("detailed_description", ""))
    else:
        detail_match = re.search(
            r"(?ms)^detailed_description:\n(.*?)(?:\n\noverall_soundscape:|\Z)", text)
        detail_text = detail_match.group(1) if detail_match else ""
    if re.search(r"[\"“]", detail_text) and not re.search(r"\(S\d+\)", detail_text):
        issues.append({"code": "DIALOGUE_UNNUMBERED", "severity": "fail",
                       "message": "detailed_description carries quoted speech with no "
                                  "numbered (Sn) speaker; the dialogue was not rewritten "
                                  "and no voice can be bound to it"})
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

# Whitelist for ``final_source`` (2026-10-31 prompt audit, fix 7):
# only a finished-text origin counts. An absent source stays
# allowed (unspecified, as before); any other stated source
# fails. ``"action"`` and ``"intent"`` keep their own, older
# failure below and are deliberately NOT on this list.
FINAL_SOURCE_WHITELIST = ("expanded", "action_text", "expanded_text", "final")


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
    coming from the intent fails; a ``final_source`` outside the
    whitelist in :data:`FINAL_SOURCE_WHITELIST` fails; a finished
    text that changed since its last review is ``stale`` and
    must be reviewed again. When intent and finished text
    disagree, the finished text governs; a finished text
    identical to the intent fails, since it means the prompt
    was never written.
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
    elif source and source not in FINAL_SOURCE_WHITELIST:
        issues.append({"code": "INVALID_FINAL_SOURCE", "severity": "fail",
                       "message": f"final_source {source!r} is not in the whitelist "
                                  f"{list(FINAL_SOURCE_WHITELIST)}; the finished text "
                                  "must be recorded as coming from a finished-text origin"})
    intent = record.get("intent", "")
    if isinstance(intent, str) and intent.strip() and final_text == intent.strip():
        issues.append({"code": "FINAL_EQUALS_INTENT", "severity": "fail",
                       "message": "the finished text is identical to the intent; "
                                  "the prompt was never written, so the finished "
                                  "text is refused"})
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


# ---------------------------------------------------------------- photo scene

MAX_ANGLES = 4
MOVIE_ANGLE_LIMIT = 3

# Narrow wording heuristic only: a place description must describe
# the place, not people in it and not the photographs or their
# quality. It judges the record's wording, never a picture.
_PEOPLE_RE = re.compile(
    r"\b(people|person|man|woman|men|women|boy|girl|child|children)\b",
    re.IGNORECASE)
_PEOPLE_WORDS = ("人物", "男人", "女人", "男孩", "女孩", "小孩", "男子", "女子")
_QUALITY_RE = re.compile(
    r"\b(blurry|blurriness|overexposed|underexposed|noisy|grainy|"
    r"out of focus|photo quality|image quality)\b",
    re.IGNORECASE)
_QUALITY_WORDS = ("照片质量", "图片质量", "清晰度", "曝光过度", "噪点", "模糊")


def _photo_pictures(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise a photo-scene record to main-first picture rows.

    Two shapes are accepted: a ``pictures`` list whose rows carry a
    ``role`` of ``main`` or ``angle``, or a ``main_view`` plus an
    ``angles`` list. A record with neither shape yields no rows;
    the caller reports the missing main view as a gate failure.
    """
    pictures = record.get("pictures")
    if pictures is not None:
        rows = _req_list(pictures, "photo_scene.pictures")
        normalised: list[dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                raise CapabilityError(
                    "pipeline.scene_reference: every picture must be an object")
            role = _req_str(item.get("role"), "picture.role")
            description = item.get("description", "")
            if not isinstance(description, str):
                raise CapabilityError(
                    "pipeline.scene_reference: picture.description must be a string")
            normalised.append({"ref_id": _req_str(item.get("ref_id"), "picture.ref_id"),
                               "role": role, "description": description.strip()})
        return normalised
    main_view = record.get("main_view")
    if main_view is None:
        return []
    if isinstance(main_view, str):
        main_id = _req_str(main_view, "photo_scene.main_view")
    elif isinstance(main_view, dict):
        main_id = _req_str(main_view.get("ref_id"), "photo_scene.main_view.ref_id")
    else:
        raise CapabilityError(
            "pipeline.scene_reference: main_view must be a string or object")
    rows = [{"ref_id": main_id, "role": "main", "description": ""}]
    for item in _req_list(record.get("angles", []), "photo_scene.angles"):
        if isinstance(item, str):
            rows.append({"ref_id": _req_str(item, "angle"),
                         "role": "angle", "description": ""})
        elif isinstance(item, dict):
            description = item.get("description", "")
            if not isinstance(description, str):
                raise CapabilityError(
                    "pipeline.scene_reference: angle.description must be a string")
            rows.append({"ref_id": _req_str(item.get("ref_id"), "angle.ref_id"),
                         "role": "angle", "description": description.strip()})
        else:
            raise CapabilityError(
                "pipeline.scene_reference: every angle must be a string or object")
    return rows


def check_photo_scene(record: Any) -> dict[str, Any]:
    """Judge a photo-scene record: one main view, angles, place text.

    Exactly one main view is required and, in the ``pictures``
    shape, it must come first. At most four angles are carried.
    An angle with no description is ``pending``. Angles go to the
    movie branch by default: in the picture branch they are not
    applied unless ``angles_in_pictures`` is set, and either way
    the record is warned about, since a picture model has been
    seen to take an angle's camera instead of the main view's.
    A missing place description is ``pending``; one that
    describes people or comments on the photographs or their
    quality fails.
    """
    if not isinstance(record, dict):
        raise CapabilityError("pipeline.scene_reference: photo_scene must be a JSON object")
    issues: list[dict[str, Any]] = []
    rows = _photo_pictures(record)
    mains = [row for row in rows if row["role"] == "main"]
    angles = [row for row in rows if row["role"] == "angle"]
    for row in rows:
        if row["role"] not in ("main", "angle"):
            issues.append({"code": "UNKNOWN_PICTURE_ROLE", "severity": "fail",
                           "message": f"picture {row['ref_id']!r} has unknown role {row['role']!r}"})
    if not mains:
        issues.append({"code": "NO_MAIN_VIEW", "severity": "fail",
                       "message": "a photo scene needs exactly one main view; none was given"})
    elif len(mains) > 1:
        issues.append({"code": "MULTIPLE_MAIN_VIEWS", "severity": "fail",
                       "message": f"a photo scene needs exactly one main view; got {len(mains)}"})
    elif "pictures" in record and rows and rows[0] is not mains[0]:
        issues.append({"code": "MAIN_VIEW_NOT_FIRST", "severity": "fail",
                       "message": "the main view must be the first picture"})
    if len(angles) > MAX_ANGLES:
        issues.append({"code": "ANGLE_CAP", "severity": "fail",
                       "message": f"{len(angles)} angles exceed the cap of {MAX_ANGLES}"})
    for angle in angles:
        if not angle["description"]:
            issues.append({"code": "ANGLE_WITHOUT_DESCRIPTION", "severity": "pending",
                           "message": f"angle {angle['ref_id']!r} states no description of its viewpoint"})
    place = record.get("place_description", record.get("description", ""))
    if not isinstance(place, str):
        raise CapabilityError("pipeline.scene_reference: place_description must be a string")
    place = place.strip()
    if not place:
        issues.append({"code": "PLACE_DESCRIPTION_MISSING", "severity": "pending",
                       "message": "the place description is missing; it is never written in"})
    else:
        if _PEOPLE_RE.search(place) or any(word in place for word in _PEOPLE_WORDS):
            issues.append({"code": "PLACE_DESCRIPTION_CONTENT", "severity": "fail",
                           "message": "the place description must not describe people in the scene"})
        elif _QUALITY_RE.search(place) or any(word in place for word in _QUALITY_WORDS):
            issues.append({"code": "PLACE_DESCRIPTION_CONTENT", "severity": "fail",
                           "message": "the place description must not comment on the photographs or their quality"})
    create = record.get("create", "image")
    if not isinstance(create, str):
        raise CapabilityError("pipeline.scene_reference: create must be a string")
    create = create.strip()
    angles_in_pictures = record.get("angles_in_pictures", False)
    if not isinstance(angles_in_pictures, bool):
        raise CapabilityError("pipeline.scene_reference: angles_in_pictures must be a boolean")
    angles_applied = False
    if create not in ("image", "movie"):
        issues.append({"code": "UNKNOWN_CREATE_MODE", "severity": "fail",
                       "message": f"unknown branch {create!r}; expected 'image' or 'movie'"})
    elif angles:
        if create == "movie":
            angles_applied = True
        elif angles_in_pictures:
            angles_applied = True
            issues.append({"code": "ANGLES_IN_PICTURES_RISK", "severity": "warn",
                           "message": "angles are asked for in the picture branch; a picture model "
                                      "has been seen to take an angle's camera instead of the main view's"})
        else:
            issues.append({"code": "ANGLES_NOT_APPLIED_TO_IMAGE", "severity": "warn",
                           "message": "angles are recorded but not applied in the picture branch; "
                                      "they go to the movie branch by default"})
    fatal = any(i["severity"] == "fail" for i in issues)
    pending = any(i["severity"] == "pending" for i in issues)
    verdict = "fail" if fatal else ("pending" if pending else "pass")
    return {"verdict": verdict, "issues": issues,
            "main_view": mains[0]["ref_id"] if mains else None,
            "angle_count": len(angles),
            "angles_applied": angles_applied,
            "angles_for_movie": min(MOVIE_ANGLE_LIMIT, len(angles)) if create == "movie" else 0,
            "picture_count": len(rows),
            "place_description": place}


# ---------------------------------------------------------------- blocking

SCREEN_ZONES = ("left", "center", "right")
DEPTHS = ("foreground", "midground", "background")
CAMERA_RELATIONS = (
    "facing_camera",
    "back_to_camera",
    "left_profile",
    "right_profile",
    "three_quarter_left",
    "three_quarter_right",
)

# Camera relation -> character-sheet views that show the person
# that way. The catalogue has no right-profile full-body view, so
# a right profile is a portrait view only. This is a method
# default, not a measured property of any model.
_RELATION_VIEWS: dict[str, tuple[str, ...]] = {
    "facing_camera": ("face_front", "body_front"),
    "back_to_camera": ("face_back", "body_back", "clothing_back"),
    "left_profile": ("face_left", "face_3q_left", "body_left"),
    "right_profile": ("face_right", "face_3q_right"),
    "three_quarter_left": ("face_3q_left",),
    "three_quarter_right": ("face_3q_right",),
}


def _cast_names(cast: Any) -> list[str]:
    if cast is None:
        return []
    names: list[str] = []
    for item in _req_list(cast, "blocking.cast"):
        if isinstance(item, str):
            names.append(_req_str(item, "cast member"))
        elif isinstance(item, dict):
            names.append(_req_str(item.get("name"), "cast member.name"))
        else:
            raise CapabilityError("pipeline.scene_reference: every cast member must be a string or object")
    return names


def _sheet_current_views(sheet: Any) -> list[str] | None:
    if sheet is None:
        return None
    if not isinstance(sheet, dict):
        raise CapabilityError("pipeline.scene_reference: character_sheet must be a JSON object")
    views = sheet.get("views")
    if views is None:
        return None
    current: list[str] = []
    for item in _req_list(views, "character_sheet.views"):
        if isinstance(item, str):
            current.append(_req_str(item, "view"))
        elif isinstance(item, dict):
            status = item.get("status", "current")
            if status == "current":
                current.append(_req_str(item.get("view"), "view"))
        else:
            raise CapabilityError("pipeline.scene_reference: every sheet view must be a string or object")
    return current


def check_blocking(record: Any) -> dict[str, Any]:
    """Judge a blocking record: markers bound to cast, zone, depth.

    Every marker needs a screen zone, a depth and a camera
    relation, and an explicit declaration that the marker does
    not appear in the finished film -- a missing declaration
    fails. A marker bound to nobody is recorded as a person
    distinct from the cast; one bound to a name outside the cast
    fails. A marker's view and visible parts are checked against
    the character sheet gate's catalogue and part-scope table:
    a face shown from behind, a part that is not visible from
    the marker's view, a view that contradicts the camera
    relation, or a view the sheet does not carry all fail and
    name the marker, the person and the part or view.
    """
    if not isinstance(record, dict):
        raise CapabilityError("pipeline.scene_reference: blocking must be a JSON object")
    markers = _req_list(record.get("markers", []), "blocking.markers")
    cast = _cast_names(record.get("cast"))
    sheet_views = _sheet_current_views(record.get("character_sheet"))
    issues: list[dict[str, Any]] = []
    normalised: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in markers:
        if not isinstance(item, dict):
            raise CapabilityError("pipeline.scene_reference: every marker must be an object")
        marker_id = _req_str(item.get("marker_id"), "marker.marker_id")
        if marker_id in seen_ids:
            issues.append({"code": "DUPLICATE_MARKER", "severity": "fail",
                           "message": f"marker {marker_id!r} appears more than once"})
        seen_ids.add(marker_id)
        character = item.get("character", "")
        role = item.get("role", "")
        if not isinstance(character, str) or not isinstance(role, str):
            raise CapabilityError("pipeline.scene_reference: marker character and role must be strings")
        character = character.strip()
        role = role.strip()
        bound = character or role
        if character and cast and character not in cast:
            issues.append({"code": "UNKNOWN_BLOCKING_CHARACTER", "severity": "fail",
                           "message": f"marker {marker_id!r} is bound to {character!r}, "
                                      "who is not in the cast"})
        if not bound:
            issues.append({"code": "UNBOUND_MARKER", "severity": "warn",
                           "message": f"marker {marker_id!r} is bound to nobody; "
                                      "it is recorded as a person distinct from the cast"})
        declared = item.get("placeholder_not_in_film") is True
        declaration = item.get("placeholder_declaration", "")
        if isinstance(declaration, str) and declaration.strip():
            declared = True
        if not declared:
            issues.append({"code": "MISSING_PLACEHOLDER_DECLARATION", "severity": "fail",
                           "message": f"marker {marker_id!r} carries no explicit declaration "
                                      "that the marker does not appear in the finished film"})
        zone = item.get("screen_zone", "")
        depth = item.get("depth", "")
        relation = item.get("camera_relation", "")
        if not isinstance(zone, str) or not isinstance(depth, str) or not isinstance(relation, str):
            raise CapabilityError("pipeline.scene_reference: marker zone, depth and relation must be strings")
        zone, depth, relation = zone.strip(), depth.strip(), relation.strip()
        if not zone:
            issues.append({"code": "MISSING_SCREEN_ZONE", "severity": "fail",
                           "message": f"marker {marker_id!r} states no screen zone"})
        elif zone not in SCREEN_ZONES:
            issues.append({"code": "UNKNOWN_SCREEN_ZONE", "severity": "fail",
                           "message": f"marker {marker_id!r} has unknown screen zone {zone!r}"})
        if not depth:
            issues.append({"code": "MISSING_DEPTH", "severity": "fail",
                           "message": f"marker {marker_id!r} states no depth"})
        elif depth not in DEPTHS:
            issues.append({"code": "UNKNOWN_DEPTH", "severity": "fail",
                           "message": f"marker {marker_id!r} has unknown depth {depth!r}"})
        if not relation:
            issues.append({"code": "MISSING_CAMERA_RELATION", "severity": "fail",
                           "message": f"marker {marker_id!r} states no camera relation"})
        elif relation not in CAMERA_RELATIONS:
            issues.append({"code": "UNKNOWN_CAMERA_RELATION", "severity": "fail",
                           "message": f"marker {marker_id!r} has unknown camera relation {relation!r}"})
        view = item.get("view", "")
        if not isinstance(view, str):
            raise CapabilityError("pipeline.scene_reference: marker view must be a string")
        view = view.strip()
        if view:
            if view not in VIEW_IDS:
                issues.append({"code": "UNKNOWN_VIEW", "severity": "fail",
                               "message": f"marker {marker_id!r} has unknown view {view!r}"})
            else:
                if relation in _RELATION_VIEWS and view not in _RELATION_VIEWS[relation]:
                    issues.append({"code": "BLOCKING_VIEW_RELATION_CONFLICT", "severity": "fail",
                                   "message": f"marker {marker_id!r} ({bound or 'unbound'}) pairs view "
                                              f"{view!r} with camera relation {relation!r}, which shows "
                                              f"{', '.join(_RELATION_VIEWS[relation])}"})
                if sheet_views is not None and view not in sheet_views:
                    issues.append({"code": "BLOCKING_VIEW_NOT_IN_SHEET", "severity": "fail",
                                   "message": f"marker {marker_id!r} ({bound or 'unbound'}) uses view "
                                              f"{view!r}, which the character sheet does not carry"})
        parts = item.get("visible_parts", [])
        part_list = _req_list(parts, "marker.visible_parts")
        for part in part_list:
            if not isinstance(part, str):
                raise CapabilityError("pipeline.scene_reference: every visible part must be a string")
            part = part.strip()
            if part not in PART_IDS:
                issues.append({"code": "UNKNOWN_PART", "severity": "fail",
                               "message": f"marker {marker_id!r} names unknown part {part!r}"})
                continue
            if not view or view not in VIEW_IDS:
                continue
            if part == "face" and view in REAR_VIEWS:
                issues.append({"code": "BLOCKING_FACE_IN_REAR_VIEW", "severity": "fail",
                               "message": f"marker {marker_id!r} ({bound or 'unbound'}) shows face "
                                          f"from rear view {view!r}"})
            elif view not in DEFAULT_PART_TABLE[part]["views"]:
                issues.append({"code": "BLOCKING_PART_SCOPE", "severity": "fail",
                               "message": f"marker {marker_id!r} ({bound or 'unbound'}) shows part "
                                          f"{part!r}, which is not visible from view {view!r}"})
        normalised.append({"marker_id": marker_id,
                           "character": character or None, "role": role or None,
                           "bound_to": bound or None,
                           "distinct_from_cast": not bool(bound),
                           "placeholder_declared": declared,
                           "screen_zone": zone or None, "depth": depth or None,
                           "camera_relation": relation or None, "view": view or None})
    fatal = any(i["severity"] == "fail" for i in issues)
    return {"verdict": "fail" if fatal else "pass", "issues": issues,
            "markers": normalised, "marker_count": len(normalised)}


# ---------------------------------------------------------------- output precheck

H3_FPS = 24
H3_FRAME_STEP = 17
H3_FRAME_OFFSET = 5
H3_GRID = 32
CROP_GRID = 16
DEFAULT_TARGET_MEGAPIXELS = 0.4


# ---------------------------------------------------------------- frame truth
#
# SINGLE SOURCE OF TRUTH for frame counts (2026-10-31). Two routes
# disagree about "10 seconds" and both are right -- for their own
# route, never interchangeably:
# * H3 / SceneRef lattice (``route="h3"``): 17k + 5 frames, so 10 s
#   at 24 fps is 243 frames (10.125 s of picture).
# * FastH3 local execution (``route="fasth3_local"``): frames =
#   round(seconds * 24), locked to [124, 360] in
#   video.fasth3_local, so 10 s is 240 frames (10.0 s).
# Every prompt that states a frame count must say which route it
# used. Any other route (a provider key that is neither) counts
# frames as round(seconds * fps) and names the provider. Never
# silently mix the two: a prompt written for one route and rendered
# on the other drifts by 3 frames per 10 seconds.


def canonical_frame_count(seconds: float, fps: float = H3_FPS, route: str = "h3") -> int:
    """Frame count for ``seconds`` on one named execution route.

    ``route="h3"`` snaps to the 17k+5 lattice; ``route="fasth3_local"``
    rounds to the nearest frame; any other route name also rounds
    and is recorded by the caller. Plan arithmetic only.
    """
    for value, what in ((seconds, "seconds"), (fps, "fps")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise CapabilityError(f"pipeline.scene_reference: {what} must be a finite number")
    if seconds <= 0 or fps <= 0:
        raise CapabilityError("pipeline.scene_reference: seconds and fps must be positive")
    if route == "h3":
        frames = max(H3_FRAME_OFFSET, int(round(seconds * fps)))
        return frames + (H3_FRAME_OFFSET - frames % H3_FRAME_STEP) % H3_FRAME_STEP
    if not isinstance(route, str) or not route.strip():
        raise CapabilityError("pipeline.scene_reference: route must be a non-empty string")
    return max(1, int(round(seconds * fps)))


def h3_frame_count(seconds: float, fps: float = H3_FPS) -> int:
    """Snap a duration to the H3 frame lattice: 17k + 5 frames.

    At 24 fps, 5 seconds snaps to 124 frames (5.167 seconds of
    picture). Short requests floor at 5 frames. This is plan
    arithmetic only; it does not change any other capability's
    locked execution values. Delegates to
    :func:`canonical_frame_count` with ``route="h3"``.
    """
    return canonical_frame_count(seconds, fps, route="h3")


def fasth3_frame_count(seconds: float, fps: float = H3_FPS) -> int:
    """Frame count on the FastH3 local route: round(seconds * fps).

    At 24 fps, 10 seconds is 240 frames -- not the 243 of the H3
    lattice. The [124, 360] lock itself lives in
    video.fasth3_local and is enforced there, not here.
    """
    return canonical_frame_count(seconds, fps, route="fasth3_local")


def h3_output_size(width: int, height: int, megapixels: float = DEFAULT_TARGET_MEGAPIXELS,
                   grid: int = H3_GRID) -> tuple[int, int]:
    """Snap a frame size to about ``megapixels``, both sides on ``grid``.

    The aspect is kept: the frame is scaled to the target area
    and each side is rounded to the nearest grid multiple. Plan
    arithmetic only; no picture is resized here.
    """
    for value, what in ((width, "width"), (height, "height"), (grid, "grid")):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise CapabilityError(f"pipeline.scene_reference: {what} must be a positive integer")
    if isinstance(megapixels, bool) or not isinstance(megapixels, (int, float)) \
            or not math.isfinite(megapixels) or megapixels <= 0:
        raise CapabilityError("pipeline.scene_reference: megapixels must be a positive number")
    scale = math.sqrt(megapixels * 1_000_000 / (width * height))
    return (max(grid, round(width * scale / grid) * grid),
            max(grid, round(height * scale / grid) * grid))


def _parse_ratio(value: Any) -> float:
    if isinstance(value, bool):
        raise CapabilityError("pipeline.scene_reference: aspect must be a number or 'W:H' text")
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value <= 0:
            raise CapabilityError("pipeline.scene_reference: aspect must be positive")
        return float(value)
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) == 2:
            try:
                numerator, denominator = float(parts[0]), float(parts[1])
            except ValueError:
                raise CapabilityError(
                    f"pipeline.scene_reference: unparseable aspect {value!r}") from None
            if numerator > 0 and denominator > 0:
                return numerator / denominator
        raise CapabilityError(f"pipeline.scene_reference: unparseable aspect {value!r}")
    raise CapabilityError("pipeline.scene_reference: aspect must be a number or 'W:H' text")


def _centred_crop(width: int, height: int, ratio: float) -> tuple[int, int, int, int]:
    """Centred crop of a frame to ``ratio``: (left, top, width, height)."""
    if width / height > ratio:
        cropped_width = int(height * ratio) // CROP_GRID * CROP_GRID
        return (width - cropped_width) // 2, 0, cropped_width, height
    cropped_height = int(width / ratio) // CROP_GRID * CROP_GRID
    return 0, (height - cropped_height) // 2, width, cropped_height


def _positive_int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CapabilityError(f"pipeline.scene_reference: {what} must be a positive integer")
    return value


def check_output_plan(plan: Any) -> dict[str, Any]:
    """Precheck a delivery plan: frame lattice, grid size, declared crops.

    ``seconds`` (at ``fps``, default 24) snaps to the frame
    lattice; a ``requested_frames`` value that disagrees with the
    snap fails. The output size snaps to the grid at
    ``target_megapixels`` (default 0.4). A ``target_aspect`` that
    differs from the source aspect needs a crop, and a
    ``delivery_frames`` value below the snapped count needs a
    delivery crop: either crop without a declaration in the plan
    fails and names the numbers. Nothing here generates, crops
    or resizes a picture.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("pipeline.scene_reference: output plan must be a JSON object")
    issues: list[dict[str, Any]] = []
    seconds = plan.get("seconds")
    fps = plan.get("fps", H3_FPS)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) \
            or not math.isfinite(fps) or fps <= 0:
        raise CapabilityError("pipeline.scene_reference: fps must be a positive number")
    frames: int | None = None
    if seconds is not None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) \
                or not math.isfinite(seconds) or seconds <= 0:
            raise CapabilityError("pipeline.scene_reference: seconds must be a positive number")
        frames = h3_frame_count(seconds, fps)
    requested = plan.get("requested_frames")
    if requested is not None:
        requested = _positive_int(requested, "requested_frames")
        if frames is not None and requested != frames:
            issues.append({"code": "REQUESTED_FRAMES_OFF_LATTICE", "severity": "fail",
                           "message": f"requested {requested} frames, but {seconds} s at {fps} fps "
                                      f"snaps to {frames} frames on the 17k+5 lattice"})
        elif frames is None:
            if requested < H3_FRAME_OFFSET or (requested - H3_FRAME_OFFSET) % H3_FRAME_STEP != 0:
                issues.append({"code": "REQUESTED_FRAMES_OFF_LATTICE", "severity": "fail",
                               "message": f"requested {requested} frames is not on the 17k+5 lattice"})
            frames = requested
    if frames is None:
        raise CapabilityError(
            "pipeline.scene_reference: an output plan needs seconds or requested_frames")
    source_width = _positive_int(
        plan.get("source_width", plan.get("width")), "source_width")
    source_height = _positive_int(
        plan.get("source_height", plan.get("height")), "source_height")
    megapixels = plan.get("target_megapixels", DEFAULT_TARGET_MEGAPIXELS)
    if isinstance(megapixels, bool) or not isinstance(megapixels, (int, float)) \
            or not math.isfinite(megapixels) or megapixels <= 0:
        raise CapabilityError("pipeline.scene_reference: target_megapixels must be a positive number")
    crop: dict[str, Any] | None = None
    base_width, base_height = source_width, source_height
    cropped = False
    target_aspect = plan.get("target_aspect")
    if target_aspect is not None:
        ratio = _parse_ratio(target_aspect)
        left, top, cropped_width, cropped_height = _centred_crop(
            source_width, source_height, ratio)
        if (cropped_width, cropped_height) != (source_width, source_height):
            cropped = True
            crop = {"left": left, "top": top, "width": cropped_width, "height": cropped_height,
                    "aspect": str(target_aspect)}
            base_width, base_height = cropped_width, cropped_height
            declared = plan.get("crop_declared") is True or isinstance(plan.get("crop"), dict)
            if not declared:
                issues.append({"code": "UNDECLARED_CROP", "severity": "fail",
                               "message": f"framing {source_width}x{source_height} to aspect "
                                          f"{target_aspect} crops to {cropped_width}x{cropped_height}; "
                                          "the crop must be declared in the plan"})
    output_width, output_height = h3_output_size(base_width, base_height, megapixels)
    delivery_frames: int | None = None
    delivery_declared = plan.get("delivery_crop_declared") is True \
        or isinstance(plan.get("delivery_crop"), dict)
    if plan.get("delivery_frames") is not None:
        delivery_frames = _positive_int(plan.get("delivery_frames"), "delivery_frames")
        if delivery_frames != frames and not delivery_declared:
            issues.append({"code": "UNDECLARED_DELIVERY_CROP", "severity": "fail",
                           "message": f"delivering {delivery_frames} frames from a {frames}-frame "
                                      "clip is a crop; it must be declared in the plan"})
    fatal = any(i["severity"] == "fail" for i in issues)
    return {"verdict": "fail" if fatal else "pass", "issues": issues,
            "frames": frames, "frame_seconds": frames / fps,
            "source_width": source_width, "source_height": source_height,
            "output_width": output_width, "output_height": output_height,
            "cropped": cropped, "crop": crop,
            "delivery_frames": delivery_frames}


# ---------------------------------------------------------------- combined

def check_scene_reference(plan: dict[str, Any]) -> dict[str, Any]:
    """Judge one scene-reference plan: prompt, assembly, final text,
    and any photo-scene, blocking or output sections it carries."""
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
    photo_result: dict[str, Any] | None = None
    if "photo_scene" in plan:
        photo_result = check_photo_scene(plan.get("photo_scene"))
        issues += photo_result["issues"]
    blocking_result: dict[str, Any] | None = None
    if "blocking" in plan:
        blocking_result = check_blocking(plan.get("blocking"))
        issues += blocking_result["issues"]
    output_result: dict[str, Any] | None = None
    if "output" in plan:
        output_result = check_output_plan(plan.get("output"))
        issues += output_result["issues"]
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
            "final": final_result, "photo_scene": photo_result,
            "blocking": blocking_result, "output": output_result}


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
            "assembly record with picture/voice slot budgets, an "
            "intent/final separation gate, a photo-scene record, a "
            "blocking record checked against the character sheet "
            "gate, and a frame/size output precheck. Judges and "
            "assembles JSON plans only; no image is generated here."
        ),
        line="pipeline",
    ))
    return ["pipeline.scene_reference"]


register_scene_reference_capabilities_once()
