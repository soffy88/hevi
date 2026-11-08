"""Greenscreen generation gate (``qa.greenscreen_generation_gate``).

Method reconstructed from the *article description* in
``hevi-vs-code-stage-mv.md`` section 2 (see
CODE_STAGE_MV_ATTRIBUTION.md): the article itself supplies no
code, no workflow file and no reproducible engineering, and its
self-reported numbers are not used here as thresholds. This
module judges a generation *plan* (prompt text plus structured
fields) only. It generates no video, calls no provider and
touches no external account.

Five executable constraints; a plan missing any one of them
fails, naming the constraint:

1. Fixed full-body camera: the camera is fixed and the shot is
   full-body, and the prompt carries no camera-movement wording.
2. Subject stays in frame: full-body visibility is declared and
   the subject is declared not to exit the frame.
3. Pure green background, no stage / lighting / effects: the
   background is declared pure green (``#00FF00``), and the
   prompt carries no stage, lighting or effect wording.
4. Duration / fps / resolution consistent with the provider cap:
   the provider cap is resolved exactly the way
   ``story.prompt_compiler`` resolves it -- explicit
   ``provider_caps`` win, otherwise the provider key resolves
   through ``duration_tiers.json`` -- and an unknown tier fails.
   No cap is invented: when the tier table declares no fps or
   resolution cap, only presence and positivity of fps /
   resolution are checked, and that is recorded.
5. Character anchor + reference binding through the strict
   entry: the character's anchor is resolved by
   ``pipeline.scene_reference.resolve_character_anchor`` (a
   confirmed anchor only, exactly as the strict prompt-compiler
   path requires), the anchor file must appear in the Picture
   bindings, and Picture 1 must be bound.

Failure contract: a malformed plan (not a JSON object, or no
usable prompt / character text) raises
:class:`CapabilityError`. A well-formed plan that violates a
constraint returns ``verdict: "fail"`` with named issues; it
never raises. Anchor / binding problems found by the strict
resolver are reported as issues, not raised, because they are
plan failures, not malformed input -- except that missing
``anchors`` / ``reference_bindings`` entirely is itself a
named issue, never a silent fallback to a bare name.
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

PURE_GREEN_HEX = "#00ff00"

# Stage / lighting / effect wording that must never appear in a
# greenscreen dance prompt: the dance carries the movement only;
# stage, light and effects are added later, in code.
STAGE_BANNED_WORDS = (
    "stage",
    "spotlight",
    "strobe",
    "laser",
    "neon",
    "backdrop",
    "scenery",
    "props",
    "special effect",
    "special effects",
    "particle",
    "particles",
    "lens flare",
    "bokeh",
    "concert",
    "led wall",
    "light show",
    "lighting rig",
    "lighting",
    "舞臺",
    "舞台",
    "灯光",
    "聚光灯",
    "特效",
    "粒子",
    "布景",
    "道具",
    "霓虹",
    "镭射",
)

# Camera-movement wording that contradicts a fixed camera.
CAMERA_MOVEMENT_WORDS = (
    "pan",
    "tilt",
    "dolly",
    "crane",
    "tracking shot",
    "tracking",
    "zoom",
    "handheld",
    "orbit",
    "push in",
    "pull out",
    "camera moves",
    "camera movement",
    "镜头移动",
    "推拉",
    "摇镜",
    "跟拍",
    "手持",
)

FIXED_MOVEMENTS = {"fixed", "static", "locked", "locked_off", "locked-off", "none"}
FULL_BODY_SHOTS = {"full_body", "full-body", "full_shot", "full-shot", "full_length", "full", "全身", "全身景"}


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _find_words(text: str, words: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for word in words:
        if all(ord(ch) < 128 for ch in word):
            if re.search(r"\b" + re.escape(word) + r"\b", lowered):
                found.append(word)
        elif word in text:
            found.append(word)
    return found


def _normalise_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def check_greenscreen_generation_plan(
    plan: Any,
    *,
    anchors: Any = None,
    reference_bindings: Any = None,
    provider_caps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Judge one greenscreen dance generation plan against the five constraints. Composes (3O SPEC 1.2): resolve_provider_caps."""
    if not isinstance(plan, dict):
        raise CapabilityError(
            "qa.greenscreen_generation_gate: generation plan must be a JSON object"
        )
    prompt = plan.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise CapabilityError(
            "qa.greenscreen_generation_gate: plan requires a non-empty 'prompt' string"
        )
    character = plan.get("character")
    if not isinstance(character, str) or not character.strip():
        raise CapabilityError(
            "qa.greenscreen_generation_gate: plan requires a non-empty 'character' string"
        )
    character = character.strip()
    issues: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}

    # --- 1. Fixed full-body camera -------------------------------------
    camera = plan.get("camera")
    camera_ok = True
    if not isinstance(camera, dict):
        issues.append(_issue("camera_missing", "plan requires a 'camera' object declaring a fixed full-body shot"))
        camera_ok = False
    else:
        movement = _normalise_token(camera.get("movement"))
        if movement not in FIXED_MOVEMENTS:
            issues.append(
                _issue(
                    "camera_not_fixed",
                    f"camera movement must be fixed/static/locked, got {camera.get('movement')!r}",
                    movement=camera.get("movement"),
                )
            )
            camera_ok = False
        shot_size = _normalise_token(camera.get("shot_size"))
        if shot_size not in FULL_BODY_SHOTS:
            issues.append(
                _issue(
                    "shot_not_full_body",
                    f"camera shot_size must be full-body, got {camera.get('shot_size')!r}",
                    shot_size=camera.get("shot_size"),
                )
            )
            camera_ok = False
    movement_words = _find_words(prompt, CAMERA_MOVEMENT_WORDS)
    if movement_words:
        issues.append(
            _issue(
                "camera_movement_in_prompt",
                f"prompt carries camera-movement wording, contradicting a fixed camera: {movement_words}",
                words=movement_words,
            )
        )
        camera_ok = False
    checks["camera"] = camera_ok

    # --- 2. Subject stays in frame --------------------------------------
    framing = plan.get("framing")
    containment_ok = True
    if not isinstance(framing, dict):
        issues.append(
            _issue(
                "framing_missing",
                "plan requires a 'framing' object declaring full-body visibility and no frame exit",
            )
        )
        containment_ok = False
    else:
        if framing.get("full_body_visible") is not True:
            issues.append(
                _issue(
                    "full_body_not_visible",
                    "framing.full_body_visible must be strictly True",
                    full_body_visible=framing.get("full_body_visible"),
                )
            )
            containment_ok = False
        if framing.get("subject_exits_frame") is not False:
            issues.append(
                _issue(
                    "subject_exits_frame",
                    "framing.subject_exits_frame must be strictly False: "
                    "the subject must not run out of frame",
                    subject_exits_frame=framing.get("subject_exits_frame"),
                )
            )
            containment_ok = False
    if "exits the frame" in prompt.lower() or "walks out of frame" in prompt.lower() or "跑出画面" in prompt or "出画" in prompt:
        issues.append(
            _issue(
                "frame_exit_in_prompt",
                "prompt describes the subject exiting the frame",
            )
        )
        containment_ok = False
    checks["containment"] = containment_ok

    # --- 3. Pure green background, no stage / light / effects -----------
    background = plan.get("background")
    background_ok = True
    if not isinstance(background, dict):
        issues.append(
            _issue("background_missing", "plan requires a 'background' object declaring a pure green screen")
        )
        background_ok = False
    else:
        color_hex = background.get("color_hex")
        if not isinstance(color_hex, str) or color_hex.strip().lower() != PURE_GREEN_HEX:
            issues.append(
                _issue(
                    "background_not_pure_green",
                    f"background color_hex must be {PURE_GREEN_HEX}, got {color_hex!r}",
                    color_hex=color_hex,
                )
            )
            background_ok = False
        if background.get("green_screen") is not True:
            issues.append(
                _issue(
                    "background_not_green_screen",
                    "background.green_screen must be strictly True",
                    green_screen=background.get("green_screen"),
                )
            )
            background_ok = False
        if background.get("props"):
            issues.append(
                _issue("background_props", "a greenscreen background must carry no props", props=background.get("props"))
            )
            background_ok = False
        if background.get("stage"):
            issues.append(
                _issue("background_stage", "a greenscreen background must carry no stage", stage=background.get("stage"))
            )
            background_ok = False
    banned = _find_words(prompt, STAGE_BANNED_WORDS)
    if banned:
        issues.append(
            _issue(
                "stage_word_in_prompt",
                f"prompt carries stage/lighting/effect wording, which belongs to the later code stage: {banned}",
                words=banned,
            )
        )
        background_ok = False
    checks["background"] = background_ok

    # --- 4. Duration / fps / resolution vs provider cap -----------------
    caps_ok = True
    caps: dict[str, Any] | None = None
    provider: str | None = None
    duration_s = plan.get("duration_s")
    fps = plan.get("fps")
    width = plan.get("width")
    height = plan.get("height")
    if not _is_num(duration_s) or float(duration_s) <= 0:
        issues.append(_issue("duration_invalid", "duration_s must be a positive number", duration_s=duration_s))
        caps_ok = False
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        issues.append(_issue("fps_invalid", "fps must be a positive integer", fps=fps))
        caps_ok = False
    for field, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            issues.append(_issue(f"{field}_invalid", f"{field} must be a positive integer", value=value))
            caps_ok = False
    effective_caps = provider_caps if provider_caps is not None else plan.get("provider_caps")
    if effective_caps is not None:
        if not isinstance(effective_caps, dict):
            raise CapabilityError("qa.greenscreen_generation_gate: provider_caps must be a JSON object")
        caps = dict(effective_caps)
        provider = str(caps.get("provider") or plan.get("provider") or "") or None
    else:
        provider = plan.get("provider")
        if isinstance(provider, str) and provider.strip():
            provider = provider.strip()
            from hevi.capabilities.prompt_compiler import resolve_provider_caps

            caps = resolve_provider_caps(provider)
        else:
            provider = None
    if caps is None:
        issues.append(
            _issue(
                "provider_missing",
                "a provider (or explicit provider_caps) is required; "
                "an unknown tier never reaches generation",
                provider=plan.get("provider"),
            )
        )
        caps_ok = False
    else:
        max_shot = caps.get("max_shot_s")
        min_shot = caps.get("min_shot_s")
        if max_shot is None and min_shot is None and caps.get("max_total_s") is None:
            issues.append(
                _issue(
                    "tier_unknown",
                    f"provider {provider!r} declares no verified duration cap; "
                    "pass provider_caps explicitly to enforce a tier",
                    provider=provider,
                )
            )
            caps_ok = False
        if _is_num(duration_s):
            if max_shot is not None and float(duration_s) > float(max_shot) + 1e-9:
                issues.append(
                    _issue(
                        "duration_exceeds_provider_cap",
                        f"duration {duration_s:g}s exceeds the provider single-generation cap {float(max_shot):g}s",
                        duration_s=duration_s,
                        max_shot_s=max_shot,
                    )
                )
                caps_ok = False
            if min_shot is not None and float(duration_s) < float(min_shot) - 1e-9:
                issues.append(
                    _issue(
                        "duration_below_provider_minimum",
                        f"duration {duration_s:g}s is under the provider single-generation minimum {float(min_shot):g}s",
                        duration_s=duration_s,
                        min_shot_s=min_shot,
                    )
                )
                caps_ok = False
        for cap_key, plan_key in (("max_fps", "fps"), ("max_width", "width"), ("max_height", "height")):
            cap_value = caps.get(cap_key)
            plan_value = plan.get(plan_key)
            if cap_value is not None and isinstance(plan_value, int) and plan_value > int(cap_value):
                issues.append(
                    _issue(
                        f"{plan_key}_exceeds_provider_cap",
                        f"{plan_key} {plan_value} exceeds the provider cap {cap_value}",
                        value=plan_value,
                        cap=cap_value,
                    )
                )
                caps_ok = False
    checks["caps"] = caps_ok

    # --- 5. Anchor + reference binding (strict entry) -------------------
    anchor_ok = True
    resolved_anchor: dict[str, Any] | None = None
    effective_anchors = anchors if anchors is not None else plan.get("anchors")
    effective_bindings = reference_bindings if reference_bindings is not None else plan.get("reference_bindings")
    if effective_anchors is None:
        issues.append(
            _issue("anchors_missing", "anchors are required; a bare character name never reaches generation")
        )
        anchor_ok = False
    if effective_bindings is None:
        issues.append(
            _issue("reference_bindings_missing", "reference_bindings are required; unbound Pictures never reach generation")
        )
        anchor_ok = False
    if effective_anchors is not None and effective_bindings is not None:
        from hevi.capabilities.pure_helpers import (
            resolve_character_anchor,
            resolve_picture_bindings,
        )

        try:
            resolved_anchor = resolve_character_anchor(character, effective_anchors)
        except CapabilityError as exc:
            issues.append(_issue("anchor_unresolved", str(exc)))
            anchor_ok = False
        bindings: dict[int, dict[str, Any]] | None = None
        try:
            bindings = resolve_picture_bindings(effective_bindings)
        except CapabilityError as exc:
            issues.append(_issue("bindings_invalid", str(exc)))
            anchor_ok = False
        if bindings is not None:
            if 1 not in bindings:
                issues.append(
                    _issue("picture_1_missing", "reference_bindings has no Picture 1; Picture numbers without file bindings never reach generation")
                )
                anchor_ok = False
            if resolved_anchor is not None:
                bound = any(
                    b.get("file") == resolved_anchor["file"] and b.get("sha256") == resolved_anchor["sha256"]
                    for b in bindings.values()
                )
                if not bound:
                    issues.append(
                        _issue(
                            "anchor_not_bound",
                            f"anchor file for {character!r} is not in reference_bindings; "
                            "an anchor with no Picture binding is not usable",
                        )
                    )
                    anchor_ok = False
        if resolved_anchor is not None and character not in prompt and resolved_anchor["look"] not in prompt:
            issues.append(
                _issue(
                    "character_not_in_prompt",
                    "prompt names neither the character nor the confirmed anchor look",
                    character=character,
                )
            )
            anchor_ok = False
    checks["anchor"] = anchor_ok

    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "issues": issues,
        "checks": checks,
        "character": character,
        "provider": provider,
        "caps": caps,
        "anchor": resolved_anchor,
        "duration_s": float(duration_s) if _is_num(duration_s) else duration_s,
        "fps": fps,
        "width": width,
        "height": height,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    report = check_greenscreen_generation_plan(
        params.get("plan"),
        anchors=params.get("anchors"),
        reference_bindings=params.get("reference_bindings"),
        provider_caps=params.get("provider_caps"),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "greenscreen_generation_gate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "checks": report["checks"],
        },
    )


def register_greenscreen_generation_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.greenscreen_generation_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                    "anchors": {"type": "object"},
                    "reference_bindings": {"type": "object"},
                    "provider_caps": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Greenscreen generation gate (method reconstructed from "
                "an article description; see CODE_STAGE_MV_ATTRIBUTION.md): "
                "judges a dance-generation plan against five constraints -- "
                "fixed full-body camera, subject stays in frame, pure green "
                "background with no stage/lighting/effect wording, "
                "duration/fps/resolution within the provider cap resolved "
                "as story.prompt_compiler resolves it, and a confirmed "
                "character anchor bound to a Picture reference. Plan text "
                "only: no video is generated and no provider is called."
            ),
            line="qa",
        )
    )
    return ["qa.greenscreen_generation_gate"]


register_greenscreen_generation_gate_capabilities_once()
