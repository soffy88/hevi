"""story-to-film orchestration capability (一句话 → 成片).

Registers ``story.film_from_prompt`` so every product line can invoke the
full chain by dotted name (CAPABILITY_CONTRACT.md; precedent:
``hevi/capabilities/multimodel.py``):

  premise → story draft (LLM via Monid: hook + character profiles + beats)
  → GPT-Image character key still + per-shot scene stills (character-consistent)
  → LuxTTS narration → measured word alignment (ElevenLabs forced alignment)
  → shots.json (each shot carries first_frame / motion_prompt / duration)
  → final render route (explicit routing, see
    ``hevi.storyfilm.pipeline.resolve_render_route``):
      * ``ken_burns``        — in-house film: Ken Burns motion over the shot
                              stills (``render_motion_film``). The legacy name
                              ``hyperframes`` is an alias for this route only;
                              it does NOT invoke the CSK styled renderer
                              (``video.hyperframes_styled_render``), which is
                              a separate beats-driven capability.
      * ``pixstag_package`` — 真人线: 只产镜头包, 交 video.pixstag_generate

Also registers ``story.oneclick_film``: the preset-driven one-click
entry (hevi/storyfilm/oneclick.py) with gate retries and an
oneclick_delivery.json ledger; and ``story.asset_library``: the
cross-episode character/scene asset registry (hevi/storyfilm/assets.py)
that series runs upsert into and read locked descriptions from.

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

_ROUTES = ("ken_burns", "hyperframes", "pixstag_package")


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
    route = str(params.get("render_route") or "ken_burns")
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
    image_provider = str(params.get("image_provider") or "gpt")
    if image_provider not in ("gpt", "brush"):
        raise CapabilityError(
            "story.film_from_prompt: image_provider must be 'gpt' or 'brush'"
        )
    series = str(params.get("series") or "").strip() or None
    asset_library = str(params.get("asset_library") or "").strip() or None
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
                image_provider=image_provider,
                series=series,
                asset_library=asset_library,
            )
        )
    except (StoryFilmError, MonidError) as exc:
        raise CapabilityError(f"story.film_from_prompt: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"story.film_from_prompt failed: {exc}") from exc

    qa = {
        "title": delivery.get("title"),
        "render_route": route,
        "render_route_resolved": delivery.get("render_route_resolved"),
        "render_entry": delivery.get("render_entry"),
        "total_cost_usd": delivery.get("total_cost_usd"),
        "stages": {
            k: v.get("status") for k, v in delivery.get("stages", {}).items()
        },
        "gates": delivery.get("gates"),
        "delivery_json": str(out_dir / "delivery.json"),
        "note": (
            "Per-stage costs are billed per Monid endpoint rate; "
            "see delivery.json in the job dir. 'hyperframes' is a legacy "
            "alias for the ken_burns route (Ken Burns over shot stills); "
            "the CSK styled renderer is not on this path."
        ),
    }
    if route in ("ken_burns", "hyperframes"):
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
    series = str(params.get("series") or "").strip() or None
    asset_library = str(params.get("asset_library") or "").strip() or None
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
            series=series,
            asset_library=asset_library,
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


def _render_asset_library(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    import json

    from hevi.capabilities.registry import compute_sha256
    from hevi.storyfilm import assets as asset_registry

    action = str(params.get("action") or "list")
    if action not in ("list", "register_character", "register_scene"):
        raise CapabilityError(
            "story.asset_library: action must be list|register_character|register_scene"
        )
    library_param = str(params.get("library") or "").strip()
    root = (
        Path(library_param).expanduser()
        if library_param
        else asset_registry.default_library_root()
    )
    series = str(params.get("series") or "").strip()
    try:
        library = asset_registry.load_library(root)
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"story.asset_library: {exc}") from exc

    changed: dict[str, Any] | None = None
    if action in ("register_character", "register_scene"):
        name = str(params.get("name") or "").strip()
        if not series or not name:
            raise CapabilityError(
                f"story.asset_library: {action} needs 'series' and 'name'"
            )
        if action == "register_character":
            record, created = asset_registry.upsert_character(
                library,
                series=series,
                name=name,
                appearance_en=str(params.get("description") or ""),
                role=str(params.get("role") or ""),
                voice=str(params.get("voice") or "") or None,
            )
        else:
            record, created = asset_registry.upsert_scene(
                library,
                series=series,
                name=name,
                description_en=str(params.get("description") or ""),
                brush_template=str(params.get("brush_template") or "") or None,
            )
        asset_registry.save_library(root, library)
        changed = {"asset_id": record["id"], "created": created}

    listing = asset_registry.library_listing(library, series=series or None)
    payload = {
        "library_root": str(root),
        "action": action,
        "changed": changed,
        **listing,
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = out_dir / "asset_library.json"
    snapshot_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        sha256=compute_sha256(snapshot_path),
        qa={
            "asset_library_json": str(snapshot_path),
            "library_root": str(root),
            "counts": listing["counts"],
            "changed": changed,
            "note": (
                "Cross-episode character/scene registry (AID-learned). "
                "Appearance text locks at first registration; films run "
                "with a series name upsert their cast/scenes and inject "
                "the locked text per shot."
            ),
        },
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
                        "default": "ken_burns",
                        "description": (
                            "ken_burns: in-house film, Ken Burns motion over "
                            "shot stills (render_motion_film). hyperframes: "
                            "legacy alias for ken_burns only; it does not "
                            "invoke the CSK styled renderer. "
                            "pixstag_package: live-action line, emits a shot "
                            "package for video.pixstag_generate."
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
                    "image_provider": {
                        "type": "string",
                        "enum": ["gpt", "brush"],
                        "default": "gpt",
                        "description": (
                            "gpt: GPT-Image stills (paid). brush: zero-cost "
                            "procedural brush-painting stills (landscapes)"
                        ),
                    },
                    "series": {
                        "type": "string",
                        "description": (
                            "Series name: enables the cross-episode asset "
                            "registry (locked character/scene assets, "
                            "key-still reuse, per-shot cast injection)"
                        ),
                    },
                    "asset_library": {
                        "type": "string",
                        "description": (
                            "Asset library root (default: "
                            "$HEVI_ASSET_LIBRARY or ~/.hevi/storyfilm_assets)"
                        ),
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
                "Ken Burns film with gates, or a PixStag shot package for "
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
                    "series": {
                        "type": "string",
                        "description": (
                            "Series name: enables the cross-episode asset "
                            "registry for this run"
                        ),
                    },
                    "asset_library": {
                        "type": "string",
                        "description": "Asset library root (see story.asset_library)",
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

    register(
        Capability(
            name="story.asset_library",
            kind="data",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "register_character", "register_scene"],
                        "default": "list",
                        "description": "list the registry, or upsert one asset",
                    },
                    "library": {
                        "type": "string",
                        "description": (
                            "Library root (default: $HEVI_ASSET_LIBRARY "
                            "or ~/.hevi/storyfilm_assets)"
                        ),
                    },
                    "series": {
                        "type": "string",
                        "description": "Series scope (required for register actions)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Asset name (register actions)",
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "Locked appearance/scene description in English "
                            "(register actions; first registration wins)"
                        ),
                    },
                    "role": {
                        "type": "string",
                        "description": "Character role, e.g. 主角 (register_character)",
                    },
                    "voice": {
                        "type": "string",
                        "description": "Bound LuxTTS voice (register_character)",
                    },
                    "brush_template": {
                        "type": "string",
                        "description": "Bound brushpaint template (register_scene)",
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_asset_library,
            description=(
                "Cross-episode asset registry for the storyfilm line "
                "(AID-learned): characters and scenes keyed by "
                "(series, normalised name) with locked appearance text, "
                "accumulating reference images, a hero voice binding and "
                "scene→brush-template bindings. Films run with a series "
                "name upsert their cast/scenes here and inject the locked "
                "text into every shot that references the asset."
            ),
            line="storyfilm",
        )
    )
    registered.append("story.asset_library")

    return registered
