"""Talking-head capability (G14): portrait + script -> lip-synced MP4.

Registers ``talking_head.render`` on the unified registry. The render is a
thin, honest wrapper over :func:`hevi.talking_head.pipeline.run_talking_head`
(local-only: LuxTTS LAN service, faster-whisper CPU, wav2lip/musetalk
local, earshot model-free; no paid call is ever made by these stages):

* params ``script_text`` / ``portrait_path`` are required; a missing
  portrait file fails fast with :class:`CapabilityError`;
* a pipeline ``failed`` status is surfaced as :class:`CapabilityError`
  (never a fake success); ``delivered_with_warnings`` still delivers,
  with the failing gates recorded in ``qa``;
* ``duration_s`` is probed from the delivered MP4 with ffprobe when
  available, else 0.0 with a ``qa`` note (the pipeline ledger carries no
  duration of its own).

The pipeline itself (preflight / TTS / lip-sync / gates / ledger) is
unchanged; this module only adapts it to the capability contract.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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


def _probe_duration_s(mp4: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(mp4)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return float(json.loads(proc.stdout or "{}")["format"]["duration"])
    except Exception:
        return 0.0


def _render_talking_head(
    params: dict[str, Any], out_dir: str | Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.talking_head.pipeline import run_talking_head

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    script_text = str(params.get("script_text") or "").strip()
    portrait = str(params.get("portrait_path") or "").strip()
    if not script_text:
        raise CapabilityError("talking_head.render: params.script_text is required")
    if not portrait:
        raise CapabilityError("talking_head.render: params.portrait_path is required")
    if not Path(portrait).is_file():
        raise CapabilityError(f"talking_head.render: portrait not found: {portrait}")
    engine = str(params.get("engine") or "musetalk")
    voice = str(params.get("voice") or "soffy")
    character_id = str(params.get("character_id") or "d03ft")
    from hevi.talking_head.pipeline import TalkingHeadConfig

    try:
        ledger = run_talking_head(
            script_text=script_text,
            portrait_path=portrait,
            out_dir=out,
            config=TalkingHeadConfig(engine=engine, voice=voice, character_id=character_id),
        )
    except Exception as exc:
        raise CapabilityError(f"talking_head.render: pipeline failed: {exc}") from exc
    status = str(ledger.get("status") or "")
    delivered = (ledger.get("deliver") or {}).get("output_video")
    if status not in ("delivered", "delivered_with_warnings") or not delivered:
        failed_stage = ledger.get("failed_stage")
        raise CapabilityError(
            f"talking_head.render: pipeline status={status or 'unknown'} "
            f"failed_stage={failed_stage}"
        )
    mp4 = Path(delivered)
    if not mp4.is_file():
        raise CapabilityError(f"talking_head.render: delivered file missing: {mp4}")
    duration_s = _probe_duration_s(mp4)
    gates = ledger.get("gates") or {}
    failed_gates = [
        name for name, gate in gates.items()
        if isinstance(gate, dict) and gate.get("pass") is not True
    ]
    qa: dict[str, Any] = {
        "status": status,
        "engine": engine,
        "voice": voice,
        "ledger_json": str(out / "job-state.json"),
        "gates": gates,
        "failed_gates": failed_gates,
    }
    if duration_s == 0.0:
        qa["duration_note"] = "ffprobe unavailable or unparsable; duration_s left 0.0"
    return CapabilityResult(
        mp4=str(mp4),
        duration_s=duration_s,
        sha256=compute_sha256(mp4),
        qa=qa,
    )


def register_talking_head_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="talking_head.render",
            kind="line",
            aspects=["1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "script_text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Narration script (Chinese supported via LuxTTS soffy voice)",
                    },
                    "portrait_path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Path to a frontal portrait image file",
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["wav2lip", "musetalk", "livliv"],
                        "default": "musetalk",
                    },
                    "character_id": {
                        "type": "string",
                        "default": "d03ft",
                        "description": "LivLiv character id when engine=livliv (e.g. d03ft Nana). Credits: Characters: LivLiv (livliv.ai), AI制作",
                    },
                    "voice": {
                        "type": "string",
                        "enum": ["soffy", "en_male", "auto"],
                        "default": "soffy",
                    },
                },
                "required": ["script_text", "portrait_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=2.0,
            render=_render_talking_head,
            description=(
                "Talking-head presenter line (local, zero-fee): one portrait "
                "plus one script in, one lip-synced MP4 out via LuxTTS "
                "narration, wav2lip/musetalk/livliv lip-sync, and whisper/earshot/"
                "visual gates with a job-state.json ledger. A failed "
                "pipeline raises instead of returning a fake success."
            ),
            line="talking_head",
        )
    )
    return ["talking_head.render"]


# Import-time registration (same guarded pattern as the other capability
# modules); hevi/capabilities/__init__.py also imports this module.
register_talking_head_capabilities_once()
