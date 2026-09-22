"""Fail-closed CPU production strategy for approved low-cost recipes.

This module is deliberately a strategy, not a second production authority.  The
Studio ``produce`` entrypoint calls it only when ``production_mode=low_cost`` is
explicit.  It never calls a video-generation provider or a local GPU renderer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.production.artifacts import Artifact, ArtifactManifest, verify_production_artifact


class LowCostBlocked(RuntimeError):
    """A required real production dependency is unavailable."""


@dataclass(frozen=True)
class ProductionPolicy:
    mode: str = "production"
    local_gpu_required: bool = True
    zero_human_after_start: bool = True
    final_output: str = "real_mp4"


LOW_COST_POLICY = ProductionPolicy(mode="low_cost", local_gpu_required=False)
GPU_POLICY = ProductionPolicy(mode="gpu", local_gpu_required=True)
AUTO_POLICY = ProductionPolicy(mode="auto", local_gpu_required=False)


def policy_for(mode: str | None) -> ProductionPolicy:
    value = str(mode or "low_cost").strip().lower()
    if value == "low_cost":
        return LOW_COST_POLICY
    if value == "gpu":
        return GPU_POLICY
    if value == "auto":
        return AUTO_POLICY
    if value == "production":  # backwards-compatible name for standard renderer
        return ProductionPolicy()
    raise ValueError(f"unknown production_mode: {value}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False, timeout=60,
    )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise LowCostBlocked(f"audio duration unavailable: {path}") from exc


class VisualAssetResolver:
    """Resolve only supplied/approved local media for the first low-cost slice."""

    def resolve(self, slots: dict[str, Any], output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
        raw = slots.get("asset_paths") or slots.get("visual_assets") or []
        if isinstance(raw, (str, Path)):
            raw = [raw]
        if slots.get("cover_path") or slots.get("book_cover_path"):
            raw = [slots.get("cover_path") or slots.get("book_cover_path"), *list(raw)]
        assets: list[dict[str, Any]] = []
        seen: set[str] = set()
        cache_hits = 0
        for index, value in enumerate(raw):
            source = Path(str(value)).expanduser()
            if not source.is_file() or source.stat().st_size <= 0:
                raise LowCostBlocked(f"approved visual asset missing: {source}")
            resolved = source.resolve()
            key = _sha256(resolved)
            if key in seen:
                cache_hits += 1
                continue
            seen.add(key)
            assets.append({
                "path": str(resolved),
                "source": str(resolved),
                "license": str(slots.get("asset_license") or "caller-approved-local-asset"),
                "provider": "reusable_local_asset",
                "sha256": key,
                "cache_key": f"local:{key}",
                "index": index,
            })
        if not assets:
            raise LowCostBlocked("LOW_COST requires at least one approved real visual asset")
        return assets, {"hits": cache_hits, "misses": 0}


def _script(slots: dict[str, Any]) -> str:
    value = slots.get("full_script") or slots.get("script") or slots.get("source_text")
    if isinstance(value, list):
        value = "\n".join(str(item.get("text") if isinstance(item, dict) else item) for item in value)
    text = str(value or "").strip()
    if not text:
        raise LowCostBlocked("LOW_COST requires script/source_text; no silent narration fallback")
    return text


def _subtitle_text(text: str, duration: float) -> str:
    parts = [part.strip() for part in text.replace("\n", " ").split("。") if part.strip()]
    if not parts:
        parts = [text]
    total = max(duration, 0.1)
    lines: list[str] = []
    cursor = 0.0
    for index, part in enumerate(parts):
        end = total if index == len(parts) - 1 else cursor + total * len(part) / max(len(text), 1)
        def stamp(value: float) -> str:
            ms = int(max(0.0, value) * 1000)
            return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"
        lines.extend([str(index + 1), f"{stamp(cursor)} --> {stamp(end)}", part, ""])
        cursor = end
    return "\n".join(lines)


async def _voice(text: str, output_dir: Path, slots: dict[str, Any]) -> tuple[Path, str]:
    provider = str(slots.get("voice_provider") or slots.get("audio_provider") or "edge_tts").strip()
    if provider not in {"edge_tts", "edge-tts"}:
        raise LowCostBlocked(f"declared low-cost voice provider unavailable: {provider}")
    from hevi.providers.registry import ProviderRegistry

    output = output_dir / "narration.mp3"
    line = SimpleNamespace(text=text, emotion=slots.get("emotion"), voice=slots.get("voice"))
    try:
        try:
            tts = ProviderRegistry.get().generic("audio", provider)
        except Exception as exc:
            # App startup normally registers this provider.  A direct Studio
            # invocation may happen before startup registration; use the same
            # canonical implementation, never an alternate/silent provider.
            if "not registered" not in str(exc).lower():
                raise
            from hevi.audio.edge_tts_custom import edge_tts_synthesize_smart

            tts = edge_tts_synthesize_smart
        await tts(
            config={"language": slots.get("language") or "zh-CN"},
            script=[line], output_path=output,
            language=str(slots.get("language") or "zh-CN"),
            voice=slots.get("voice"), emotion=slots.get("emotion"),
        )
    except Exception as exc:
        raise LowCostBlocked(f"voice provider failed: {type(exc).__name__}: {exc}") from exc
    if not output.is_file() or output.stat().st_size <= 100:
        raise LowCostBlocked("voice provider returned no real audio")
    return output, provider


def _render_cpu(assets: list[dict[str, Any]], audio: Path, subtitles: Path, output: Path, duration: float, slots: dict[str, Any]) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise LowCostBlocked("ffmpeg and ffprobe are required for LOW_COST CPU render")
    width, height = (720, 1280) if str(slots.get("aspect_ratio") or "16:9") == "9:16" else (1280, 720)
    scene_duration = max(duration / len(assets), 0.5)
    args: list[str] = ["ffmpeg", "-y"]
    for asset in assets:
        args += ["-loop", "1", "-t", f"{scene_duration:.3f}", "-i", asset["path"]]
    args += ["-i", str(audio)]
    filters: list[str] = []
    labels: list[str] = []
    frames = max(1, int(scene_duration * 24))
    for index in range(len(assets)):
        label = f"v{index}"
        filters.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase," 
            f"crop={width}:{height},zoompan=z='min(zoom+0.0007,1.08)':d={frames}:s={width}x{height}:fps=24,setsar=1[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append("".join(labels) + f"concat=n={len(assets)}:v=1:a=0[v]")
    subtitle_path = str(subtitles).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    filters.append(f"[v]subtitles='{subtitle_path}':force_style='FontSize=22,Outline=2,Alignment=2'[vs]")
    args += ["-filter_complex", ";".join(filters), "-map", "[vs]", "-map", f"{len(assets)}:a", "-t", f"{duration:.3f}", "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(output)]
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=max(300, int(duration * 30)))
    if result.returncode != 0 or not output.is_file():
        raise LowCostBlocked(f"CPU ffmpeg render failed: {result.stderr[-800:]}")


def _write_storyboard(assets: list[dict[str, Any]], duration: float, output: Path) -> None:
    scene_duration = max(duration / len(assets), 0.5)
    scenes = []
    for index, asset in enumerate(assets):
        start = round(index * scene_duration, 3)
        end = round(duration if index == len(assets) - 1 else (index + 1) * scene_duration, 3)
        scenes.append({
            "scene": index + 1,
            "asset": asset["path"],
            "start": start,
            "end": end,
            "motion": "ken_burns_zoom",
            "transition": "cut" if index == 0 else "crossfade",
            "subtitle_window": [start, end],
        })
    output.write_text(
        json.dumps({"duration": duration, "scenes": scenes}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def execute_low_cost(*, line_id: str, slots: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    policy = policy_for("low_cost")
    output_dir.mkdir(parents=True, exist_ok=True)
    text = _script(slots)
    assets, cache = VisualAssetResolver().resolve(slots, output_dir)
    audio, voice_provider = await _voice(text, output_dir, slots)
    duration = _duration(audio)
    storyboard_path = output_dir / "storyboard.json"
    _write_storyboard(assets, duration, storyboard_path)
    timeline_path = output_dir / "audio_timeline.json"
    timeline_path.write_text(
        json.dumps({"audio": str(audio), "duration": duration, "source": "measured_ffprobe"}, indent=2),
        encoding="utf-8",
    )
    subtitle_path = output_dir / "subtitles.srt"
    subtitle_path.write_text(_subtitle_text(text, duration), encoding="utf-8")
    final = output_dir / "final.mp4"
    _render_cpu(assets, audio, subtitle_path, final, duration, slots)
    media = verify_production_artifact(final, require_audio=True)
    from hevi.video.quality_check import quality_report

    try:
        quality = await quality_report(final, require_audio=True, subtitle_path=subtitle_path, n_samples=4)
    except Exception as exc:
        raise LowCostBlocked(f"quality gate could not run: {type(exc).__name__}: {exc}") from exc
    passed = bool(media.get("verified")) and quality.passed
    ledger = {
        "llm_cost": float(slots.get("llm_cost") or 0),
        "tts_cost": float(slots.get("tts_cost") or 0),
        "image_cost": float(slots.get("image_cost") or 0),
        "video_generation_cost": 0.0,
        "other_api_cost": float(slots.get("other_api_cost") or 0),
        "estimated_total_cost": sum(float(slots.get(k) or 0) for k in ("llm_cost", "tts_cost", "image_cost", "other_api_cost")),
        "low_cost_estimate": sum(float(slots.get(k) or 0) for k in ("llm_cost", "tts_cost", "image_cost", "other_api_cost")),
        "gpu_estimate": float(slots.get("gpu_estimate") or 0),
        "cache_hits": cache["hits"], "cache_misses": cache["misses"],
        "reused_assets": len(assets), "new_generated_assets": 0,
        "local_gpu_used": False, "video_generation_api_calls": 0,
    }
    provenance = {
        "production_mode": policy.mode, "line_id": line_id,
        "local_gpu_required": False, "voice_provider": voice_provider,
        "assets": assets, "storyboard_path": str(storyboard_path),
        "audio_timeline_path": str(timeline_path), "subtitle_path": str(subtitle_path),
        "artifact_sha256": media.get("sha256"), "cost_ledger": ledger,
    }
    manifest = ArtifactManifest(artifacts=[Artifact.from_path(final, kind="video", media_type="video/mp4", primary=True, logical_role="final_video")])
    return {
        "status": "completed" if passed else "blocked",
        "line_id": line_id, "result_video_path": str(final) if passed else None,
        "artifact_manifest": manifest.model_dump(mode="json") if passed else {},
        "quality": {**quality.__dict__, "stats": quality.stats.__dict__},
        "quality_report": {**quality.__dict__, "stats": quality.stats.__dict__},
        "provenance": provenance, "provider_trace": [{"provider": voice_provider, "fallback_used": False}],
        "cost_ledger": ledger, "policy": policy.__dict__,
        "stages": {"script": True, "storyboard": True, "visual_assets": True, "voice": True, "real_audio_timeline": True, "subtitles": True, "cpu_render": passed, "audio_mix": passed, "qa": passed},
        "reason": "LOW_COST_FINAL_GATE_FAILED" if not passed else "",
    }


__all__ = ["AUTO_POLICY", "GPU_POLICY", "LOW_COST_POLICY", "ProductionPolicy", "VisualAssetResolver", "execute_low_cost", "policy_for"]
