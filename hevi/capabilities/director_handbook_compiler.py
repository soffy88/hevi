"""Director handbook block compiler (``story.director_handbook_compiler``).

Clean-room rewrite of the *method* in ``hevi-vs-ai-manju-skills.md``
section 2 / B2: a per-episode director handbook block -- one
still-image prompt (segment A) plus one staged video prompt
(segment B) per shot -- is compiled through hevi's own prompt
caliber instead of being pasted as free text:

1. Reference numbering: each shot's reference plan is judged by
   ``qa.reference_numbering_gate`` and must pass; the foreign
   ``{{Mixed N}}`` notation never enters, because the numbering
   gate only knows the declared conventions.
2. Three layers: segment B is rendered by
   ``qa.three_layer_clip`` (common constraints / opening still /
   staged action), with millisecond timecodes, and must pass its
   gate. The A-segment still text becomes the clip's opening
   still, so the two segments cannot drift apart.
3. Duration tier: a declared provider resolves through
   ``duration_tiers.json`` (the ``story.prompt_compiler`` gate 5
   table); a shot longer than the tier's per-shot cap fails, and
   an unresolvable provider is recorded as ``unknown``, never
   used to clamp or pad.
4. Cross-shot continuity: the axis side must not flip without a
   declared justification, a prop's state must not change
   without a declared transition, and a prop must not vanish
   without a declared exit. Where two or more shots declare
   match sides, the chain is judged by ``qa.segment_match_gate``
   and must pass.

This module compiles plans into prompt text. It calls no
generator, stores no key, and touches no budget. Real
generation waits on a channel, a key, and a budget, and is not
covered here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.reference_numbering_gate import check_reference_numbering
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.segment_match_gate import check_segment_match
from hevi.capabilities.three_layer_clip import (
    check_three_layer_clip,
    render_three_layer_clip,
)

_Registered = False


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _report_ok(report: dict[str, Any]) -> bool:
    if "ok" in report:
        return bool(report["ok"])
    return report.get("verdict") == "pass"


def _duration_tiers() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parent
        / "model_catalog_data"
        / "duration_tiers.json"
    )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tiers = doc.get("tiers")
    return tiers if isinstance(tiers, dict) else {}


def compile_handbook_block(block: Any) -> dict[str, Any]:
    """Compile one handbook block. Returns a report; never raises for a bad plan.

    Verdicts are ``pass`` / ``fail`` only. ``compiled_text`` is
    present per shot only when that shot passed every check.
    """
    issues: list[dict[str, Any]] = []
    shots_out: list[dict[str, Any]] = []
    tier_verdict = "unknown"
    provider = None

    if not isinstance(block, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "episode_no": None,
            "shots": [],
            "continuity": {},
            "issues": [
                _issue(
                    "block_not_object",
                    "story.director_handbook_compiler: handbook block "
                    "must be an object",
                )
            ],
        }

    episode_no = block.get("episode_no")
    if not isinstance(episode_no, int) or isinstance(episode_no, bool):
        issues.append(
            _issue(
                "episode_no_missing",
                "story.director_handbook_compiler: the block must declare "
                "an integer 'episode_no'",
            )
        )
    provider = block.get("provider")
    tier: dict[str, Any] | None = None
    if provider is not None:
        if not isinstance(provider, str) or not provider.strip():
            issues.append(
                _issue(
                    "provider_invalid",
                    "story.director_handbook_compiler: 'provider' must be "
                    "a non-empty string",
                )
            )
        else:
            tier = _duration_tiers().get(provider)
            if not isinstance(tier, dict) or tier.get("max_shot_s") is None:
                issues.append(
                    _issue(
                        "duration_tier_unresolved",
                        "story.director_handbook_compiler: provider "
                        f"{provider!r} does not resolve to a known "
                        "duration tier; the tier is recorded as unknown, "
                        "never invented",
                    )
                )
                tier = None
            else:
                tier_verdict = "known"

    shots = block.get("shots")
    if not isinstance(shots, list) or not shots:
        issues.append(
            _issue(
                "shots_missing",
                "story.director_handbook_compiler: the block needs a "
                "non-empty 'shots' list in play order",
            )
        )
        shots = []

    last_side: str | None = None
    prop_states: dict[str, Any] = {}
    match_segments: list[dict[str, Any]] = []
    match_declared = True
    for index, shot in enumerate(shots):
        label = f"shot {index + 1}"
        entry: dict[str, Any] = {"label": label}
        if not isinstance(shot, dict):
            issues.append(
                _issue(
                    "shot_not_object",
                    f"story.director_handbook_compiler: {label} must be an "
                    "object",
                )
            )
            shots_out.append(entry)
            continue
        shot_no = shot.get("shot_no")
        if shot_no is not None:
            label = f"shot {shot_no}"
            entry["label"] = label
        entry["shot_no"] = shot_no

        # 1. Reference numbering.
        references = shot.get("references")
        if not isinstance(references, dict):
            issues.append(
                _issue(
                    "missing_reference_plan",
                    f"story.director_handbook_compiler: {label} must carry "
                    "a 'references' plan for the numbering gate",
                )
            )
        else:
            numbering = check_reference_numbering(references)
            entry["numbering"] = {
                "verdict": numbering.get("verdict"),
                "convention": numbering.get("convention"),
            }
            if not _report_ok(numbering):
                issues.append(
                    _issue(
                        "numbering_gate_failed",
                        f"story.director_handbook_compiler: {label} "
                        "reference plan failed the numbering gate: "
                        f"{numbering.get('issues')}",
                    )
                )

        # 2. Three-layer clip: A-segment still + B-segment beats.
        segment_a = shot.get("segment_a")
        segment_b = shot.get("segment_b")
        still_text = None
        clip: dict[str, Any] | None = None
        if isinstance(segment_a, dict):
            still_text = segment_a.get("still_text")
        if not isinstance(still_text, str) or not still_text.strip():
            issues.append(
                _issue(
                    "still_text_missing",
                    f"story.director_handbook_compiler: {label} segment A "
                    "must declare a non-empty 'still_text'",
                )
            )
        if not isinstance(segment_b, dict):
            issues.append(
                _issue(
                    "segment_b_missing",
                    f"story.director_handbook_compiler: {label} must carry "
                    "a 'segment_b' staged-action block",
                )
            )
        else:
            beats = segment_b.get("beats")
            duration_s = segment_b.get("duration_s")
            if not isinstance(beats, list) or not beats:
                issues.append(
                    _issue(
                        "beats_missing",
                        f"story.director_handbook_compiler: {label} "
                        "segment B needs a non-empty 'beats' list",
                    )
                )
            elif not all(
                isinstance(b, dict)
                and _is_number(b.get("t_start_s"))
                and _is_number(b.get("t_end_s"))
                and isinstance(b.get("action"), str)
                and b.get("action").strip()
                for b in beats
            ):
                issues.append(
                    _issue(
                        "beat_shape_invalid",
                        f"story.director_handbook_compiler: {label} every "
                        "beat needs numeric t_start_s/t_end_s and a "
                        "non-empty 'action'",
                    )
                )
            if not _is_number(duration_s) or duration_s <= 0:
                issues.append(
                    _issue(
                        "duration_missing",
                        f"story.director_handbook_compiler: {label} "
                        "segment B must declare a positive 'duration_s'",
                    )
                )
            elif tier is not None and float(duration_s) > float(tier["max_shot_s"]):
                issues.append(
                    _issue(
                        "shot_exceeds_tier_cap",
                        f"story.director_handbook_compiler: {label} runs "
                        f"{float(duration_s):g}s, over the {provider} "
                        f"per-shot cap of {tier['max_shot_s']:g}s",
                    )
                )
            if (
                isinstance(still_text, str)
                and still_text.strip()
                and isinstance(beats, list)
                and beats
                and _is_number(duration_s)
            ):
                clip = {
                    "style": segment_b.get("style", ""),
                    "characters": segment_b.get("characters", []),
                    "still_instant": still_text.strip(),
                    "beats": beats,
                    "duration_s": duration_s,
                    "aspect": segment_b.get("aspect", ""),
                }
                if segment_b.get("static_camera") is True:
                    clip["static_camera"] = True
                layer = check_three_layer_clip(clip)
                entry["three_layer"] = {
                    "verdict": layer.get("verdict", "pass" if _report_ok(layer) else "fail"),
                    "issues": layer.get("issues", []),
                }
                if _report_ok(layer):
                    entry["compiled_text"] = render_three_layer_clip(clip)
                else:
                    issues.append(
                        _issue(
                            "three_layer_gate_failed",
                            f"story.director_handbook_compiler: {label} "
                            "failed the three-layer clip gate: "
                            f"{layer.get('issues')}",
                        )
                    )
        entry["duration_tier"] = {"provider": provider, "verdict": tier_verdict}

        # 4a. Axis discipline across shots.
        side = shot.get("camera_side")
        if side is not None:
            if side not in ("left", "right"):
                issues.append(
                    _issue(
                        "camera_side_unknown",
                        f"story.director_handbook_compiler: {label} "
                        f"'camera_side' {side!r} must be 'left' or 'right'",
                    )
                )
            elif last_side is not None and side != last_side:
                if shot.get("axis_crossing_justified") is not True:
                    issues.append(
                        _issue(
                            "axis_crossing_unjustified",
                            f"story.director_handbook_compiler: {label} "
                            f"crosses the axis ({last_side} -> {side}) "
                            "without 'axis_crossing_justified: true'",
                        )
                    )
            last_side = side

        # 4b. Prop state chain across shots.
        props = shot.get("props")
        transitions = shot.get("prop_transitions") or []
        exits = shot.get("prop_exits") or []
        if props is None:
            # No props declaration at all: read as an empty prop set,
            # so a prop carried by earlier shots vanishes undeclared
            # unless the shot declares a prop exit.
            props = []
        if True:
            if not isinstance(props, list):
                issues.append(
                    _issue(
                        "props_not_list",
                        f"story.director_handbook_compiler: {label} 'props' "
                        "must be a list",
                    )
                )
            else:
                seen_here: dict[str, Any] = {}
                for prop in props:
                    if not isinstance(prop, dict) or not prop.get("prop_id"):
                        issues.append(
                            _issue(
                                "prop_shape_invalid",
                                f"story.director_handbook_compiler: {label} "
                                "every prop needs a 'prop_id'",
                            )
                        )
                        continue
                    seen_here[prop["prop_id"]] = prop.get("state")
                    if prop["prop_id"] in prop_states and prop.get("state") != prop_states[prop["prop_id"]]:
                        if prop["prop_id"] not in transitions:
                            issues.append(
                                _issue(
                                    "prop_state_break",
                                    f"story.director_handbook_compiler: "
                                    f"{label} prop {prop['prop_id']!r} "
                                    "changes state without a declared "
                                    "'prop_transitions' entry",
                                )
                            )
                for prop_id in prop_states:
                    if prop_id not in seen_here and prop_id not in exits:
                        issues.append(
                            _issue(
                                "prop_disappears_undeclared",
                                f"story.director_handbook_compiler: {label} "
                                f"prop {prop_id!r} vanishes without a "
                                "declared 'prop_exits' entry",
                            )
                        )
                prop_states = seen_here

        # 4c. Match sides for the segment-match gate.
        outgoing = shot.get("outgoing")
        incoming = shot.get("incoming")
        segment: dict[str, Any] = {"segment_id": shot_no if shot_no is not None else index + 1}
        if isinstance(outgoing, dict):
            segment["outgoing"] = outgoing
        if isinstance(incoming, dict):
            segment["incoming"] = incoming
        if len(shots) > 1 and (outgoing is None or incoming is None):
            # First shot needs only outgoing, last only incoming; the
            # middle shots need both. A missing side on an edge shot
            # is still a missing declaration for its one boundary.
            if not (index == 0 and incoming is None and outgoing is not None) and not (
                index == len(shots) - 1 and outgoing is None and incoming is not None
            ):
                match_declared = False
        match_segments.append(segment)
        shots_out.append(entry)

    continuity: dict[str, Any] = {
        "axis_sides": last_side,
        "prop_states": prop_states,
    }
    if len(shots) > 1:
        if not match_declared:
            issues.append(
                _issue(
                    "missing_match_declarations",
                    "story.director_handbook_compiler: a multi-shot block "
                    "must declare outgoing/incoming match sides on every "
                    "shot so the match chain can be judged",
                )
            )
            continuity["segment_match"] = "not_checked"
        else:
            match = check_segment_match({"segments": match_segments})
            continuity["segment_match"] = match.get("verdict")
            continuity["segment_match_boundaries"] = match.get("boundaries")
            if not _report_ok(match):
                issues.append(
                    _issue(
                        "segment_match_failed",
                        "story.director_handbook_compiler: the match chain "
                        f"failed: {match.get('issues')}",
                    )
                )
    elif len(shots) == 1:
        continuity["segment_match"] = "not_applicable"

    verdict = "pass" if not issues else "fail"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "episode_no": episode_no if isinstance(episode_no, int) else None,
        "duration_tier": {"provider": provider, "verdict": tier_verdict},
        "shots": shots_out,
        "continuity": continuity,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = compile_handbook_block(params.get("block"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "director_handbook_compiler_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_director_handbook_compiler_capabilities_once() -> list[str]:
    """Register ``story.director_handbook_compiler`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.director_handbook_compiler",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "block": {"type": "object"},
                },
                "required": ["block"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Director handbook block compiler: each shot's still "
                "prompt and staged video prompt are compiled through "
                "the numbering gate, the three-layer clip gate with "
                "millisecond timecodes, the duration-tier table, and "
                "the segment-match chain, with axis and prop continuity "
                "checked across shots. Plans are compiled, never sent "
                "to a generator."
            ),
            line="story",
        )
    )
    return ["story.director_handbook_compiler"]


register_director_handbook_compiler_capabilities_once()
