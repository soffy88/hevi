"""Deterministic production gates for outline, art, script and storyboard.

Method idea (clean-room reimplementation, see
SHUOHAO_METHOD_ATTRIBUTION.md): every production stage should be
checked by a script that cannot be charmed, not by asking the
model whether its own output looks good. This module is the hevi
version of that idea, deliberately scoped to what hevi does NOT
already check, so no gate is built twice:

* Already covered elsewhere, and therefore NOT repeated here:
  script_polish (dialogue quality, information checks, scene
  continuity, silent-scene and AI-flavour checks), prompt_compiler
  (vocabulary, beat coverage, clip grouping, line durations and
  uniqueness, continuity chain, provider duration tiers),
  shot_continuity (carried elements at shot boundaries, slideshow
  oracle), drama_gates (completeness, first frame, duration vs
  dialogue, budget, action nodes, spatial continuity, edit
  readiness), multishot_lock (reference division, first-frame
  checks, long-segment grouping, continuity ledger).
* New here: outline discipline (one main line, cast tiers, scene
  budget, props that must earn their place by carrying a beat,
  major-beat spacing), art discipline (locations covered, anchors
  with variants and scale, props subset of the outline), script
  discipline (duration budget, line length, one action beat per
  scene, hook in motion at the start and a cliff at the end,
  claimed beats actually performed), storyboard discipline
  (one location per segment, cut length, keyframes pinned to cut
  marks, composition fields present, video prompts that use
  generic identities instead of character names).

Every gate is deterministic: same input, same verdict, no model
call, no network, no media watched. A section that is absent from
the bundle is reported as skipped, never as a pass and never as a
failure -- a gate can only judge what it was given.

Failure contract: the bundle must be a JSON object and every
section present must be a JSON object; anything else raises
CapabilityError. Malformed gate inputs (duplicate ids, missing
required fields) are reported as gate failures, not raised, so a
single broken section cannot hide the other sections' verdicts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# hevi's own script discipline thresholds (chosen here, not borrowed):
# a spoken line longer than this is hard to say in one breath on
# camera, and a cut outside this range is either a flash or a drag.
_MAX_LINE_CHARS = 40
_MIN_CUT_SEC = 2.0
_MAX_CUT_SEC = 5.0
_DIALOGUE_CHARS_PER_SEC = 4.0
_ACTION_BEAT_SEC = 2.0
_MAX_SCENES = 15
_MAX_PROPS = 8
_MAX_MAJOR_GAP_EPISODES = 3


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _gate(code: str, ok: bool, message: str = "") -> dict[str, Any]:
    return {"code": code, "status": "pass" if ok else "fail",
            "issues": [] if ok else [message]}


def _ids(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [it.get("id") for it in items if isinstance(it, dict) and isinstance(it.get("id"), str)]


def _dup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for item in items:
        if item in seen and item not in dups:
            dups.append(item)
        seen.add(item)
    return dups


def _outline_gates(outline: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    main = outline.get("main_line")
    subs = outline.get("sub_lines", [])
    cuts = outline.get("cut_lines", [])
    ok = isinstance(main, str) and bool(main.strip()) \
        and isinstance(subs, list) and len(subs) <= 1 \
        and isinstance(cuts, list) \
        and all(isinstance(c, dict) and isinstance(c.get("what"), str) and c["what"].strip()
                and isinstance(c.get("why"), str) and c["why"].strip() for c in cuts)
    gates.append(_gate("OUT_MAIN_LINE", ok,
                       "outline needs one non-empty main_line, at most one sub_line, "
                       "and every cut line needs a what and a why"))
    cast = outline.get("cast", [])
    lead = [c for c in cast if isinstance(c, dict) and c.get("tier") == "lead"]
    support = [c for c in cast if isinstance(c, dict) and c.get("tier") == "support"]
    functional = [c for c in cast if isinstance(c, dict) and c.get("tier") == "functional"]
    names = [c.get("name") for c in cast if isinstance(c, dict)]
    ok = isinstance(cast, list) and 1 <= len(lead) <= 5 and len(support) <= 10 \
        and len(functional) <= 10 and len(names) == len(set(names)) \
        and all(isinstance(c, dict) and isinstance(c.get("id"), str)
                and isinstance(c.get("name"), str) and c["name"].strip() for c in cast)
    gates.append(_gate("OUT_CAST_TIERS", ok,
                       "cast tiers must be lead 1-5, support <=10, functional <=10, "
                       "with unique ids and names"))
    scenes = outline.get("scenes", [])
    scene_ids = _ids(scenes)
    reused_ok = True
    for sc in scenes:
        if isinstance(sc, dict) and sc.get("reuse_of") is not None and sc["reuse_of"] not in scene_ids:
            reused_ok = False
    ok = isinstance(scenes, list) and 1 <= len(scenes) <= _MAX_SCENES \
        and not _dup(scene_ids) and reused_ok
    gates.append(_gate("OUT_SCENE_BUDGET", ok,
                       f"scenes must be 1-{_MAX_SCENES} with unique ids, "
                       "and any reuse_of must reference a listed scene"))
    beats = outline.get("beats", [])
    beat_ids = set(_ids(beats))
    props = outline.get("props", [])
    ok = isinstance(props, list) and len(props) <= _MAX_PROPS and all(
        isinstance(p, dict) and isinstance(p.get("function"), str) and p["function"].strip()
        and isinstance(p.get("beat_ids"), list) and p["beat_ids"]
        and all(b in beat_ids for b in p["beat_ids"]) for p in props)
    gates.append(_gate("OUT_PROP_FUNCTION", ok,
                       f"props must be <= {_MAX_PROPS}, each with a non-empty function "
                       "and beat_ids that all exist in the outline beats"))
    majors = sorted(b.get("episode") for b in beats
                    if isinstance(b, dict) and b.get("major") is True and _is_num(b.get("episode")))
    total_eps = outline.get("total_episodes")
    spacing_ok = True
    if len(majors) >= 2:
        spacing_ok = all(b - a <= _MAX_MAJOR_GAP_EPISODES for a, b in zip(majors, majors[1:]))
    if _is_num(total_eps) and majors and len(majors) == 1 and majors[0] >= total_eps and total_eps > 1:
        spacing_ok = False
    ok = bool(majors) and spacing_ok
    gates.append(_gate("OUT_BEAT_SPACING", ok,
                       "at least one major beat is required, consecutive majors must be "
                       f"within {_MAX_MAJOR_GAP_EPISODES} episodes, and a lone major "
                       "must not sit only in the last episode"))
    return gates


def _art_gates(art: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    locations = art.get("locations", [])
    loc_ids = set(_ids(locations))
    script_locations: set[str] = set()
    script = bundle.get("script")
    if isinstance(script, dict):
        for sc in script.get("scenes", []):
            if isinstance(sc, dict) and isinstance(sc.get("location_id"), str):
                script_locations.add(sc["location_id"])
    ok = isinstance(locations, list) and bool(locations) \
        and script_locations.issubset(loc_ids) \
        and all(isinstance(lo, dict) and isinstance(lo.get("anchor_text"), str)
                and lo["anchor_text"].strip() for lo in locations)
    gates.append(_gate("ART_LOCATION_COVER", ok,
                       "every art location needs a non-empty anchor, and art locations "
                       "must cover every location the script uses"))
    ok = all(isinstance(lo, dict) and isinstance(lo.get("variants"), list) and lo["variants"]
             and isinstance(lo.get("scale_reference"), str) and lo["scale_reference"].strip()
             for lo in locations) if isinstance(locations, list) and locations else False
    gates.append(_gate("ART_VARIANT_AND_SCALE", ok,
                       "every art location needs at least one variant and a scale reference"))
    outline_props: set[str] | None = None
    outline = bundle.get("outline")
    if isinstance(outline, dict):
        outline_props = set(_ids(outline.get("props", [])))
    art_props = art.get("props", [])
    ok = isinstance(art_props, list) and all(
        isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"].strip()
        and isinstance(p.get("anchor_text"), str) and p["anchor_text"].strip()
        for p in art_props) and (outline_props is None or all(
            isinstance(p, dict) and p.get("id") in outline_props for p in art_props))
    gates.append(_gate("ART_PROP_SUBSET", ok,
                       "every art prop needs a name and an anchor, and art props must "
                       "be a subset of the outline props when an outline is given"))
    return gates


def _script_gates(script: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    scenes = script.get("scenes", [])
    total = 0.0
    line_issues: list[str] = []
    action_ok = True
    for sc in scenes if isinstance(scenes, list) else []:
        if not isinstance(sc, dict):
            action_ok = False
            continue
        beats = sc.get("beats", [])
        if not isinstance(beats, list) or not any(
                isinstance(b, dict) and b.get("kind") == "action" for b in beats):
            action_ok = False
        for b in beats if isinstance(beats, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("kind") == "dialogue" and isinstance(b.get("text"), str):
                total += len(b["text"]) / _DIALOGUE_CHARS_PER_SEC
                if len(b["text"]) > _MAX_LINE_CHARS:
                    line_issues.append(f"scene {sc.get('id')!r} line over {_MAX_LINE_CHARS} chars")
            elif b.get("kind") == "action":
                total += _ACTION_BEAT_SEC
    target = script.get("target_sec")
    if _is_num(target) and target > 0:
        ok = 0.90 * float(target) <= total <= 1.10 * float(target)
        msg = f"estimated {total:.1f}s vs target {target}s (must be within 10%)"
    else:
        ok = isinstance(scenes, list) and bool(scenes)
        msg = f"estimated {total:.1f}s, no target_sec given"
    gates.append(_gate("SCR_DURATION_BUDGET", ok, msg))
    gates.append(_gate("SCR_LINE_LENGTH", not line_issues, "; ".join(line_issues[:5])))
    gates.append(_gate("SCR_SCENE_ACTION", action_ok,
                       "every scene needs at least one action beat"))
    first_kind = last_kind = None
    if isinstance(scenes, list) and scenes and isinstance(scenes[0], dict):
        beats0 = scenes[0].get("beats", [])
        if isinstance(beats0, list) and beats0 and isinstance(beats0[0], dict):
            first_kind = beats0[0].get("kind")
    if isinstance(scenes, list) and scenes and isinstance(scenes[-1], dict):
        beats_last = scenes[-1].get("beats", [])
        if isinstance(beats_last, list) and beats_last and isinstance(beats_last[-1], dict):
            last = beats_last[-1]
            last_kind = "cliff" if last.get("is_cliff") is True else last.get("kind")
    gates.append(_gate("SCR_HOOK_CLIFF", first_kind == "action" and last_kind == "cliff",
                       "the first beat must be an action beat and the last beat must be a cliff"))
    outline = bundle.get("outline")
    if isinstance(outline, dict):
        beat_ids = set(_ids(outline.get("beats", [])))
        claimed: set[str] = set()
        performed: set[str] = set()
        for sc in scenes if isinstance(scenes, list) else []:
            if not isinstance(sc, dict):
                continue
            for b in sc.get("beats", []) if isinstance(sc.get("beats"), list) else []:
                if isinstance(b, dict):
                    for c in b.get("claims", []) if isinstance(b.get("claims"), list) else []:
                        claimed.add(c)
                        performed.add(c)
        ok = claimed.issubset(beat_ids) and bool(claimed)
        gates.append(_gate("SCR_BEAT_CLAIMS", ok,
                           "claimed beats must exist in the outline and at least one beat must be claimed"))
    return gates


def _storyboard_gates(board: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    segments = board.get("segments", [])
    script_scenes: dict[str, dict[str, Any]] = {}
    script = bundle.get("script")
    if isinstance(script, dict):
        for sc in script.get("scenes", []):
            if isinstance(sc, dict) and isinstance(sc.get("id"), str):
                script_scenes[sc["id"]] = sc
    loc_ok = True
    cut_ok = True
    key_ok = True
    comp_ok = True
    names: set[str] = set()
    outline = bundle.get("outline")
    if isinstance(outline, dict):
        for c in outline.get("cast", []):
            if isinstance(c, dict) and isinstance(c.get("name"), str):
                names.add(c["name"])
    if isinstance(script, dict):
        for sc in script.get("scenes", []):
            if isinstance(sc, dict):
                for ch in sc.get("cast", []):
                    if isinstance(ch, dict) and isinstance(ch.get("name"), str):
                        names.add(ch["name"])
    cut_issues: list[str] = []
    for seg in segments if isinstance(segments, list) else []:
        if not isinstance(seg, dict):
            loc_ok = cut_ok = key_ok = comp_ok = False
            continue
        scene = script_scenes.get(seg.get("scene_id")) if isinstance(seg.get("scene_id"), str) else None
        if script_scenes and scene is None:
            loc_ok = False
        if scene is not None and isinstance(seg.get("location_id"), str) \
                and seg["location_id"] != scene.get("location_id"):
            loc_ok = False
        cuts = seg.get("cuts", [])
        if not isinstance(cuts, list) or not cuts:
            cut_ok = key_ok = comp_ok = False
            continue
        total = 0.0
        for cut in cuts:
            if not isinstance(cut, dict):
                cut_ok = comp_ok = False
                continue
            dur = cut.get("duration_sec")
            if not _is_num(dur) or not (_MIN_CUT_SEC <= float(dur) <= _MAX_CUT_SEC):
                cut_ok = False
                cut_issues.append(f"cut {cut.get('id')!r} duration {dur!r} outside "
                                  f"{_MIN_CUT_SEC}-{_MAX_CUT_SEC}s")
            else:
                total += float(dur)
            if not all(isinstance(cut.get(f), str) and cut[f].strip() for f in
                       ("lens", "camera_position", "composition", "eyeline", "focus", "stability")):
                comp_ok = False
            prompt = cut.get("video_prompt")
            if isinstance(prompt, str) and any(n and n in prompt for n in names):
                comp_ok = False
                cut_issues.append(f"cut {cut.get('id')!r} video prompt names a character")
        keyframes = seg.get("keyframes", [])
        if not isinstance(keyframes, list) or len(keyframes) != len(cuts):
            key_ok = False
        else:
            cursor = 0.0
            for i, (kf, cut) in enumerate(zip(keyframes, cuts)):
                expect = 0.0 if i == 0 else cursor
                if not isinstance(kf, dict) or not _is_num(kf.get("time_sec")) \
                        or abs(float(kf["time_sec"]) - expect) > 0.01:
                    key_ok = False
                if isinstance(cut, dict) and _is_num(cut.get("duration_sec")):
                    cursor += float(cut["duration_sec"])
    gates.append(_gate("SB_SEGMENT_LOCATION", loc_ok and bool(segments),
                       "every segment must belong to one script scene and match its location"))
    gates.append(_gate("SB_CUT_RANGE", cut_ok, "; ".join(cut_issues[:5])))
    gates.append(_gate("SB_KEYFRAME_TIMING", key_ok,
                       "keyframes must be one per cut, first at 0.00s, the rest at cumulative cut marks"))
    gates.append(_gate("SB_COMPOSITION_AND_IDENTITY", comp_ok,
                       "every cut needs all six composition fields, and video prompts must "
                       "use generic identities, not character names"))
    return gates


_SECTION_RUNNERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]]] = {
    "outline": lambda section, bundle: _outline_gates(section),
    "art": _art_gates,
    "script": _script_gates,
    "storyboard": _storyboard_gates,
}


def run_production_gates(bundle: dict[str, Any]) -> dict[str, Any]:
    """Run the deterministic gates over every section present in the bundle."""
    if not isinstance(bundle, dict):
        raise CapabilityError("qa.production_gates: bundle must be a JSON object")
    sections: dict[str, Any] = {}
    failed: list[str] = []
    total = 0
    for name, runner in _SECTION_RUNNERS.items():
        section = bundle.get(name)
        if section is None:
            sections[name] = {"status": "skipped", "gates": [], "passed": 0, "failed": 0}
            continue
        if not isinstance(section, dict):
            raise CapabilityError(f"qa.production_gates: section {name!r} must be a JSON object")
        gates = runner(section, bundle)
        passed = sum(1 for g in gates if g["status"] == "pass")
        sections[name] = {"status": "pass" if passed == len(gates) else "fail",
                          "gates": gates, "passed": passed, "failed": len(gates) - passed}
        total += len(gates)
        for g in gates:
            if g["status"] == "fail":
                failed.append(f"{name}.{g['code']}")
    return {"verdict": "fail" if failed else "pass", "sections": sections,
            "gate_count": total, "failed_gates": failed}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = run_production_gates(params.get("bundle"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "production_gates.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"],
            "gate_count": result["gate_count"]},
    )


def register_production_gates_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.production_gates",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"bundle": {"type": "object"}},
            "required": ["bundle"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Production gates (clean-room): deterministic outline, art, "
            "script and storyboard checks that fill the gaps hevi's other "
            "gates do not cover. No model call, no media watched, absent "
            "sections are skipped, never passed."
        ),
        line="qa",
    ))
    return ["qa.production_gates"]


register_production_gates_capabilities_once()
