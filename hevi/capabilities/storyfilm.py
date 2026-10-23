"""story-to-film orchestration capability (一句话 → 成片).

Registers ``story.film_from_prompt`` so every product line can invoke the
full chain by dotted name (CAPABILITY_CONTRACT.md; precedent:
``hevi/capabilities/multimodel.py``):

  premise → story draft (LLM via Monid: hook + character profiles + beats)
  → GPT-Image character key still + per-shot scene stills (character-consistent)
  → LuxTTS narration → measured word alignment (ElevenLabs forced alignment)
  → shots.json (each shot carries first_frame / motion_prompt / duration)
  → final render route:
      * ``hyperframes``     — 代码动画线: HyperFrames storyboard composition
                              + film_gate / audio.earshot_gate checks
      * ``pixstag_package`` — 真人线: 只产镜头包, 交 video.pixstag_generate

Also registers ``story.oneclick_film``: the preset-driven one-click
entry (hevi/storyfilm/oneclick.py) with gate retries and an
oneclick_delivery.json ledger.

Every stage writes evidence into the job dir (story.json, characters.json,
images/, narration.wav, alignment.json, shots.json, film.mp4 or
pixstag_package.json, gates.json, delivery.json). A failed stage raises
CapabilityError with the stage's own error — never a fake success.
Paid calls are billed per Monid endpoint rate; per-stage costs land in
delivery.json.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import Capability, CapabilityResult, register

_Registered = False

_ROUTES = ("hyperframes", "pixstag_package")


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run an async pipeline from the synchronous capability render."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _render_story_film(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.audio.monid_client import MonidError
    from hevi.storyfilm.pipeline import (
        DEFAULT_STYLE,
        StoryFilmError,
        run_story_film,
    )

    premise = str(params.get("premise") or "").strip()
    if not premise:
        raise CapabilityError("story.film_from_prompt: 'premise' is required")
    style = str(params.get("style") or DEFAULT_STYLE)
    route = str(params.get("render_route") or "hyperframes")
    if route not in _ROUTES:
        raise CapabilityError(
            f"story.film_from_prompt: render_route must be one of {_ROUTES}"
        )
    try:
        max_shots = int(params.get("max_shots") or 5)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(
            "story.film_from_prompt: max_shots must be an integer"
        ) from exc
    if not 3 <= max_shots <= 6:
        raise CapabilityError(
            "story.film_from_prompt: max_shots must be between 3 and 6 "
            "(image budget guard)"
        )
    voice = str(params.get("voice") or "soffy")
    film_aspect = str(params.get("aspect") or aspect or "9:16")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        delivery = _run_coro(
            run_story_film(
                premise=premise,
                style=style,
                max_shots=max_shots,
                render_route=route,
                aspect=film_aspect,
                voice=voice,
                out_dir=out_dir,
            )
        )
    except (StoryFilmError, MonidError) as exc:
        raise CapabilityError(f"story.film_from_prompt: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"story.film_from_prompt failed: {exc}") from exc

    qa = {
        "title": delivery.get("title"),
        "render_route": route,
        "total_cost_usd": delivery.get("total_cost_usd"),
        "stages": {
            k: v.get("status") for k, v in delivery.get("stages", {}).items()
        },
        "gates": delivery.get("gates"),
        "delivery_json": str(out_dir / "delivery.json"),
        "note": (
            "Per-stage costs are billed per Monid endpoint rate; "
            "see delivery.json in the job dir."
        ),
    }
    if route == "hyperframes":
        film = delivery.get("film") or {}
        return CapabilityResult(
            mp4=film.get("path"),
            duration_s=float(film.get("duration_s") or 0.0),
            qa=qa,
        )
    shots_total = 0.0
    shots_path = out_dir / "shots.json"
    if shots_path.is_file():
        import json

        shots_total = sum(
            float(s.get("duration_s") or 0.0)
            for s in json.loads(shots_path.read_text(encoding="utf-8"))
        )
    qa["pixstag_package"] = delivery.get("pixstag_package")
    return CapabilityResult(
        mp4=None,
        duration_s=shots_total,
        qa=qa,
    )


def _render_oneclick_film(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.storyfilm.oneclick import PRESETS, run_oneclick_film

    premise = str(params.get("premise") or "").strip()
    if not premise:
        raise CapabilityError("story.oneclick_film: 'premise' is required")
    preset = str(params.get("preset") or "storybook")
    if preset not in PRESETS:
        raise CapabilityError(
            f"story.oneclick_film: preset must be one of {sorted(PRESETS)}"
        )
    try:
        max_shots = int(params.get("max_shots") or 5)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(
            "story.oneclick_film: max_shots must be an integer"
        ) from exc
    if not 3 <= max_shots <= 6:
        raise CapabilityError(
            "story.oneclick_film: max_shots must be between 3 and 6 "
            "(image budget guard)"
        )
    voice = str(params.get("voice") or "soffy")
    music = bool(params.get("music", True))
    film_aspect = str(params.get("aspect") or aspect or "9:16")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        ledger = run_oneclick_film(
            premise,
            preset=preset,
            aspect=film_aspect,
            max_shots=max_shots,
            voice=voice,
            music=music,
            out_dir=out_dir,
        )
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"story.oneclick_film failed: {exc}") from exc

    film = ledger.get("film") or {}
    qa = {
        "preset": preset,
        "status": ledger.get("status"),
        "total_cost_usd": ledger.get("cost_usd"),
        "stages": ledger.get("stages"),
        "gates": ledger.get("gates"),
        "retries": ledger.get("retries"),
        "degradations": ledger.get("degradations"),
        "ledger_json": str(out_dir / "oneclick_delivery.json"),
        "note": (
            "One-click preset run; per-stage costs are in the inner "
            "delivery.json, gate retries/degradations in "
            "oneclick_delivery.json."
        ),
    }
    return CapabilityResult(
        mp4=film.get("path"),
        duration_s=float(film.get("duration_s") or 0.0),
        qa=qa,
    )


def register_storyfilm_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="story.film_from_prompt",
            kind="line",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "premise": {
                        "type": "string",
                        "minLength": 1,
                        "description": "一句话故事前提, e.g. 一只小猫在雨夜里找回家的路",
                    },
                    "style": {
                        "type": "string",
                        "description": "Visual style prompt for the stills",
                    },
                    "max_shots": {
                        "type": "integer",
                        "minimum": 3,
                        "maximum": 6,
                        "default": 5,
                        "description": "Shot count cap (image budget guard)",
                    },
                    "render_route": {
                        "type": "string",
                        "enum": list(_ROUTES),
                        "default": "hyperframes",
                        "description": (
                            "hyperframes: code-animation line, composes the "
                            "film in-house. pixstag_package: live-action line, "
                            "emits a shot package for video.pixstag_generate."
                        ),
                    },
                    "voice": {
                        "type": "string",
                        "default": "soffy",
                        "description": "LuxTTS narration voice",
                    },
                    "aspect": {
                        "type": "string",
                        "enum": ["9:16", "16:9", "1:1"],
                        "description": "Overrides the render aspect when set",
                    },
                },
                "required": ["premise"],
                "additionalProperties": False,
            },
            cpu_cost_hint=1.0,  # local storyboard render + cloud calls
            render=_render_story_film,
            description=(
                "One-sentence-to-film orchestration: premise → story draft "
                "(hook, character profiles, beats) → GPT-Image character + "
                "scene stills → LuxTTS narration → measured word alignment → "
                "timed shots (first_frame/motion_prompt/duration) → "
                "HyperFrames film with gates, or a PixStag shot package for "
                "the live-action line. Stage evidence + costs land in the "
                "job dir (delivery.json)."
            ),
            line="storyfilm",
        )
    )
    registered.append("story.film_from_prompt")

    from hevi.storyfilm.oneclick import PRESETS as _ONECLICK_PRESETS

    register(
        Capability(
            name="story.oneclick_film",
            kind="line",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "premise": {
                        "type": "string",
                        "minLength": 1,
                        "description": "一句话故事前提, e.g. 一只小猫在雨夜里找回家的路",
                    },
                    "preset": {
                        "type": "string",
                        "enum": sorted(_ONECLICK_PRESETS),
                        "default": "storybook",
                        "description": (
                            "storybook: GPT stills + cute BGM; tuantuan: "
                            "expression-rig character; cinema: cinematic "
                            "stills + score; watercolor: watercolor "
                            "stills + calm BGM"
                        ),
                    },
                    "aspect": {
                        "type": "string",
                        "enum": ["9:16", "16:9", "1:1"],
                        "description": "Overrides the render aspect when set",
                    },
                    "max_shots": {
                        "type": "integer",
                        "minimum": 3,
                        "maximum": 6,
                        "default": 5,
                        "description": "Shot count cap (image budget guard)",
                    },
                    "voice": {
                        "type": "string",
                        "default": "soffy",
                        "description": "LuxTTS narration voice",
                    },
                    "music": {
                        "type": "boolean",
                        "default": True,
                        "description": "Generate + mix a score_render BGM",
                    },
                },
                "required": ["premise"],
                "additionalProperties": False,
            },
            cpu_cost_hint=1.0,
            render=_render_oneclick_film,
            description=(
                "One-click film: preset (storybook/tuantuan/cinema/"
                "watercolor/brush) -> story.film pipeline with BGM and "
                "optional rig character -> film_gate red retry with "
                "boosted Ken Burns, earshot gain-fix retry, and a "
                "qa.review_sheet pass; evidence + retries land in "
                "oneclick_delivery.json."
            ),
            line="storyfilm",
        )
    )
    registered.append("story.oneclick_film")

    return registered
