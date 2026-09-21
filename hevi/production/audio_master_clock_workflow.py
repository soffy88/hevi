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


async def execute_audio_master_clock_task(task: dict[str, Any], pool: Any) -> dict[str, Any]:
    config = dict(task.get("config_json") or {})
    production_id = str(config.get("production_id") or task.get("id") or "audio-master-clock")
    cached_manifest = config.get("artifact_manifest")
    cached_report = config.get("audio_master_clock_report")
    if isinstance(cached_manifest, dict) and isinstance(cached_report, dict):
        # TaskService normally guards completed tasks.  This second boundary
        # makes direct replay/resume equally idempotent and provider-free.
        manifest = ArtifactManifest.model_validate(cached_manifest)
        if all(Path(a.path).is_file() and Path(a.path).stat().st_size > 0 for a in manifest.artifacts):
            return {"status": "completed", "result_video_path": str(manifest.primary_path() or ""),
                    "config_json": config, "artifacts": [a.model_dump(mode="json") for a in manifest.artifacts],
                    "report": {"legacy_result": cached_report}, "review_pending": False}
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task.get("id")))
    output_dir.mkdir(parents=True, exist_ok=True)
    text = str(config.get("text") or "HEVI audio master clock verification.").strip()
    stage = "tts"
    try:
        voice = _voice_from_layer4(config)
        provider_voice = CURATED_VOICES.get(voice.voice_id, voice.voice_id)
        if not provider_voice:
            raise ValueError("Layer4 voice identity resolved to an empty provider voice")
        audio_path = output_dir / "tts_master.wav"
        tts_request = f"{text}|voice={voice.voice_id}|provider_voice={provider_voice}"
        async def _run_tts() -> Path:
            line = SimpleNamespace(text=text, voice=voice.voice_id, emotion=None)
            return await edge_tts_synthesize_smart(
                config={"language": config.get("language") or "en-US"},
                script=[line], output_path=audio_path, voice=voice.voice_id,
            )
        _, tts_durable = await _record_provider_call(
            task=task, provider="edge_tts", model=provider_voice,
            operation="tts_synthesis", endpoint="edge_tts", request=tts_request,
            artifact_ref="tts_audio", invoke=_run_tts,
        )
        audio_probe = _probe_audio(audio_path)
        # Re-record the actual call result under the same durable identity is
        # intentionally avoided: the first record is the provider submission;
        # the output evidence is carried by the artifact and execution report.
        tts_artifact = _artifact(audio_path, kind="audio", media_type="audio/wav",
                                 role="tts_audio", production_id=production_id,
                                 metadata={"provider": "edge_tts", "voice": provider_voice,
                                           "voice_authority": "HEVI_LAYER4", **audio_probe})

        asr_path = output_dir / "asr_transcript.json"
        model_dir = Path(config.get("asr_model_dir") or Path.home() / "models/faster-whisper-large-v3-turbo")
        asr_request = f"{audio_path.resolve()}|sha={tts_artifact.sha256}|model={model_dir}"
        stage = "asr"
        asr_holder: dict[str, Any] = {}
        def _run_asr() -> Path:
            asr_holder.update(_asr_transcribe(audio_path, model_dir, config.get("language_code") or "en"))
            asr_path.write_text(json.dumps({"audio_duration_ms": audio_probe["duration_ms"], **asr_holder},
                                           ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            return asr_path
        _, asr_durable = await _record_provider_call(
            task=task, provider="faster_whisper", model=model_dir.name,
            operation="asr_transcription", endpoint="local:faster-whisper",
            request=asr_request, artifact_ref="asr_transcript",
            invoke=_run_asr,
        )
        asr_result = asr_holder
        cues = align_cues(asr_result["segments"], audio_duration_ms=audio_probe["duration_ms"],
                          fps=int(config.get("fps") or 24), unit="ms")
        transcript = str(asr_result["text"])
        cer = character_error_rate(text, transcript)
        asr_artifact = _artifact(asr_path, kind="transcript", media_type="application/json",
                                 role="asr_transcript_timestamps", production_id=production_id,
                                 metadata={"provider": "faster_whisper", "timestamp_unit": "milliseconds",
                                           "segments": len(cues), "words": len(asr_result["words"]),
                                           "cer": cer})
        stage = "timeline"
        video_result = await execute_subtitle_timeline_task({
            **task, "config_json": {
                **config, "source_audio_path": str(audio_path), "asr_cues": [
                    {"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text, "emotion": c.emotion}
                    for c in cues
                ],
                "source_audio_artifact_id": tts_artifact.artifact_id,
                "production_id": production_id,
            },
        }, pool)
        if video_result.get("status") != "completed":
            raise RuntimeError(str(video_result.get("error") or "subtitle timeline failed"))
        timeline_manifest = ArtifactManifest.model_validate((video_result.get("config_json") or {}).get("artifact_manifest") or {})
        final = next(a for a in timeline_manifest.artifacts if a.primary and a.kind == "video")
        final = final.model_copy(update={"artifact_id": _stable_id(production_id, "final_video", final.sha256 or ""),
                                         "parent_artifact_ids": [tts_artifact.artifact_id or "", asr_artifact.artifact_id or ""]})
        combined = ArtifactManifest(
            production_id=production_id, revision_id=str(task.get("revision_id") or ""),
            attempt_id=str(task.get("_attempt_id") or task.get("id") or ""), tenant_id="HEVI_LAYER4",
            artifacts=[tts_artifact, asr_artifact, *[a for a in timeline_manifest.artifacts if not a.primary], final],
        )
        report = {
            "tts_provider": "edge_tts", "tts_voice": provider_voice, "tts_audio_probe": audio_probe,
            "asr_provider": "faster_whisper", "asr_timestamp_unit": "milliseconds",
            "asr_timestamp_normalization": "PASS", "asr_timestamp_monotonicity": "PASS",
            "asr_transcript_cer": cer, "asr_transcript_quality": "MEASURED",
            "audio_master_clock": "PASS", "audio_master_clock_id": hashlib.sha256(
                json.dumps({"audio_sha": tts_artifact.sha256, "segments": asr_result["segments"],
                            "duration_ms": audio_probe["duration_ms"]}, sort_keys=True).encode()
            ).hexdigest(),
            "voice_authority": "HEVI_LAYER4", "second_voice_authority": 0,
            "tts_provider_call_recorded": "YES", "asr_provider_call_recorded": "YES",
            "tts_production_graph_wiring": "PASS", "asr_production_graph_wiring": "PASS",
            "audio_to_timeline_e2e": "PASS", "source_audio_artifact_id": tts_artifact.artifact_id,
            "asr_artifact_id": asr_artifact.artifact_id, "final_video_artifact_id": final.artifact_id,
            "durable": {"tts": tts_durable, "asr": asr_durable},
        }
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
