"""Voice Studio adapter executed by the shared HEVI task lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from obase.persistence import PgPool

from hevi.audio.edge_tts_custom import synthesize_with_voice_control
from hevi.audio.voicebox_service import voicebox_synthesize
from hevi.explainer.voicebox_client import VoiceboxError
from hevi.production.artifacts import Artifact, ArtifactManifest


async def execute_voice_studio_task(task: dict[str, Any], pool: PgPool) -> dict[str, Any]:
    """Create a real WAV delivery and persist it as the task's artifact manifest."""
    config = task.get("config_json") or {}
    text = str(config.get("text") or "").strip()
    if not text:
        raise ValueError("voice studio task missing text")

    output_path = Path("output/tasks") / str(task["id"]) / "voice.wav"
    emotion = str(config.get("effects") or "").strip() or None
    line = SimpleNamespace(text=text)
    provider_used = "voicebox"
    fallback: dict[str, str] | None = None
    try:
        await voicebox_synthesize(script=[line], output_path=output_path, emotion=emotion)
    except VoiceboxError as exc:
        if not _allow_edge_fallback():
            raise
        provider_used = "edge_tts"
        fallback = {
            "from": "voicebox",
            "to": "edge_tts",
            "reason": str(exc)[:500],
        }
        await synthesize_with_voice_control(
            script=[line], output_path=output_path, emotion=emotion
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Voicebox completed without a WAV artifact")

    manifest = ArtifactManifest(
        artifacts=[
            Artifact(
                kind="audio",
                path=str(output_path),
                media_type="audio/wav",
                primary=True,
            )
        ]
    )
    config_json = {
        **config,
        "audio_provider_used": provider_used,
        "audio_fallback": fallback,
        "artifact_manifest": manifest.model_dump(mode="json"),
    }
    # TaskService owns the only persistence write after the oservi execution
    # result is normalized.  Returning the manifest prevents a later progress
    # projection from overwriting it with stale config_json.
    return {**task, "status": "completed", "config_json": config_json}


def _allow_edge_fallback() -> bool:
    """Require an explicit opt-in before changing the voice provider."""
    return os.getenv("VOICEBOX_ALLOW_EDGE_FALLBACK", "0").lower() in {"1", "true", "yes"}
