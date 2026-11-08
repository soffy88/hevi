"""Koubo cut capability (口播精剪): talking-head -> evidence-backed kinetic cut."""

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
    ffprobe = shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(mp4)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return float(json.loads(proc.stdout or "{}")["format"]["duration"])
    except Exception:
        return 0.0


def _render_koubo_cut(
    params: dict[str, Any], out_dir: str | Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.koubo_cut.pipeline import run_koubo_cut

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    input_video = str(params.get("input_video") or params.get("input") or "").strip()
    script_text = str(params.get("script_text") or params.get("script") or "").strip()
    script_lines = params.get("script_lines") or []
    topic = str(params.get("topic") or "").strip()
    duration_s = float(params.get("duration_s") or duration or 30.0)
    engine = str(params.get("engine") or "wav2lip").strip() or "wav2lip"
    character_id = str(params.get("character_id") or "d03ft").strip() or "d03ft"
    try:
        ledger = run_koubo_cut(
            input_video=input_video if input_video else None,
            script_text=script_text,
            script_lines=script_lines,
            topic=topic,
            out_dir=out,
            seed=seed,
            duration_s=duration_s,
            engine=engine,
            character_id=character_id,
        )
    except Exception as exc:
        raise CapabilityError(f"koubo_cut.render: pipeline failed: {exc}") from exc
    status = str(ledger.get("status") or "")
    mp4 = Path(ledger.get("output") or (out / "koubo_cut.mp4"))
    if status not in ("delivered", "delivered_with_warnings") or not mp4.is_file():
        detail = str(ledger.get("error") or "")
        raise CapabilityError(f"koubo_cut.render: pipeline status={status} {detail}".strip())
    duration_s = _probe_duration_s(mp4) or float(ledger.get("duration_s") or 0.0)
    qa = {"status": status, "ledger": ledger}
    return CapabilityResult(mp4=str(mp4), duration_s=duration_s, sha256=compute_sha256(mp4), qa=qa)


def register_koubo_cut_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="koubo_cut.render",
            kind="line",
            aspects=["9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "input_video": {"type": "string", "description": "input talking-head video path"},
                    "script_text": {"type": "string", "description": "optional script"},
                    "script_lines": {"type": "array", "description": "pre-planned narration lines"},
                    "topic": {"type": "string", "description": "topic when no script is supplied"},
                    "duration_s": {"type": "number", "description": "target duration"},
                    "engine": {"type": "string", "enum": ["wav2lip", "livliv"],
                               "default": "wav2lip",
                               "description": "lip-sync engine; livliv = LivLiv 2.5D character (non-commercial, LIVLIV_CHARACTERS_ENABLED)"},
                    "character_id": {"type": "string", "default": "d03ft",
                                     "description": "LivLiv character id when engine=livliv"},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=2.0,
            render=_render_koubo_cut,
            description="Koubo cut production line (口播精剪).",
            line="koubo_cut",
        )
    )
    return ["koubo_cut.render"]


register_koubo_cut_capabilities_once()
