"""VoiceStudio-shaped local speech platform workflow.

This is the ``omodul`` layer: it composes HEVI speech primitives, model
registry state, voice gallery metadata, and production handoff plans.  Heavy
TTS/ASR inference remains behind the existing provider adapters.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.audio.speech_platform import diagnostics as speech_diagnostics
from hevi.audio.speech_platform import get_engine, list_engines
from hevi.voicepro.oprim.model_registry import ModelRecord, inspect_path, make_record

_MODEL_OVERRIDES: dict[str, ModelRecord] = {}
_GALLERY: dict[str, VoiceGalleryProfile] = {}


@dataclass
class VoiceGalleryProfile:
    profile_id: str
    name: str
    engine: str
    language: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_model_catalog(*, include_unavailable: bool = True) -> list[dict[str, Any]]:
    """Expose engine/model lifecycle state without loading a model."""

    rows: list[dict[str, Any]] = []
    known: set[str] = set()
    for engine in list_engines(include_unavailable=include_unavailable):
        known.add(engine.id)
        override = _MODEL_OVERRIDES.get(engine.id)
        if override is not None:
            rows.append(override.to_dict())
            continue
        state = "ready" if engine.available else "catalog"
        rows.append(
            make_record(
                model_id=engine.id,
                name=engine.name,
                kind=engine.kind,
                engine=engine.id,
                state=state,
                device="auto",
                languages=engine.languages,
                capabilities=engine.capabilities,
                source="hevi-engine-registry",
            ).to_dict()
        )
    rows.extend(item.to_dict() for key, item in _MODEL_OVERRIDES.items() if key not in known)
    return rows


def register_model(
    *,
    model_id: str,
    name: str,
    kind: str,
    engine: str,
    path: str,
    device: str = "auto",
    languages: list[str] | None = None,
    capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Register a model path and mark it ready only when it exists locally."""

    state, error = inspect_path(path)
    runtime = get_engine(engine)
    execution_ready = bool(runtime and runtime.kind == kind and runtime.available)
    if state == "ready" and not execution_ready:
        error = error or f"语音运行时未就绪: {engine}"
    record = make_record(
        model_id=model_id,
        name=name,
        kind=kind,
        engine=engine,
        state=state,
        path=str(Path(path).expanduser()),
        device=device,
        languages=tuple(languages or []),
        capabilities=tuple(capabilities or []),
        source="user-registered",
        error=error,
        execution_ready=execution_ready,
    )
    _MODEL_OVERRIDES[model_id] = record
    return record.to_dict()


def unregister_model(model_id: str) -> bool:
    """Remove registry metadata; never deletes user model files."""

    return _MODEL_OVERRIDES.pop(model_id, None) is not None


def route_model(
    *,
    kind: str,
    preferred: str | None = None,
    device: str = "auto",
) -> dict[str, Any]:
    """Select a ready local engine and leave a machine-readable decision trail."""

    catalog = [item for item in list_model_catalog() if item["kind"] == kind]
    preferred_row = next((item for item in catalog if item["model_id"] == preferred), None)
    if preferred_row is not None and preferred_row["ready"] and preferred_row["execution_ready"]:
        return {
            "selected": preferred_row,
            "device": device,
            "policy": "local-first",
            "decision_trail": ["preferred model is ready"],
        }
    ready = next(
        (item for item in catalog if item["ready"] and item["execution_ready"]),
        None,
    )
    trail = []
    if preferred:
        trail.append("preferred model unavailable; searched ready catalog")
    if ready is None:
        trail.append("no ready model registered")
    else:
        trail.append(f"selected first ready {ready['model_id']}")
    return {
        "selected": ready,
        "device": device,
        "policy": "local-first",
        "decision_trail": trail,
    }


def create_voice_profile(
    *,
    name: str,
    engine: str,
    reference_audio: str,
    language: str = "",
    reference_text: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create a reusable local voice profile from an existing audio file."""

    if get_engine(engine) is None:
        raise ValueError(f"unknown speech engine: {engine}")
    path = Path(reference_audio).expanduser()
    if not path.is_file():
        raise ValueError(f"reference audio not found: {path}")
    profile = VoiceGalleryProfile(
        profile_id=f"voice-{uuid.uuid4().hex[:12]}",
        name=name.strip() or "untitled voice",
        engine=engine,
        language=language,
        reference_audio=str(path),
        reference_text=reference_text,
        tags=list(tags or []),
    )
    _GALLERY[profile.profile_id] = profile
    return profile.to_dict()


def list_gallery_profiles() -> list[dict[str, Any]]:
    return [item.to_dict() for item in _GALLERY.values()]


def delete_voice_profile(profile_id: str) -> bool:
    """Delete profile metadata without touching the reference audio."""

    return _GALLERY.pop(profile_id, None) is not None


def plan_dubbing(
    *,
    source_video: str,
    target_language: str,
    preserve_speakers: bool = True,
    keep_bed: bool = True,
    asr_engine: str = "faster_whisper",
    tts_engine: str = "edge_tts",
) -> dict[str, Any]:
    """Compile a speaker-preserving dubbing handoff without claiming a render."""

    source = Path(source_video).expanduser()
    errors: list[str] = []
    if not source.is_file():
        errors.append(f"source video not found: {source}")
    asr = get_engine(asr_engine)
    tts = get_engine(tts_engine)
    if asr is None or asr.kind != "asr":
        errors.append(f"unknown ASR engine: {asr_engine}")
    if tts is None or tts.kind != "tts":
        errors.append(f"unknown TTS engine: {tts_engine}")
    if preserve_speakers and not any(
        item["model_id"] == "pyannote" and item["ready"]
        for item in list_model_catalog()
    ):
        errors.append("强说话人分离模型未就绪，将只能使用启发式标签")
    return {
        "status": "blocked" if errors and any("not found" in e or "unknown" in e for e in errors) else "planned",
        "valid": not any("not found" in e or "unknown" in e for e in errors),
        "source_video": str(source),
        "target_language": target_language,
        "preserve_speakers": preserve_speakers,
        "keep_bed": keep_bed,
        "engines": {"asr": asr_engine, "tts": tts_engine},
        "steps": ["extract_audio", "transcribe", "diarize", "translate", "synthesize", "remix", "mux"],
        "errors": errors,
        "notes": [
            "没有 pyannote 时保留启发式 speaker 标签，不伪装声纹分离已完成。",
            "该接口输出的是可审查 handoff，不是成片文件。",
        ],
    }


def plan_audiobook(
    *,
    source_document: str,
    output_path: str = "output/audiobooks/book.m4b",
    voice_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create an EPUB/PDF audiobook production plan."""

    source = Path(source_document).expanduser()
    suffix = source.suffix.lower()
    supported = suffix in {".epub", ".pdf", ".txt", ".md"}
    errors = [] if source.is_file() and supported else [f"unsupported or missing document: {source}"]
    return {
        "status": "planned" if not errors else "blocked",
        "valid": not errors,
        "source_document": str(source),
        "output_path": str(Path(output_path)),
        "format": "m4b",
        "voice_map": dict(voice_map or {}),
        "steps": ["parse_chapters", "map_voices", "batch_synthesize", "chapter_metadata", "package_m4b"],
        "errors": errors,
        "notes": ["章节音频与 m4b 封装必须在真实 TTS 产物存在后执行。"],
    }


def plan_dictation(*, language: str = "", engine: str = "faster_whisper") -> dict[str, Any]:
    selected = get_engine(engine)
    streaming_configured = bool(os.getenv("VOICE_ASR_STREAM_WS_URL", "").strip())
    return {
        "valid": bool(selected and selected.kind == "asr"),
        "engine": engine,
        "language": language or "auto",
        "streaming": streaming_configured,
        "batch_available": bool(selected and selected.available),
        "transport": "websocket",
        "notes": ["浏览器麦克风实时转写需要配置 ASR streaming sidecar。"],
    }


def plan_watermark(*, audio_path: str, operation: str = "embed") -> dict[str, Any]:
    path = Path(audio_path).expanduser()
    return {
        "valid": path.is_file() and operation in {"embed", "detect"},
        "audio_path": str(path),
        "operation": operation,
        "provider": "audioseal",
        "status": "ready" if path.is_file() else "blocked",
        "notes": ["AudioSeal 未安装时只保留计划，不返回伪造 watermark 结果。"],
    }


def platform_diagnostics() -> dict[str, Any]:
    base = speech_diagnostics()
    base.update(
        {
            "model_catalog_count": len(list_model_catalog()),
            "registered_models": sum(item["source"] == "user-registered" for item in list_model_catalog()),
            "gallery_profiles": len(_GALLERY),
            "openai_compatible": True,
            "mcp": True,
            "streaming_asr": bool(os.getenv("VOICE_ASR_STREAM_WS_URL", "").strip()),
            "notes": [
                *base.get("notes", []),
                "模型生命周期、OpenAI 音频协议和语音 Gallery 已有 HEVI 契约；具体引擎仍按环境逐项启用。",
            ],
        }
    )
    return base


def reset_platform() -> None:
    _MODEL_OVERRIDES.clear()
    _GALLERY.clear()


__all__ = [
    "VoiceGalleryProfile",
    "create_voice_profile",
    "delete_voice_profile",
    "list_gallery_profiles",
    "list_model_catalog",
    "plan_audiobook",
    "plan_dictation",
    "plan_dubbing",
    "plan_watermark",
    "platform_diagnostics",
    "register_model",
    "reset_platform",
    "route_model",
    "unregister_model",
]
