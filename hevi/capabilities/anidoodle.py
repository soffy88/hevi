"""Capabilities over the vendored anidoodle style library.

Five names are registered:

* ``anidoodle.style_list``  — the 32 hand-drawn styles, grouped, with a reason.
* ``anidoodle.still``       — one finished plate of a style (PNG).
* ``anidoodle.draw_clip``   — the style's drawing-process film (MP4).
* ``anidoodle.music``       — a code-composed, checked BGM bed (MP3/WAV).
* ``anidoodle.gate``        — the engine gate + export verification on a clip.

They fail closed: a missing Node install, engine or browser raises
``CapabilityError`` with the precondition that failed.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from hevi.anidoodle import (
    AnidoodleError,
    compose_bgm,
    families,
    list_styles,
    recommend_style,
    render_draw_clip,
    render_still,
    run_gate,
    run_verify_export,
    validation_for,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def _copy_artifact(source: str, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    shutil.copy2(source, target)
    return target


def _render_styles(params: dict[str, Any], out_dir: Path, **_: Any) -> CapabilityResult:
    intent = str(params.get("intent") or "")
    topic = str(params.get("topic") or "")
    rows = [{**style.to_dict(), **validation_for(style.id)} for style in list_styles()]
    payload: dict[str, Any] = {
        "styles": rows,
        "families": families(),
        "total": len(rows),
        "attribution": "anidoodle by Alex Greenshpun, Apache-2.0, https://github.com/alexgreensh/anidoodle",
    }
    if topic or intent:
        payload["recommendation"] = recommend_style(topic or "unfilled brief", intent=intent)
    report = out_dir / "anidoodle-styles.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    import json

    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def _render_still_cap(params: dict[str, Any], out_dir: Path, **_: Any) -> CapabilityResult:
    try:
        result = render_still(
            str(params["style_id"]),
            frame=params.get("frame"),
            scale=float(params.get("scale") or 1.0),
        )
        target = _copy_artifact(result["path"], out_dir, Path(result["path"]).name)
    except (AnidoodleError, KeyError, TypeError) as exc:
        raise CapabilityError(f"anidoodle.still: {exc}") from exc
    return CapabilityResult(
        png=str(target),
        duration_s=0.0,
        sha256=result["sha256"],
        qa={
            **result,
            "path": str(target),
            "attribution": "anidoodle / Alex Greenshpun (Apache-2.0)",
        },
    )


def _render_draw_cap(params: dict[str, Any], out_dir: Path, **_: Any) -> CapabilityResult:
    try:
        result = render_draw_clip(
            str(params["style_id"]),
            poster_frame=params.get("poster_frame"),
            scale=float(params.get("scale") or 1.0),
        )
        target = _copy_artifact(result["path"], out_dir, Path(result["path"]).name)
    except (AnidoodleError, KeyError, TypeError) as exc:
        raise CapabilityError(f"anidoodle.draw_clip: {exc}") from exc
    scale = float(params.get("scale") or 1.0)
    if scale == 1.0:
        gate = run_gate(result["film"], str(target), drawing=True)
        verify = run_verify_export(str(target))
        gate_row = {
            k: gate[k] for k in ("ok", "verdict", "passed_count", "failures", "dead_air_profile")
        }
        verify_row = {k: verify[k] for k in ("ok", "verdict", "passed_count", "failures")}
    else:
        gate_row = {"ok": None, "verdict": "preview_scale_not_gated", "failures": []}
        verify_row = {"ok": None, "verdict": "preview_scale_not_gated", "failures": []}
    return CapabilityResult(
        mp4=str(target),
        duration_s=float(result["duration_s"]),
        sha256=result["sha256"],
        qa={
            **result,
            "path": str(target),
            "gate": gate_row,
            "verify_export": verify_row,
            "attribution": "anidoodle / Alex Greenshpun (Apache-2.0)",
        },
    )


def _render_music_cap(params: dict[str, Any], out_dir: Path, **_: Any) -> CapabilityResult:
    try:
        result = compose_bgm(
            style=str(params.get("style") or "lofiElectronic"),
            mood=str(params.get("mood") or ""),
            key=str(params.get("key") or ""),
            bpm=int(params.get("bpm") or 0),
            bars=int(params.get("bars") or 12),
            seed=int(params.get("seed") or 29),
            fmt=str(params.get("format") or "wav"),
        )
        target = _copy_artifact(result["path"], out_dir, Path(result["path"]).name)
    except (AnidoodleError, ValueError) as exc:
        raise CapabilityError(f"anidoodle.music: {exc}") from exc
    return CapabilityResult(
        wav=str(target) if str(target).endswith(".wav") else None,
        duration_s=0.0,
        sha256=result["sha256"],
        qa={
            **result,
            "path": str(target),
            "attribution": "anidoodle music engine / Alex Greenshpun (Apache-2.0)",
        },
    )


def _render_gate_cap(params: dict[str, Any], out_dir: Path, **_: Any) -> CapabilityResult:
    path = Path(str(params.get("mp4") or "")).expanduser().resolve()
    try:
        from hevi.anidoodle.engine import output_root

        root = output_root().resolve()
        path.relative_to(root)
    except Exception as exc:
        raise CapabilityError(
            f"anidoodle.gate: path outside the anidoodle output root: {path}"
        ) from exc
    if not path.is_file():
        raise CapabilityError(f"anidoodle.gate: no such file: {path}")
    gate = run_gate(str(params["film"]), path, drawing=bool(params.get("drawing")))
    verify = run_verify_export(path)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(path),
        qa={"gate": gate, "verify_export": verify, "mp4": str(path)},
    )


def register_anidoodle_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    register(
        Capability(
            name="anidoodle.style_list",
            kind="line",
            aspects=["1:1", "16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "default": ""},
                    "intent": {
                        "type": "string",
                        "enum": ["", "explainer", "story", "brand", "education", "editorial"],
                        "default": "",
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_styles,
            description=(
                "The 32 anidoodle code-drawn styles, grouped by medium, with a "
                "recommendation and one reason. Apache-2.0 (Alex Greenshpun)."
            ),
            line="anidoodle",
        )
    )
    register(
        Capability(
            name="anidoodle.still",
            kind="shot",
            aspects=["1:1", "16:9", "9:16"],
            params_schema={
                "type": "object",
                "required": ["style_id"],
                "properties": {
                    "style_id": {"type": "string"},
                    "frame": {"type": "integer", "minimum": 0},
                    "scale": {"type": "number", "exclusiveMinimum": 0, "maximum": 2},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.2,
            render=_render_still_cap,
            description="One finished plate of an anidoodle style, drawn in code and hash-checked.",
            line="anidoodle",
        )
    )
    register(
        Capability(
            name="anidoodle.draw_clip",
            kind="line",
            aspects=["1:1", "16:9", "9:16"],
            params_schema={
                "type": "object",
                "required": ["style_id"],
                "properties": {
                    "style_id": {"type": "string"},
                    "poster_frame": {"type": "integer", "minimum": 0},
                    "scale": {"type": "number", "exclusiveMinimum": 0, "maximum": 2},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=2.3,
            render=_render_draw_cap,
            description=(
                "The style's drawing-process film (line to finish, last frame = "
                "the plate) with the determinism gate and export verification."
            ),
            line="anidoodle",
        )
    )
    register(
        Capability(
            name="anidoodle.music",
            kind="audio",
            aspects=["1:1", "16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "style": {
                        "type": "string",
                        "enum": ["lofiElectronic", "cinematic", "folk", "musicBox"],
                        "default": "lofiElectronic",
                    },
                    "mood": {"type": "string", "default": ""},
                    "key": {"type": "string", "default": ""},
                    "bpm": {"type": "integer", "minimum": 0, "maximum": 200, "default": 0},
                    "bars": {"type": "integer", "minimum": 6, "maximum": 96, "default": 12},
                    "seed": {"type": "integer", "minimum": 0, "default": 29},
                    "format": {"type": "string", "enum": ["mp3", "wav"], "default": "wav"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.5,
            render=_render_music_cap,
            description=(
                "A BGM bed composed and synthesized in code, with the engine's "
                "key/mode, loudness, masking, stems and novelty verdict."
            ),
            line="anidoodle",
        )
    )
    register(
        Capability(
            name="anidoodle.gate",
            kind="line",
            aspects=["1:1", "16:9", "9:16"],
            params_schema={
                "type": "object",
                "required": ["film", "mp4"],
                "properties": {
                    "film": {"type": "string"},
                    "mp4": {"type": "string"},
                    "drawing": {"type": "boolean", "default": True},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=3.0,
            render=_render_gate_cap,
            description="Run anidoodle's determinism/dead-air gate and export verification on a clip.",
            line="anidoodle",
        )
    )
    return [
        "anidoodle.style_list",
        "anidoodle.still",
        "anidoodle.draw_clip",
        "anidoodle.music",
        "anidoodle.gate",
    ]
