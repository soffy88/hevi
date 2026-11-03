"""Season pack schema gate (``qa.season_pack_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-ai-manju-skills.md``
section 2 / A1: a season pack is only usable when the season /
episode / scene structure is declared in full -- episode count,
per-episode scene counts, and a per-episode duration -- and when
later episodes are not shorter than the first. Two disciplines
from the source method are kept, both restated in hevi's own
caliber:

1. Every episode declares its hook, and the pack declares its
   foreshadow and clue ledgers. A hook that contradicts the
   episode synopsis (when synopses are supplied) fails.
2. Duration tiers are mapped, never invented: the pack names a
   provider tier from ``model_catalog_data/duration_tiers.json``
   (the same table ``story.prompt_compiler`` gate 5 reads). That
   table declares per-shot caps only -- ``max_total_s`` is null
   everywhere -- so this gate never invents an episode-total cap;
   it only requires the tier to resolve to a known provider and
   records the tier verdict. An unresolvable provider fails.

This module judges plans only. It reads no media bytes, calls
no generator, and touches no budget.
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

_EPS = 1e-9


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_season_pack(pack: Any) -> dict[str, Any]:
    """Judge one season pack. Returns a report; never raises for a bad plan.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    episodes_out: list[dict[str, Any]] = []
    tier_verdict = "unknown"
    provider = None

    if not isinstance(pack, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "episodes": [],
            "duration_tier": None,
            "issues": [
                _issue(
                    "pack_not_object",
                    "qa.season_pack_gate: season pack must be an object",
                )
            ],
        }

    season_no = pack.get("season_no")
    if not isinstance(season_no, int) or isinstance(season_no, bool) or season_no < 1:
        issues.append(
            _issue(
                "season_no_missing",
                "qa.season_pack_gate: 'season_no' must be a positive integer",
            )
        )

    provider = pack.get("duration_tier_provider")
    if not _is_nonempty_str(provider):
        issues.append(
            _issue(
                "duration_tier_provider_missing",
                "qa.season_pack_gate: the pack must name a "
                "'duration_tier_provider' resolving through "
                "duration_tiers.json; an episode total cap must never "
                "be invented from a per-shot tier table",
            )
        )
    else:
        tier = _duration_tiers().get(provider)
        if not isinstance(tier, dict) or tier.get("max_shot_s") is None:
            issues.append(
                _issue(
                    "duration_tier_unresolved",
                    f"qa.season_pack_gate: provider {provider!r} does not "
                    "resolve to a known duration tier with a per-shot cap",
                )
            )
        else:
            tier_verdict = "known"

    for name in ("foreshadow_ledger", "clue_ledger"):
        if not isinstance(pack.get(name), list):
            issues.append(
                _issue(
                    "ledger_missing",
                    f"qa.season_pack_gate: '{name}' must be declared as a "
                    "list (possibly empty); an undeclared ledger is not "
                    "a kept ledger",
                )
            )

    episodes = pack.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        issues.append(
            _issue(
                "episodes_missing",
                "qa.season_pack_gate: the pack needs a non-empty "
                "'episodes' list in play order",
            )
        )
        episodes = []
    synopses = pack.get("episode_synopses")
    if synopses is not None and not isinstance(synopses, dict):
        issues.append(
            _issue(
                "synopses_not_object",
                "qa.season_pack_gate: 'episode_synopses' must be an object "
                "keyed by episode number",
            )
        )
        synopses = None

    first_duration: float | None = None
    for index, episode in enumerate(episodes):
        label = f"episode {index + 1}"
        entry: dict[str, Any] = {"label": label}
        if not isinstance(episode, dict):
            issues.append(
                _issue(
                    "episode_not_object",
                    f"qa.season_pack_gate: {label} must be an object",
                )
            )
            episodes_out.append(entry)
            continue
        number = episode.get("episode_no")
        if number != index + 1:
            issues.append(
                _issue(
                    "episode_order",
                    f"qa.season_pack_gate: {label} must carry "
                    f"'episode_no' {index + 1} in play order, got {number!r}",
                )
            )
        entry["episode_no"] = number
        duration = episode.get("duration_s")
        if not _is_number(duration) or duration <= 0:
            issues.append(
                _issue(
                    "episode_duration_missing",
                    f"qa.season_pack_gate: {label} must declare a "
                    "positive 'duration_s'",
                )
            )
        else:
            entry["duration_s"] = duration
            if first_duration is None:
                first_duration = float(duration)
            elif float(duration) < first_duration - _EPS:
                issues.append(
                    _issue(
                        "later_episode_shorter_than_first",
                        f"qa.season_pack_gate: {label} runs "
                        f"{float(duration):g}s, shorter than episode 1 "
                        f"({first_duration:g}s); later episodes must not "
                        "run shorter than the first",
                    )
                )
        scenes = episode.get("scenes")
        if isinstance(scenes, list):
            if not scenes:
                issues.append(
                    _issue(
                        "scenes_empty",
                        f"qa.season_pack_gate: {label} declares an empty "
                        "scene list",
                    )
                )
            entry["scene_count"] = len(scenes)
        elif isinstance(scenes, int) and not isinstance(scenes, bool) and scenes >= 1:
            entry["scene_count"] = scenes
        else:
            issues.append(
                _issue(
                    "scenes_missing",
                    f"qa.season_pack_gate: {label} must declare 'scenes' "
                    "as a positive count or a non-empty scene list",
                )
            )
        hook = episode.get("hook")
        if not _is_nonempty_str(hook):
            issues.append(
                _issue(
                    "hook_missing",
                    f"qa.season_pack_gate: {label} must declare a "
                    "non-empty 'hook'",
                )
            )
        else:
            entry["hook"] = hook
            if isinstance(synopses, dict) and str(number) in synopses:
                synopsis = synopses[str(number)]
                if isinstance(synopsis, str) and hook.strip() not in synopsis:
                    issues.append(
                        _issue(
                            "hook_synopsis_mismatch",
                            f"qa.season_pack_gate: {label} hook does not "
                            "appear in its episode synopsis; the hook and "
                            "the synopsis must agree",
                        )
                    )
        episodes_out.append(entry)

    verdict = "pass" if not issues else "fail"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "season_no": season_no if isinstance(season_no, int) else None,
        "episodes": episodes_out,
        "duration_tier": {"provider": provider, "verdict": tier_verdict},
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_season_pack(params.get("pack"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "season_pack_gate_report.json"
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


def register_season_pack_gate_capabilities_once() -> list[str]:
    """Register ``qa.season_pack_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.season_pack_gate",
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
            description=(
                "Season pack schema gate: a season pack must declare "
                "season/episode/scene structure, per-episode hooks and "
                "duration, and foreshadow/clue ledgers; later episodes "
                "must not run shorter than the first, and the duration "
                "tier must resolve through duration_tiers.json. Plans "
                "are judged, never rewritten to pass."
            ),
            line="qa",
        )
    )
    return ["qa.season_pack_gate"]


register_season_pack_gate_capabilities_once()
