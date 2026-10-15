"""消费 production_order:配方阶段继续跑产品工具,不是停在交接单。"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from hevi.production.artifacts import (
    Artifact,
    ArtifactManifest,
    ArtifactVerificationError,
    verify_local_manifest,
    verify_production_artifact,
)
from hevi.layer4_legacy.zerolines.oprim_impl.specs import ZERO_LINES, resolve_engine
from hevi.studio.kit import explainer_cues_from_text, storygraph_extract, tongjian_l0

TARGETS = ("explainer", "tongjian", "shortdrama")


def _texts_from_order(order: dict[str, Any]) -> list[str]:
    lines = order.get("script_lines") or []
    texts: list[str] = []
    for item in lines:
        if isinstance(item, str) and item.strip():
            texts.append(item.strip())
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("line") or "").strip()
            if text:
                texts.append(text)
    topic = str(order.get("topic") or "").strip()
    if not texts and topic:
        texts = [topic]
    return texts


def _write_job(dest: Path, body: dict[str, Any]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def _write_json_atomic(dest: Path, body: dict[str, Any]) -> Path:
    """Persist runtime evidence without exposing a partial JSON document."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{dest.name}.", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(raw_tmp, dest)
    finally:
        if os.path.exists(raw_tmp):
            os.unlink(raw_tmp)
    return dest


def _persist_hyperframes_evidence(
    output_dir: Path, order: dict[str, Any], result: dict[str, Any]
) -> None:
    manifest = result.get("artifact_manifest") or {}
    artifacts = manifest.get("artifacts") or []
    primary = next(
        (item for item in artifacts if item.get("primary")), artifacts[0] if artifacts else {}
    )
    retry = result.get("retry_evidence") or {}
    operation_id = str(
        retry.get("operation_id")
        or order.get("idempotency_key")
        or order.get("slate_id")
        or "kinetic_promo:render"
    )
    _write_json_atomic(
        output_dir / "provenance.json",
        {
            "schema_version": 1,
            "line_id": "kinetic_promo",
            "logical_job_id": operation_id,
            "input_source": {
                "topic": _slot(order, "topic") or "HEVI",
                "script_lines": order.get("script_lines") or [],
                "source_refs": order.get("source_refs") or [],
            },
            "provider_request": result.get("provider_request") or {},
            "render_job": {
                "operation_id": operation_id,
                "runtime": "hyperframes",
                "workspace": result.get("workspace"),
            },
            "final_hevi_asset": primary,
        },
    )
    _write_json_atomic(output_dir / "retry.json", retry)


async def fulfill_explainer(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    cues = await explainer_cues_from_text({"texts": _texts_from_order(order)})
    job: dict[str, Any] = {
        "target": "explainer",
        "topic": order.get("topic"),
        "cues": cues.get("cues") or [],
        "render_runtime": order.get("render_runtime"),
        "bound_assets": order.get("bound_assets") or [],
        "timeline_id": order.get("timeline_id"),
        "compose_after_qc": True,
        "next": "hevi.explainer.service.ExplainerMasterService.assemble",
    }
    path = _write_job(output_dir / "explainer.dispatch.json", job)
    return {
        "status": "dispatched",
        "target": "explainer",
        "dispatch_path": str(path),
        "cue_count": len(job.get("cues") or []),
        "next": job["next"],
    }


async def fulfill_tongjian(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    raw = str(order.get("topic") or order.get("source_text") or "")
    ir = await tongjian_l0(
        {
            "raw_text": raw,
            "source_name": order.get("source_name") or "studio",
        }
    )
    job = {
        "target": "tongjian",
        "topic": order.get("topic"),
        "chapter_ir": ir.get("chapter_ir") or {},
        "mix": order.get("mix"),
        "compose_after_qc": True,
        "defer_avatar": True,
        "next": "hevi.tongjian.script.build_script",
    }
    path = _write_job(output_dir / "tongjian.dispatch.json", job)
    return {
        "status": "dispatched" if ir.get("status") != "failed" else "failed",
        "target": "tongjian",
        "dispatch_path": str(path),
        "quote_count": ir.get("quote_count") or 0,
        "reason": ir.get("reason") or "",
        "next": job["next"],
    }


async def fulfill_shortdrama(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    raw = str(order.get("manuscript") or order.get("topic") or "")
    extracted = await storygraph_extract(
        {"raw_text": raw, "source_name": order.get("source_name") or "studio"}
    )
    job = {
        "target": "shortdrama",
        "story_graph": extracted.get("story_graph") or {},
        "bound_assets": order.get("bound_assets") or [],
        "compose_after_qc": True,
        "next": "hevi.season_planner.planner.build_season_plan",
    }
    path = _write_job(output_dir / "shortdrama.dispatch.json", job)
    return {
        "status": "dispatched" if extracted.get("status") != "failed" else "failed",
        "target": "shortdrama",
        "dispatch_path": str(path),
        "characters": extracted.get("characters") or 0,
        "events": extracted.get("events") or 0,
        "reason": extracted.get("reason") or "",
        "next": job["next"],
    }


_ADAPTERS = {
    "explainer": fulfill_explainer,
    "tongjian": fulfill_tongjian,
    "shortdrama": fulfill_shortdrama,
}


def _slot(order: dict[str, Any], key: str, default: Any = None) -> Any:
    """Read a value from the normalized order or its original input slots."""

    value = order.get(key)
    if value is not None and value != "":
        return value
    slots = order.get("slots")
    return slots.get(key, default) if isinstance(slots, dict) else default


def _blocked(reason: str, *, target: str, line_id: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "target": target,
        "line_id": line_id,
        "reason": reason,
        "quality": {"verdict": "blocked", "passed": False, "violations": [reason]},
    }


async def _verified_video_manifest(
    paths: list[tuple[Path, bool, str]], *, require_audio: bool = False
) -> tuple[ArtifactManifest, dict[str, Any]]:
    """Build a local manifest and apply the final media delivery gate."""

    manifest = ArtifactManifest(
        artifacts=[
            Artifact.from_path(
                path,
                kind="video",
                media_type="video/mp4",
                primary=primary,
                logical_role=role,
            )
            for path, primary, role in paths
        ]
    )
    verified = verify_local_manifest(manifest)
    quality_reports: list[dict[str, Any]] = []
    if require_audio:
        from hevi.production.delivery_gate import probe_video

        for artifact in verified.artifacts:
            if artifact.kind != "video":
                continue
            probe = probe_video(artifact.path)
            if not probe.has_audio:
                raise ArtifactVerificationError(f"video-audio:{artifact.path}")
    # Integrity (existence + SHA-256) is necessary but is not a media quality
    # verdict.  Measure every video with the same ffprobe/ffmpeg gate used by
    # the canonical production path before returning PASS.
    from hevi.video.quality_check import quality_report

    violations: list[str] = []
    for index, artifact in enumerate(verified.artifacts):
        if artifact.kind != "video":
            continue
        report = await quality_report(Path(artifact.path), require_audio=require_audio, n_samples=4)
        quality_reports.append(
            {
                "index": index,
                "duration": report.stats.duration,
                "width": report.stats.width,
                "height": report.stats.height,
                "fps": report.stats.fps,
                "has_audio": report.stats.has_audio,
                "passed": report.passed,
            }
        )
        violations.extend(f"artifact[{index}]: {item}" for item in report.violations)
    passed = bool(quality_reports) and not violations
    return verified, {
        "verdict": "pass" if passed else "fail",
        "passed": passed,
        "violations": violations,
        "checks": {"media_quality_reports": quality_reports},
    }


def _wants_talkcraft_host(order: dict[str, Any]) -> bool:
    """Opt-in: ``renderer="talkcraft"`` on the order or HEVI_AVATAR_LINE_RENDERER=talkcraft."""
    chosen = _slot(order, "renderer") or os.getenv("HEVI_AVATAR_LINE_RENDERER") or ""
    return str(chosen).strip().lower() == "talkcraft"


def _line_engine(order: dict[str, Any]) -> str:
    """``engine`` slot on the order > ``HEVI_LINE_ENGINE`` env > ``legacy``.

    ``zero`` = CPU-only, no-paid-API engine (hevi.zerolines) for the 11 lines in
    ``ZERO_LINES``; documentary_montage / localization_dub always resolve to
    legacy.  An unknown engine name raises ValueError (-> blocked, never guessed).
    """
    return resolve_engine(
        line_id=str(order.get("line_id") or ""),
        slot_engine=_slot(order, "engine"),
        env_engine=os.getenv("HEVI_LINE_ENGINE"),
    )


def _zero_input(order: dict[str, Any], line_id: str) -> dict[str, Any]:
    """Map a Studio order onto the zero-line request (inputs only, nothing invented)."""
    raw_lines = _slot(order, "script_lines") or order.get("script_lines") or []
    texts = _texts_from_order({"script_lines": raw_lines})
    return {
        "line_id": line_id,
        "texts": texts,
        "queries": _slot(order, "queries") or _slot(order, "broll_queries") or [],
        "topic": str(_slot(order, "topic") or ""),
        "title": str(_slot(order, "title") or ""),
        "lang": str(_slot(order, "language") or "zh"),
        "media_path": str(_slot(order, "media_path") or _slot(order, "reference_path") or _slot(order, "source") or ""),
        "offsets": _slot(order, "offsets") or [],
        "labels": _slot(order, "labels") or [],
        "extras": _slot(order, "zero_extras") or {},
    }


async def _render_zero_line(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Zero-cost engine: Piper TTS + Pexels free stock / procedural 2D + ffmpeg.

    The engine's own measured QA gate and then the canonical media quality gate
    must both pass; anything else is ``failed``/``blocked`` (never completed).
    """
    from hevi.layer4_legacy.zerolines import zero_line_workflow

    line_id = str(order.get("line_id") or "")
    target = str(order.get("target") or line_id)
    out = await asyncio.to_thread(zero_line_workflow, {}, _zero_input(order, line_id), Path(output_dir))
    base = {"target": target, "line_id": line_id, "engine": "zero", "zero_record": out.get("record_path")}
    if out["status"] == "blocked":
        return {**_blocked(str(out["reason"]), target=target, line_id=line_id), **base}
    if out["status"] != "succeeded":
        return {
            **base,
            "status": "failed",
            "reason": str(out.get("reason") or "zero engine failed"),
            "quality": {"verdict": "fail", "passed": False, "violations": [str(out.get("reason"))],
                        "checks": {"zero_line_qa": out.get("qa") or []}},
        }
    finals = [Path(p) for p in out["finals"]]
    manifest, quality = await _verified_video_manifest(
        [(p, i == 0, "video" if i == 0 else f"video_{i + 1}") for i, p in enumerate(finals)],
        require_audio=True,
    )
    quality.setdefault("checks", {})["zero_line_qa"] = out.get("qa") or []
    if not quality.get("passed"):
        return {**base, "status": "failed", "reason": "CANONICAL_QUALITY_GATE_FAILED", "quality": quality}
    return {
        **base,
        "status": "completed",
        "result_video_path": str(finals[0]),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": "zero",
        "provenance": {
            "line_id": line_id,
            "engine": "zero",
            "cost_usd": 0.0,
            "gpu": False,
            "paid_api": False,
            "sources": out.get("provenance") or [],
            "record": out.get("record_path"),
        },
        "provider_trace": [{"resolved_provider": "zero", "fallback_used": False}],
    }


def _engine_switch(line_id: str, legacy: Any) -> Any:
    """Route a zero-capable line by engine; the original renderer stays the default."""

    async def render(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        if line_id in {"talking_head", "avatar_spokesperson"} and _wants_talkcraft_host(order):
            return await legacy(order, output_dir)  # explicit photoreal talkcraft host wins
        if _line_engine(order) == "zero":
            return await _render_zero_line(order, output_dir)
        return await legacy(order, output_dir)

    render.__name__ = f"{getattr(legacy, '__name__', 'render')}_or_zero"
    render.legacy = legacy  # type: ignore[attr-defined]
    return render


async def _render_talkcraft_host_line(
    order: dict[str, Any], output_dir: Path, *, line_id: str, topic: str, texts: list[str], image: str | None
) -> dict[str, Any]:
    """talking_head / avatar_spokesperson on the talkcraft presenter (host) layout.

    CPU only (Piper + Wav2Lip ONNX); a missing portrait falls back to the bundled
    AI-generated presenter.  Any failed measured gate raises -> fail-closed.
    """
    from hevi.talkcraft.host_lines import render_host_line

    out = await render_host_line(
        line_id, texts=texts, topic=topic or line_id, output_dir=output_dir, image=image,
        lang=str(_slot(order, "language") or "zh"),
    )
    manifest, quality = await _verified_video_manifest(
        [
            (Path(out["portrait_path"]), True, "portrait_video"),
            (Path(out["landscape_path"]), False, "landscape_video"),
        ],
        require_audio=True,
    )
    return {
        "status": "completed",
        "target": str(order.get("target") or "explainer"),
        "line_id": line_id,
        "result_video_path": str(out["portrait_path"]),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": "talkcraft_host",
        "talkcraft_record": str(Path(output_dir) / "record.json"),
    }


async def _render_explainer_line(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Render explainer-compatible Studio lines into portrait + landscape MP4."""

    from hevi.explainer.assembly import assemble_explainer_cues
    from hevi.explainer.contracts import ExplainerCue

    line_id = str(order.get("line_id") or "")
    topic = str(
        _slot(order, "topic") or order.get("source_text") or order.get("manuscript") or ""
    ).strip()
    texts = _texts_from_order(order)
    if not texts:
        return _blocked(
            "需要脚本或主题文本", target=str(order.get("target") or "explainer"), line_id=line_id
        )

    avatar_lines = {"avatar_spokesperson", "talking_head"}
    presenter_image = _slot(order, "image_path") or _slot(order, "presenter_image_path")
    presenter_video = _slot(order, "presenter_video_path")
    if line_id in avatar_lines and _wants_talkcraft_host(order):
        return await _render_talkcraft_host_line(
            order, output_dir, line_id=line_id, topic=topic, texts=texts,
            image=str(presenter_image) if presenter_image else None,
        )
    if line_id in avatar_lines and not (presenter_image or presenter_video):
        return _blocked(
            "数字人口播需要 image_path 或 presenter_video_path",
            target=str(order.get("target") or "explainer"),
            line_id=line_id,
        )

    visual_type: Literal["heygen_avatar", "voiceover"] = (
        "heygen_avatar" if line_id in avatar_lines else "voiceover"
    )
    cues = [
        ExplainerCue(
            text=text,
            visual_type=visual_type,
            time_estimate_s=float(item.get("time_estimate_s") or item.get("duration_s") or 5.0)
            if isinstance(item, dict)
            else 5.0,
            visual_config={},
        )
        for item, text in (
            (item, str(item.get("text") or item.get("line") or "").strip())
            if isinstance(item, dict)
            else (item, str(item).strip())
            for item in (order.get("script_lines") or texts)
        )
        if text
    ]
    if not cues:
        return _blocked("脚本没有可渲染文本", target="explainer", line_id=line_id)

    result = await assemble_explainer_cues(
        topic or line_id or "HEVI",
        cues,
        output_dir,
        voice=str(_slot(order, "voice") or "zh-CN-YunxiNeural"),
        aspect_ratio=str(_slot(order, "aspect_ratio") or "9:16"),
        presenter_image_url=str(presenter_image) if presenter_image else None,
        presenter_reference_video=str(presenter_video) if presenter_video else None,
        presenter_provider="remotion",
        tts_provider=(
            str(_slot(order, "tts_engine") or "").strip()
            or os.environ.get("HEVI_EXPLAINER_TTS_PROVIDER", "").strip()
            or os.environ.get("HEVI_TTS_FORMAL_PROVIDER", "").strip()
            or "lux_tts"
        ),
        source_text=str(order.get("source_text") or ""),
        reference_url=str(_slot(order, "reference_url") or ""),
    )
    manifest, quality = await _verified_video_manifest(
        [
            (result.portrait_path, True, "portrait_video"),
            (result.landscape_path, False, "landscape_video"),
        ],
        require_audio=True,
    )
    return {
        "status": "completed",
        "target": str(order.get("target") or "explainer"),
        "line_id": line_id,
        "result_video_path": str(result.portrait_path),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": getattr(result, "render_runtime", "remotion"),
    }


async def _render_localization_line(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    from hevi.production.media_workflows import video_localization_workflow

    source = _slot(order, "media_path") or _slot(order, "video_path")
    if not source:
        return _blocked(
            "译制需要 media_path/video_path",
            target="localize_video",
            line_id=str(order.get("line_id") or ""),
        )
    data = {
        "source_video_path": str(source),
        "source_segments": _slot(order, "segments") or _slot(order, "transcript_segments"),
        "translated_segments": _slot(order, "translated_segments"),
        "subtitle_path": _slot(order, "subtitle_path"),
    }
    config = {
        "target_language": _slot(order, "lang") or _slot(order, "target_language") or "zh-CN",
        "source_language": _slot(order, "source_language") or "auto",
        "translation_provider": _slot(order, "translation_provider") or "llm_translate",
        "bilingual": bool(_slot(order, "bilingual", True)),
        "dub": bool(_slot(order, "dub", False)),
        "keep_bed": bool(_slot(order, "keep_bed", False)),
        "tts_engine": _slot(order, "tts_engine") or "edge_tts",
        "voice": _slot(order, "voice") or "",
        "reference_audio": _slot(order, "reference_audio") or "",
        "glossary": _slot(order, "glossary") or {},
        "watermark": _slot(order, "watermark") or "",
    }
    result = await video_localization_workflow(config, data, output_dir)
    if result.get("status") != "succeeded":
        return {**result, "target": "localize_video", "line_id": str(order.get("line_id") or "")}
    manifest = verify_local_manifest(
        ArtifactManifest.model_validate({"artifacts": result.get("artifacts") or []})
    )
    primary = manifest.primary_path()
    _, quality = await _verified_video_manifest(
        [(primary, True, "localized_video")] if primary is not None else [],
        require_audio=False,
    )
    if not quality["passed"]:
        return {
            "status": "failed",
            "target": "localize_video",
            "line_id": str(order.get("line_id") or ""),
            "error": {"code": "QUALITY_GATE_FAILED", "violations": quality["violations"]},
            "quality": quality,
        }
    return {
        "status": "completed",
        "target": "localize_video",
        "line_id": str(order.get("line_id") or ""),
        "result_video_path": str(primary or ""),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": "ffmpeg",
    }


async def _render_clip_line(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    from hevi.production.media_workflows import shorts_generation_workflow

    source = _slot(order, "media_path") or _slot(order, "video_path") or _slot(order, "source")
    if not source:
        return _blocked(
            "拆条需要 media_path/video_path/source",
            target="clip_video",
            line_id=str(order.get("line_id") or ""),
        )
    result = await shorts_generation_workflow(
        {
            "target_clips": int(_slot(order, "max_clips", 5)),
            "max_clips": int(_slot(order, "max_clips", 5)),
            "aspect_ratio": _slot(order, "aspect_ratio") or "9:16",
            "strategy": _slot(order, "strategy") or "viral",
            "subtitle_path": _slot(order, "subtitle_path"),
        },
        {
            "source_video_path": str(source),
            "source_segments": _slot(order, "transcript_segments") or _slot(order, "segments"),
            "subtitle_path": _slot(order, "subtitle_path"),
        },
        output_dir,
    )
    if result.get("status") != "succeeded":
        return {**result, "target": "clip_video", "line_id": str(order.get("line_id") or "")}
    manifest = verify_local_manifest(
        ArtifactManifest.model_validate({"artifacts": result.get("artifacts") or []})
    )
    primary = manifest.primary_path()
    _, quality = await _verified_video_manifest(
        [(primary, True, "short_clip")] if primary is not None else [],
        require_audio=False,
    )
    if not quality["passed"]:
        return {
            "status": "failed",
            "target": "clip_video",
            "line_id": str(order.get("line_id") or ""),
            "error": {"code": "QUALITY_GATE_FAILED", "violations": quality["violations"]},
            "quality": quality,
        }
    return {
        "status": "completed",
        "target": "clip_video",
        "line_id": str(order.get("line_id") or ""),
        "result_video_path": str(primary or ""),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": "ffmpeg",
    }


async def _render_manim_line(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    from hevi.studio.kit import explainer_manim

    path = output_dir / "character_animation.mp4"
    result = await explainer_manim(
        {
            "prompt": _slot(order, "topic") or "character beats",
            "output_path": str(path),
            "duration_s": float(_slot(order, "duration_s", 6.0)),
        }
    )
    if result.get("status") != "ok":
        return _blocked(
            str(result.get("reason") or "Manim renderer unavailable"),
            target="character_animation",
            line_id="character_animation",
        )
    manifest, quality = await _verified_video_manifest(
        [(Path(str(result["asset_path"])), True, "character_animation")]
    )
    return {
        "status": "completed",
        "target": "character_animation",
        "line_id": "character_animation",
        "result_video_path": str(manifest.primary_path() or ""),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": "manim",
    }


async def _render_hyperframes_line(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    from hevi.providers.hyperframes.provider import hyperframes_generate

    path = output_dir / "kinetic_promo.mp4"
    provider_request = {
        "topic": _slot(order, "topic") or "HEVI",
        "script_lines": order.get("script_lines") or [],
        "edit_plan": order.get("edit_plan") or {},
        "output_path": str(path),
    }
    produced = await hyperframes_generate(
        prompt=provider_request,
        output_path=path,
    )
    manifest, quality = await _verified_video_manifest([(Path(produced), True, "kinetic_promo")])
    return {
        "status": "completed",
        "target": "kinetic_promo",
        "line_id": "kinetic_promo",
        "result_video_path": str(manifest.primary_path() or ""),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": "hyperframes",
        "provider_request": provider_request,
        "workspace": str(path.parent / ".hyperframes"),
    }


async def _render_longvideo_line(order: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo

    topic = str(
        _slot(order, "topic") or order.get("manuscript") or order.get("source_text") or ""
    ).strip()
    if not topic:
        return _blocked(
            "长视频生产需要 topic/manuscript/source_text",
            target="longvideo",
            line_id=str(order.get("line_id") or ""),
        )
    result = await orchestrate_longvideo(
        topic=topic,
        duration_archetype=str(_slot(order, "duration_archetype") or "1-5min"),
        video_provider=str(order.get("video_provider") or "auto"),
        audio_provider=str(_slot(order, "audio_provider") or "edge_tts"),
        style="cinematic",
        aspect_ratio=str(_slot(order, "aspect_ratio") or "9:16"),
        output_dir=output_dir,
        local_fallback_video=bool(_slot(order, "local_fallback_video", False)),
    )
    path = Path(str(result.get("url") or ""))
    if not path.is_file():
        return _blocked(
            "视频 Provider 未返回可验证的本地成片",
            target="longvideo",
            line_id=str(order.get("line_id") or ""),
        )
    manifest, quality = await _verified_video_manifest([(path, True, "final_video")])
    return {
        "status": "completed",
        "target": "longvideo",
        "line_id": str(order.get("line_id") or ""),
        "result_video_path": str(path),
        "artifact_manifest": manifest.model_dump(mode="json"),
        "quality": quality,
        "render_runtime": "longvideo",
    }


_RENDERERS = {
    "localization_dub": _render_localization_line,
    "shorts_clip": _render_clip_line,
    "podcast_repurpose": _render_clip_line,
    "character_animation": _render_manim_line,
    "kinetic_promo": _render_hyperframes_line,
    "cinematic": _render_longvideo_line,
    "director_pipeline": _render_longvideo_line,
    "history_scene": _render_longvideo_line,
    "explainer": _render_explainer_line,
    "documentary_montage": _render_explainer_line,
    "reference_adapt": _render_explainer_line,
    "talking_head": _render_explainer_line,
    "avatar_spokesperson": _render_explainer_line,
}

for _zero_line in ZERO_LINES:
    _RENDERERS[_zero_line] = _engine_switch(_zero_line, _RENDERERS[_zero_line])


def _enforce_final_contract(result: dict[str, Any], *, line_id: str) -> dict[str, Any]:
    """Convert renderer claims into the canonical fail-closed result."""
    if result.get("status") != "completed":
        return result
    path = result.get("result_video_path")
    media = (
        verify_production_artifact(
            path,
            require_audio=line_id
            not in {
                "shorts_clip",
                "podcast_repurpose",
                "localization_dub",
                "character_animation",
                "kinetic_promo",
            },
        )
        if path
        else {"verified": False, "passed": False, "errors": ["result_video_path missing"]}
    )
    quality = result.get("quality") or result.get("quality_report") or {}
    if media["verified"] and quality.get("passed") is True:
        manifest = dict(result.get("artifact_manifest") or {})
        manifest["verified"] = True
        manifest["truth_gate"] = media
        result["artifact_manifest"] = manifest
        result["quality_report"] = quality
        result.setdefault(
            "provenance",
            {
                "line_id": line_id,
                "artifact_sha256": media.get("sha256"),
                "source": "canonical_renderer",
            },
        )
        result["provider_trace"] = result.get("provider_trace") or [
            {
                "resolved_provider": result.get("render_runtime", "canonical_renderer"),
                "fallback_used": False,
            }
        ]
        return result
    result["status"] = (
        "blocked"
        if any(
            item in " ".join(media.get("errors", []))
            for item in ("ffprobe", "stream", "path", "duration")
        )
        else "failed"
    )
    result["reason"] = "FINAL_ARTIFACT_TRUTH_GATE_FAILED"
    result["quality"] = {
        **quality,
        "passed": False,
        "violations": list(quality.get("violations", [])) + media.get("errors", []),
    }
    result["artifact_verification"] = media
    return result


async def fulfill_order(
    order: dict[str, Any],
    *,
    execute: bool = False,
    output_dir: Path | str | None = None,
    adapters: dict[str, Any] | None = None,
    render: bool = False,
) -> dict[str, Any]:
    """签发或执行工单。

    ``render=False`` 保留旧的审查/签发语义；``render=True`` 才允许进入
    真实媒体执行器，并且必须返回经过本地文件与媒体探测的产物清单。
    """
    target = str(order.get("target") or "none")
    if target == "none" and not render:
        return {"status": "planned", "target": target}
    if not execute:
        return {"status": "issued", "target": target, "order": order}
    dest = Path(output_dir or f"output/studio/{order.get('slate_id') or 'order'}")
    if render:
        line_id = str(order.get("line_id") or "")
        renderer = _RENDERERS.get(line_id)
        if renderer is None:
            return _blocked(
                f"产线 {line_id or target} 没有真实媒体执行器",
                target=target,
                line_id=line_id,
            )
        try:
            if line_id in {
                "character_animation",
                "kinetic_promo",
                "documentary_montage",
                "podcast_repurpose",
                "shorts_clip",
                "localization_dub",
                "explainer",
                "reference_adapt",
                "history_scene",
                "cinematic",
                "director_pipeline",
                "talking_head",
                "avatar_spokesperson",
            }:
                from hevi.resilience import RetryPolicy, with_retry_evidence
                from hevi.resilience.errors import RetryableError

                async def render_attempt(attempt: int) -> dict[str, Any]:
                    if (
                        attempt == 1
                        and os.getenv("HEVI_PRODUCTION_FAULT_INJECTION") == "transient_once"
                    ):
                        raise RetryableError("controlled transient render transport failure")
                    return await renderer(order, dest)

                result, retry_evidence = await with_retry_evidence(
                    render_attempt,
                    operation_id=f"{line_id}:render",
                    idempotency_key=str(
                        order.get("idempotency_key") or order.get("slate_id") or line_id
                    ),
                    policy=RetryPolicy(
                        max_attempts=3, base_delay_s=0.1, max_delay_s=1.0, jitter=False
                    ),
                )
                result["retry_evidence"] = retry_evidence.to_dict()
                if line_id == "kinetic_promo" and result.get("status") == "completed":
                    _persist_hyperframes_evidence(dest, order, result)
                return _enforce_final_contract(result, line_id=line_id)
            return _enforce_final_contract(await renderer(order, dest), line_id=line_id)
        except (ArtifactVerificationError, FileNotFoundError, ValueError) as exc:
            return _blocked(str(exc), target=target, line_id=line_id)
        except Exception as exc:
            return {
                "status": "failed",
                "target": target,
                "line_id": line_id,
                "reason": str(exc),
            }
    table = adapters or _ADAPTERS
    fn = table.get(target)
    if fn is None:
        return {"status": "failed", "target": target, "reason": f"no adapter: {target}"}
    return await fn(order, dest)
