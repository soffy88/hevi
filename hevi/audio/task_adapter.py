"""Voice Studio adapter executed by the shared HEVI task lifecycle."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
    line = SimpleNamespace(
        text=text,
        voice=str(config.get("voice") or "") or None,
        emotion=emotion,
    )
    requested = str(config.get("engine") or task.get("audio_provider") or "voicebox").strip().lower()
    provider_used = requested
    fallback: dict[str, str] | None = None
    try:
        await _synthesize_with_engine(
            requested,
            line=line,
            output_path=output_path,
            config=config,
            emotion=emotion,
        )
    except VoiceboxError as exc:
        if requested != "voicebox" or not _allow_edge_fallback():
            raise
        provider_used = "edge_tts"
        fallback = {"from": "voicebox", "to": "edge_tts", "reason": str(exc)[:500]}
        await synthesize_with_voice_control(
            script=[line], output_path=output_path, emotion=emotion, config=config
        )
    audio_probe = _probe_audio_artifact(output_path)

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
        "audio_probe": audio_probe,
        "artifact_manifest": manifest.model_dump(mode="json"),
    }
    # TaskService owns the only persistence write after the oservi execution
    # result is normalized.  Returning the manifest prevents a later progress
    # projection from overwriting it with stale config_json.
    return {**task, "status": "completed", "config_json": config_json}


def _probe_audio_artifact(path: Path) -> dict[str, Any]:
    """Require a real decodable audio stream before the task can complete."""
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"TTS completed without an audio artifact: {path}")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is required to validate the TTS artifact")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"TTS artifact is not decodable audio: {path}")
    try:
        payload = json.loads(result.stdout or "{}")
        stream = (payload.get("streams") or [])[0]
        duration = float((payload.get("format") or {}).get("duration") or 0.0)
        sample_rate = int(stream.get("sample_rate") or 0)
        channels = int(stream.get("channels") or 0)
        codec = str(stream.get("codec_name") or "")
    except (ValueError, TypeError, IndexError, AttributeError) as exc:
        raise RuntimeError(f"TTS artifact probe returned invalid metadata: {path}") from exc
    if duration <= 0 or sample_rate <= 0 or channels <= 0 or not codec:
        raise RuntimeError(f"TTS artifact probe failed required media checks: {path}")
    return {
        "duration_s": duration,
        "sample_rate": sample_rate,
        "channels": channels,
        "codec": codec,
        "size_bytes": path.stat().st_size,
    }


async def _synthesize_with_engine(
    engine: str,
    *,
    line: SimpleNamespace,
    output_path: Path,
    config: dict[str, Any],
    emotion: str | None,
) -> None:
    """Dispatch one catalog engine without silently changing the requested one."""
    if engine == "voicebox":
        await voicebox_synthesize(script=[line], output_path=output_path, emotion=emotion)
        return
    if engine == "edge_tts":
        await synthesize_with_voice_control(
            script=[line],
            output_path=output_path,
            voice=str(config.get("voice") or "") or None,
            emotion=emotion,
            config=config,
        )
        return
    if engine == "cosyvoice":
        from hevi.audio.cosyvoice_service import cosyvoice_synthesize

        line.inference_mode = str(config.get("inference_mode") or "") or None
        line.instruct_text = str(config.get("instruct") or emotion or "") or None
        line.voice_ref = str(config.get("reference_audio") or "") or None
        line.ref_text = str(config.get("reference_text") or "") or None
        await cosyvoice_synthesize(config=config, script=[line], output_path=output_path)
        return
    if engine == "f5_tts":
        from hevi.audio.f5_tts_service import f5_tts_synthesize

        await f5_tts_synthesize(
            text=line.text,
            output_path=output_path,
            reference_audio=str(config.get("reference_audio") or os.getenv("F5_TTS_REFERENCE_AUDIO", "")),
            reference_text=str(config.get("reference_text") or os.getenv("F5_TTS_REFERENCE_TEXT", "")),
            speed=float(config.get("speed") or 1.0),
            language=str(config.get("language") or "") or None,
        )
        return
    if engine == "lux_tts":
        from hevi.audio.lux_tts_service import synth_with_luxvoice

        await synth_with_luxvoice(
            line.text,
            output_path,
            reference_audio=str(config.get("reference_audio") or "") or None,
            speed=float(config.get("speed") or 1.0),
        )
        return
    if engine == "voxcpm":
        from hevi.audio.voxcpm_service import synth_with_voxcpm

        await synth_with_voxcpm(
            line.text,
            output_path,
            language=str(config.get("language") or ""),
            reference_audio=str(config.get("reference_audio") or "") or None,
            voice_design=str(config.get("voice_design") or ""),
            speed=float(config.get("speed") or 1.0),
        )
        return
    if engine == "pocket_tts":
        from hevi.audio.pocket_tts_service import synth_with_pocket_tts

        await synth_with_pocket_tts(
            line.text,
            output_path=output_path,
            voice=str(config.get("voice") or "alba"),
            language=str(config.get("language") or ""),
            reference_audio=str(config.get("reference_audio") or "") or None,
            voice_design=str(config.get("voice_design") or ""),
            speed=float(config.get("speed") or 1.0),
            config=str(config.get("model_config") or "") or None,
        )
        return
    raise ValueError(f"unsupported speech engine: {engine}")


def _allow_edge_fallback() -> bool:
    """Require an explicit opt-in before changing the voice provider."""
    return os.getenv("VOICEBOX_ALLOW_EDGE_FALLBACK", "0").lower() in {"1", "true", "yes"}
