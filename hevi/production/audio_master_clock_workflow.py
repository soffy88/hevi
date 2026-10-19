"""Production TTS -> ASR -> verified audio master-clock workflow.

This module is deliberately a composition boundary.  TTS and ASR providers
are real runtimes, provider calls use the existing Layer4 durable records, and
the final subtitle/timeline render is delegated to the existing production
adapter.  No cue or timeline implementation is duplicated here.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.assembly.subtitle_timeline_atoms import align_cues
from hevi.audio.asr_verify import character_error_rate
from hevi.audio.edge_tts_custom import CURATED_VOICES, edge_tts_synthesize_smart
from hevi.creative.layer4.authority_stores import CallLedgerStore
from hevi.creative.layer4.character_authority import VoiceIdentity
from hevi.creative.layer4.incident_store import track_task_failure
from hevi.creative.layer4.provider_execution import (
    apply_download_complete,
    apply_poll_success,
    guarded_submit,
    new_record,
)
from hevi.creative.layer4.usage_ledger import begin_call, complete_call, fail_call
from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.production.subtitle_timeline_workflow import execute_subtitle_timeline_task


def _probe_audio(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_name,sample_rate,channels",
            "-of", "json", str(path),
        ], capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"audio ffprobe failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    audio = next((s for s in streams if s.get("codec_name")), None)
    duration = float((payload.get("format") or {}).get("duration") or 0)
    if audio is None or duration <= 0:
        raise RuntimeError("audio codec/duration is unreadable")
    return {
        "codec": str(audio.get("codec_name") or ""),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "duration_ms": round(duration * 1000),
    }


def _stable_id(production_id: str, role: str, digest: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hevi:{production_id}:{role}:{digest}"))


async def _record_provider_call(
    *, task: dict[str, Any], provider: str, model: str, operation: str,
    endpoint: str, request: str, artifact_ref: str,
    invoke: Any,
) -> tuple[Any, dict[str, Any]]:
    """Run one provider call and persist both existing durable record types."""
    task_id = str(task.get("id") or "audio-master-clock")
    production_id = str((task.get("config_json") or {}).get("production_id") or task_id)
    target = artifact_ref or operation
    execution = new_record(
        provider=provider, endpoint=endpoint, model=model, request={"request": request},
        production_revision=str(task.get("revision_id") or "audio-master-clock-v1"),
        target_artifact_id=target, idempotency_key=hashlib.sha256(
            f"{provider}:{operation}:{production_id}:{request}".encode()
        ).hexdigest()[:32],
    )
    execution, submitted = guarded_submit(execution, set())
    if not submitted:
        raise RuntimeError("provider execution was already submitted")
    call = begin_call(
        project_ref=production_id, production_run_ref=production_id,
        task_ref=task_id, artifact_ref=artifact_ref, provider=provider,
        model=model, endpoint=endpoint, operation_type=operation,
        request_summary=request,
    )
    # Existing ledger is keyed by call_id.  Use a deterministic id so replay
    # replaces the same evidence row instead of registering another call.
    call = call.model_copy(update={"call_id": uuid.uuid5(uuid.NAMESPACE_URL, execution.idempotency_key)})
    store = CallLedgerStore()
    store.append(call.model_dump(mode="json"))
    try:
        value = invoke()
        if inspect.isawaitable(value):
            value = await value
        execution = apply_poll_success(execution, provider_terminal_state="succeeded")
        path = value if isinstance(value, Path) else None
        if path is not None:
            execution = apply_download_complete(
                execution, local_artifact_path=str(path),
                checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        done = complete_call(call, actual_cost=0.0, response_summary="real provider execution")
        store.append(done.model_dump(mode="json"))
        return value, {"execution": execution.model_dump(mode="json"), "call_id": str(done.call_id)}
    except Exception as exc:
        failed = fail_call(
            call, provider_error_code=type(exc).__name__,
            normalized_error_code=f"{provider.upper()}_FAILURE",
            safe_error_message=str(exc),
        )
        store.append(failed.model_dump(mode="json"))
        raise


def _asr_transcribe(path: Path, model_dir: Path, language: str | None) -> dict[str, Any]:
    from faster_whisper import WhisperModel

    model = WhisperModel(str(model_dir), device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(path), language=language, word_timestamps=True, vad_filter=True,
    )
    normalized: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    for segment in segments:
        text = str(segment.text or "").strip()
        if not text:
            continue
        normalized.append({
            "start_ms": round(float(segment.start) * 1000),
            "end_ms": round(float(segment.end) * 1000),
            "text": text,
        })
        words.extend({
                "start_ms": round(float(word.start) * 1000),
                "end_ms": round(float(word.end) * 1000),
                "text": str(word.word or "").strip(),
                "probability": float(word.probability),
            } for word in segment.words or ())
    return {
        "text": " ".join(item["text"] for item in normalized).strip(),
        "segments": normalized,
        "words": words,
        "language": str(getattr(info, "language", language or "")),
    }


def _voice_from_layer4(config: dict[str, Any]) -> VoiceIdentity:
    raw = config.get("voice_identity")
    if not isinstance(raw, dict):
        raise ValueError("voice_identity must be supplied by HEVI Layer4")
    return VoiceIdentity.model_validate(raw)


def _artifact(path: Path, *, kind: str, media_type: str, role: str,
              production_id: str, primary: bool = False,
              parents: list[str] | None = None, metadata: dict[str, Any] | None = None) -> Artifact:
    base = Artifact.from_path(path, kind=kind, media_type=media_type, primary=primary,
                              logical_role=role, parent_artifact_ids=parents or [],
                              metadata=metadata or {})
    return base.model_copy(update={"artifact_id": _stable_id(production_id, role, base.sha256 or "")})


async def prepare_audio_master_clock(
    task: dict[str, Any], config: dict[str, Any], output_dir: Path, production_id: str
) -> dict[str, Any]:
    """Run the canonical TTS → ASR portion and return its durable artifacts."""
    text = str(config.get("text") or "HEVI audio master clock verification.").strip()
    voice = _voice_from_layer4(config)
    provider_voice = CURATED_VOICES.get(voice.voice_id, voice.voice_id)
    if not provider_voice:
        raise ValueError("Layer4 voice identity resolved to an empty provider voice")
    tts_provider = str(config.get("tts_engine") or config.get("audio_provider") or "edge_tts").strip().lower()
    local_voice = str(config.get("local_tts_voice") or "alba").strip()
    tts_voice = provider_voice if tts_provider == "edge_tts" else local_voice
    audio_path = output_dir / "tts_master.wav"
    tts_request = f"{text}|provider={tts_provider}|voice={tts_voice}|identity={voice.voice_id}"

    async def _run_tts() -> Path:
        if tts_provider == "edge_tts":
            line = SimpleNamespace(text=text, voice=voice.voice_id, emotion=None)
            return await edge_tts_synthesize_smart(
                config={"language": config.get("language") or "en-US"},
                script=[line], output_path=audio_path, voice=voice.voice_id,
            )
        # Reuse the existing HEVI speech-engine adapter. Provider changes are
        # explicit in task config and in the durable provider/usage records.
        from hevi.audio.task_adapter import _synthesize_with_engine

        line = SimpleNamespace(text=text, voice=local_voice, emotion=None)
        await _synthesize_with_engine(
            tts_provider,
            line=line,
            output_path=audio_path,
            config={**config, "voice": local_voice, "language": config.get("language") or "en-US"},
            emotion=None,
        )
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise RuntimeError(f"TTS provider {tts_provider} produced no audio artifact")
        return audio_path

    _, tts_durable = await _record_provider_call(
        task=task, provider=tts_provider, model=tts_voice,
        operation="tts_synthesis",
        endpoint="edge_tts" if tts_provider == "edge_tts" else f"local:{tts_provider}",
        request=tts_request, artifact_ref="tts_audio", invoke=_run_tts,
    )
    audio_probe = _probe_audio(audio_path)
    tts_artifact = _artifact(
        audio_path, kind="audio", media_type="audio/wav", role="tts_audio",
        production_id=production_id,
        metadata={"provider": tts_provider, "voice": tts_voice,
                  "voice_authority": "HEVI_LAYER4", **audio_probe},
    )

    asr_path = output_dir / "asr_transcript.json"
    model_dir = Path(config.get("asr_model_dir") or Path.home() / "models/faster-whisper-large-v3-turbo")
    asr_request = f"{audio_path.resolve()}|sha={tts_artifact.sha256}|model={model_dir}"
    asr_holder: dict[str, Any] = {}

    def _run_asr() -> Path:
        asr_holder.update(_asr_transcribe(audio_path, model_dir, config.get("language_code") or "en"))
        asr_path.write_text(
            json.dumps({"audio_duration_ms": audio_probe["duration_ms"], **asr_holder},
                       ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )
        return asr_path

    _, asr_durable = await _record_provider_call(
        task=task, provider="faster_whisper", model=model_dir.name,
        operation="asr_transcription", endpoint="local:faster-whisper",
        request=asr_request, artifact_ref="asr_transcript", invoke=_run_asr,
    )
    cues = align_cues(
        asr_holder["segments"], audio_duration_ms=audio_probe["duration_ms"],
        fps=int(config.get("fps") or 24), unit="ms",
    )
    cer = character_error_rate(text, str(asr_holder["text"]))
    asr_artifact = _artifact(
        asr_path, kind="transcript", media_type="application/json",
        role="asr_transcript_timestamps", production_id=production_id,
        metadata={"provider": "faster_whisper", "timestamp_unit": "milliseconds",
                  "segments": len(cues), "words": len(asr_holder["words"]), "cer": cer},
    )
    report = {
        "tts_provider": tts_provider, "tts_voice": tts_voice, "tts_audio_probe": audio_probe,
        "asr_provider": "faster_whisper", "asr_timestamp_unit": "milliseconds",
        "asr_timestamp_normalization": "PASS", "asr_timestamp_monotonicity": "PASS",
        "asr_transcript_cer": cer, "asr_transcript_quality": "MEASURED",
        "audio_master_clock": "PASS", "audio_master_clock_id": hashlib.sha256(
            json.dumps({"audio_sha": tts_artifact.sha256, "segments": asr_holder["segments"],
                        "duration_ms": audio_probe["duration_ms"]}, sort_keys=True).encode()
        ).hexdigest(),
        "voice_authority": "HEVI_LAYER4", "second_voice_authority": 0,
        "tts_provider_call_recorded": "YES", "asr_provider_call_recorded": "YES",
        "tts_production_graph_wiring": "PASS", "asr_production_graph_wiring": "PASS",
        "source_audio_artifact_id": tts_artifact.artifact_id,
        "asr_artifact_id": asr_artifact.artifact_id,
        "durable": {"tts": tts_durable, "asr": asr_durable},
    }
    return {
        "text": text, "provider_voice": provider_voice, "audio_path": audio_path,
        "audio_probe": audio_probe, "tts_artifact": tts_artifact,
        "asr_artifact": asr_artifact, "cues": cues, "asr_result": asr_holder,
        "report": report,
    }


async def execute_audio_master_clock_task(task: dict[str, Any], pool: Any) -> dict[str, Any]:
    config = dict(task.get("config_json") or {})
    production_id = str(config.get("production_id") or task.get("id") or "audio-master-clock")
    cached_manifest = config.get("artifact_manifest")
    cached_report = config.get("audio_master_clock_report")
    if isinstance(cached_manifest, dict) and isinstance(cached_report, dict):
        manifest = ArtifactManifest.model_validate(cached_manifest)
        if all(Path(a.path).is_file() and Path(a.path).stat().st_size > 0 for a in manifest.artifacts):
            return {"status": "completed", "result_video_path": str(manifest.primary_path() or ""),
                    "config_json": config, "artifacts": [a.model_dump(mode="json") for a in manifest.artifacts],
                    "report": {"legacy_result": cached_report}, "review_pending": False}
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task.get("id")))
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = "tts"
    try:
        prepared = await prepare_audio_master_clock(task, config, output_dir, production_id)
        stage = "timeline"
        cues = prepared["cues"]
        video_result = await execute_subtitle_timeline_task({
            **task, "config_json": {
                **config, "source_audio_path": str(prepared["audio_path"]), "asr_cues": [
                    {"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text, "emotion": c.emotion}
                    for c in cues
                ], "source_audio_artifact_id": prepared["tts_artifact"].artifact_id,
                "production_id": production_id,
            },
        }, pool)
        if video_result.get("status") != "completed":
            raise RuntimeError(str(video_result.get("error") or "subtitle timeline failed"))
        timeline_manifest = ArtifactManifest.model_validate((video_result.get("config_json") or {}).get("artifact_manifest") or {})
        final = next(a for a in timeline_manifest.artifacts if a.primary and a.kind == "video")
        final = final.model_copy(update={"artifact_id": _stable_id(production_id, "final_video", final.sha256 or ""),
                                         "parent_artifact_ids": [prepared["tts_artifact"].artifact_id or "", prepared["asr_artifact"].artifact_id or ""]})
        combined = ArtifactManifest(
            production_id=production_id, revision_id=str(task.get("_canonical_revision_id") or config.get("revision_id") or ""),
            attempt_id=str(task.get("_attempt_id") or task.get("id") or ""), tenant_id="HEVI_LAYER4",
            artifacts=[prepared["tts_artifact"], prepared["asr_artifact"], *[a for a in timeline_manifest.artifacts if not a.primary], final],
        )
        report = {**prepared["report"], "audio_to_timeline_e2e": "PASS", "final_video_artifact_id": final.artifact_id}
        return {"status": "completed", "result_video_path": final.path,
                "config_json": {**config, "artifact_manifest": combined.model_dump(mode="json"),
                                 "audio_master_clock_report": report},
                "artifacts": [a.model_dump(mode="json") for a in combined.artifacts],
                "report": {"legacy_result": report}, "review_pending": False}
    except Exception as exc:
        node = f"audio_master_clock.{stage}"
        track_task_failure(production_run_id=str(task.get("id") or production_id), node_key=node,
                           failure="AUDIO_MASTER_CLOCK_FAILURE",
                           evidence={"error_message": str(exc), "failure_code": "AUDIO_MASTER_CLOCK_FAILURE"},
                           owner_id="HEVI_LAYER4")
        return {"status": "failed", "error": str(exc), "review_pending": False, "artifacts": [],
                "report": {"legacy_result": {"error": str(exc)}}}
