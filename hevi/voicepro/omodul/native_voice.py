"""HEVI-native voice transaction.

This is the reusable 3O business transaction for low-resource speech.  It
keeps report, fingerprint and decision-trail concerns here; the application
service only owns task persistence and delivery.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.voicepro.oskill import synthesize_native_batch

_enabled_pillars = {"fingerprint", "decision_trail", "report", "cost"}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped) if isinstance(dumped, dict) else {}
    return {}


def _fingerprint(config: dict[str, Any], input_data: dict[str, Any]) -> str:
    texts = input_data.get("texts") or []
    shape = {
        "engine": config.get("engine", "hevi-native"),
        "language": config.get("language", ""),
        "has_reference": bool(config.get("reference_audio")),
        "has_design": bool(config.get("voice_design")),
        "count": len(texts) if isinstance(texts, list) else (1 if input_data.get("text") else 0),
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:24]


async def native_voice_workflow(
    config: Any,
    input_data: Any,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Batch native voice synthesis with standard omodul failure semantics."""

    cfg = _mapping(config)
    data = _mapping(input_data)
    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "native_voice_report.json"
    fingerprint = _fingerprint(cfg, data)
    trail: list[dict[str, Any]] = []

    async def notify(stage: str, progress_pct: float) -> None:
        if on_step is None:
            return
        result = on_step({"stage": stage, "progress_pct": progress_pct})
        if inspect.isawaitable(result):
            await result

    try:
        texts = [str(item or "").strip() for item in data.get("texts") or []]
        if not texts and data.get("text"):
            texts = [str(data["text"]).strip()]
        texts = [item for item in texts if item]
        if not texts:
            raise ValueError("native voice workflow requires text or texts")
        await notify("synthesize", 20.0)
        results = await synthesize_native_batch(
            texts,
            root / "audio",
            voice=str(cfg.get("voice") or ""),
            language=str(cfg.get("language") or ""),
            reference_audio=cfg.get("reference_audio") or None,
            voice_design=str(cfg.get("voice_design") or ""),
            speed=float(cfg.get("speed") or 1.0),
        )
        trail.append(
            {
                "stage": "synthesize",
                "count": len(results),
                "backend": "hevi-native",
            }
        )
        manifest = ArtifactManifest(
            artifacts=[
                Artifact.from_path(
                    result.path,
                    kind="audio",
                    media_type="audio/wav",
                    primary=index == 0,
                    logical_role="speech_segment",
                    metadata={
                        "duration_s": result.duration_s,
                        "sample_rate": result.sample_rate,
                        "backend": result.backend,
                    },
                )
                for index, result in enumerate(results)
            ]
        )
        report = {
            "status": "succeeded",
            "operation": "native_voice_workflow",
            "pillars": sorted(_enabled_pillars),
            "fingerprint": fingerprint,
            "count": len(results),
            "decision_trail": trail,
            "artifact_manifest": manifest.model_dump(mode="json"),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        await notify("completed", 100.0)
        return {
            "status": "succeeded",
            "error": None,
            "fingerprint": fingerprint,
            "decision_trail": trail,
            "report_path": str(report_path),
            "cost_usd": 0.0,
            "pillars": sorted(_enabled_pillars),
            "artifacts": manifest.model_dump(mode="json")["artifacts"],
            "findings": {
                "count": len(results),
                "backend": "hevi-native",
                "audio_paths": [str(result.path) for result in results],
            },
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        trail.append({"stage": "failed", "error": type(exc).__name__})
        report_path.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "operation": "native_voice_workflow",
                    "pillars": sorted(_enabled_pillars),
                    "fingerprint": fingerprint,
                    "error": {"type": type(exc).__name__, "message": str(exc)[:500]},
                    "decision_trail": trail,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "status": "failed",
            "error": {"code": type(exc).__name__.upper(), "message": str(exc)[:500]},
            "fingerprint": fingerprint,
            "decision_trail": trail,
            "report_path": str(report_path),
            "cost_usd": 0.0,
            "pillars": sorted(_enabled_pillars),
            "artifacts": [],
            "findings": {},
        }


__all__ = ["native_voice_workflow"]
