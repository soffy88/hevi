"""Earshot-backed audio gate + code-defined SFX bank (local, model-free).

Registers two ``hevi.capabilities`` entries (CAPABILITY_CONTRACT.md):

* ``audio.earshot_gate`` — the audio-side gate, counterpart of ``film_gate``
  (which checks pictures).  Wraps earshot's model-free ``measure`` and fails
  the render when the media breaks loudness/peak hygiene:

  - true peak above the ceiling (default -1.0 dBTP),
  - integrated loudness outside ``lufs_target ± lufs_tolerance``
    (default -14 LUFS, the streaming/video target),
  - sample peak at full scale (hard-clipping risk),
  - no measurable loudness at all (silence / un-decodable audio).

  The gate always writes its report JSON; ``qa["pass"]`` carries the verdict
  so pipelines decide how to react.  earshot missing or failing raises
  ``CapabilityError`` — a gate that could not listen never passes silently.

* ``audio.sfx_render`` — render one of earshot's 201 code-defined sound
  effects by id (``sfx list`` shows them all).  The bank ships as synthesis
  recipes (JSON) inside the earshot package: rendering is local, CPU-only,
  needs no model download and no network, and is seed-reproducible.
  Upstream: Leonxlnx/earshot, MIT License.

Model-based earshot commands (describe / timeline / critique) are NOT wired
here on purpose: their CLAP/AST weights (~1.1 GB) are not installed and each
CLI call would pay a 20-40 s model load.  See docs/rules/audio_gate.md for
the extension path (earshot MCP server, models resident).
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

_SFX_LICENSE_NOTE = (
    "Sound bank from earshot (Leonxlnx/earshot), MIT License; "
    "sounds are synthesis recipes rendered locally, no samples, no network."
)

_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}


def _gate_checks(
    measurements: dict[str, Any],
    *,
    lufs_target: float,
    lufs_tolerance: float,
    true_peak_ceiling: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    true_peak = measurements.get("true_peak_dbtp")
    checks.append(
        {
            "name": "true_peak",
            "ok": true_peak is not None and true_peak <= true_peak_ceiling,
            "value": true_peak,
            "threshold": f"<= {true_peak_ceiling} dBTP",
        }
    )

    clipped = measurements.get("clipped_samples")
    peak = measurements.get("peak_dbfs")
    if clipped is not None:
        clipping = {
            "name": "no_hard_clipping",
            "ok": clipped == 0,
            "value": clipped,
            "threshold": "0 samples at full scale (|x| >= 0.999)",
        }
    else:
        clipping = {
            "name": "no_hard_clipping",
            "ok": peak is not None and peak <= -0.3,
            "value": peak,
            "threshold": "sample peak <= -0.3 dBFS",
        }
    checks.append(clipping)

    lufs = measurements.get("lufs")
    if lufs is None:
        checks.append(
            {
                "name": "loudness",
                "ok": False,
                "value": None,
                "threshold": f"{lufs_target} ± {lufs_tolerance} LUFS",
                "detail": "no integrated loudness measured (silence or too short)",
            }
        )
    else:
        checks.append(
            {
                "name": "loudness",
                "ok": abs(lufs - lufs_target) <= lufs_tolerance,
                "value": lufs,
                "threshold": f"{lufs_target} ± {lufs_tolerance} LUFS",
            }
        )
    return checks


def _render_earshot_gate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.audio import earshot_client

    media_path = Path(params["media_path"])
    lufs_target = float(params.get("lufs_target", -14.0))
    lufs_tolerance = float(params.get("lufs_tolerance", 2.0))
    true_peak_ceiling = float(params.get("true_peak_ceiling", -1.0))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not media_path.is_file():
        raise CapabilityError(f"audio.earshot_gate: media file not found: {media_path}")
    try:
        measurements = earshot_client.measure(media_path)
    except earshot_client.EarshotError as exc:
        raise CapabilityError(f"audio.earshot_gate: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"audio.earshot_gate failed: {exc}") from exc

    checks = _gate_checks(
        measurements,
        lufs_target=lufs_target,
        lufs_tolerance=lufs_tolerance,
        true_peak_ceiling=true_peak_ceiling,
    )
    passed = all(c["ok"] for c in checks)
    report = {
        "media_path": str(media_path),
        "tool": "earshot measure (model-free)",
        "pass": passed,
        "thresholds": {
            "lufs_target": lufs_target,
            "lufs_tolerance": lufs_tolerance,
            "true_peak_ceiling_dbtp": true_peak_ceiling,
        },
        "measurements": measurements,
        "checks": checks,
    }
    report_path = out_dir / "earshot_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    is_audio = media_path.suffix.lower() in _AUDIO_SUFFIXES
    return CapabilityResult(
        wav=str(media_path) if is_audio else None,
        mp4=None if is_audio else str(media_path),
        duration_s=float(measurements.get("duration") or 0.0),
        sha256=compute_sha256(media_path),
        qa={
            "report": str(report_path),
            "pass": passed,
            "lufs": measurements.get("lufs"),
            "true_peak_dbtp": measurements.get("true_peak_dbtp"),
            "failed_checks": [c["name"] for c in checks if not c["ok"]],
        },
    )


def _render_sfx(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.audio import earshot_client

    sfx_id = str(params["sfx_id"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / "sfx.wav"
    try:
        info = earshot_client.sfx_render(
            sfx_id,
            wav_path,
            dur=params.get("dur"),
            apex=params.get("apex"),
            pitch=params.get("pitch"),
            seed=seed,
        )
    except earshot_client.EarshotError as exc:
        raise CapabilityError(f"audio.sfx_render: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"audio.sfx_render failed: {exc}") from exc

    meta = info.get("meta", {}) if isinstance(info, dict) else {}
    duration = (
        (meta.get("dur_s") if isinstance(meta, dict) else None)
        or info.get("dur_s")
        or info.get("duration")
        or 0.0
    )
    return CapabilityResult(
        wav=str(wav_path),
        duration_s=float(duration),
        sha256=compute_sha256(wav_path),
        qa={
            "sfx_id": sfx_id,
            "category": sfx_id.split("/")[0] if "/" in sfx_id else None,
            "render_info": info,
            "license": _SFX_LICENSE_NOTE,
        },
    )


def register_earshot_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="audio.earshot_gate",
            kind="audio",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "media_path": {
                        "type": "string",
                        "description": "Local media file to gate (audio or video)",
                    },
                    "lufs_target": {
                        "type": "number",
                        "minimum": -40.0,
                        "maximum": -5.0,
                        "default": -14.0,
                        "description": "Integrated loudness target in LUFS "
                        "(-14 streaming/video, -16 game BGM, -23 broadcast)",
                    },
                    "lufs_tolerance": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 10.0,
                        "default": 2.0,
                    },
                    "true_peak_ceiling": {
                        "type": "number",
                        "minimum": -10.0,
                        "maximum": 0.0,
                        "default": -1.0,
                        "description": "True-peak ceiling in dBTP",
                    },
                },
                "required": ["media_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.5,
            render=_render_earshot_gate,
            description=(
                "Audio gate (earshot measure, model-free, local): true peak, "
                "integrated LUFS vs target, hard-clipping and silence checks. "
                "The picture-side counterpart is film_gate. Writes "
                "earshot_gate_report.json; qa['pass'] is the verdict. Use on "
                "final mixes / narration before delivery."
            ),
            line="earshot",
        )
    )
    registered.append("audio.earshot_gate")

    register(
        Capability(
            name="audio.sfx_render",
            kind="audio",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "sfx_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Bank sound id, e.g. 'click/double', "
                        "'whoosh_fast/tight' (201 ids; earshot sfx list)",
                    },
                    "dur": {
                        "type": "number",
                        "minimum": 0.05,
                        "maximum": 30.0,
                        "description": "Aim the sound at this duration (s)",
                    },
                    "apex": {
                        "type": "number",
                        "minimum": 0.0,
                        "description": "Time of the loudest moment (s)",
                    },
                    "pitch": {
                        "type": "string",
                        "description": "Note name (e.g. 'A4') or frequency in Hz",
                    },
                },
                "required": ["sfx_id"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.2,
            render=_render_sfx,
            description=(
                "Render one of earshot's 201 code-defined sound effects by id "
                "to wav (48 kHz). Fully local and offline: the bank is "
                "synthesis recipes, no samples and no model download. Use for "
                "UI clicks, whooshes, hits and stingers in code-animated films."
            ),
            line="earshot",
        )
    )
    registered.append("audio.sfx_render")

    return registered
