"""Generation spec sheet gate (``qa.generation_spec_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-video-workflow-7steps.md``
step 1 ("spec first"): before any generation call, the four spec items
are written down in one spec sheet and locked -- total duration and
shot count, aspect ratio, camera strategy, and audio strategy. A spec
sheet missing any item, or whose items disagree with each other or
with the provider tier table, fails here instead of burning a
generation call on an underspecified brief.

The four items:

* ``total_duration_s`` + ``shot_count`` -- the episode length and
  how many shots it splits into. When ``shot_durations_s`` is
  supplied, its entries must sum to the total and each entry must
  fit the provider tier (see below); when it is absent, the uniform
  split ``total / shot_count`` is checked instead.
* ``aspect`` -- closed list ``16:9`` / ``9:16`` / ``1:1``.
* ``camera_strategy`` -- closed list: ``locked`` (fixed camera),
  ``push_pull`` (dolly/zoom moves), ``tracking`` (follow moves),
  ``mixed`` (per-shot movement declared on each shot; the spec
  alone does not lock it, so ``mixed`` requires ``shot_durations_s``
  to be present so per-shot checks still have durations to check).
* ``audio_strategy`` -- closed list: ``silent_post_dubbed`` (silent
  picture, dialogue added in post -- generation never worries
  about lip sync), ``ambient_only``, ``dialogue_live``,
  ``music_only``.

Tier discipline reuses ``story.prompt_compiler.resolve_provider_caps``
and the ``duration_tiers.json`` table verbatim: no number in this
module invents or overrides a tier. When ``provider`` is absent,
the tier check is ``not_checked`` (recorded, never counted as a
pass). When ``provider`` is present but the table has no verified
cap for it, the spec fails -- an unlockable spec is not a locked
spec. ``max_total_s`` is null everywhere in the table and is never
used as a cap.

This module judges plans only. It calls no generator, spends
nothing, and holds no key or budget.
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

ASPECTS = ("16:9", "9:16", "1:1")

CAMERA_STRATEGIES = ("locked", "push_pull", "tracking", "mixed")

AUDIO_STRATEGIES = (
    "silent_post_dubbed",
    "ambient_only",
    "dialogue_live",
    "music_only",
)

SPEC_FIELDS = (
    "total_duration_s",
    "shot_count",
    "aspect",
    "camera_strategy",
    "audio_strategy",
)

_EPS = 1e-9


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_generation_spec(
    spec: Any,
    *,
    provider_caps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Judge one spec sheet. Returns a report; never raises for a bad spec.

    ``provider_caps`` is an explicit caller-supplied tier record
    (``resolve_provider_caps`` output) and always wins over the
    table lookup, matching the compiler's rule. Pass ``None`` to
    look the provider up from the table by ``spec["provider"]``.
    """
    issues: list[dict[str, Any]] = []
    missing: list[str] = []

    if not isinstance(spec, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "missing": list(SPEC_FIELDS),
            "issues": [{
                "code": "spec_not_object",
                "detail": "qa.generation_spec_gate: spec sheet must be an object",
            }],
            "tier": {"status": "not_checked", "reason": "no spec supplied"},
        }

    for field in SPEC_FIELDS:
        if spec.get(field) in (None, ""):
            missing.append(field)
            issues.append({
                "code": f"missing_{field}",
                "detail": f"qa.generation_spec_gate: spec sheet is missing "
                         f"'{field}'; the four spec items must all be "
                         f"written down before generation",
            })

    total = spec.get("total_duration_s")
    if "total_duration_s" not in missing:
        if not _is_number(total) or float(total) <= 0:
            issues.append({
                "code": "bad_total_duration_s",
                "detail": "qa.generation_spec_gate: total_duration_s must be "
                         "a positive number",
            })
    count = spec.get("shot_count")
    if "shot_count" not in missing:
        if not _is_int(count) or int(count) < 1:
            issues.append({
                "code": "bad_shot_count",
                "detail": "qa.generation_spec_gate: shot_count must be a "
                         "whole number of at least 1",
            })
    if "aspect" not in missing and spec.get("aspect") not in ASPECTS:
        issues.append({
            "code": "bad_aspect",
            "detail": "qa.generation_spec_gate: aspect must be one of "
                     f"{', '.join(ASPECTS)}",
        })
    if "camera_strategy" not in missing \
            and spec.get("camera_strategy") not in CAMERA_STRATEGIES:
        issues.append({
            "code": "bad_camera_strategy",
            "detail": "qa.generation_spec_gate: camera_strategy must be one of "
                     f"{', '.join(CAMERA_STRATEGIES)}",
        })
    if "audio_strategy" not in missing \
            and spec.get("audio_strategy") not in AUDIO_STRATEGIES:
        issues.append({
            "code": "bad_audio_strategy",
            "detail": "qa.generation_spec_gate: audio_strategy must be one of "
                     f"{', '.join(AUDIO_STRATEGIES)}",
        })
    if spec.get("camera_strategy") == "mixed" \
            and spec.get("shot_durations_s") is None:
        issues.append({
            "code": "mixed_needs_shot_durations",
            "detail": "qa.generation_spec_gate: camera_strategy 'mixed' leaves "
                     "movement to each shot, so shot_durations_s must be "
                     "supplied for the per-shot checks to have durations",
        })

    # Shot durations: explicit list wins; otherwise the uniform split.
    durations: list[float] | None = None
    raw_durations = spec.get("shot_durations_s")
    if raw_durations is not None:
        if not isinstance(raw_durations, list) or not raw_durations:
            issues.append({
                "code": "bad_shot_durations_s",
                "detail": "qa.generation_spec_gate: shot_durations_s must be "
                         "a non-empty list of positive numbers",
            })
        elif not all(_is_number(d) and float(d) > 0 for d in raw_durations):
            issues.append({
                "code": "bad_shot_durations_s",
                "detail": "qa.generation_spec_gate: every shot_durations_s "
                         "entry must be a positive number",
            })
        else:
            durations = [float(d) for d in raw_durations]
            if _is_int(count) and len(durations) != int(count):
                issues.append({
                    "code": "shot_durations_count_mismatch",
                    "detail": "qa.generation_spec_gate: shot_durations_s has "
                             f"{len(durations)} entries but shot_count is "
                             f"{count}",
                })
            if _is_number(total) and abs(sum(durations) - float(total)) > _EPS:
                issues.append({
                    "code": "shot_durations_sum_mismatch",
                    "detail": "qa.generation_spec_gate: shot_durations_s sums to "
                             f"{sum(durations)} but total_duration_s is {total}",
                })
    elif _is_number(total) and _is_int(count) and int(count) >= 1:
        durations = [float(total) / int(count)] * int(count)

    # Tier check: explicit caps win; else table lookup by provider;
    # absent provider leaves the check not_checked, never passed.
    tier: dict[str, Any] = {"status": "not_checked",
                            "reason": "no provider named"}
    provider = spec.get("provider")
    caps = provider_caps
    if caps is None and isinstance(provider, str) and provider.strip():
        from hevi.capabilities.prompt_compiler import resolve_provider_caps
        caps = resolve_provider_caps(provider)
    if caps is not None:
        tier = {"status": "checked", "provider": caps.get("provider"),
                "max_shot_s": caps.get("max_shot_s"),
                "min_shot_s": caps.get("min_shot_s"),
                "source": caps.get("source")}
        if caps.get("max_shot_s") is None and caps.get("min_shot_s") is None:
            tier["status"] = "unknown"
            issues.append({
                "code": "tier_unknown",
                "detail": "qa.generation_spec_gate: provider "
                         f"{caps.get('provider')!r} has no verified duration "
                         "tier in duration_tiers.json; a spec that cannot "
                         "be checked against a cap is not locked",
            })
        elif durations is not None:
            for index, duration in enumerate(durations):
                if caps.get("max_shot_s") is not None \
                        and duration > float(caps["max_shot_s"]) + _EPS:
                    issues.append({
                        "code": "shot_over_provider_cap",
                        "detail": "qa.generation_spec_gate: shot "
                                 f"{index + 1} is {duration}s, over provider "
                                 f"{caps.get('provider')!r} max_shot_s "
                                 f"{caps['max_shot_s']}s",
                    })
                if caps.get("min_shot_s") is not None \
                        and duration < float(caps["min_shot_s"]) - _EPS:
                    issues.append({
                        "code": "shot_under_provider_min",
                        "detail": "qa.generation_spec_gate: shot "
                                 f"{index + 1} is {duration}s, under provider "
                                 f"{caps.get('provider')!r} min_shot_s "
                                 f"{caps['min_shot_s']}s",
                    })

    ok = not issues
    return {
        "ok": ok,
        "verdict": "pass" if ok else "fail",
        "missing": missing,
        "issues": issues,
        "tier": tier,
        "checked_durations_s": durations,
    }


def authorize_generation_spec(
    spec: Any,
    *,
    provider_caps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Approve a spec sheet, or refuse it loudly (raises CapabilityError)."""
    report = check_generation_spec(spec, provider_caps=provider_caps)
    if not report["ok"]:
        raise CapabilityError(
            "qa.generation_spec_gate: spec sheet is not locked: "
            + "; ".join(i["detail"] for i in report["issues"])
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = authorize_generation_spec(
        params.get("spec"), provider_caps=params.get("provider_caps"))
    report_path = out_dir / "generation_spec_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_generation_spec_gate_capabilities_once() -> list[str]:
    """Register ``qa.generation_spec_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.generation_spec_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "spec": {"type": "object"},
                    "provider_caps": {"type": "object"},
                },
                "required": ["spec"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Spec sheet gate: the four spec items (total duration + "
                "shot count, aspect, camera strategy, audio strategy) "
                "must all be written down and agree with each other and "
                "with the provider tier table before generation. A "
                "missing item, a sum/count mismatch, or a shot outside "
                "the provider tier fails. Judges plans only; calls no "
                "generator and spends nothing."
            ),
            line="qa",
        )
    )
    return ["qa.generation_spec_gate"]


register_generation_spec_gate_capabilities_once()
