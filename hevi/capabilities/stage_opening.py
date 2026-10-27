"""Opening blocking for a scene, decided before storyboarding.

Method idea (clean-room reimplementation, see
SHUOHAO_METHOD_ATTRIBUTION.md): a short drama is generated one
segment at a time, and every segment invents its own seating if
nobody fixes it first. So each scene gets one fixed opening
arrangement -- who is present at the start, next to which object,
on which side, sitting or standing, facing which way, and how
many extras are where -- before any storyboard is written. A
deterministic sentence is generated from that arrangement, and
the storyboard must copy that sentence verbatim into the first
segment of the same scene. Later segments continue from it; they
do not re-decide the opening.

This module judges structure only. It does not look at pictures:
recognising which objects exist in a scene image is still a human
or model-vision step that happens before the data arrives here.
What it does guarantee is that, once the objects are listed, every
placement lands on a listed object, nobody overlaps on one side,
nobody appears from nowhere, and the handoff sentence is exact.

Failure contract: the staging document must be a JSON object with
``locations`` and ``scenes`` lists, and every location, scene and
character id must be a non-empty string. Anything else raises
CapabilityError. Gate failures (bad counts, unknown locations,
cast mismatches, bad placements, overlaps, undeclared extras) do
not raise; they are reported as issues and the scene gets no
blocking sentence, because a sentence built on a broken
arrangement must not be handed to a storyboard.
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

_SIDES = ("north", "south", "east", "west", "on")
_POSTURES = ("sit", "stand")
_FACINGS = ("north", "south", "east", "west",
            "northeast", "northwest", "southeast", "southwest")
_SIDE_TEXT = {"north": "北侧", "south": "南侧", "east": "东侧",
              "west": "西侧", "on": "上"}
_FACING_TEXT = {"north": "北", "south": "南", "east": "东", "west": "西",
                "northeast": "东北", "northwest": "西北",
                "southeast": "东南", "southwest": "西南"}
# Same side of one object: two people need at least this much room
# between their along-positions, or they are standing on each other.
_MIN_ALONG_GAP = 0.10
_MAX_ITEMS_PER_LOCATION = 30


def _req_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"story.opening_blocking: {what} must be a non-empty string")
    return value.strip()


def _req_list(value: Any, what: str) -> list:
    if not isinstance(value, list):
        raise CapabilityError(f"story.opening_blocking: {what} must be a list")
    return value


def _clean_locations(raw: Any) -> dict[str, dict[str, Any]]:
    locations: dict[str, dict[str, Any]] = {}
    for i, loc in enumerate(_req_list(raw, "locations")):
        if not isinstance(loc, dict):
            raise CapabilityError(f"story.opening_blocking: locations[{i}] must be a JSON object")
        lid = _req_str(loc.get("id"), f"locations[{i}].id")
        if lid in locations:
            raise CapabilityError(f"story.opening_blocking: duplicate location id {lid!r}")
        items_raw = _req_list(loc.get("items", []), f"location {lid!r}.items")
        items: dict[str, dict[str, Any]] = {}
        for j, item in enumerate(items_raw):
            if not isinstance(item, dict):
                raise CapabilityError(
                    f"story.opening_blocking: location {lid!r} items[{j}] must be a JSON object")
            iid = _req_str(item.get("id"), f"location {lid!r} items[{j}].id")
            if iid in items:
                raise CapabilityError(
                    f"story.opening_blocking: location {lid!r} duplicate item id {iid!r}")
            items[iid] = {
                "id": iid,
                "name": _req_str(item.get("name"), f"location {lid!r} item {iid!r}.name"),
                "can_sit": bool(item.get("can_sit", False)),
            }
        locations[lid] = {
            "id": lid,
            "name": _req_str(loc.get("name"), f"location {lid!r}.name"),
            "items": items,
        }
    return locations


def _clean_scenes(raw: Any) -> list[dict[str, Any]]:
    scenes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, sc in enumerate(_req_list(raw, "scenes")):
        if not isinstance(sc, dict):
            raise CapabilityError(f"story.opening_blocking: scenes[{i}] must be a JSON object")
        sid = _req_str(sc.get("id"), f"scenes[{i}].id")
        if sid in seen:
            raise CapabilityError(f"story.opening_blocking: duplicate scene id {sid!r}")
        seen.add(sid)
        cast: dict[str, str] = {}
        for j, ch in enumerate(_req_list(sc.get("cast", []), f"scene {sid!r}.cast")):
            if not isinstance(ch, dict):
                raise CapabilityError(f"story.opening_blocking: scene {sid!r} cast[{j}] must be a JSON object")
            cid = _req_str(ch.get("id"), f"scene {sid!r} cast[{j}].id")
            cast[cid] = _req_str(ch.get("name"), f"scene {sid!r} cast[{j}].name")
        places: list[dict[str, Any]] = []
        for j, pl in enumerate(_req_list(sc.get("places", []), f"scene {sid!r}.places")):
            if not isinstance(pl, dict):
                raise CapabilityError(f"story.opening_blocking: scene {sid!r} places[{j}] must be a JSON object")
            places.append({
                "character_id": _req_str(pl.get("character_id"), f"scene {sid!r} places[{j}].character_id"),
                "present": pl.get("present"),
                "item_id": pl.get("item_id"),
                "side": pl.get("side"),
                "along": pl.get("along"),
                "posture": pl.get("posture"),
                "facing": pl.get("facing"),
            })
        script_cast = sc.get("script_cast")
        if script_cast is not None:
            if not isinstance(script_cast, list) or not all(isinstance(c, str) for c in script_cast):
                raise CapabilityError(f"story.opening_blocking: scene {sid!r}.script_cast must be a list of strings")
        scenes.append({
            "id": sid,
            "location_id": _req_str(sc.get("location_id"), f"scene {sid!r}.location_id"),
            "cast": cast,
            "places": places,
            "extras": sc.get("extras", 0),
            "extras_where": sc.get("extras_where"),
            "script_cast": script_cast,
        })
    return scenes


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _blocking_sentence(scene: dict[str, Any], location: dict[str, Any]) -> str:
    parts: list[str] = []
    for pl in scene["places"]:
        name = scene["cast"][pl["character_id"]]
        if not pl["present"]:
            parts.append(f"{name}开场不在场")
            continue
        item = location["items"][pl["item_id"]]
        verb = "坐" if pl["posture"] == "sit" else "站"
        if pl["side"] == "on":
            place_text = f"{item['name']}上"
        else:
            place_text = f"{item['name']}{_SIDE_TEXT[pl['side']]}"
        parts.append(f"{name}{verb}在{place_text}，面朝{_FACING_TEXT[pl['facing']]}")
    if scene["extras"]:
        parts.append(f"另有{scene['extras']}名群演在{scene['extras_where']}")
    else:
        parts.append("没有其他人")
    return "；".join(parts) + "。"


def build_opening_blocking(staging: dict[str, Any]) -> dict[str, Any]:
    """Validate a staging document and generate one blocking sentence per scene.

    Returns ``{"verdict": "pass"|"fail", "issues": [...], "scenes": [...]}``.
    A scene with any issue gets ``blocking: None`` -- a broken
    arrangement must not produce a sentence for a storyboard to copy.
    """
    if not isinstance(staging, dict):
        raise CapabilityError("story.opening_blocking: staging must be a JSON object")
    locations = _clean_locations(staging.get("locations"))
    scenes = _clean_scenes(staging.get("scenes"))
    issues: list[dict[str, Any]] = []
    out_scenes: list[dict[str, Any]] = []

    for loc in locations.values():
        count = len(loc["items"])
        if count < 1 or count > _MAX_ITEMS_PER_LOCATION:
            issues.append({"code": "LOC_ITEMS", "scene": None,
                           "message": f"location {loc['id']!r} lists {count} items, "
                                      f"expected 1-{_MAX_ITEMS_PER_LOCATION}"})

    for scene in scenes:
        scene_issues: list[dict[str, Any]] = []

        def _issue(code: str, message: str) -> None:
            entry = {"code": code, "scene": scene["id"], "message": message}
            scene_issues.append(entry)
            issues.append(entry)

        location = locations.get(scene["location_id"])
        if location is None:
            _issue("LOC_KNOWN", f"scene location {scene['location_id']!r} is not a listed location")
        place_ids = [pl["character_id"] for pl in scene["places"]]
        if len(set(place_ids)) != len(place_ids):
            _issue("CAST_EXACT", "a character has more than one placement in this scene")
        if set(place_ids) != set(scene["cast"]):
            _issue("CAST_EXACT", "placements do not cover the scene cast exactly once each")
        if scene["script_cast"] is not None and set(place_ids) != set(scene["script_cast"]):
            _issue("CAST_EXACT", "placements do not match the script cast for this scene")
        present_flags = [pl["present"] for pl in scene["places"]]
        if any(not isinstance(p, bool) for p in present_flags):
            _issue("PRESENT", "every placement must state present as true or false")
        elif not any(present_flags):
            _issue("PRESENT", "at least one character must be present at the opening")
        for pl in scene["places"]:
            cid = pl["character_id"]
            if pl["present"] is True:
                if location is not None and pl["item_id"] not in location["items"]:
                    _issue("ANCHOR", f"character {cid!r} is placed on unlisted item {pl['item_id']!r}")
                    continue
                if pl["side"] not in _SIDES:
                    _issue("PLACEMENT", f"character {cid!r} has unknown side {pl['side']!r}")
                if pl["posture"] not in _POSTURES:
                    _issue("PLACEMENT", f"character {cid!r} has unknown posture {pl['posture']!r}")
                if pl["facing"] not in _FACINGS:
                    _issue("PLACEMENT", f"character {cid!r} has unknown facing {pl['facing']!r}")
                if not _is_num(pl["along"]) or not (0.0 <= float(pl["along"]) <= 1.0):
                    _issue("PLACEMENT", f"character {cid!r} along must be a number in [0, 1]")
                if location is not None and pl["item_id"] in location["items"]:
                    item = location["items"][pl["item_id"]]
                    if pl["posture"] == "sit" and not item["can_sit"]:
                        _issue("PLACEMENT", f"character {cid!r} sits on {item['name']!r}, which cannot be sat on")
                    if pl["side"] == "on" and not item["can_sit"]:
                        _issue("PLACEMENT", f"character {cid!r} is on {item['name']!r}, which cannot be sat or stood on")
            elif pl["present"] is False:
                if any(pl[k] is not None for k in ("item_id", "side", "along", "posture", "facing")):
                    _issue("ANCHOR", f"character {cid!r} is absent at the opening but still has a placement")
        if location is not None:
            grouped: dict[tuple[str, str], list[tuple[str, float]]] = {}
            for pl in scene["places"]:
                if pl["present"] is True and pl["item_id"] in location["items"] \
                        and pl["side"] in _SIDES and _is_num(pl["along"]):
                    grouped.setdefault((pl["item_id"], pl["side"]), []).append(
                        (pl["character_id"], float(pl["along"])))
            for (item_id, side), members in grouped.items():
                members.sort(key=lambda m: m[1])
                for (c1, a1), (c2, a2) in zip(members, members[1:]):
                    if a2 - a1 < _MIN_ALONG_GAP:
                        _issue("OVERLAP", f"characters {c1!r} and {c2!r} overlap on "
                                          f"item {item_id!r} side {side!r} (gap {a2 - a1:.2f})")
        extras = scene["extras"]
        if not isinstance(extras, int) or isinstance(extras, bool) or extras < 0:
            _issue("EXTRAS", "extras must be a non-negative integer")
        elif extras > 0 and not (isinstance(scene["extras_where"], str) and scene["extras_where"].strip()):
            _issue("EXTRAS", "extras are declared but extras_where is empty")
        elif extras == 0 and scene["extras_where"] not in (None, ""):
            _issue("EXTRAS", "extras_where is set but extras is 0")
        blocking = None
        if not scene_issues and location is not None:
            blocking = _blocking_sentence(scene, location)
        out_scenes.append({
            "id": scene["id"],
            "location_id": scene["location_id"],
            "blocking": blocking,
            "present": [pl["character_id"] for pl in scene["places"] if pl["present"] is True],
            "issues": scene_issues,
        })
    return {"verdict": "fail" if issues else "pass", "issues": issues, "scenes": out_scenes}


def check_storyboard_opening(staging: dict[str, Any], storyboard: dict[str, Any]) -> dict[str, Any]:
    """Check that every scene's first storyboard segment copies its blocking sentence.

    The comparison is exact string equality after stripping: a
    paraphrase is a mismatch, because the whole point of the
    blocking sentence is that downstream segments do not re-decide
    the opening. Scenes whose blocking failed validation cannot be
    verified and count as failures here too.
    """
    if not isinstance(storyboard, dict):
        raise CapabilityError("qa.storyboard_opening_gate: storyboard must be a JSON object")
    blocking = build_opening_blocking(staging)
    board_scenes: dict[str, dict[str, Any]] = {}
    for i, sc in enumerate(_req_list(storyboard.get("scenes"), "storyboard.scenes")):
        if not isinstance(sc, dict):
            raise CapabilityError(f"qa.storyboard_opening_gate: storyboard scenes[{i}] must be a JSON object")
        board_scenes[_req_str(sc.get("id"), f"storyboard scenes[{i}].id")] = sc
    issues: list[dict[str, Any]] = []
    checked = 0
    for scene in blocking["scenes"]:
        checked += 1
        board = board_scenes.get(scene["id"])
        if board is None:
            issues.append({"code": "SCENE_MISSING", "scene": scene["id"],
                           "message": "scene has no storyboard entry"})
            continue
        if scene["blocking"] is None:
            issues.append({"code": "BLOCKING_UNAVAILABLE", "scene": scene["id"],
                           "message": "scene blocking failed validation, so its first segment cannot be verified"})
            continue
        segments = board.get("segments")
        if not isinstance(segments, list) or not segments:
            issues.append({"code": "SEGMENT_MISSING", "scene": scene["id"],
                           "message": "scene has no storyboard segments"})
            continue
        first = segments[0]
        if not isinstance(first, dict):
            issues.append({"code": "SEGMENT_MISSING", "scene": scene["id"],
                           "message": "first segment must be a JSON object"})
            continue
        copied = first.get("opening_blocking")
        if not isinstance(copied, str) or copied.strip() != scene["blocking"]:
            issues.append({"code": "BLOCKING_MISMATCH", "scene": scene["id"],
                           "message": "first segment does not copy the scene blocking sentence verbatim"})
    return {"verdict": "fail" if issues else "pass", "issues": issues,
            "checked_scenes": checked, "staging_verdict": blocking["verdict"]}


def _render_blocking(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_opening_blocking(params.get("staging"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "opening_blocking.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"],
            "scene_count": len(result["scenes"])},
    )


def _render_gate(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_storyboard_opening(params.get("staging"), params.get("storyboard"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "storyboard_opening_gate.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"],
            "checked_scenes": result["checked_scenes"]},
    )


def register_stage_opening_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="story.opening_blocking",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"staging": {"type": "object"}},
            "required": ["staging"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_blocking,
        has_media_output=False,
        description=(
            "Opening blocking (clean-room): validate one fixed opening "
            "arrangement per scene and generate the exact sentence the "
            "storyboard must copy into each scene's first segment. "
            "Structure only; scene images are not read here."
        ),
        line="story",
    ))
    register(Capability(
        name="qa.storyboard_opening_gate",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"staging": {"type": "object"}, "storyboard": {"type": "object"}},
            "required": ["staging", "storyboard"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_gate,
        has_media_output=False,
        description=(
            "Storyboard opening gate (clean-room): every scene's first "
            "segment must copy its blocking sentence verbatim. "
            "Paraphrases and missing scenes fail."
        ),
        line="qa",
    ))
    return ["story.opening_blocking", "qa.storyboard_opening_gate"]


register_stage_opening_capabilities_once()
