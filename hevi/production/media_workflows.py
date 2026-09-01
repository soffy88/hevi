"""3O-shaped media transactions used by HEVI's application service layer.

The public functions in this module are ``omodul`` transactions: they accept
configuration, input data and an output directory, compose lower-level HEVI /
3O primitives, validate artifacts, write a report and never turn an ordinary
provider failure into a false success.  Persistence, billing and queue state
remain in ``TaskService``.

The module contains the two concrete capabilities that were previously only
exposed as plans:

* ``video_localization_workflow``: ASR/subtitle input -> terminology-aware
  translation -> bilingual ASS/SRT -> optional timed dubbing -> mux -> burn.
* ``shorts_generation_workflow``: transcript -> explainable virality scoring
  -> real FFmpeg vertical clips -> subtitles and manifest.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.ingest.subtitle_polish import polish_segments
from hevi.ingest.video_localize import plan_localize
from hevi.ingest.video_transcript import (
    TranscriptError,
    TranscriptSegment,
    fetch_transcript,
    read_subtitle_file,
)
from hevi.production.artifacts import Artifact, ArtifactManifest

# Kept as a patchable seam for tests and injected project adapters.  The real
# renderer is imported inside the shorts transaction so importing the service
# registry does not initialize the media/FFmpeg stack.
render_clip_batch: Any = None


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped) if isinstance(dumped, dict) else {}
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return {}


def _segments(raw: Any) -> list[TranscriptSegment]:
    result: list[TranscriptSegment] = []
    for item in raw or []:
        if isinstance(item, TranscriptSegment):
            result.append(item)
            continue
        if not isinstance(item, dict):
            continue
        try:
            raw_start = item.get("start", item.get("start_s", -1))
            raw_end = item.get("end", item.get("end_s", -1))
            if raw_start is None or raw_end is None:
                continue
            start = float(raw_start)
            end = float(raw_end)
        except (TypeError, ValueError):
            continue
        text = str(item.get("text") or "").strip()
        if start >= 0 and end > start and text:
            result.append(
                TranscriptSegment(
                    start=start,
                    end=end,
                    text=text,
                    speaker=str(item.get("speaker") or ""),
                )
            )
    return sorted(result, key=lambda item: item.start)


def _safe_fingerprint(operation: str, config: dict[str, Any], input_data: dict[str, Any]) -> str:
    """Hash execution shape only; never put user text, paths or secrets in it."""

    excluded = {
        "api_key",
        "token",
        "secret",
        "password",
        "translator",
        "llm",
        "renderer",
        "source_video_path",
        "video_path",
        "output_dir",
        "reference_audio",
        "reference_text",
        "glossary",
    }
    clean_config = {
        key: value
        for key, value in config.items()
        if key.lower() not in excluded and not callable(value)
    }
    shape = {
        "operation": operation,
        "config": clean_config,
        "schema_version": input_data.get("schema_version", 1),
        "has_source_segments": bool(input_data.get("source_segments") or input_data.get("segments")),
        "has_translation": bool(
            input_data.get("translated_segments") or input_data.get("translated")
        ),
        "segment_count": len(input_data.get("source_segments") or input_data.get("segments") or []),
    }
    encoded = json.dumps(shape, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


async def _notify(on_step: Any, stage: str, pct: float, **metadata: Any) -> None:
    if on_step is None:
        return
    callback_result = on_step({"stage": stage, "progress_pct": pct, **metadata})
    if inspect.isawaitable(callback_result):
        await callback_result


def _clock(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(path: Path, segments: list[TranscriptSegment]) -> Path:
    if not segments:
        raise ValueError("cannot write an empty subtitle file")
    body: list[str] = []
    for index, segment in enumerate(segments, start=1):
        body.extend(
            [
                str(index),
                f"{_clock(segment.start)} --> {_clock(segment.end)}",
                segment.text.strip(),
                "",
            ]
        )
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def _coerce_translation(raw: Any, source: list[TranscriptSegment]) -> list[TranscriptSegment]:
    if isinstance(raw, (str, bytes)):
        raise ValueError("translator must return one translation per source segment")
    rows = list(raw or [])
    result: list[TranscriptSegment] = []
    for index, source_segment in enumerate(source):
        item = rows[index] if index < len(rows) else None
        if isinstance(item, TranscriptSegment):
            text = item.text
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("translated_text") or item.get("translation") or "")
        else:
            text = str(item)
        text = str(text or "").strip()
        if not text:
            raise ValueError(f"translator returned an empty line at index {index}")
        result.append(
            TranscriptSegment(
                start=source_segment.start,
                end=source_segment.end,
                text=text,
                speaker=source_segment.speaker,
            )
        )
    if len(rows) != len(source):
        raise ValueError(f"translator returned {len(rows)} lines, expected {len(source)}")
    return result


async def _translate(
    source: list[TranscriptSegment],
    *,
    config: dict[str, Any],
    input_data: dict[str, Any],
) -> tuple[list[TranscriptSegment], str]:
    explicit = input_data.get("translated_segments") or input_data.get("translated")
    if explicit:
        return _coerce_translation(explicit, source), "supplied"

    translator = input_data.get("translator") or config.get("translator")
    target = str(config.get("target_language") or "zh-CN")
    if callable(translator):
        try:
            translated = translator(
                source,
                target_language=target,
                glossary=config.get("glossary") or {},
            )
        except TypeError:
            translated = translator([item.text for item in source], target)
        if inspect.isawaitable(translated):
            translated = await translated
        return _coerce_translation(translated, source), "injected"

    # The project-side 3O translation skill composes its public translation
    # primitives.  Provider SDKs remain optional and failures are surfaced.
    from hevi.voicepro_translate.oskill import skill_batch_translate
    from hevi.voicepro_translate.schemas import TranslateProvider

    provider_name = str(config.get("translation_provider") or "llm_translate")
    try:
        provider = TranslateProvider(provider_name)
    except ValueError as exc:
        raise ValueError(f"unsupported translation provider: {provider_name}") from exc
    if provider is TranslateProvider.LLM_TRANSLATE:
        translated = await _translate_with_hevi_llm(
            source,
            target_language=target,
            glossary=config.get("glossary") or {},
        )
        return _coerce_translation(translated, source), "hevi_llm"
    results = await skill_batch_translate(
        [item.text for item in source],
        provider=provider,
        source_lang=str(config.get("source_language") or "auto"),
        target_lang=target,
    )
    translated = []
    for index, item in enumerate(results):
        text = str(getattr(item, "translated_text", "") or "").strip()
        if not text or bool(getattr(item, "kept_original", False)):
            raise RuntimeError(f"translation provider returned no translation at index {index}")
        translated.append(text)
    return _coerce_translation(translated, source), provider_name


async def _translate_with_hevi_llm(
    source: list[TranscriptSegment],
    *,
    target_language: str,
    glossary: dict[str, str],
) -> list[str]:
    """Use HEVI's registered LLM without adding a second provider stack."""

    from obase.provider_registry import ProviderRegistry

    try:
        llm = ProviderRegistry.get().llm("default")
    except Exception as exc:
        raise RuntimeError(
            "HEVI default LLM is unavailable; inject translator or configure a provider"
        ) from exc
    terms = "\n".join(f"- {key} -> {value}" for key, value in glossary.items())
    prompt = (
        f"Translate each numbered subtitle line to {target_language}. Return JSON only, "
        f"with string keys 0 through {len(source) - 1}; preserve names and meaning.\n"
        + (f"Terminology:\n{terms}\n" if terms else "")
        + "\n".join(f"{index}: {item.text}" for index, item in enumerate(source))
    )
    response: Any = llm(messages=[{"role": "user", "content": prompt}], max_tokens=2048)
    if inspect.isawaitable(response):
        response = await response
    content = response.get("content") if isinstance(response, dict) else str(response)
    if isinstance(content, list):
        content = "".join(
            str(item.get("text") or "") for item in content if isinstance(item, dict)
        )
    raw = str(content or "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        raise RuntimeError("HEVI default LLM returned no JSON translation object")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise RuntimeError("HEVI default LLM returned invalid translation JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("HEVI default LLM translation must be a JSON object")
    translated = [str(payload.get(str(index)) or "").strip() for index in range(len(source))]
    if any(not item for item in translated):
        raise RuntimeError("HEVI default LLM returned incomplete translation lines")
    return translated


async def _burn_subtitles(
    video: Path,
    subtitle_paths: list[Path],
    output: Path,
    *,
    primary_alignment: int = 2,
    secondary_alignment: int = 8,
    watermark: str = "",
) -> Path:
    """Use the public 3O subtitle primitive, with a strict obase fallback."""

    try:
        from oprim import subtitle_burn
    except (ImportError, AttributeError):
        subtitle_burn = None
    if subtitle_burn is not None and not watermark.strip():
        await subtitle_burn(
            video_path=video,
            srt_paths=subtitle_paths,
            output_path=output,
            primary_alignment=primary_alignment,
            secondary_alignment=secondary_alignment,
        )
    else:
        from obase.ffmpeg import run as ffmpeg_run

        filters = []
        for path, alignment in zip(
            subtitle_paths,
            [primary_alignment, secondary_alignment],
            strict=False,
        ):
            escaped = str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
            filters.append(f"subtitles='{escaped}':force_style='Alignment={alignment}'")
        if watermark.strip():
            text = (
                watermark.replace("\\", "\\\\")
                .replace("'", r"\'")
                .replace(":", r"\:")
            )
            filters.append(
                f"drawtext=text='{text}':x=w-tw-24:y=24:fontsize=20:fontcolor=white@0.7"
            )
        await ffmpeg_run(
            args=[
                "-y",
                "-i",
                str(video),
                "-vf",
                ",".join(filters),
                "-c:v",
                "libx264",
                "-c:a",
                "copy",
                str(output),
            ],
            expected_output=output,
        )
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("subtitle burn completed without a non-empty video artifact")
    return output


async def _dub(
    source: list[TranscriptSegment],
    *,
    config: dict[str, Any],
    output_dir: Path,
) -> Path:
    from hevi.assembly.subtitle_align import Cue
    from hevi.audio.task_adapter import _synthesize_with_engine
    from hevi.dub._synth import synth_cues_on_timeline

    engine = str(config.get("tts_engine") or config.get("audio_provider") or "edge_tts")
    language = str(config.get("target_language") or "zh-CN")
    voice = str(config.get("voice") or "")

    async def synth_one(*, cue: Cue, language: str, output_path: Path) -> Path:
        line = SimpleNamespace(text=cue.text, voice=voice or None, emotion=cue.emotion)
        await _synthesize_with_engine(
            engine,
            line=line,
            output_path=output_path,
            config={
                **config,
                "language": language,
                "voice": voice,
                "reference_audio": config.get("reference_audio", ""),
            },
            emotion=cue.emotion,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(f"TTS engine produced no artifact for cue: {engine}")
        return output_path

    cues = [Cue(item.start, item.end, item.text) for item in source]
    output = output_dir / "dubbed_audio.wav"
    await synth_cues_on_timeline(
        cues=cues,
        language=language,
        output_path=output,
        synth_one=synth_one,
    )
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("dubbing completed without a non-empty audio artifact")
    return output


def _manifest(paths: list[tuple[Path, str, str, bool, str]]) -> ArtifactManifest:
    return ArtifactManifest(
        artifacts=[
            Artifact.from_path(
                path,
                kind=kind,
                media_type=media_type,
                primary=primary,
                logical_role=role,
            )
            for path, kind, media_type, primary, role in paths
        ]
    )


async def video_localization_workflow(
    config: Any,
    input_data: Any,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Execute video localization/dubbing as a standard omodul transaction."""

    _enabled_pillars = {"fingerprint", "decision_trail", "report", "cost"}
    cfg = _mapping(config)
    data = _mapping(input_data)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _safe_fingerprint("video_localization_workflow", cfg, data)
    trail: list[dict[str, Any]] = []
    report_path = output_dir / "video_localization_report.json"

    def record(stage: str, **metadata: Any) -> None:
        trail.append({"stage": stage, **metadata})

    try:
        source_path = Path(str(data.get("source_video_path") or data.get("video_path") or "")).expanduser()
        if not source_path.is_file():
            raise FileNotFoundError(f"source video not found: {source_path}")

        await _notify(on_step, "transcribe", 10.0)
        source = _segments(data.get("source_segments") or data.get("segments"))
        subtitle_path = data.get("subtitle_path") or cfg.get("subtitle_path")
        if not source and subtitle_path:
            source = read_subtitle_file(str(subtitle_path))
        if not source:
            source = fetch_transcript(
                source_path,
                whisper_fallback=True,
                language=str(cfg.get("source_language") or "") or None,
                work_dir=output_dir / "transcript",
            )
        if not source:
            raise TranscriptError("transcription produced no timed segments")
        source = polish_segments(source, glossary=cfg.get("glossary"))
        record("transcribe", segments=len(source))

        await _notify(on_step, "translate", 30.0)
        target = await _translate(source, config=cfg, input_data=data)
        translated, translation_provider = target
        record("translate", segments=len(translated), provider=translation_provider)

        await _notify(on_step, "subtitles", 50.0)
        source_srt = _write_srt(output_dir / "source.srt", source)
        target_srt = _write_srt(output_dir / "translated.srt", translated)
        plan = plan_localize(
            source,
            translated=translated,
            bilingual=bool(cfg.get("bilingual", True)),
            glossary=cfg.get("glossary"),
            speakers=bool(cfg.get("speakers", False)),
            work_dir=output_dir,
        )
        ass_path = Path(plan.ass_path)
        record("subtitles", bilingual=plan.bilingual)

        current_video = source_path
        dubbed_audio: Path | None = None
        if bool(cfg.get("dub", False)):
            await _notify(on_step, "dub", 65.0, engine=cfg.get("tts_engine", "edge_tts"))
            dubbed_audio = await _dub(
                translated,
                config=cfg,
                output_dir=output_dir,
            )
            from hevi.dub._mux import mux_audio_into_video, mux_remix_into_video

            muxed = output_dir / "localized_dubbed.mp4"
            if bool(cfg.get("keep_bed", False)):
                await mux_remix_into_video(
                    video=source_path,
                    audio=dubbed_audio,
                    output=muxed,
                    bed=Path(str(cfg["bed_path"])) if cfg.get("bed_path") else None,
                )
            else:
                await mux_audio_into_video(video=source_path, audio=dubbed_audio, output=muxed)
            current_video = muxed
            record("dub", engine=str(cfg.get("tts_engine") or "edge_tts"))

        await _notify(on_step, "burn", 82.0)
        final_video = output_dir / "localized.mp4"
        subtitles = [target_srt, source_srt] if bool(cfg.get("bilingual", True)) else [target_srt]
        await _burn_subtitles(
            current_video,
            subtitles,
            final_video,
            watermark=str(cfg.get("watermark") or ""),
        )
        record("burn", subtitles=len(subtitles))

        manifest_items: list[tuple[Path, str, str, bool, str]] = [
            (final_video, "video", "video/mp4", True, "localized_video"),
            (ass_path, "subtitle", "text/x-ass", False, "styled_subtitles"),
            (source_srt, "subtitle", "application/x-subrip", False, "source_subtitles"),
            (target_srt, "subtitle", "application/x-subrip", False, "translated_subtitles"),
        ]
        if dubbed_audio is not None:
            manifest_items.append((dubbed_audio, "audio", "audio/wav", False, "dubbed_audio"))
        manifest = _manifest(manifest_items)
        report = {
            "status": "succeeded",
            "operation": "video_localization_workflow",
            "pillars": sorted(_enabled_pillars),
            "fingerprint": fingerprint,
            "source_segments": len(source),
            "translated_segments": len(translated),
            "translation_provider": translation_provider,
            "dubbed": dubbed_audio is not None,
            "bilingual": bool(cfg.get("bilingual", True)),
            "decision_trail": trail,
            "artifact_manifest": manifest.model_dump(mode="json"),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        await _notify(on_step, "completed", 100.0)
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
                "output_video_path": str(final_video),
                "ass_path": str(ass_path),
                "source_srt_path": str(source_srt),
                "translated_srt_path": str(target_srt),
                "dubbed_audio_path": str(dubbed_audio) if dubbed_audio else None,
                "segments": len(source),
            },
        }
    except Exception as exc:
        record("failed", error=type(exc).__name__)
        report_path.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "operation": "video_localization_workflow",
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


def compute_fingerprint_for(
    config: Any, input_data: Any, *, operation: str = "video_localization_workflow"
) -> str:
    """Public PII-free fingerprint helper for task idempotency and tests."""

    return _safe_fingerprint(operation, _mapping(config), _mapping(input_data))


async def shorts_generation_workflow(
    config: Any,
    input_data: Any,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Execute AI-Shorts candidate selection and FFmpeg rendering."""

    _enabled_pillars = {"fingerprint", "decision_trail", "report", "cost"}
    cfg = _mapping(config)
    data = _mapping(input_data)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _safe_fingerprint("shorts_generation_workflow", cfg, data)
    report_path = output_dir / "shorts_generation_report.json"
    trail: list[dict[str, Any]] = []
    try:
        source = str(data.get("source_video_path") or data.get("video_path") or "")
        if not Path(source).is_file():
            raise FileNotFoundError(f"source video not found: {source}")
        await _notify(on_step, "select", 20.0)
        renderer = render_clip_batch
        if renderer is None:
            from hevi.openshorts.clip_engine import render_clip_batch as renderer

        result = renderer(
            source,
            output_dir=output_dir,
            target_clips=int(cfg.get("target_clips") or cfg.get("max_clips") or 5),
            config={
                **cfg,
                "transcript_segments": data.get("source_segments")
                or data.get("segments")
                or cfg.get("transcript_segments"),
                "subtitle_path": data.get("subtitle_path") or cfg.get("subtitle_path"),
                "llm_fn": data.get("llm_fn") or cfg.get("llm_fn"),
            },
        )
        if result.get("status") != "completed":
            raise RuntimeError(str(result.get("error") or "clip renderer failed"))
        clips = list(result.get("clips") or [])
        if not clips:
            raise RuntimeError("clip renderer returned no clips")
        trail.append(
            {
                "stage": "render",
                "clips": len(clips),
                "aspect_ratio": str(cfg.get("aspect_ratio") or "9:16"),
            }
        )
        await _notify(on_step, "report", 90.0, clips=len(clips))
        raw_manifest = (result.get("config_json") or {}).get("artifact_manifest") or {"artifacts": []}
        manifest = ArtifactManifest.model_validate(raw_manifest)
        report = {
            "status": "succeeded",
            "operation": "shorts_generation_workflow",
            "pillars": sorted(_enabled_pillars),
            "fingerprint": fingerprint,
            "clips": len(clips),
            "decision_trail": trail,
            "artifact_manifest": manifest.model_dump(mode="json"),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        await _notify(on_step, "completed", 100.0)
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
                "result_video_path": result.get("result_video_path"),
                "clips": clips,
                "total_shots": len(clips),
                "completed_shots": len(clips),
                "quality": result.get("quality"),
                "config_json": result.get("config_json") or {},
            },
        }
    except Exception as exc:
        trail.append({"stage": "failed", "error": type(exc).__name__})
        report_path.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "operation": "shorts_generation_workflow",
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


async def execute_clip_video_task(task: dict[str, Any], _pool: Any) -> dict[str, Any]:
    """TaskService adapter for ``production_source=clip_video``."""

    config = dict(task.get("config_json") or {})
    request = dict(config.get("clip_request") or {})
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task["id"]))
    result = await shorts_generation_workflow(
        request,
        {
            "source_video_path": request.get("video_path") or task.get("topic"),
            "source_segments": request.get("transcript_segments"),
            "subtitle_path": request.get("subtitle_path"),
        },
        output_dir,
    )
    if result.get("status") != "succeeded":
        return {"status": "failed", "error": result.get("error"), "config_json": config}
    findings = result.get("findings") or {}
    return {
        "status": "completed",
        "result_video_path": findings.get("result_video_path"),
        "total_shots": findings.get("total_shots", 0),
        "completed_shots": findings.get("completed_shots", 0),
        "quality": findings.get("quality"),
        "config_json": {
            **config,
            **(findings.get("config_json") or {}),
            "artifact_manifest": {"artifacts": result.get("artifacts") or []},
            "report_path": result.get("report_path"),
            "decision_trail": result.get("decision_trail") or [],
            "fingerprint": result.get("fingerprint"),
        },
    }


async def execute_video_localize_task(task: dict[str, Any], _pool: Any) -> dict[str, Any]:
    """TaskService adapter for ``production_source=localize_video``."""

    config = dict(task.get("config_json") or {})
    request = dict(config.get("localize_request") or {})
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task["id"]))
    result = await video_localization_workflow(
        request,
        {
            "source_video_path": request.get("video_path") or task.get("topic"),
            "source_segments": request.get("transcript_segments"),
            "translated_segments": request.get("translated_segments"),
            "subtitle_path": request.get("subtitle_path"),
        },
        output_dir,
    )
    if result.get("status") != "succeeded":
        return {"status": "failed", "error": result.get("error"), "config_json": config}
    findings = result.get("findings") or {}
    output_path = Path(str(findings.get("output_video_path") or ""))
    if not output_path.is_file():
        return {
            "status": "failed",
            "error": {"code": "ARTIFACT_MISSING", "message": "localization returned no video artifact"},
            "config_json": config,
        }
    from hevi.video.quality_check import quality_report

    measured = await quality_report(output_path, require_audio=False, n_samples=4)
    return {
        "status": "completed",
        "result_video_path": str(output_path),
        "quality": {
            "verdict": "pass" if measured.passed else "fail",
            "passed": measured.passed,
            "violations": list(measured.violations),
            "checks": {
                "duration": measured.stats.duration,
                "width": measured.stats.width,
                "height": measured.stats.height,
                "fps": measured.stats.fps,
                "has_audio": measured.stats.has_audio,
            },
        },
        "config_json": {
            **config,
            "artifact_manifest": {"artifacts": result.get("artifacts") or []},
            "report_path": result.get("report_path"),
            "decision_trail": result.get("decision_trail") or [],
            "fingerprint": result.get("fingerprint"),
        },
    }


__all__ = [
    "compute_fingerprint_for",
    "execute_clip_video_task",
    "execute_video_localize_task",
    "shorts_generation_workflow",
    "video_localization_workflow",
]
