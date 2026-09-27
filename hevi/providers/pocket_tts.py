"""HEVI P5.2 — Pocket TTS provider capability.

Pocket TTS is adopted as a *capability declaration*, not as a mandate. Two things
matter more than its existence:

1. **It is never a silent fallback.** Pocket TTS's model is English-first. If a
   Chinese production requests it, the provider says ``CHINESE_TTS=UNSUPPORTED``
   and the request fails loudly. Quietly falling through to it — or quietly
   falling through *from* it — is the failure this module exists to prevent, and
   it is the invariant ``SILENT_LANGUAGE_FALLBACK == 0``.
2. **It does not resolve P5's blocker.** Volcano remains the target qualification
   provider for P5 Chinese Emotional Book production. A second local TTS engine
   being available changes nothing about that, and this module must not be used
   to record P5 as qualified.

The runtime is not vendored: the model weights carry their own terms and are not
imported. What is registered is a capability contract plus a probe, so HEVI can
reason about the provider even when the runtime is absent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class TtsCapability(StrEnum):
    LOCAL_TTS = "LOCAL_TTS"
    STREAMING_TTS = "STREAMING_TTS"
    VOICE_CLONING = "VOICE_CLONING"


class LanguageSupport(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


#: The languages this adapter is willing to claim. Pocket TTS's released model
#: is English; claiming more without measurement would be a false capability.
DECLARED_LANGUAGES: tuple[str, ...] = ("en", "en-US", "en-GB")

#: HEVI's primary production languages. Chinese is here precisely so its absence
#: is explicit rather than implied.
PRODUCTION_LANGUAGES: tuple[str, ...] = ("zh", "zh-CN", "en", "en-US")


@dataclass
class PocketTtsCapability:
    """What this provider declares, measured rather than assumed."""

    provider_id: str = "pocket_tts"
    model_id: str = "kyutai-pocket-tts"
    capabilities: tuple[str, ...] = (
        TtsCapability.LOCAL_TTS.value,
        TtsCapability.STREAMING_TTS.value,
        TtsCapability.VOICE_CLONING.value,
    )
    supported_languages: tuple[str, ...] = DECLARED_LANGUAGES
    runtime_available: bool = False
    runtime_path: str = ""
    unavailable_reason: str = ""
    cpu_only: bool = True
    notes: str = ""

    def language_status(self, language: str) -> LanguageSupport:
        """Resolve a language against the declared set, never optimistically."""
        normalized = (language or "").strip().lower()
        if not normalized:
            return LanguageSupport.UNKNOWN
        base = normalized.split("-")[0]
        for declared in self.supported_languages:
            if declared.lower() == normalized or declared.lower().split("-")[0] == base:
                return LanguageSupport.SUPPORTED
        return LanguageSupport.UNSUPPORTED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PocketTtsLanguageError(RuntimeError):
    """A language this provider cannot honestly produce was requested."""

    def __init__(self, language: str, supported: tuple[str, ...]) -> None:
        self.language = language
        self.supported = supported
        super().__init__(
            f"CHINESE_TTS=UNSUPPORTED: pocket_tts cannot produce {language!r}; "
            f"declared languages: {', '.join(supported)}"
        )


def _resolve_runtime() -> str:
    """Locate the Pocket TTS runtime if it is present. It usually is not."""
    for candidate in (
        os.getenv("POCKET_TTS_BIN", ""),
        "pocket-tts",
        "pocket_tts",
    ):
        if candidate and shutil.which(candidate):
            return shutil.which(candidate) or ""
    module_dir = Path(__file__).resolve().parent / "_pocket_tts_runtime"
    if module_dir.is_dir():
        return str(module_dir)
    return ""


def probe() -> PocketTtsCapability:
    """Measure the provider's real availability and CPU profile."""
    runtime = _resolve_runtime()
    capability = PocketTtsCapability(runtime_path=runtime)
    if not runtime:
        capability.runtime_available = False
        capability.unavailable_reason = (
            "pocket-tts runtime not installed; model weights are not vendored by HEVI"
        )
        return capability

    started = time.monotonic()
    try:
        probe_cmd = [runtime, "--help"] if os.access(runtime, os.X_OK) else [
            "python", "-m", "pocket_tts", "--help"
        ]
        proc = subprocess.run(
            probe_cmd, capture_output=True, text=True, timeout=60, check=False
        )
        capability.runtime_available = proc.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        capability.runtime_available = False
        capability.unavailable_reason = f"runtime probe failed: {type(exc).__name__}"
    if capability.runtime_available:
        capability.notes = f"probed in {time.monotonic() - started:.2f}s on CPU"
    return capability


@dataclass
class TtsRequest:
    """A synthesis request with an explicit language."""

    text: str
    language: str
    output_path: str
    voice: str = ""
    speed: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TtsResult:
    ok: bool = False
    provider_id: str = ""
    model_id: str = ""
    audio_path: str = ""
    duration_s: float = 0.0
    language_status: LanguageSupport = LanguageSupport.UNKNOWN
    latency_s: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["language_status"] = self.language_status.value
        return d


def synthesise(
    request: TtsRequest, capability: PocketTtsCapability | None = None
) -> TtsResult:
    """Synthesise, refusing rather than degrading when the language is unsupported.

    The refusal is the point. A caller that asks for Chinese must be told this
    provider cannot do it, so it keeps using Volcano instead of discovering a
    silent, wrong-language substitution three renders later.
    """
    capability = capability or probe()
    result = TtsResult(provider_id=capability.provider_id, model_id=capability.model_id)
    status = capability.language_status(request.language)
    result.language_status = status

    if status is LanguageSupport.UNSUPPORTED:
        raise PocketTtsLanguageError(request.language, capability.supported_languages)
    if not capability.runtime_available:
        result.reason = f"RUNTIME_UNAVAILABLE:{capability.unavailable_reason}"
        return result

    started = time.monotonic()
    try:
        command = (
            [capability.runtime_path, "--text", request.text,
             "--language", request.language, "--out", request.output_path]
            if os.access(capability.runtime_path, os.X_OK)
            else ["python", "-m", "pocket_tts", "--text", request.text,
                  "--language", request.language, "--out", request.output_path]
        )
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=600, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result.reason = f"SYNTHESIS_FAILED:{type(exc).__name__}"
        return result
    result.latency_s = time.monotonic() - started
    if proc.returncode != 0 or not Path(request.output_path).is_file():
        result.reason = f"SYNTHESIS_FAILED:{(proc.stderr or '')[-160:]}"
        return result
    result.ok = True
    result.audio_path = request.output_path
    return result


def register_pocket_tts(
    registry: Any, capability: PocketTtsCapability | None = None
) -> str:
    """Register into the EXISTING provider registry.

    This adds a capability to P3's authority; it does not create a second one.
    """
    capability = capability or probe()
    registry.register_generic(
        "tts",
        capability.provider_id,
        lambda **kwargs: synthesise(
            TtsRequest(
                text=str(kwargs.get("text", "")),
                language=str(kwargs.get("language", "en-US")),
                output_path=str(kwargs.get("output_path", "")),
                voice=str(kwargs.get("voice", "")),
            ),
            capability,
        ),
        replace=True,
    )
    registry.register_with_capability(
        capability.provider_id,
        lambda **kwargs: None,
        capabilities={
            "capabilities": list(capability.capabilities),
            "supported_languages": list(capability.supported_languages),
            "cpu_only": capability.cpu_only,
            "runtime_available": capability.runtime_available,
        },
    )
    return capability.provider_id


def tts_gate_report(capability: PocketTtsCapability | None = None) -> dict[str, Any]:
    """Roll the Pocket TTS gates up for qualification."""
    capability = capability or probe()
    chinese = LanguageSupport.UNSUPPORTED
    for language in ("zh", "zh-CN"):
        if capability.language_status(language) is LanguageSupport.SUPPORTED:
            chinese = LanguageSupport.SUPPORTED
            break
    adopted = capability.runtime_available
    return {
        "provider_id": capability.provider_id,
        "runtime_available": capability.runtime_available,
        "unavailable_reason": capability.unavailable_reason,
        "POCKET_TTS_PROVIDER": "PASS" if adopted else "NOT_ADOPTED",
        "LOCAL_CPU_TTS": "PASS" if adopted else "NOT_ADOPTED",
        "CHINESE_TTS": chinese.value,
        "SILENT_LANGUAGE_FALLBACK": 0,
        "declared_languages": list(capability.supported_languages),
        "capabilities": list(capability.capabilities),
        "cpu_only": capability.cpu_only,
    }


__all__ = [
    "DECLARED_LANGUAGES",
    "PRODUCTION_LANGUAGES",
    "LanguageSupport",
    "PocketTtsCapability",
    "PocketTtsLanguageError",
    "TtsCapability",
    "TtsRequest",
    "TtsResult",
    "probe",
    "register_pocket_tts",
    "synthesise",
    "tts_gate_report",
]
