"""Reference numbering gate (``qa.reference_numbering_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-h3-exemplar-prompts.md``
section 4, gap 1: a reference set is only usable when the numbering
convention it was mounted under is declared in the plan and the
pictures actually follow it. Two conventions exist in hevi and they
disagree about Picture 1, so silence is a swap waiting to happen:

* ``identity-first`` -- the H3 exemplar order: Picture 1 is the
  person (``identity``), Picture 2 is the overhead composition
  (``camera_composition``), Picture 3 is the environment
  (``scene``).
* ``scene-first`` -- the six-section H3 order of
  ``pipeline.scene_reference`` (scene first as Subject 1, other
  angles next, cast last): Picture 1 is the ``scene`` and every
  cast role (``identity`` / ``costume`` / ``pose``) comes after
  every scene / angle picture.

This module never redefines ``H3_SECTIONS``: the six-section
structure stays the single definition in
``pipeline.scene_reference``. This gate judges the *mounting*
(number -> role order, plus audio registration), not the prompt
sections.

Three further disciplines:

1. ``camera_composition`` is its own role, never ``pose`` stretched.
   A composition picture takes composition geometry only -- the
   framing of the overhead shot, not the face, not the costume,
   not the environment. Every ``camera_composition`` picture must
   declare ``composition_only`` exactly ``True``; a composition
   picture mounted under ``pose`` fails outright, and one file
   bound to two different roles fails as a role conflict.
2. Audio references are registered, not mentioned. Each audio
   entry carries a file, a sha256 binding, and a local-clock
   start (``local_start_s`` seconds, or a ``local_start``
   timecode such as ``00:00.000``). A filename the plan mentions
   (``audio_mentions`` / ``audio_file``) without a matching
   registration fails.
3. The H3 scene-assembly route is judged here, never deferred.
   Unlike ``qa.reference_role_gate``, whose four-image cap yields
   to the H3 slot budget with ``not_checked``, this gate has no
   ``not_checked`` verdict at all: a plan that declares
   ``route: "h3_scene_assembly"`` without a numbering convention
   fails, and one with a convention is judged against it. Either
   the numbering is judged, or it fails loudly -- it is never
   waved through.

This module judges plans only. It reads no image or audio bytes
and calls no generator.
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

NUMBERING_CONVENTIONS = ("identity-first", "scene-first")

ROLES = ("identity", "costume", "pose", "scene", "camera_composition")

# Exemplar (identity-first) mounting for the first three numbers.
IDENTITY_FIRST_MAP = {
    1: "identity",
    2: "camera_composition",
    3: "scene",
}

# Scene-first: cast roles come last, after scene / angle pictures.
_CAST_ROLES = ("identity", "costume", "pose")
_ANGLE_ROLES = ("scene", "camera_composition")

_TIMECODE_RE = re.compile(
    r"^(?:(\d+):)?([0-5]?\d):([0-5]?\d(?:\.\d+)?)$"
)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_local_start(value: Any) -> float | None:
    """Parse a local-clock start to seconds, or None when unparseable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds if seconds >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        match = _TIMECODE_RE.match(text)
        if match:
            hours = int(match.group(1)) if match.group(1) else 0
            return hours * 3600 + int(match.group(2)) * 60 + float(match.group(3))
        try:
            seconds = float(text)
        except ValueError:
            return None
        return seconds if seconds >= 0 else None
    return None


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def check_reference_numbering(plan: Any) -> dict[str, Any]:
    """Judge one mounted reference set. Returns a report; never raises for a bad plan.

    Verdicts are ``pass`` / ``fail`` only. There is no ``not_checked``:
    the H3 scene-assembly route is judged under its declared
    convention, and an undeclared convention fails.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> None:
        issues.append({"code": code, "detail": detail})

    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "convention": None,
            "route": None,
            "pictures": {},
            "audio": [],
            "issues": [{
                "code": "plan_not_object",
                "detail": "qa.reference_numbering_gate: reference plan "
                         "must be an object",
            }],
        }
    route = plan.get("route", "generation")
    convention = plan.get("numbering_convention")
    if not _is_nonempty_str(convention):
        fail("missing_numbering_convention",
             "qa.reference_numbering_gate: the plan declares no "
             "'numbering_convention' (identity-first or scene-first); "
             "without a declared convention a Picture 1 mount is "
             "ambiguous -- person under one order, scene under the "
             "other -- and the H3 assembly route is judged here, "
             "never left not_checked")
        convention = None
    elif convention not in NUMBERING_CONVENTIONS:
        fail("unsupported_numbering_convention",
             f"qa.reference_numbering_gate: numbering_convention "
             f"{convention!r} is not supported; use one of "
             f"{', '.join(NUMBERING_CONVENTIONS)}")
        convention = None

    pictures = plan.get("pictures")
    numbered: dict[int, dict[str, Any]] = {}
    if not isinstance(pictures, list) or not pictures:
        fail("pictures_missing",
             "qa.reference_numbering_gate: the plan needs a non-empty "
             "'pictures' list mounted in number order")
        pictures = []
    else:
        numbers: list[int] = []
        seen_files: dict[str, str] = {}
        for index, picture in enumerate(pictures):
            label = f"picture {index + 1}"
            if not isinstance(picture, dict):
                fail("picture_not_object",
                     f"qa.reference_numbering_gate: {label} must be an object")
                continue
            number = picture.get("number")
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                fail("bad_picture_number",
                     f"qa.reference_numbering_gate: {label} needs an "
                     f"integer 'number' >= 1, got {number!r}")
                continue
            numbers.append(number)
            if number in numbered:
                fail("duplicate_picture_number",
                     f"qa.reference_numbering_gate: Picture {number} is "
                     "mounted twice; one number, one picture")
                continue
            role = picture.get("role")
            entry: dict[str, Any] = {"number": number, "role": role}
            if role not in ROLES:
                fail("bad_role",
                     f"qa.reference_numbering_gate: {label} (Picture "
                     f"{number}) role must be one of "
                     f"{', '.join(ROLES)}, not {role!r}")
            if not _is_nonempty_str(picture.get("file")):
                fail(f"missing_file_picture_{number}",
                     f"qa.reference_numbering_gate: Picture {number} "
                     "needs a 'file' binding")
            else:
                entry["file"] = str(picture["file"]).strip()
                key = _basename(entry["file"])
                if key in seen_files and seen_files[key] != role:
                    fail("file_role_conflict",
                         f"qa.reference_numbering_gate: file "
                         f"{entry['file']!r} is bound to two roles "
                         f"({seen_files[key]!r} and {role!r}); one file, "
                         "one job -- a composition picture must not "
                         "also stand in as the identity")
                else:
                    seen_files[key] = role  # type: ignore[assignment]
            if not _is_nonempty_str(picture.get("sha256")):
                fail(f"missing_sha256_picture_{number}",
                     f"qa.reference_numbering_gate: Picture {number} "
                     "needs a 'sha256' binding so the file is the file "
                     "that was reviewed")
            else:
                entry["sha256"] = str(picture["sha256"]).strip()
            if not _is_nonempty_str(picture.get("duty")):
                fail(f"missing_duty_picture_{number}",
                     f"qa.reference_numbering_gate: Picture {number} "
                     "needs a non-empty 'duty' naming what it governs")
            else:
                entry["duty"] = str(picture["duty"]).strip()
            if role == "camera_composition" and picture.get("composition_only") is not True:
                fail("composition_only_undeclared",
                     f"qa.reference_numbering_gate: Picture {number} "
                     "claims role 'camera_composition' but does not "
                     "declare composition_only exactly true; a "
                     "composition picture takes composition geometry "
                     "only -- not the face, not the costume, not the "
                     "environment -- and the declaration must say so")
            numbered[number] = entry
        if numbers and numbers != list(range(1, len(pictures) + 1)):
            fail("numbering_order_mismatch",
                 "qa.reference_numbering_gate: 'pictures' must be "
                 "mounted in ascending number order, contiguous from "
                 f"Picture 1, got numbers {numbers}; the mount order "
                 "is the convention -- a shuffled list silently "
                 "reassigns every role")
        attachment_order = plan.get("attachment_order")
        if attachment_order is not None:
            if isinstance(attachment_order, list):
                attached = [
                    _basename(str(item)) if _is_nonempty_str(item)
                    else item for item in attachment_order
                ]
                mounted = [_basename(str(p.get("file", "")))
                           for p in pictures if isinstance(p, dict)]
                if attached != mounted:
                    fail("attachment_order_mismatch",
                         "qa.reference_numbering_gate: 'attachment_order' "
                         f"{attached} does not match the mounted picture "
                         f"order {mounted}; the declared convention "
                         "must match the files as attached, not only "
                         "as listed")
            else:
                fail("bad_attachment_order",
                     "qa.reference_numbering_gate: 'attachment_order' "
                     "must be a list when supplied")

    if convention == "identity-first":
        for number, expected_role in IDENTITY_FIRST_MAP.items():
            entry = numbered.get(number)
            if entry is None:
                continue
            if entry["role"] != expected_role:
                if number == 2 and entry["role"] == "pose":
                    fail("pose_stretched_for_composition",
                         "qa.reference_numbering_gate: identity-first "
                         "Picture 2 is the overhead composition, not a "
                         "pose -- mounting it under 'pose' stretches "
                         "the pose duty (starting/key pose) over "
                         "composition geometry; use role "
                         "'camera_composition' with composition_only "
                         "declared")
                else:
                    fail("identity_first_role_mismatch",
                         f"qa.reference_numbering_gate: identity-first "
                         f"Picture {number} must be role "
                         f"{expected_role!r}, not {entry['role']!r}")
        identity_numbers = [n for n, e in numbered.items() if e["role"] == "identity"]
        if identity_numbers and identity_numbers != [1]:
            fail("identity_first_identity_not_first",
                 "qa.reference_numbering_gate: identity-first mounts "
                 f"the identity at Picture {identity_numbers}, not "
                 "Picture 1; the person is Picture 1 under this "
                 "convention")
    elif convention == "scene-first":
        first = numbered.get(1)
        if first is not None and first["role"] != "scene":
            fail("scene_first_picture1_not_scene",
                 "qa.reference_numbering_gate: scene-first Picture 1 "
                 f"must be the scene, not {first['role']!r}; the "
                 "six-section order mounts the scene first")
        angle_numbers = [n for n, e in numbered.items() if e["role"] in _ANGLE_ROLES]
        cast_numbers = [n for n, e in numbered.items() if e["role"] in _CAST_ROLES]
        if angle_numbers and cast_numbers and max(angle_numbers) > min(cast_numbers):
            fail("cast_not_last",
                 "qa.reference_numbering_gate: scene-first mounts cast "
                 "last -- cast pictures "
                 f"{sorted(cast_numbers)} must come after every scene "
                 f"/ angle picture {sorted(angle_numbers)}")

    audio_entries = plan.get("audio_references")
    registered: list[dict[str, Any]] = []
    registered_files: set[str] = set()
    if audio_entries is not None:
        if not isinstance(audio_entries, list):
            fail("bad_audio_references",
                 "qa.reference_numbering_gate: 'audio_references' must "
                 "be a list when supplied")
        else:
            for index, entry in enumerate(audio_entries):
                label = f"audio reference {index + 1}"
                if not isinstance(entry, dict):
                    fail("audio_reference_not_object",
                         f"qa.reference_numbering_gate: {label} must be "
                         "an object")
                    continue
                record: dict[str, Any] = {}
                if not _is_nonempty_str(entry.get("file")):
                    fail("audio_reference_missing_file",
                         f"qa.reference_numbering_gate: {label} needs a "
                         "'file' (audio filename)")
                else:
                    record["file"] = str(entry["file"]).strip()
                    if _basename(record["file"]) in registered_files:
                        fail("duplicate_audio_reference",
                             f"qa.reference_numbering_gate: audio file "
                             f"{record['file']!r} is registered twice")
                    registered_files.add(_basename(record["file"]))
                if not _is_nonempty_str(entry.get("sha256")):
                    fail("audio_reference_missing_sha256",
                         f"qa.reference_numbering_gate: {label} needs a "
                         "'sha256' binding")
                else:
                    record["sha256"] = str(entry["sha256"]).strip()
                start = _parse_local_start(
                    entry.get("local_start_s", entry.get("local_start")))
                if start is None:
                    fail("audio_reference_missing_local_start",
                         f"qa.reference_numbering_gate: {label} needs a "
                         "local-clock start ('local_start_s' seconds or "
                         "a 'local_start' timecode such as 00:00.000); "
                         "an audio slice without its local start cannot "
                         "be placed against the segment")
                else:
                    record["local_start_s"] = start
                registered.append(record)
    mentions: list[str] = []
    for field in ("audio_mentions",):
        value = plan.get(field)
        if value is not None:
            if isinstance(value, list):
                mentions.extend(str(v).strip() for v in value if _is_nonempty_str(v))
            else:
                fail("bad_audio_mentions",
                     "qa.reference_numbering_gate: 'audio_mentions' "
                     "must be a list of filenames when supplied")
    if _is_nonempty_str(plan.get("audio_file")):
        mentions.append(str(plan["audio_file"]).strip())
    for mentioned in mentions:
        if _basename(mentioned) not in registered_files:
            fail("unregistered_audio_reference",
                 f"qa.reference_numbering_gate: audio file "
                 f"{mentioned!r} is mentioned by the plan but has no "
                 "audio_references registration (file + sha256 + "
                 "local-clock start); unregistered audio is refused")

    ok = not issues
    return {
        "ok": ok,
        "verdict": "pass" if ok else "fail",
        "convention": convention,
        "route": route,
        "route_judged": True,
        "pictures": {str(n): e for n, e in sorted(numbered.items())},
        "audio": registered,
        "issues": issues,
    }


def authorize_reference_numbering(plan: Any) -> dict[str, Any]:
    """Approve a mounted reference set, or refuse it loudly (raises CapabilityError)."""
    report = check_reference_numbering(plan)
    if not report["ok"]:
        raise CapabilityError(
            "qa.reference_numbering_gate: reference mounting refused: "
            + "; ".join(i["detail"] for i in report["issues"])
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = authorize_reference_numbering(params.get("plan"))
    report_path = out_dir / "reference_numbering_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_reference_numbering_gate_capabilities_once() -> list[str]:
    """Register ``qa.reference_numbering_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_numbering_gate",
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
                "Reference numbering gate: the numbering convention "
                "(identity-first or scene-first) must be declared and "
                "the mounted pictures must follow it in number order; "
                "the overhead composition is its own "
                "camera_composition role (composition geometry only, "
                "never pose stretched); audio references are "
                "registered with file, sha256 and a local-clock start, "
                "and unregistered audio fails. The H3 scene-assembly "
                "route is judged here and never returns not_checked. "
                "Judges plans only; does not redefine H3_SECTIONS."
            ),
            line="qa",
        )
    )
    return ["qa.reference_numbering_gate"]


register_reference_numbering_gate_capabilities_once()
