"""Local ASR transcription (``audio.asr_transcribe``).

This capability brings the transcription step that previously lived
only in the stable-acceptance experiment script
(``scripts/run_experiment.py::run_asr`` in the experiment directory,
outside this repo) into hevi, so gates stop judging passed-in
dialogue evidence alone and every ASR result carries the same
auditable evidence: model name, model path, device/compute settings,
normalisation backend and glossary version, raw and normalised
transcripts, glossary hits, and CPU load/transcribe timings.

Defaults (2026-11-01 ASR-fix measurement, same audio, same coverage
measure as R1):

* model ``small`` (``faster-whisper-small``, 464 MB, already cached;
  single-episode CPU int8 transcribe ~3.9 s vs ~1.6 s for ``base``).
  ``base`` was the R1 default and is still selectable by name, but it
  is never the default any more.
* ``large-v3-turbo`` ONLY as a final-review fallback: when expected
  lines are supplied and the ``small`` + normalisation coverage is
  below 0.90, one ``large-v3-turbo`` pass runs and its evidence is
  kept alongside the ``small`` pass. Without expected lines there is
  no coverage to trigger on, so no fallback runs. The fallback is
  never the default model.
* normalisation ``builtin`` (built-in t2s table + audited glossary,
  observed side only). ``opencc`` is opt-in; ``none`` is an explicit
  opt-out recorded in evidence.

Deliberately NOT in the default path: SenseVoice/FunASR (present on
disk but never verified runnable in the measurement run) and forced
alignment (``audio.forced_align`` stays a separate, later upgrade;
recogniser word timestamps from faster-whisper are recorded in the
evidence but are NOT forced-alignment timings and must never be fed
to a gate as ``vo_word_timings``).

Models are resolved ONLY to already-cached local directories. A bare
model name is never handed to faster-whisper in a way that could
trigger a download: an unknown name or a missing cache raises
``CapabilityError`` naming the missing location.
"""

from __future__ import annotations

import glob
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.capabilities.asr_glossary import GLOSSARY_VERSION
from hevi.capabilities.asr_normalization import normalize_observed_text
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

DEFAULT_ASR_MODEL = "small"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "int8"
DEFAULT_LANGUAGE = "zh"
FALLBACK_ASR_MODEL = "large-v3-turbo"
FALLBACK_COVERAGE_FLOOR = 0.90

_KNOWN_MODELS = ("base", "small", "large-v3-turbo", "large", "turbo")


def _snapshot_dir(pattern: str) -> str | None:
    matches = sorted(
        p for p in glob.glob(pattern)
        if Path(p, "model.bin").is_file()
    )
    return matches[0] if matches else None


def resolve_model_path(model: str, model_path: str | None = None) -> str:
    """Resolve a model name to an already-cached local directory.

    ``model_path`` (an existing directory) wins. Otherwise ``model``
    must be one of the known names and must resolve to a cached
    directory on this machine; anything else raises
    ``CapabilityError`` instead of letting faster-whisper download.
    """
    if model_path:
        candidate = Path(model_path).expanduser()
        if candidate.is_dir() and Path(candidate, "model.bin").is_file():
            return str(candidate)
        raise CapabilityError(
            f"audio.asr_transcribe: model_path is not a faster-whisper "
            f"model directory (no model.bin): {model_path}"
        )
    if isinstance(model, str) and (
        "/" in model or "\\" in model or Path(model).expanduser().exists()
    ):
        candidate = Path(model).expanduser()
        if candidate.is_dir() and Path(candidate, "model.bin").is_file():
            return str(candidate)
        raise CapabilityError(
            f"audio.asr_transcribe: model path is not a faster-whisper "
            f"model directory (no model.bin): {model}"
        )
    name = str(model)
    if name == "base":
        candidate = Path("/data/soffy/models/faster-whisper-base")
        if candidate.is_dir():
            return str(candidate)
    elif name == "small":
        for pattern in (
            "/data/soffy/models/hf/hub/models--Systran--faster-whisper-small/snapshots/*",
            str(Path.home() / ".cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/*"),
            "/data/soffy/models/faster-whisper-small",
        ):
            found = _snapshot_dir(pattern)
            if found:
                return found
            direct = Path(pattern.rstrip("*"))
            if direct.is_dir() and Path(direct, "model.bin").is_file():
                return str(direct)
    elif name in ("large-v3-turbo", "large", "turbo"):
        for candidate in (
            Path("/home/soffy/models/faster-whisper-large-v3-turbo"),
            Path.home() / "models/faster-whisper-large-v3-turbo",
            Path("/data/soffy/models/faster-whisper-large-v3-turbo"),
        ):
            if candidate.is_dir() and Path(candidate, "model.bin").is_file():
                return str(candidate)
    else:
        raise CapabilityError(
            f"audio.asr_transcribe: unknown model {model!r}; known models "
            f"are {list(_KNOWN_MODELS)} or an existing model directory"
        )
    raise CapabilityError(
        f"audio.asr_transcribe: model {name!r} is not cached on this "
        f"machine (checked the known local locations); refusing to "
        f"download -- place the converted model in its cached location "
        f"or pass model_path explicitly"
    )


def _transcribe_with_model(
    model_path: str,
    audio_path: Path,
    *,
    device: str,
    compute_type: str,
    language: str,
    word_timestamps: bool,
    beam_size: int | None,
    vad_filter: bool | None,
) -> dict[str, Any]:
    """One faster-whisper pass; timings cover load + transcription."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise CapabilityError(
            "audio.asr_transcribe: faster-whisper is not installed in "
            "this environment; no transcript was produced"
        ) from exc
    load_start = time.perf_counter()
    model = WhisperModel(model_path, device=device, compute_type=compute_type)
    load_seconds = time.perf_counter() - load_start
    kwargs: dict[str, Any] = {
        "language": language,
        "word_timestamps": word_timestamps,
    }
    if beam_size is not None:
        kwargs["beam_size"] = beam_size
    if vad_filter is not None:
        kwargs["vad_filter"] = vad_filter
    transcribe_start = time.perf_counter()
    segments, info = model.transcribe(str(audio_path), **kwargs)
    segment_list: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    for segment in segments:
        segment_list.append({
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": str(segment.text),
        })
        words.extend(
            {
                "word": str(word.word),
                "start": round(float(word.start), 3),
                "end": round(float(word.end), 3),
                "probability": round(float(word.probability), 3),
            }
            for word in (segment.words or [])
        )
    transcribe_seconds = time.perf_counter() - transcribe_start
    return {
        "segments": segment_list,
        "words": words,
        "language": str(getattr(info, "language", language)),
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        "load_seconds": round(load_seconds, 3),
        "transcribe_seconds": round(transcribe_seconds, 3),
    }


def _coverage_for(
    expected_lines: list[str] | None, normalized: str
) -> dict[str, Any] | None:
    if not expected_lines:
        return None
    from hevi.capabilities.prompt_eval_harness import _containment_coverage

    per_line = [
        round(_containment_coverage(line, normalized), 4) for line in expected_lines
    ]
    return {
        "per_line": per_line,
        "mean": round(sum(per_line) / len(per_line), 4) if per_line else 1.0,
        "floor": 0.8,
    }


def transcribe_audio(
    audio_path: str | Path,
    *,
    expected_lines: list[str] | None = None,
    model: str = DEFAULT_ASR_MODEL,
    model_path: str | None = None,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    language: str = DEFAULT_LANGUAGE,
    word_timestamps: bool = True,
    beam_size: int | None = None,
    vad_filter: bool | None = None,
    normalization: str = "builtin",
    apply_glossary: bool = True,
    glossary_version: str = GLOSSARY_VERSION,
    enable_fallback: bool = True,
    fallback_model: str = FALLBACK_ASR_MODEL,
    fallback_coverage_floor: float = FALLBACK_COVERAGE_FLOOR,
    _transcriber: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Transcribe ``audio_path`` with faster-whisper and normalise it.

    Returns the full evidence dict (see module docstring). The raw
    transcript is always preserved; ``transcript_normalized`` is the
    observed-side normalised form used for coverage. When expected
    lines are supplied and the default pass scores below
    ``fallback_coverage_floor``, the fallback model runs once and
    both passes are kept in ``passes``; the fallback pass becomes the
    reported result. No other model (SenseVoice/FunASR) is ever used.
    ``_transcriber`` is a test seam only: a callable with the same
    contract as :func:`_transcribe_with_model`.
    """
    audio = Path(audio_path)
    if not audio.is_file():
        raise CapabilityError(f"audio.asr_transcribe: audio file not found: {audio}")
    if glossary_version != GLOSSARY_VERSION:
        raise CapabilityError(
            f"audio.asr_transcribe: unknown glossary version "
            f"{glossary_version!r}; this build ships {GLOSSARY_VERSION}"
        )
    if not (0.0 < float(fallback_coverage_floor) <= 1.0):
        raise CapabilityError(
            "audio.asr_transcribe: fallback_coverage_floor must be in (0, 1]"
        )
    lines = list(expected_lines) if expected_lines is not None else None
    run = _transcriber or _transcribe_with_model
    warnings: list[str] = []

    def _one_pass(model_name: str, resolved: str) -> dict[str, Any]:
        result = run(
            resolved, audio,
            device=device, compute_type=compute_type, language=language,
            word_timestamps=word_timestamps, beam_size=beam_size,
            vad_filter=vad_filter,
        )
        raw = "".join(seg["text"] for seg in result["segments"])
        norm = normalize_observed_text(
            raw, normalization=normalization, apply_glossary=apply_glossary
        )
        coverage = _coverage_for(lines, norm["normalized"])
        return {
            "model": model_name,
            "model_path": resolved,
            "device": device,
            "compute_type": compute_type,
            "language": result["language"],
            "language_probability": result["language_probability"],
            "load_seconds": result["load_seconds"],
            "transcribe_seconds": result["transcribe_seconds"],
            "transcript_raw": raw,
            "transcript_t2s": norm["t2s"],
            "transcript_normalized": norm["normalized"],
            "glossary_hits": norm["glossary_hits"],
            "segments": result["segments"],
            "words": result["words"],
            "coverage": coverage,
        }

    resolved_primary = resolve_model_path(model, model_path)
    primary = _one_pass(model, resolved_primary)
    passes = [primary]
    final = primary
    fallback_record: dict[str, Any] = {
        "enabled": bool(enable_fallback),
        "triggered": False,
        "model": fallback_model,
        "coverage_floor": float(fallback_coverage_floor),
    }
    primary_mean = primary["coverage"]["mean"] if primary["coverage"] else None
    if (
        enable_fallback
        and lines
        and primary_mean is not None
        and primary_mean < float(fallback_coverage_floor)
        and model != fallback_model
    ):
        fallback_record["triggered"] = True
        fallback_record["reason"] = (
            f"primary model {model!r} coverage {primary_mean} below "
            f"fallback floor {float(fallback_coverage_floor)}"
        )
        try:
            resolved_fallback = resolve_model_path(fallback_model)
        except CapabilityError as exc:
            fallback_record["available"] = False
            fallback_record["error"] = str(exc)
            warnings.append(f"large-model fallback unavailable: {exc}")
        else:
            fallback_record["available"] = True
            try:
                fallback_pass = _one_pass(fallback_model, resolved_fallback)
            except Exception as exc:  # recorded, primary kept
                fallback_record["error"] = str(exc)
                warnings.append(f"large-model fallback failed: {exc}")
            else:
                passes.append(fallback_pass)
                final = fallback_pass
                fallback_record["coverage"] = fallback_pass["coverage"]
    elif enable_fallback and lines and primary_mean is not None:
        fallback_record["reason"] = (
            f"primary model {model!r} coverage {primary_mean} meets "
            f"fallback floor {float(fallback_coverage_floor)}; no fallback run"
        )
    norm_warning = None
    if normalization == "none":
        norm_warning = (
            "normalization explicitly disabled; raw transcript used as-is"
        )
        warnings.append(norm_warning)
    return {
        "capability": "audio.asr_transcribe",
        "audio_path": str(audio),
        "model": final["model"],
        "model_path": final["model_path"],
        "model_name": final["model"],
        "device": device,
        "compute_type": compute_type,
        "language": final["language"],
        "language_probability": final["language_probability"],
        "word_timestamps": bool(word_timestamps),
        "beam_size": beam_size,
        "vad_filter": vad_filter,
        "normalization": normalization,
        "normalization_backend": normalization,
        "apply_glossary": bool(apply_glossary),
        "glossary_version": GLOSSARY_VERSION if apply_glossary and normalization != "none" else None,
        "glossary_hits": final["glossary_hits"],
        "transcript_raw": final["transcript_raw"],
        "transcript_t2s": final["transcript_t2s"],
        "transcript_normalized": final["transcript_normalized"],
        "segments": final["segments"],
        "words": final["words"],
        "load_seconds": final["load_seconds"],
        "transcribe_seconds": final["transcribe_seconds"],
        "coverage": final["coverage"],
        "expected_lines": lines,
        "passes": passes,
        "fallback": fallback_record,
        "warnings": warnings,
        "note": (
            "Recogniser word timestamps are faster-whisper output, NOT "
            "forced alignment; never feed them to a gate as vo_word_timings. "
            "Forced alignment remains audio.forced_align, a separate upgrade."
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = params.get("expected_lines")
    evidence = transcribe_audio(
        params["audio_path"],
        expected_lines=[str(line) for line in expected] if expected is not None else None,
        model=str(params.get("model", DEFAULT_ASR_MODEL)),
        model_path=str(params["model_path"]) if params.get("model_path") else None,
        device=str(params.get("device", DEFAULT_DEVICE)),
        compute_type=str(params.get("compute_type", DEFAULT_COMPUTE_TYPE)),
        language=str(params.get("language", DEFAULT_LANGUAGE)),
        word_timestamps=bool(params.get("word_timestamps", True)),
        beam_size=int(params["beam_size"]) if params.get("beam_size") is not None else None,
        vad_filter=bool(params["vad_filter"]) if params.get("vad_filter") is not None else None,
        normalization=str(params.get("normalization", "builtin")),
        apply_glossary=bool(params.get("apply_glossary", True)),
        glossary_version=str(params.get("glossary_version", GLOSSARY_VERSION)),
        enable_fallback=bool(params.get("enable_fallback", True)),
        fallback_model=str(params.get("fallback_model", FALLBACK_ASR_MODEL)),
        fallback_coverage_floor=float(params.get("fallback_coverage_floor", FALLBACK_COVERAGE_FLOOR)),
    )
    report_path = out_dir / "asr_transcribe_report.json"
    report_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    coverage = evidence["coverage"]
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "model": evidence["model"],
            "model_path": evidence["model_path"],
            "transcript_normalized": evidence["transcript_normalized"],
            "glossary_hits": evidence["glossary_hits"],
            "glossary_version": evidence["glossary_version"],
            "coverage": coverage,
            "fallback": evidence["fallback"],
            "load_seconds": evidence["load_seconds"],
            "transcribe_seconds": evidence["transcribe_seconds"],
        },
    )


def register_asr_transcribe_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="audio.asr_transcribe",
            kind="audio",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "audio_path": {"type": "string"},
                    "expected_lines": {"type": "array", "items": {"type": "string"}},
                    "model": {"type": "string"},
                    "model_path": {"type": "string"},
                    "device": {"type": "string", "enum": ["cpu", "cuda", "auto"]},
                    "compute_type": {"type": "string"},
                    "language": {"type": "string"},
                    "word_timestamps": {"type": "boolean"},
                    "beam_size": {"type": "integer", "exclusiveMinimum": 0},
                    "vad_filter": {"type": "boolean"},
                    "normalization": {"type": "string", "enum": ["builtin", "opencc", "none"]},
                    "apply_glossary": {"type": "boolean"},
                    "glossary_version": {"type": "string"},
                    "enable_fallback": {"type": "boolean"},
                    "fallback_model": {"type": "string"},
                    "fallback_coverage_floor": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                },
                "required": ["audio_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Local ASR transcription with faster-whisper (default "
                "model small, CPU int8; large-v3-turbo only as a "
                "final-review fallback when small + normalisation "
                "coverage is below 0.90). Observed-side traditional-"
                "to-simplified normalisation plus the versioned "
                "audited misrecognition glossary; raw transcript, "
                "normalised text, glossary hits, model/params and CPU "
                "timings are all recorded in the evidence JSON."
            ),
            line="audio",
        )
    )
    return ["audio.asr_transcribe"]


register_asr_transcribe_capabilities_once()
