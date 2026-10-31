"""Beat-schema prompt compiler (``story.prompt_compiler``).

Clean-room implementation, 2026-10-26. No prompt text or code is copied
from any external repository: the schema, the five compile gates, the
line-duration estimator and the prompt template wording below are all
newly written for hevi.

What this module does
---------------------
A dramatic episode is encoded once, as JSON-shaped dicts, in the
beat schema (see :func:`compile_episode` docstring for the field
list). The compiler then:

* validates every value against closed vocabularies (shot size,
  camera angle, camera movement, line mode, speech pace);
* runs five gates, in order. Any gate failure raises
  :class:`PromptCompilerError` naming the exact shot, beat, line or
  state item -- never a warning that lets a bad script through to
  generation;
* renders one prompt text per shot, in a fixed section order, with
  lines taken verbatim from the schema and nothing else spoken.

Vocabulary provenance (stated here, not hidden)
------------------------------------------------
* Camera movements come from hevi's own
  ``hevi.capabilities.cinematic_techniques`` data file
  (``cinematic_data/camera_movements.json``: 40 movements, each with
  an ``id``, a Chinese name and an English name). The compiler loads
  that table at run time, so a movement id that does not exist there
  cannot pass validation -- no movement id is invented here.
* Shot sizes and camera angles are standard film grammar, defined
  in this module (see ``SHOT_SIZES`` / ``ANGLES``); they are not
  taken from any supplier catalogue.

Line-duration estimator
-----------------------
``estimate_min_line_duration_s`` converts a line to a minimum
planned duration: characters per second by pace tier, plus a fixed
0.3-0.5s pause allowance per punctuation mark (fixed at 0.4s, the
midpoint, so results are deterministic), plus a fixed 1.0s head/tail
margin. Pace tiers: default 4 chars/s, fast (urgent) 4 chars/s,
normal 3 chars/s, slow (tender / whisper) 2 chars/s. A beat that
omits ``pace`` uses the default tier (4 chars/s); a beat may also
spell the tier in Chinese (urgent/normal/tender/whisper aliases are
accepted and normalised).

Long lines
----------
A single beat line longer than 20 content characters must be split
across consecutive beats of the same shot: the beats share a
``line_group`` id, the same speaker and line mode, and the first beat
may carry ``line_full``. An unsplit long line is a compile failure
naming the line -- it is never silently truncated.

Continuity rule (gate 4)
------------------------
``continuity`` carries ``entry_state``, ``exit_state`` and
``new_changes``. States are nested dicts in five categories
(people / costume / props / gaze / anchor, keyed in Chinese as
``人物`` / ``服装`` / ``道具`` / ``视线`` / ``空间锚点``); the
compiler flattens them to dotted keys for comparison. For every shot
after the first, the entry state must equal the previous shot's exit
state plus exactly the declared ``new_changes``: every carried key
must be unchanged, every changed or added key must be declared with
its new value, and every declared change must appear in the entry.
A dropped key with no removal declaration also fails. A null value
in ``new_changes`` is the removal declaration itself: ``_flatten_state``
preserves None (it used to stringify it to "None", which made every
null removal fail gate 4 -- fixed, see gate 4).

Start-frame rule (gate 4, second half)
--------------------------------------
``camera.start_frame`` must be a dict with ``state_kind`` exactly
``"trigger_in_progress"``: the frame shows the triggering moment
still unfinished. Any other marker (``"completed"``,
``"result"``, ``"landed"``, or a missing marker) fails, naming the
shot. The check reads the marker only; it does not guess from the
description text, so a script that describes a result state must
also mark it honestly -- and then it fails, as intended.

Duration tiers (gate 5, second half)
-------------------------------------
Tier values live in ``model_catalog_data/duration_tiers.json`` next
to the provider/model catalogues, loaded by default at compile time.
Each entry is a single-generation cap with a cited hevi source:
``hevi/providers/facts.py`` PROVIDER_CATALOGUE
``max_duration_s`` rows, ``hevi/video/pixstag_client.py``
DURATION_MIN/MAX, and ``hevi/capabilities/fasth3_local.py``
MIN/MAX_FRAMES over FPS. No episode-total cap is verified anywhere,
so ``max_total_s`` is null in every entry, never invented.
The tier is checked per generation call, i.e. per clip: a shot may
carry an explicit ``clips`` list (each clip names its beats by
beat_no; a clip's duration is the sum of its beats' spans), and
gate 5 checks every clip against [min_shot_s, max_shot_s]. A shot
with ``clips == []`` is pure still -- no generation call -- and is
not tier-checked at all. A shot without a ``clips`` key keeps the
legacy unit: the whole shot duration, as one generation call.
Beat-level segments (2-3s actions) are not clips and are never
tier-checked; gates 1/2 already govern them.
Resolution order: explicit ``provider_caps`` win; otherwise a
``provider`` name resolves through the tier table; otherwise the
tier verdict is ``"unknown"``. A table entry with null caps, or a
provider with no table entry, also resolves to ``"unknown"`` with
that reason -- recorded, never used to clamp, pad or truncate, and
never blocking compilation. The total-duration check runs in all
cases. Nothing is ever clamped, padded or truncated to fit a tier.

Start-frame marker contract (by design, not a gap)
--------------------------------------------------
The ``state_kind`` marker is a script-layer honesty contract, not a
compiler-detectable fact: the compiler checks marker presence and
rejects result-state markers, but it does not guess the picture's
semantic state from description text, and it must not pretend to.
Semantic truth of a start frame belongs to two other layers: the
image-level endpoint check (``frame_consistency.check_clip_endpoints``,
which compares designed frames against generated clip pixels) and
the script layer that writes the marker. Treating the marker as a
gap to be "fixed" with text guessing would manufacture false
confidence; the contract above is the correct division of labour.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PromptCompilerError(ValueError):
    """Any schema, vocabulary or gate failure. Always fatal, never a warning."""


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------

# Shot sizes: standard film grammar, defined here (see module docstring).
SHOT_SIZES = (
    "大特写",
    "特写",
    "近景",
    "中近景",
    "中景",
    "中远景",
    "全景",
    "远景",
    "大远景",
)

# Camera angles / positions: standard film grammar, defined here.
ANGLES = (
    "平视",
    "低机位",
    "高机位",
    "俯视",
    "仰视",
    "荷兰角",
    "过肩",
    "主观视角",
)

# Line modes: dialogue (on-screen speech), os (off-screen voice from a
# character who is not in frame), vo (narration voice-over). OS/VO
# speakers never lip-sync; they must declare line_source.
LINE_MODES = ("dialogue", "os", "vo")

# Pace tiers: chars per second. Aliases map Chinese tier names to tiers.
PACE_RATES = {
    "default": 4.0,
    "fast": 4.0,
    "normal": 3.0,
    "slow": 2.0,
}
PACE_ALIASES = {
    "默认": "default",
    "急促": "fast",
    "正常": "normal",
    "深情": "slow",
    "低语": "slow",
}

MAX_LINE_CHARS = 20
MIN_BEAT_S = 1.0
PAUSE_PER_PUNCT_S = 0.4
HEAD_TAIL_MARGIN_S = 1.0

_PUNCT = set("，。！？；：、……·—-「」『』（）《》〈〉\"'“”‘’.…?!;:,")

_MOVEMENT_TABLE: dict[str, dict[str, str]] | None = None
_MOVEMENT_ZH_TO_ID: dict[str, str] = {}


def _load_movement_table() -> dict[str, dict[str, str]]:
    """Movement id -> {zh, en}, from hevi's own cinematic_techniques data.

    Loaded from the same ``camera_movements.json`` that
    ``cinematic_techniques.load_movements`` reads, so the table can
    never drift from hevi's own 40-movement list.
    """
    global _MOVEMENT_TABLE, _MOVEMENT_ZH_TO_ID
    if _MOVEMENT_TABLE is not None:
        return _MOVEMENT_TABLE
    movements: list[dict[str, Any]] = []
    try:
        from hevi.capabilities.cinematic_techniques import load_movements

        movements = load_movements()
    except Exception:
        data_path = (
            Path(__file__).resolve().parent
            / "cinematic_data"
            / "camera_movements.json"
        )
        try:
            movements = json.loads(data_path.read_text(encoding="utf-8"))[
                "movements"
            ]
        except Exception as exc:
            raise PromptCompilerError(
                "story.prompt_compiler: cannot load camera movement table "
                f"from cinematic_techniques data: {exc}"
            ) from exc
    table: dict[str, dict[str, str]] = {}
    zh_to_id: dict[str, str] = {}
    for entry in movements:
        movement_id = str(entry.get("id", "")).strip()
        zh = str(entry.get("name_zh", "")).strip()
        en = str(entry.get("name_en", "")).strip()
        if not movement_id:
            continue
        table[movement_id] = {"zh": zh, "en": en}
        if zh:
            zh_to_id[zh] = movement_id
    if not table:
        raise PromptCompilerError(
            "story.prompt_compiler: camera movement table is empty"
        )
    _MOVEMENT_TABLE = table
    _MOVEMENT_ZH_TO_ID = zh_to_id
    return table


def resolve_movement(value: str) -> tuple[str, str, str]:
    """Normalise a movement reference to (id, zh, en).

    Accepts a movement id or its Chinese name; anything else raises,
    naming the rejected value.
    """
    table = _load_movement_table()
    wanted = str(value or "").strip()
    if wanted in table:
        entry = table[wanted]
        return wanted, entry["zh"], entry["en"]
    if wanted in _MOVEMENT_ZH_TO_ID:
        movement_id = _MOVEMENT_ZH_TO_ID[wanted]
        entry = table[movement_id]
        return movement_id, entry["zh"], entry["en"]
    known = ", ".join(sorted(table))
    raise PromptCompilerError(
        f"story.prompt_compiler: unknown camera movement {wanted!r}; "
        f"must be one of the 40 cinematic_techniques movements: {known}"
    )


def normalise_pace(value: Any) -> str:
    """Normalise a pace tier (English id or Chinese alias) to its id."""
    if value is None or value == "":
        return "default"
    wanted = str(value).strip()
    if wanted in PACE_RATES:
        return wanted
    if wanted in PACE_ALIASES:
        return PACE_ALIASES[wanted]
    raise PromptCompilerError(
        f"story.prompt_compiler: unknown pace tier {wanted!r}; "
        f"allowed: {', '.join(sorted(PACE_RATES))} "
        f"or aliases {', '.join(sorted(PACE_ALIASES))}"
    )


# ---------------------------------------------------------------------------
# Line-duration estimator
# ---------------------------------------------------------------------------


def _content_chars(line: str) -> int:
    return sum(1 for ch in str(line) if not ch.isspace() and ch not in _PUNCT)


def _punct_count(line: str) -> int:
    return sum(1 for ch in str(line) if ch in _PUNCT)


def estimate_min_line_duration_s(line: str, pace: Any = "default") -> float:
    """Minimum planned duration (seconds) for one spoken line.

    ``chars / rate + 0.4s per punctuation mark + 1.0s head/tail
    margin``. An empty / silent line costs 0.0s.
    """
    text = str(line or "").strip()
    if not text:
        return 0.0
    rate = PACE_RATES[normalise_pace(pace)]
    return (
        _content_chars(text) / rate
        + PAUSE_PER_PUNCT_S * _punct_count(text)
        + HEAD_TAIL_MARGIN_S
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _fmt_num(value: float) -> str:
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


def _fmt_time(value: float) -> str:
    return _fmt_num(value)


def _req(container: dict[str, Any], key: str, where: str) -> Any:
    if not isinstance(container, dict) or key not in container:
        raise PromptCompilerError(
            f"story.prompt_compiler: {where} is missing required field {key!r}"
        )
    return container[key]


def _flatten_state(state: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested continuity state to dotted-key -> value.

    None values are preserved, not stringified: a null in
    ``new_changes`` is the declared-removal marker gate 4 checks for
    (``changes.get(key) is None and key in changes``), and turning it
    into the string "None" made that branch dead code -- no null
    removal could ever pass gate 4.
    """
    flat: dict[str, Any] = {}
    if isinstance(state, dict):
        for key, value in state.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flat.update(_flatten_state(value, dotted))
            elif isinstance(value, list):
                flat[dotted] = "／".join(
                    "" if v is None else str(v) for v in value
                )
            elif value is None:
                flat[dotted] = None
            else:
                flat[dotted] = str(value)
    elif state is not None:
        flat[prefix or "state"] = str(state)
    return flat


def _shot_label(shot: dict[str, Any]) -> str:
    return f"shot {shot.get('shot_no', '?')}"


def _beat_label(shot: dict[str, Any], beat: dict[str, Any]) -> str:
    return f"{_shot_label(shot)} beat {beat.get('beat_no', '?')}"


# ---------------------------------------------------------------------------
# Vocabulary + structure validation (runs before the five gates)
# ---------------------------------------------------------------------------


def check_vocabulary(episode: dict[str, Any]) -> None:
    """Closed-vocabulary interception for every shot and beat."""
    for shot in episode.get("shots", []):
        label = _shot_label(shot)
        camera = shot.get("camera", {})
        if not isinstance(camera, dict):
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} camera must be an object"
            )
        shot_size = camera.get("shot_size", "")
        if shot_size not in SHOT_SIZES:
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} shot_size {shot_size!r} "
                f"is outside the closed list: {', '.join(SHOT_SIZES)}"
            )
        angle = camera.get("angle", "")
        if angle not in ANGLES:
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} angle {angle!r} "
                f"is outside the closed list: {', '.join(ANGLES)}"
            )
        try:
            resolve_movement(camera.get("movement", ""))
        except PromptCompilerError as exc:
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} camera.movement: {exc}"
            ) from exc
        _validate_camera_extras(camera, label)
        _normalise_negative_prompts(shot)
        _normalise_fallbacks(shot)
        for beat in shot.get("beats", []):
            beat_label = _beat_label(shot, beat)
            if beat.get("camera_move"):
                try:
                    resolve_movement(beat["camera_move"])
                except PromptCompilerError as exc:
                    raise PromptCompilerError(
                        f"story.prompt_compiler: {beat_label} "
                        f"camera_move: {exc}"
                    ) from exc
            mode = beat.get("line_mode", "")
            if mode and mode not in LINE_MODES:
                raise PromptCompilerError(
                    f"story.prompt_compiler: {beat_label} line_mode "
                    f"{mode!r} is outside the closed list: "
                    f"{', '.join(LINE_MODES)}"
                )
            if beat.get("line") and mode in ("os", "vo"):
                if not str(beat.get("line_source", "")).strip():
                    raise PromptCompilerError(
                        f"story.prompt_compiler: {beat_label} line_mode "
                        f"{mode!r} requires line_source (OS/VO speakers "
                        f"do not lip-sync, so the source must be named)"
                    )
            if beat.get("pace") is not None:
                try:
                    normalise_pace(beat["pace"])
                except PromptCompilerError as exc:
                    raise PromptCompilerError(
                        f"story.prompt_compiler: {beat_label} pace: {exc}"
                    ) from exc
            quality = beat.get("voice_quality", [])
            if quality is not None:
                if not isinstance(quality, list) or len(quality) > 3:
                    raise PromptCompilerError(
                        f"story.prompt_compiler: {beat_label} "
                        f"voice_quality must be a list of at most 3 "
                        f"voice-quality words, got {quality!r}"
                    )
            if beat.get("line") and not str(beat.get("speaker", "")).strip():
                raise PromptCompilerError(
                    f"story.prompt_compiler: {beat_label} has a line but "
                    f"no speaker; every spoken line names its speaker"
                )


def check_structure(episode: dict[str, Any]) -> list[dict[str, Any]]:
    """Required-field checks; returns the shot list for the gates."""
    for key in ("episode_no", "title", "target_duration_s", "aspect", "style"):
        _req(episode, key, "episode")
    shots = episode.get("shots")
    if not isinstance(shots, list) or not shots:
        raise PromptCompilerError(
            "story.prompt_compiler: episode must carry a non-empty "
            "'shots' list"
        )
    seen: set[str] = set()
    for shot in shots:
        label = _shot_label(shot)
        shot_no = str(_req(shot, "shot_no", label))
        if shot_no in seen:
            raise PromptCompilerError(
                f"story.prompt_compiler: duplicate shot_no {shot_no!r}"
            )
        seen.add(shot_no)
        for key in ("scene", "duration_s", "camera", "beats", "continuity"):
            _req(shot, key, label)
        if float(shot["duration_s"]) <= 0:
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} duration_s must be > 0, "
                f"got {shot['duration_s']!r}"
            )
        if not isinstance(shot["beats"], list) or not shot["beats"]:
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} must carry a non-empty "
                f"'beats' list"
            )
        continuity = shot["continuity"]
        if not isinstance(continuity, dict):
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} continuity must be an object"
            )
        for key in ("entry_state", "exit_state"):
            _req(continuity, key, f"{label} continuity")
        camera = shot["camera"]
        if not isinstance(camera, dict):
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} camera must be an object"
            )
        for key in ("shot_size", "angle", "movement", "start_frame", "end_frame"):
            _req(camera, key, f"{label} camera")
        for beat in shot["beats"]:
            beat_label = _beat_label(shot, beat)
            for key in ("beat_no", "t_start_s", "t_end_s", "action", "sound"):
                _req(beat, key, beat_label)
    return shots


# ---------------------------------------------------------------------------
# Gate 1 -- beat times cover the shot exactly
# ---------------------------------------------------------------------------


def check_beat_coverage(shots: list[dict[str, Any]]) -> None:
    """Gate 1: beats tile [0, duration_s] with no gap and no overlap."""
    for shot in shots:
        label = _shot_label(shot)
        duration = float(shot["duration_s"])
        beats = shot["beats"]
        total = 0.0
        previous_end: float | None = None
        for beat in beats:
            beat_label = _beat_label(shot, beat)
            start = float(beat["t_start_s"])
            end = float(beat["t_end_s"])
            if end <= start:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 1: {beat_label} has "
                    f"non-positive span {start:g}-{end:g}s"
                )
            if end - start < MIN_BEAT_S - 1e-9:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 1: {beat_label} span "
                    f"{end - start:g}s is under the {MIN_BEAT_S:g}s "
                    f"minimum segment length"
                )
            if previous_end is None:
                if abs(start) > 1e-9:
                    raise PromptCompilerError(
                        f"story.prompt_compiler gate 1: {label} first "
                        f"beat starts at {start:g}s, not 0s (gap at the "
                        f"head of the shot)"
                    )
            elif abs(start - previous_end) > 1e-9:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 1: {label} beat "
                    f"{beat.get('beat_no', '?')} starts at {start:g}s "
                    f"but the previous beat ends at {previous_end:g}s "
                    f"(gap or overlap)"
                )
            total += end - start
            previous_end = end
        if previous_end is None or abs(previous_end - duration) > 1e-9:
            raise PromptCompilerError(
                f"story.prompt_compiler gate 1: {label} beats end at "
                f"{previous_end} s but duration_s is {duration:g}s"
            )
        if abs(total - duration) > 1e-9:
            raise PromptCompilerError(
                f"story.prompt_compiler gate 1: {label} beat spans sum "
                f"to {total:g}s, not duration_s {duration:g}s"
            )


# ---------------------------------------------------------------------------
# Clip grouping (gate 5 input) -- one generation call = one clip
# ---------------------------------------------------------------------------


def check_clip_groups(shots: list[dict[str, Any]]) -> None:
    """Validate explicit clip grouping on shots that carry it.

    Each clip names its beats by beat_no. Beat numbers must exist in
    the shot, must not repeat across clips, and must form one
    consecutive run of the shot's beats (a generation call covers
    consecutive beats). Shots without a ``clips`` key are untouched
    here; their legacy tier unit is the whole shot (see
    :func:`_clip_units`).
    """
    for shot in shots:
        if "clips" not in shot or shot["clips"] is None:
            continue
        label = _shot_label(shot)
        clips = shot["clips"]
        if not isinstance(clips, list):
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} clips must be a list"
            )
        order = [beat.get("beat_no") for beat in shot["beats"]]
        position = {number: index for index, number in enumerate(order)}
        seen: set[Any] = set()
        for index, clip in enumerate(clips):
            clip_label = str(clip.get("clip_id", f"clip{index + 1}")) if isinstance(clip, dict) else f"clip{index + 1}"
            if not isinstance(clip, dict):
                raise PromptCompilerError(
                    f"story.prompt_compiler: {label} {clip_label} must be "
                    f"an object naming its beats"
                )
            beat_nos = clip.get("beats")
            if not isinstance(beat_nos, list) or not beat_nos:
                raise PromptCompilerError(
                    f"story.prompt_compiler: {label} {clip_label} must "
                    f"carry a non-empty 'beats' list of beat_no values"
                )
            for number in beat_nos:
                if number not in position:
                    raise PromptCompilerError(
                        f"story.prompt_compiler: {label} {clip_label} "
                        f"names unknown beat_no {number!r}"
                    )
                if number in seen:
                    raise PromptCompilerError(
                        f"story.prompt_compiler: {label} {clip_label} "
                        f"repeats beat_no {number!r}"
                    )
                seen.add(number)
            indices = sorted(position[number] for number in beat_nos)
            if indices != list(range(indices[0], indices[0] + len(indices))):
                raise PromptCompilerError(
                    f"story.prompt_compiler: {label} {clip_label} beats "
                    f"{beat_nos!r} are not consecutive beats of the shot; "
                    f"a clip covers one consecutive run"
                )


def _clip_units(shots: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str, float]]:
    """Tier-checked units: (shot, unit label, duration seconds).

    Clip-carrying shots contribute one unit per clip (duration = sum
    of the clip's beats' spans); a ``clips == []`` shot contributes
    none; a shot without a ``clips`` key contributes one unit equal
    to its whole duration (legacy behaviour).
    """
    units: list[tuple[dict[str, Any], str, float]] = []
    for shot in shots:
        label = _shot_label(shot)
        if "clips" not in shot or shot["clips"] is None:
            units.append((shot, label, float(shot["duration_s"])))
            continue
        span_by_no = {
            beat.get("beat_no"): float(beat["t_end_s"]) - float(beat["t_start_s"])
            for beat in shot["beats"]
        }
        for index, clip in enumerate(shot["clips"]):
            clip_id = str(clip.get("clip_id", f"clip{index + 1}"))
            duration = sum(span_by_no[number] for number in clip["beats"])
            units.append((shot, f"{label} {clip_id}", duration))
    return units


# ---------------------------------------------------------------------------
# Long-line split rule + gate 2 -- line duration fits its beat
# ---------------------------------------------------------------------------


def _line_groups(
    shot: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for beat in shot["beats"]:
        group = beat.get("line_group")
        if group:
            groups.setdefault(str(group), []).append(beat)
    return groups


def check_long_lines(shots: list[dict[str, Any]]) -> None:
    """Split rule: a >20-char line must be split across grouped beats."""
    for shot in shots:
        label = _shot_label(shot)
        groups = _line_groups(shot)
        grouped_ids = {id(b) for beats in groups.values() for b in beats}
        for group_id, beats in groups.items():
            if len(beats) < 2:
                beat = beats[0]
                raise PromptCompilerError(
                    f"story.prompt_compiler split rule: {_beat_label(shot, beat)} "
                    f"declares line_group {group_id!r} but the group has "
                    f"only one beat; a split needs at least 2 beats"
                )
            speakers = {str(b.get("speaker", "")) for b in beats}
            modes = {str(b.get("line_mode", "") or "dialogue") for b in beats}
            if len(speakers) != 1 or len(modes) != 1:
                raise PromptCompilerError(
                    f"story.prompt_compiler split rule: {label} line_group "
                    f"{group_id!r} spans beats with different speakers "
                    f"({sorted(speakers)}) or line modes ({sorted(modes)}); "
                    f"a split line stays with its original speaker"
                )
            for beat in beats:
                part = str(beat.get("line", ""))
                if _content_chars(part) > MAX_LINE_CHARS:
                    raise PromptCompilerError(
                        f"story.prompt_compiler split rule: "
                        f"{_beat_label(shot, beat)} split part "
                        f"{part!r} is itself over {MAX_LINE_CHARS} "
                        f"content characters; split it further"
                    )
            full = beats[0].get("line_full")
            joined = "".join(str(b.get("line", "")) for b in beats)
            if full is not None and "".join(str(full).split()) != "".join(
                joined.split()
            ):
                raise PromptCompilerError(
                    f"story.prompt_compiler split rule: {label} line_group "
                    f"{group_id!r} parts join to {joined!r}, not to the "
                    f"declared line_full {full!r}"
                )
        for beat in shot["beats"]:
            if id(beat) in grouped_ids:
                continue
            line = str(beat.get("line", "") or "")
            if _content_chars(line) > MAX_LINE_CHARS:
                raise PromptCompilerError(
                    f"story.prompt_compiler split rule: "
                    f"{_beat_label(shot, beat)} line {line!r} has "
                    f"{_content_chars(line)} content characters, over "
                    f"the {MAX_LINE_CHARS}-char limit, and carries no "
                    f"line_group split; split it at a semantic pause "
                    f"across consecutive beats (same speaker) or shorten it"
                )


def check_line_durations(shots: list[dict[str, Any]]) -> None:
    """Gate 2: every spoken line's minimum planned duration fits its beat."""
    for shot in shots:
        for beat in shot["beats"]:
            line = str(beat.get("line", "") or "")
            if not line.strip():
                continue
            span = float(beat["t_end_s"]) - float(beat["t_start_s"])
            needed = estimate_min_line_duration_s(line, beat.get("pace"))
            if needed > span + 1e-9:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 2: "
                    f"{_beat_label(shot, beat)} line {line!r} needs at "
                    f"least {needed:.2f}s (pace "
                    f"{normalise_pace(beat.get('pace'))}) but its beat "
                    f"span is only {span:g}s; split the shot or shorten "
                    f"the line, never squeeze it"
                )
        voiceover = str(shot.get("voiceover_line", "") or "")
        if voiceover.strip():
            needed = estimate_min_line_duration_s(
                voiceover, shot.get("voiceover_pace")
            )
            if needed > float(shot["duration_s"]) + 1e-9:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 2: {_shot_label(shot)} "
                    f"voiceover line {voiceover!r} needs at least "
                    f"{needed:.2f}s but the shot is only "
                    f"{float(shot['duration_s']):g}s"
                )


# ---------------------------------------------------------------------------
# Gate 3 -- one line in exactly one place
# ---------------------------------------------------------------------------


def collect_spoken_lines(
    shots: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """All spoken texts in order: (text, shot_no, beat_no or 'voiceover').

    Grouped split lines contribute their full line once, at the first
    beat of the group. Blank / purely silent beats contribute nothing.
    Shot-level voiceover lines count (OS/VO text equal to dialogue
    text is a repeat); shot-level subtitles do not speak and are
    excluded.
    """
    spoken: list[tuple[str, str, str]] = []
    for shot in shots:
        shot_no = str(shot.get("shot_no", "?"))
        groups = _line_groups(shot)
        group_first: dict[str, dict[str, Any]] = {
            group_id: beats[0] for group_id, beats in groups.items()
        }
        for beat in shot["beats"]:
            group = beat.get("line_group")
            if group:
                if group_first[str(group)] is not beat:
                    continue
                full = beat.get("line_full")
                if full is not None:
                    text = str(full)
                else:
                    text = "".join(
                        str(b.get("line", "")) for b in groups[str(group)]
                    )
            else:
                text = str(beat.get("line", "") or "")
            if text.strip():
                spoken.append((text.strip(), shot_no, str(beat.get("beat_no", "?"))))
        voiceover = str(shot.get("voiceover_line", "") or "")
        if voiceover.strip():
            spoken.append((voiceover.strip(), shot_no, "voiceover"))
    return spoken


def check_line_uniqueness(shots: list[dict[str, Any]]) -> None:
    """Gate 3: no spoken text repeats anywhere in the episode."""
    seen: dict[str, tuple[str, str]] = {}
    for text, shot_no, beat_no in collect_spoken_lines(shots):
        if text in seen:
            first_shot, first_beat = seen[text]
            raise PromptCompilerError(
                f"story.prompt_compiler gate 3: line {text!r} appears "
                f"twice: first at shot {first_shot} beat {first_beat}, "
                f"again at shot {shot_no} beat {beat_no}; reaction shots, "
                f"echoes and repeated emphasis must not reuse line text"
            )
        seen[text] = (shot_no, beat_no)


# ---------------------------------------------------------------------------
# Gate 4 -- continuity chain + start-frame trigger state
# ---------------------------------------------------------------------------


def check_continuity_chain(shots: list[dict[str, Any]]) -> None:
    """Gate 4: each entry = previous exit + this shot's new changes."""
    for index, shot in enumerate(shots):
        label = _shot_label(shot)
        continuity = shot["continuity"]
        entry = _flatten_state(continuity.get("entry_state", {}))
        # Start-frame trigger rule, checked for every shot.
        start_frame = shot["camera"].get("start_frame", {})
        if not isinstance(start_frame, dict):
            raise PromptCompilerError(
                f"story.prompt_compiler gate 4: {label} start_frame "
                f"must be an object with a state_kind marker"
            )
        marker = start_frame.get("state_kind")
        if marker != "trigger_in_progress":
            raise PromptCompilerError(
                f"story.prompt_compiler gate 4: {label} start_frame "
                f"state_kind is {marker!r}, not 'trigger_in_progress'; "
                f"the first frame must show the triggering moment "
                f"still unfinished, not its result"
            )
        if index == 0:
            continue
        previous_exit = _flatten_state(shots[index - 1]["continuity"].get("exit_state", {}))
        changes = _flatten_state(continuity.get("new_changes", {}))
        for key, old_value in previous_exit.items():
            if key not in entry:
                if changes.get(key) is None and key in changes:
                    continue
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 4: {label} entry_state "
                    f"dropped item {key!r} (previous exit value "
                    f"{old_value!r}) without declaring its removal in "
                    f"new_changes"
                )
            if entry[key] != old_value and changes.get(key) != entry[key]:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 4: {label} entry_state "
                    f"item {key!r} changed from {old_value!r} to "
                    f"{entry[key]!r} without declaring it in new_changes"
                )
        for key, new_value in entry.items():
            if key not in previous_exit and changes.get(key) != new_value:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 4: {label} entry_state "
                    f"adds new item {key!r}={new_value!r} without "
                    f"declaring it in new_changes"
                )
        for key, declared in changes.items():
            if declared is None:
                if key in entry:
                    raise PromptCompilerError(
                        f"story.prompt_compiler gate 4: {label} "
                        f"new_changes declares item {key!r} removed, "
                        f"but entry_state still carries it"
                    )
            elif entry.get(key) != declared:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 4: {label} new_changes "
                    f"declares item {key!r}={declared!r}, but entry_state "
                    f"carries {entry.get(key)!r}"
                )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Duration tier table (gate 5, second half)
# ---------------------------------------------------------------------------

_DURATION_TIERS_FILE = (
    Path(__file__).resolve().parent / "model_catalog_data" / "duration_tiers.json"
)


def load_duration_tiers() -> dict[str, Any]:
    """Load the duration tier table (provider key -> caps + source).

    Returns {} when the file is absent or unreadable: a missing table
    resolves every provider to "unknown", never to an invented cap.
    """
    try:
        doc = json.loads(_DURATION_TIERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(doc, dict) or not isinstance(doc.get("tiers"), dict):
        return {}
    return doc["tiers"]


def resolve_provider_caps(provider_key: str) -> dict[str, Any] | None:
    """Resolve one provider's caps from the tier table.

    Returns None when the key has no table entry. When the entry
    exists but declares no verified cap (all caps null), returns the
    entry with null caps so the caller can report "unknown" with the
    precise reason instead of guessing.
    """
    wanted = str(provider_key or "").strip()
    if not wanted:
        return None
    entry = load_duration_tiers().get(wanted)
    if not isinstance(entry, dict):
        return None
    return {
        "provider": wanted,
        "max_shot_s": entry.get("max_shot_s"),
        "max_total_s": entry.get("max_total_s"),
        "min_shot_s": entry.get("min_shot_s"),
        "source": entry.get("source"),
    }


# Gate 5 -- episode total + supplier tier (explicit, never invented)
# ---------------------------------------------------------------------------


def check_total_and_tier(
    episode: dict[str, Any],
    shots: list[dict[str, Any]],
    provider_caps: dict[str, Any] | None = None,
    tier_unknown_reason: str | None = None,
) -> dict[str, Any]:
    """Gate 5: shot durations sum to the episode target; tier breaches raise.

    The tier is checked per generation call (clip), not per shot:
    see :func:`_clip_units`. Shot totals are still governed by the
    episode-target check above; a clip that is too long or too short
    for the supplier tier fails here, naming the shot and clip.

    Returns the tier verdict. Without enforceable caps the verdict
    is ``unknown`` -- recorded, never guessed, and never used to
    clamp, pad or truncate anything. ``tier_unknown_reason`` (set by
    :func:`compile_episode` from the tier-table lookup outcome)
    explains which case produced the unknown verdict.
    """
    target = float(episode["target_duration_s"])
    total = sum(float(shot["duration_s"]) for shot in shots)
    if abs(total - target) > 1e-9:
        raise PromptCompilerError(
            f"story.prompt_compiler gate 5: shot durations sum to "
            f"{total:g}s, not the episode target_duration_s "
            f"{target:g}s (episode {episode.get('episode_no', '?')}); "
            f"fix the script, do not pad or cut silently"
        )
    if not provider_caps:
        return {
            "status": "unknown",
            "reason": (
                tier_unknown_reason
                or (
                    "no provider selected and no tier entry resolved "
                    "from duration_tiers.json; pass provider=... to "
                    "resolve a tier, or provider_caps=... to enforce "
                    "caps explicitly"
                )
            ),
        }
    provider = str(provider_caps.get("provider", "") or "")
    where = f" for provider {provider}" if provider else ""
    max_shot = provider_caps.get("max_shot_s")
    min_shot = provider_caps.get("min_shot_s")
    if max_shot is not None or min_shot is not None:
        for _shot, unit_label, duration in _clip_units(shots):
            if max_shot is not None and duration > float(max_shot) + 1e-9:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 5: {unit_label} "
                    f"duration {duration:g}s exceeds "
                    f"the supplier single-generation cap {float(max_shot):g}s"
                    f"{where}; send this back to the script layer, "
                    f"do not clamp or split silently"
                )
            if min_shot is not None and duration < float(min_shot) - 1e-9:
                raise PromptCompilerError(
                    f"story.prompt_compiler gate 5: {unit_label} "
                    f"duration {duration:g}s is under "
                    f"the supplier single-generation minimum {float(min_shot):g}s"
                    f"{where}; send this back to the script layer, "
                    f"do not clamp or split silently"
                )
    max_total = provider_caps.get("max_total_s")
    if max_total is not None and total > float(max_total) + 1e-9:
        raise PromptCompilerError(
            f"story.prompt_compiler gate 5: episode total {total:g}s "
            f"exceeds the supplier total cap {float(max_total):g}s"
            f"{where}; send this back to the script layer"
        )
    return {
        "status": "checked",
        "provider": provider,
        "max_shot_s": max_shot,
        "min_shot_s": min_shot,
        "max_total_s": max_total,
        "source": provider_caps.get("source"),
        "tier_scope": (
            "clip"
            if any(
                "clips" in shot and shot["clips"] is not None
                for shot in shots
            )
            else "shot"
        ),
    }


# ---------------------------------------------------------------------------
# Prompt rendering (fixed section order)
# ---------------------------------------------------------------------------

SPEECH_DISCIPLINE = (
    "说话纪律：只说本提示词里逐字写出的台词，每句只说一遍；"
    "全部对白使用现代简体普通话，自然语速；同一时刻只有一人说话；"
    "在画内的说话人嘴部必须清晰可见，画外音／旁白不对口型；"
    "静默段就是真静默，不出声、不哼唱、不加歌声。"
)
BANS = (
    "禁令：画面里不许出现任何文字、字幕、水印、拼贴、分屏，"
    "不许出现额外人物；人物视线必须落在场景内明确对象上；"
    "镜头之间禁叠化、禁交叉溶解、禁淡入淡出。"
)

# Camera easing vocabulary (closed list). The value is a text instruction
# for the generator: whether a model actually follows the curve must be
# checked by frame review after generation; the compiler only guarantees
# the instruction is present, unambiguous and closed-vocabulary.
EASINGS = {
    "ease_in_out": "起步慢、中段稍快、落定慢",
    "ease_in": "起步慢、逐渐加快",
    "ease_out": "起步快、落定慢",
    "linear": "匀速",
    "hold": "保持不动",
}


def _normalise_negative_prompts(shot: dict[str, Any]) -> list[str]:
    """Validate shot-level ``negative_prompts``; dedupe, keep order."""
    label = _shot_label(shot)
    value = shot.get("negative_prompts")
    if value is None:
        return []
    if not isinstance(value, list):
        raise PromptCompilerError(
            f"story.prompt_compiler: {label} negative_prompts must be "
            f"a list of non-empty strings, got {value!r}"
        )
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} negative_prompts "
                f"contains an empty or non-string entry {item!r}; "
                "every negative item must be a non-empty string"
            )
        text = item.strip()
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _normalise_fallbacks(shot: dict[str, Any]) -> list[dict[str, str]]:
    """Validate shot-level ``fallbacks`` (trigger + replacement each)."""
    label = _shot_label(shot)
    value = shot.get("fallbacks")
    if value is None:
        return []
    if not isinstance(value, list):
        raise PromptCompilerError(
            f"story.prompt_compiler: {label} fallbacks must be a list "
            f"of objects with 'trigger' and 'replacement', got {value!r}"
        )
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} fallback {item!r} "
                "must be an object with 'trigger' and 'replacement'"
            )
        trigger = item.get("trigger")
        replacement = item.get("replacement")
        if (
            not isinstance(trigger, str)
            or not trigger.strip()
            or not isinstance(replacement, str)
            or not replacement.strip()
        ):
            raise PromptCompilerError(
                f"story.prompt_compiler: {label} fallback {item!r} "
                "is missing a non-empty 'trigger' or 'replacement'"
            )
        out.append(
            {"trigger": trigger.strip(), "replacement": replacement.strip()}
        )
    return out


def _validate_camera_extras(camera: dict[str, Any], label: str) -> None:
    """Validate optional camera fields: easing + shot_size_end."""
    easing = camera.get("easing")
    if easing is not None and easing not in EASINGS:
        raise PromptCompilerError(
            f"story.prompt_compiler: {label} camera.easing {easing!r} "
            f"is outside the closed list: {', '.join(EASINGS)}"
        )
    end_size = camera.get("shot_size_end")
    if end_size is not None and end_size not in SHOT_SIZES:
        raise PromptCompilerError(
            f"story.prompt_compiler: {label} camera.shot_size_end "
            f"{end_size!r} is outside the closed list: "
            f"{', '.join(SHOT_SIZES)}"
        )


# ------------------------------------------------------- readiness (strict)
#
# Generation-ready discipline (2026-10-31 prompt audit). The legacy
# entry points keep their old behaviour (unknown tier recorded, bare
# names, no file bindings) so existing fixtures keep compiling; the
# strict entry points below are the production path and fail hard.
# Binding/anchor validation lives in pipeline.scene_reference
# (single implementation); this module imports it lazily so the two
# modules never form an import cycle at load time.


def _scene_reference_helpers() -> tuple[Any, Any, Any]:
    from hevi.capabilities.scene_reference import (
        canonical_frame_count,
        resolve_character_anchor,
        resolve_picture_bindings,
    )

    return canonical_frame_count, resolve_character_anchor, resolve_picture_bindings


def frames_for_provider(seconds: float, provider: str, fps: float = 24.0) -> int:
    """Frame count for ``seconds`` on ``provider``'s route.

    Single truth lives in pipeline.scene_reference.canonical_frame_count:
    10 s is 240 frames on fasth3_local and 243 on the H3 lattice.
    The route name is carried into the prompt text so a reader can
    tell which of the two numbers a prompt means.
    """
    canonical_frame_count, _, _ = _scene_reference_helpers()
    return canonical_frame_count(float(seconds), float(fps), route=provider)


def _anchor_picture_number(anchor: dict[str, Any], bindings: dict[int, dict[str, Any]]) -> int | None:
    for number, binding in bindings.items():
        if binding["file"] == anchor["file"] and binding["sha256"] == anchor["sha256"]:
            return number
    return None


def resolve_shot_anchors(
    shot: dict[str, Any],
    anchors: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Resolve confirmed anchors for every character/speaker of a shot.

    ``anchors`` maps a character name to a character_anchor sheet or
    a plain confirmed record (see scene_reference.resolve_character_anchor).
    A shot whose characters have no confirmed anchor fails here: a
    bare name is never prompt-ready. Speakers of dialogue beats are
    checked too; voiceover/narration speakers are not characters
    and are skipped.
    """
    _, resolve_character_anchor, _ = _scene_reference_helpers()
    names: list[str] = []
    for name in shot.get("characters") or []:
        if str(name) not in names:
            names.append(str(name))
    for beat in shot.get("beats") or []:
        if (beat.get("line_mode", "") or "dialogue") == "dialogue" and str(beat.get("line", "") or "").strip():
            speaker = str(beat.get("speaker", "") or "").strip()
            if speaker and speaker not in names:
                names.append(speaker)
    resolved: dict[str, dict[str, Any]] = {}
    if anchors is None:
        raise PromptCompilerError(
            f"story.prompt_compiler: {_shot_label(shot)} has no anchors supplied; "
            "generation-ready prompts need a confirmed anchor per character"
        )
    for name in names:
        resolved[name] = resolve_character_anchor(name, anchors)
    return resolved


def check_anchor_and_binding_coverage(
    episode: dict[str, Any],
    anchors: dict[str, Any] | None,
    reference_bindings: dict[Any, Any] | None,
) -> dict[str, Any]:
    """Fail unless anchors and file bindings cover the whole episode.

    Every shot character/speaker needs a confirmed anchor, every
    anchor file must appear in the Picture bindings, and Picture 1
    (the scene/first-frame reference) must be bound. Returns the
    resolved anchors and bindings for the caller to render with.
    """
    _, _, resolve_picture_bindings = _scene_reference_helpers()
    if reference_bindings is None:
        raise PromptCompilerError(
            "story.prompt_compiler: no reference_bindings supplied; "
            "Picture numbers without file bindings never reach generation"
        )
    bindings = resolve_picture_bindings(reference_bindings)
    if 1 not in bindings:
        raise PromptCompilerError(
            "story.prompt_compiler: reference_bindings has no Picture 1; "
            "the scene/first-frame reference must be bound to a file"
        )
    all_anchors: dict[str, dict[str, Any]] = {}
    for shot in episode.get("shots") or []:
        resolved = resolve_shot_anchors(shot, anchors)
        for name, anchor in resolved.items():
            if _anchor_picture_number(anchor, bindings) is None:
                raise PromptCompilerError(
                    f"story.prompt_compiler: anchor file for {name!r} "
                    "is not in reference_bindings; an anchor no Picture "
                    "points at cannot be used by the executor"
                )
            all_anchors[name] = anchor
    return {"anchors": all_anchors, "bindings": bindings}


def check_beat_progression(shot: dict[str, Any]) -> None:
    """Fail a generation shot whose beats do not progress.

    A shot with clips (or with no ``clips`` key, i.e. one generation
    call) and at least three beats whose normalised actions are all
    identical is a still frame cut into beats, not a moving shot:
    it fails naming the repeated action. Pure-still shots
    (``clips == []``) are exempt -- they make no generation call.
    """
    clips = shot.get("clips")
    if clips is not None and len(clips) == 0:
        return
    actions = [str(b.get("action", "")).strip() for b in shot.get("beats") or []]
    actions = [a for a in actions if a]
    if len(actions) < 3:
        return
    run = 1
    longest = 1
    for prev, cur in zip(actions, actions[1:]):
        run = run + 1 if cur == prev else 1
        longest = max(longest, run)
    if longest >= 3 and len(set(actions)) == 1:
        raise PromptCompilerError(
            f"story.prompt_compiler: {_shot_label(shot)} beats do not progress: "
            f"the same action repeats {len(actions)} times "
            f"({actions[0][:60]!r}); write distinct beats or mark the shot still"
        )


def check_rendered_shot_prompt(prompt: str, shot: dict[str, Any]) -> None:
    """Fail a rendered prompt whose start-frame text repeats per beat.

    The start-frame description belongs in the single ``[首帧]``
    line. If it also appears inside the ``[镜头段]`` beat lines, the
    renderer is repeating a static description once per beat and
    drowning the beat actions. The ``[收尾]`` line may legitimately
    repeat it when the end frame is the same picture.
    """
    entry = str((shot.get("camera") or {}).get("start_frame", {}).get("description", "") or "").strip()
    if not entry:
        return
    # Beat segment lines start with "[<start>–<end>秒]镜头（..."; the
    # section ends at [出口状态]. Any other "[...]" line (e.g. [机位])
    # must not end the scan early.
    in_segments = False
    for line in prompt.splitlines():
        if line.startswith("[镜头段]"):
            in_segments = True
            continue
        if in_segments and line.startswith("[出口状态]"):
            break
        if in_segments and entry in line:
            raise PromptCompilerError(
                f"story.prompt_compiler: {_shot_label(shot)} start-frame description "
                "repeats inside the beat segments; it belongs in the single [首帧] line only"
            )


def _render_line(beat: dict[str, Any]) -> str:
    """One beat's speech slot: verbatim line, or true silence."""
    line = str(beat.get("line", "") or "")
    if not line.strip():
        return "静默：真静默"
    speaker = str(beat.get("speaker", "")).strip()
    quality = beat.get("voice_quality") or []
    quality_text = "、".join(str(q) for q in quality)
    voice = f"{speaker}（{quality_text}）" if quality_text else speaker
    mode = beat.get("line_mode", "") or "dialogue"
    if mode == "dialogue":
        return f"台词 `{voice}：{line}`"
    source = str(beat.get("line_source", "")).strip()
    kind = "画外音" if mode == "os" else "旁白"
    return f"台词（{kind}，不对口型，来源：{source}）`{voice}：{line}`"


def _render_state(state: Any) -> str:
    flat = _flatten_state(state)
    if not flat:
        return "（无）"
    return "\n".join(
        f"{key}：{value if value is not None else '（已删除）'}"
        for key, value in flat.items()
    )


def compile_shot_prompt(
    episode: dict[str, Any],
    shot: dict[str, Any],
    *,
    anchors: dict[str, Any] | None = None,
    reference_bindings: dict[Any, Any] | None = None,
    provider: str | None = None,
    fps: float = 24.0,
) -> str:
    """One shot's prompt text, in the fixed section order.

    [style] -> [duration] -> [reference] -> [entry state] -> [scene]
    -> [characters] -> [first frame, once] -> per-beat segments
    (shot size + angle + landing | one main movement / previous
    landing -> beat action -> landing / speech / sound)
    -> [exit state] -> [closing frame] -> [overall sound] ->
    [negative list, if filled] -> [fallbacks, if filled] ->
    [constraints]. Beat segments follow the beats' own start/end
    seconds; durations are never split evenly across segments.
    The start-frame description appears exactly once, in the
    ``[首帧]`` line: repeating it in every beat segment drowned
    the beat actions in static text (2026-10-31 prompt audit).
    When the shot fills no new optional field, the [机位],
    [负面清单] and [备选方案] lines are emitted only when their
    fields are set.

    With ``anchors`` supplied, every character/speaker must have
    a confirmed anchor and the ``[人物]`` line carries the anchor
    look plus its Picture number; with ``reference_bindings``
    supplied, the ``[参考]`` line lists Picture -> file bindings
    and Picture 1 must be bound. With ``provider`` supplied, the
    ``[时长]`` line also states the frame count on that provider's
    route (see :func:`frames_for_provider`). Supplying none of
    them keeps the legacy output: bare names, free-text reference,
    seconds only.

    This is the canonical generation-ready ``compile_shot_prompt``
    (2026-10-31 prompt audit, fix 9). The storyboard-table
    renderer of the same name in ``hevi/avcraft/oskill/shotprompt.py``
    is LEGACY and untracked in HEAD, wired into
    ``sequence_plan``/``storyboard_enrich``; it must not gain new
    callers and its output is not generation-ready. The kids
    Style-Bible renderer in ``hevi/kids/prompt_compile.py`` is a
    separate preamble renderer, not a generation-ready compiler.
    Do not add a fourth implementation of this name.
    """
    camera = shot["camera"]
    _, movement_zh, movement_en = resolve_movement(camera["movement"])
    negatives = _normalise_negative_prompts(shot)
    fallbacks = _normalise_fallbacks(shot)
    _validate_camera_extras(camera, _shot_label(shot))
    resolved_anchors: dict[str, dict[str, Any]] = {}
    bindings: dict[int, dict[str, Any]] = {}
    if anchors is not None or reference_bindings is not None:
        if anchors is None or reference_bindings is None:
            raise PromptCompilerError(
                f"story.prompt_compiler: {_shot_label(shot)} anchors and "
                "reference_bindings must be supplied together; a confirmed "
                "anchor with no file binding (or the reverse) is not usable"
            )
        _, _, resolve_picture_bindings = _scene_reference_helpers()
        bindings = resolve_picture_bindings(reference_bindings)
        if 1 not in bindings:
            raise PromptCompilerError(
                "story.prompt_compiler: reference_bindings has no Picture 1; "
                "the scene/first-frame reference must be bound to a file"
            )
        resolved_anchors = resolve_shot_anchors(shot, anchors)
        for name, anchor in resolved_anchors.items():
            if _anchor_picture_number(anchor, bindings) is None:
                raise PromptCompilerError(
                    f"story.prompt_compiler: anchor file for {name!r} "
                    "is not in reference_bindings"
                )
    lines: list[str] = []
    lines.append(f"[风格]{episode['style']}")
    duration_line = (
        f"[时长]{_fmt_num(float(shot['duration_s']))}秒（{episode['aspect']}）"
    )
    if provider is not None:
        frames = frames_for_provider(float(shot["duration_s"]), provider, fps)
        duration_line += f"·{frames}帧（{fps:g}fps，{provider}）"
    lines.append(duration_line)
    reference = str(episode.get("reference", "") or "").strip()
    if bindings:
        mapping = "；".join(
            f"Picture {n}：{b['file']}（sha256 {b['sha256'][:8]}）"
            for n, b in sorted(bindings.items())
        )
        lines.append(f"[参考]{mapping}" + (f"｜{reference}" if reference else ""))
    else:
        lines.append(f"[参考]{reference if reference else '无指定参考'}")
    lines.append("[入口状态]")
    lines.append(_render_state(shot["continuity"]["entry_state"]))
    scene = str(shot["scene"])
    time_of_day = str(shot.get("time_of_day", "") or "").strip()
    lines.append(f"[场景]{scene}" + (f"｜{time_of_day}" if time_of_day else ""))
    characters = shot.get("characters") or []
    if characters:
        if resolved_anchors:
            parts = []
            for name in characters:
                anchor = resolved_anchors.get(str(name))
                if anchor is None:
                    parts.append(str(name))
                    continue
                picture = _anchor_picture_number(anchor, bindings)
                wardrobe = f"；服装：{anchor['wardrobe']}" if anchor["wardrobe"] else ""
                parts.append(
                    f"{name}（锚点已确认：{anchor['look']}{wardrobe}；"
                    f"参考 Picture {picture}）"
                )
            lines.append(f"[人物]{'、'.join(parts)}")
        else:
            lines.append(f"[人物]{'、'.join(str(c) for c in characters)}")
    props = shot.get("props") or []
    if props:
        lines.append(f"[道具]{'、'.join(str(p) for p in props)}")
    entry_text = str(camera["start_frame"].get("description", "")).strip()
    if entry_text:
        lines.append(f"[首帧]{entry_text}")
    lines.append("[镜头段]")
    easing = camera.get("easing")
    end_size = camera.get("shot_size_end")
    if easing is not None or (
        end_size is not None and end_size != camera["shot_size"]
    ):
        framing = camera["shot_size"]
        if end_size is not None and end_size != camera["shot_size"]:
            framing = f"{camera['shot_size']}→{end_size}"
        easing_text = (
            f"，缓动：{EASINGS[easing]}（{easing}）" if easing else ""
        )
        lines.append(
            f"[机位]{framing}，{movement_zh}（{movement_en}）{easing_text}"
        )
    prev_landing: str | None = None
    for beat in shot["beats"]:
        start = _fmt_time(float(beat["t_start_s"]))
        end = _fmt_time(float(beat["t_end_s"]))
        if beat.get("camera_move"):
            _, beat_zh, beat_en = resolve_movement(beat["camera_move"])
        else:
            beat_zh, beat_en = movement_zh, movement_en
        landing = str(beat.get("landing", "") or "").strip()
        landing_text = f"落位：{landing}" if landing else "落位：保持本镜构图"
        action = str(beat["action"])
        chain = f"{prev_landing}→{action}" if prev_landing else action
        gaze = str(beat.get("gaze_target", "") or "").strip()
        gaze_text = f"视线：{gaze}" if gaze else ""
        speech = _render_line(beat)
        if beat.get("line_group"):
            speech += f"（长句分段，组 {beat['line_group']}，与前后同组节拍同属一句，仍归原说话者）"
        segment = (
            f"[{start}–{end}秒]镜头（{camera['shot_size']}＋{camera['angle']}＋"
            f"{landing_text}｜{beat_zh}（{beat_en}）／"
            f"{chain}→{landing if landing else '保持本镜构图'}／"
            f"{speech}"
        )
        if gaze_text:
            segment += f"／{gaze_text}"
        segment += f"／声音：{beat['sound']}）"
        lines.append(segment)
        if landing:
            prev_landing = landing
    lines.append("[出口状态]")
    lines.append(_render_state(shot["continuity"]["exit_state"]))
    lines.append(
        f"[收尾]{camera['end_frame'].get('description', '')}"
    )
    voiceover = str(shot.get("voiceover_line", "") or "")
    if voiceover.strip():
        source = str(shot.get("voiceover_source", "") or "").strip()
        source_text = f"（来源：{source}）" if source else ""
        lines.append(
            f"[画外旁白·不对口型]{voiceover}{source_text}"
            f"——本句为画外旁白，不计入动镜台词，不由画内人物对口型说出。"
        )
    subtitle = str(shot.get("subtitle", "") or "")
    if subtitle.strip():
        lines.append(
            f"[字幕·后期叠加，不进画面生成]{subtitle}"
            f"——本条只作后期叠加说明，生成画面本身仍不许出现任何文字。"
        )
    overall = str(shot.get("overall_sound", "") or "").strip()
    if not overall:
        seen_sounds: list[str] = []
        for beat in shot["beats"]:
            sound = str(beat["sound"])
            if sound not in seen_sounds:
                seen_sounds.append(sound)
        overall = "；".join(seen_sounds)
    lines.append(f"[整体声音]{overall}")
    if negatives:
        lines.append("[负面清单]")
        for item in negatives:
            lines.append(f"• {item}")
    if fallbacks:
        lines.append("[备选方案]")
        for item in fallbacks:
            lines.append(
                f"触发：{item['trigger']}／改成：{item['replacement']}"
            )
    lines.append(f"[约束]{SPEECH_DISCIPLINE}{BANS}")
    return "\n".join(lines)


def clip_scene_sentence(shot: dict[str, Any], clip_index: int) -> str:
    """One clip's Scene sentence in the production clip format.

    The first clip of a shot keeps the shot's full start-frame
    description: its first frame IS the shot entry still, so the entry
    description is true for it. Later clips start from the previous
    clip's generated last frame (CHAIN), not from the shot entry, so
    repeating the entry description would assert postures the clip has
    already left (e.g. S03c3: entry says the boy sits, but beats 9-11
    play the boy standing in a laughing classroom). For those clips
    only the first sentence of the start-frame description is kept:
    framing + place + light, which stay true for the whole shot, while
    all posture and motion claims live in the Beat lines that follow.
    """
    description = str(shot["camera"]["start_frame"].get("description", "")).strip()
    if clip_index <= 0:
        return description
    first = description.split(". ")[0].strip()
    if not first:
        return description
    return first if first.endswith(".") else first + "."


def compile_clip_prompts(
    episode: dict[str, Any],
    style: str | None = None,
    *,
    anchors: dict[str, Any] | None = None,
    reference_bindings: dict[Any, Any] | None = None,
    provider: str | None = None,
    fps: float = 24.0,
) -> dict[str, str]:
    """Clip-level prompts in the E1 recut production format.

    This is the string shape actually sent to the generator: STYLE
    header + ``Scene: ...`` + one ``Beat: ...`` per beat plus one
    ``Line (speaker): ...`` per spoken beat, in beat order, then
    ``Camera:``, ``State:``, ``Constraints:`` and (when supplied)
    ``Anchors:``, ``Frames:``. Lines come verbatim from the beat
    schema; nothing is paraphrased or added. The camera, state and
    constraint lines are part of the same rendering -- a clip
    prompt without them is a different, weaker prompt than the
    shot prompt, which is what the 2026-10-31 audit found: clip
    prompts dropped camera movement, shot size, state, bans and
    constraints entirely.

    The episode gates (beat coverage, line durations, uniqueness,
    continuity chain, total + tier) still apply at the episode level
    via :func:`compile_episode`; this renderer only fixes the wording
    of the strings the generator sees. Callers that need gated output
    must run :func:`compile_episode` first and render from the same
    episode object. With ``anchors``/``reference_bindings`` supplied
    (together, never one alone), anchors are resolved the same way
    as in :func:`compile_shot_prompt` and unconfirmed anchors fail.
    """
    header = str(style if style is not None else episode.get("style", "")).strip()
    prompts: dict[str, str] = {}
    for shot in episode["shots"]:
        beats = {b["beat_no"]: b for b in shot["beats"]}
        negatives = _normalise_negative_prompts(shot)
        fallbacks = _normalise_fallbacks(shot)
        _validate_camera_extras(shot["camera"], _shot_label(shot))
        camera = shot["camera"]
        easing = camera.get("easing")
        end_size = camera.get("shot_size_end")
        resolved_anchors: dict[str, dict[str, Any]] = {}
        bindings: dict[int, dict[str, Any]] = {}
        if anchors is not None or reference_bindings is not None:
            if anchors is None or reference_bindings is None:
                raise PromptCompilerError(
                    f"story.prompt_compiler: {_shot_label(shot)} anchors and "
                    "reference_bindings must be supplied together"
                )
            _, _, resolve_picture_bindings = _scene_reference_helpers()
            bindings = resolve_picture_bindings(reference_bindings)
            resolved_anchors = resolve_shot_anchors(shot, anchors)
        _, movement_zh, movement_en = resolve_movement(camera["movement"])
        entry_state = _render_state(shot["continuity"]["entry_state"]).replace("\n", "；")
        for clip_index, clip in enumerate(shot.get("clips", [])):
            parts = [header, "Scene: " + clip_scene_sentence(shot, clip_index)]
            for beat_no in clip["beats"]:
                beat = beats[beat_no]
                parts.append("Beat: " + str(beat["action"]))
                line = str(beat.get("line", "") or "")
                if line.strip():
                    parts.append(
                        "Line (%s): %s" % (str(beat.get("speaker", "")), line)
                    )
            parts.append(
                f"Camera: {camera['shot_size']} {camera['angle']}, "
                f"{movement_zh} ({movement_en})."
            )
            parts.append(f"State: {entry_state}.")
            parts.append(f"Constraints: {SPEECH_DISCIPLINE}{BANS}")
            if resolved_anchors:
                anchor_parts = []
                for name in shot.get("characters") or []:
                    anchor = resolved_anchors.get(str(name))
                    if anchor is None:
                        continue
                    picture = _anchor_picture_number(anchor, bindings)
                    anchor_parts.append(
                        f"{name} ({anchor['look']}; Picture {picture})")
                if anchor_parts:
                    parts.append("Anchors: " + "; ".join(anchor_parts) + ".")
            if provider is not None:
                clip_beats = [beats[n] for n in clip["beats"]]
                clip_seconds = max(float(b["t_end_s"]) for b in clip_beats) - min(
                    float(b["t_start_s"]) for b in clip_beats)
                frames = frames_for_provider(clip_seconds, provider, fps)
                parts.append(f"Frames: {frames} ({fps:g}fps, {provider}).")
            if easing is not None:
                parts.append(
                    f"Easing: {easing}（{EASINGS[easing]}）"
                )
            if end_size is not None and end_size != camera["shot_size"]:
                parts.append(
                    f"Framing transition: {camera['shot_size']}→{end_size}"
                )
            if negatives:
                parts.append("Negative list: " + "; ".join(negatives))
            if fallbacks:
                parts.append(
                    "Fallbacks: "
                    + "; ".join(
                        f"{f['trigger']} => {f['replacement']}"
                        for f in fallbacks
                    )
                )
            prompts[str(clip["clip_id"])] = " ".join(parts)
    return prompts


def compile_episode(
    episode: dict[str, Any],
    provider_caps: dict[str, Any] | None = None,
    provider: str | None = None,
    *,
    anchors: dict[str, Any] | None = None,
    reference_bindings: dict[Any, Any] | None = None,
    strict: bool = False,
    fps: float = 24.0,
) -> dict[str, Any]:
    """Validate an episode through all five gates, then render prompts.

    Gate order: vocabulary/structure, gate 1 (beat coverage), clip
    grouping, split rule, gate 2 (line durations), gate 3 (line
    uniqueness), gate 4 (continuity chain + start-frame trigger
    state), gate 5 (episode total + supplier tier per clip). The
    first failure raises
    :class:`PromptCompilerError`; nothing is warned-and-passed.

    Tier resolution order: explicit ``provider_caps`` win; otherwise
    ``provider`` resolves through ``duration_tiers.json``; otherwise
    the tier verdict is ``"unknown"`` (total-duration check still
    enforced).

    With ``strict=True`` this is the generation-ready path: a
    provider with verified caps is required (``unknown`` fails),
    ``anchors`` and ``reference_bindings`` are required and must
    cover the episode, beat progression is checked, shot prompts
    are re-rendered with anchors/bindings/frames, and clip
    prompts are rendered by the same renderer and included under
    ``clip_prompts``. The legacy path (``strict=False``) is
    unchanged: it records ``unknown`` tiers and renders bare-name
    prompts, and must not be sent to generation.
    """
    if strict:
        effective_provider = provider or (
            provider_caps.get("provider") if isinstance(provider_caps, dict) else None
        ) or episode.get("provider")
        if not effective_provider:
            raise PromptCompilerError(
                "story.prompt_compiler: strict compile needs a provider; "
                "an 'unknown' tier never reaches generation"
            )
        if anchors is None or reference_bindings is None:
            raise PromptCompilerError(
                "story.prompt_compiler: strict compile needs anchors and "
                "reference_bindings; bare names and unbound Pictures "
                "never reach generation"
            )
        provider = effective_provider
    if not isinstance(episode, dict):
        raise PromptCompilerError(
            "story.prompt_compiler: episode must be a JSON object"
        )
    shots = check_structure(episode)
    check_vocabulary(episode)
    check_beat_coverage(shots)
    check_clip_groups(shots)
    check_long_lines(shots)
    check_line_durations(shots)
    check_line_uniqueness(shots)
    check_continuity_chain(shots)
    resolved_caps = provider_caps
    tier_unknown_reason = None
    if resolved_caps is None and provider:
        resolved = resolve_provider_caps(provider)
        if resolved is None:
            tier_unknown_reason = (
                f"no duration tier entry for provider {provider!r} in "
                "duration_tiers.json; pass provider_caps explicitly to "
                "enforce a tier"
            )
        elif (
            resolved.get("max_shot_s") is None
            and resolved.get("min_shot_s") is None
            and resolved.get("max_total_s") is None
        ):
            tier_unknown_reason = (
                f"duration tier entry for provider {provider!r} "
                "declares no verified cap; pass provider_caps "
                "explicitly to enforce a tier"
            )
        else:
            resolved_caps = resolved
    elif resolved_caps is None:
        tier_unknown_reason = (
            "no provider selected; pass provider=... to resolve a tier "
            "from duration_tiers.json, or provider_caps=... to enforce "
            "caps explicitly"
        )
    tier = check_total_and_tier(
        episode, shots, resolved_caps, tier_unknown_reason
    )
    if strict:
        if tier.get("status") != "checked":
            raise PromptCompilerError(
                "story.prompt_compiler: strict compile needs a provider "
                f"with verified caps; tier verdict is {tier.get('status')!r} "
                f"({tier.get('reason', '')})"
            )
        effective_provider = provider or episode.get("provider") or str(
            (provider_caps or {}).get("provider") or "")
        coverage = check_anchor_and_binding_coverage(episode, anchors, reference_bindings)
        for shot in shots:
            check_beat_progression(shot)
    prompts = [
        {
            "shot_no": str(shot.get("shot_no", "?")),
            "prompt": compile_shot_prompt(
                episode,
                shot,
                anchors=anchors if strict else None,
                reference_bindings=reference_bindings if strict else None,
                provider=effective_provider if strict else None,
                fps=fps,
            ),
            "negative_prompts": _normalise_negative_prompts(shot),
            "fallbacks": _normalise_fallbacks(shot),
            "easing": shot["camera"].get("easing"),
            "shot_size_end": shot["camera"].get("shot_size_end"),
        }
        for shot in shots
    ]
    if strict:
        for entry, shot in zip(prompts, shots):
            check_rendered_shot_prompt(entry["prompt"], shot)
    spoken = collect_spoken_lines(shots)
    result: dict[str, Any] = {
        "episode_no": episode["episode_no"],
        "title": episode["title"],
        "target_duration_s": episode["target_duration_s"],
        "total_duration_s": sum(float(s["duration_s"]) for s in shots),
        "shot_count": len(shots),
        "moving_line_count": len(
            [
                item
                for item in spoken
                if item[2] != "voiceover"
            ]
        ),
        "spoken_line_count": len(spoken),
        "tier": tier,
        "prompts": prompts,
        "strict": strict,
    }
    if strict:
        result["clip_prompts"] = compile_clip_prompts(
            episode,
            anchors=anchors,
            reference_bindings=reference_bindings,
            provider=effective_provider,
            fps=fps,
        )
        result["readiness"] = {
            "anchors": sorted(coverage["anchors"]),
            "picture_bindings": sorted(coverage["bindings"]),
            "provider": effective_provider,
        }
    return result


def compile_generation_ready_episode(
    episode: dict[str, Any],
    *,
    provider: str,
    anchors: dict[str, Any],
    reference_bindings: dict[Any, Any],
    provider_caps: dict[str, Any] | None = None,
    fps: float = 24.0,
) -> dict[str, Any]:
    """The single generation-ready entry point for beat-schema episodes.

    Fails hard on: no provider / unverified caps, unconfirmed or
    missing anchors, unbound Pictures, non-progressing beats, and
    start-frame text repeated inside beat segments. The returned
    prompts carry anchor looks, Picture -> file bindings and
    provider-route frame counts; ``clip_prompts`` come from the
    same renderer, so clip and shot prompts cannot drift apart.
    """
    return compile_episode(
        episode,
        provider_caps=provider_caps,
        provider=provider,
        anchors=anchors,
        reference_bindings=reference_bindings,
        strict=True,
        fps=fps,
    )


# ---------------------------------------------------------------------------
# Capability registration (same pattern as beat_align / episode_prompts)
# ---------------------------------------------------------------------------

_Registered = False

_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "episode": {
            "type": "object",
            "description": "Episode in the beat schema (episode + shots + beats + continuity).",
        },
        "provider_caps": {
            "type": "object",
            "description": (
                "Optional supplier tier caps, e.g. "
                '{"provider": "x", "max_shot_s": 30}. Explicit caps win '
                "over the tier table. Without caps or a provider key "
                "the tier verdict is recorded as unknown, never invented."
            ),
        },
        "provider": {
            "type": "string",
            "description": (
                "Optional provider key resolved through "
                "model_catalog_data/duration_tiers.json (e.g. "
                '"fasth3_local", "pixstag", "veo3"). Explicit '
                "provider_caps win over the table."
            ),
        },
    },
    "required": ["episode"],
    "additionalProperties": False,
}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> "CapabilityResult":
    from hevi.capabilities.errors import CapabilityError
    from hevi.capabilities.registry import CapabilityResult, compute_sha256

    try:
        payload = compile_episode(
            params["episode"], params.get("provider_caps"),
            params.get("provider"),
        )
    except PromptCompilerError as exc:
        raise CapabilityError(str(exc)) from exc
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "prompt_compiler_output.json"
    report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for item in payload["prompts"]:
        (prompts_dir / f"{item['shot_no']}.txt").write_text(
            item["prompt"], encoding="utf-8"
        )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "episode_no": payload["episode_no"],
            "shot_count": payload["shot_count"],
            "moving_line_count": payload["moving_line_count"],
            "tier": payload["tier"],
        },
    )


def register_prompt_compiler_capabilities_once() -> list[str]:
    """Register ``story.prompt_compiler`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    from hevi.capabilities.registry import Capability, register

    register(
        Capability(
            name="story.prompt_compiler",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Beat-schema prompt compiler: validates a per-shot "
                "beat-schema episode through five fatal gates (beat "
                "coverage, line durations, line uniqueness, continuity "
                "chain + start-frame trigger state, episode total + "
                "supplier tier) and renders one prompt per shot in a "
                "fixed section order, with lines taken verbatim from "
                "the schema. Closed vocabularies: shot sizes / angles "
                "are standard film grammar, movements are hevi's own "
                "40 cinematic_techniques movements. Long lines must be "
                "split across grouped beats; nothing is truncated, "
                "clamped or padded silently. Optional per-shot fields: "
                "negative_prompts (deduped list, rendered as "
                "[负面清单]), camera.easing (closed list incl. "
                "ease_in_out) and camera.shot_size_end (framing "
                "transition), and fallbacks (trigger + replacement, "
                "rendered as [备选方案] after the main prompt, never "
                "mixed into it). When none are filled, output is "
                "identical to the pre-change format."
            ),
            line="prompt_compiler",
        )
    )
    return ["story.prompt_compiler"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run story.prompt_compiler on a params JSON file"
    )
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
