"""Local AI-Shorts execution engine.

The OpenShorts planning modules intentionally stay provider independent.  This
module is the executable boundary: it accepts a local film, obtains a real
transcript (or an explicitly supplied one), scores candidate windows, renders
each selected window with FFmpeg, and emits an artifact manifest.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hevi.ingest.video_transcript import (
    TranscriptError,
    TranscriptSegment,
    fetch_transcript,
    read_subtitle_file,
)
from hevi.openshorts.virality import Highlight, score_highlights
from hevi.production.artifacts import Artifact, ArtifactManifest

_ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (9, 16),
    "16:9": (16, 9),
    "1:1": (1, 1),
    "4:5": (4, 5),
    "4:3": (4, 3),
    "3:4": (3, 4),
}


def _as_segments(raw: Iterable[Any]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for item in raw:
        if isinstance(item, TranscriptSegment):
            segments.append(item)
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
            segments.append(
                TranscriptSegment(
                    start=start,
                    end=end,
                    text=text,
                    speaker=str(item.get("speaker") or ""),
                )
            )
    return sorted(segments, key=lambda item: item.start)


def load_transcript(config: dict[str, Any], video_path: Path) -> list[TranscriptSegment]:
    """Resolve transcript input without silently manufacturing timestamps."""

    supplied = config.get("transcript_segments") or config.get("segments")
    if supplied:
        segments = _as_segments(supplied)
        if segments:
            return segments
    subtitle_path = config.get("subtitle_path") or config.get("transcript_file")
    if subtitle_path:
        segments = read_subtitle_file(str(subtitle_path))
        if segments:
            return segments
    try:
        return fetch_transcript(
            video_path,
            whisper_fallback=True,
            language=str(config.get("language") or "") or None,
            work_dir=video_path.parent / ".hevi_transcript",
        )
    except TranscriptError as exc:
        raise RuntimeError(
            "拆条需要真实字幕或可用的 faster-whisper 转写；"
            f"未能取得转写: {exc}"
        ) from exc


def _dimensions(config: dict[str, Any]) -> tuple[int, int]:
    aspect = str(config.get("aspect_ratio") or config.get("aspect") or "9:16")
    ratio_w, ratio_h = _ASPECTS.get(aspect, _ASPECTS["9:16"])
    width = int(config.get("output_width") or (720 if aspect in {"9:16", "4:5", "3:4"} else 1280))
    height = int(config.get("output_height") or round(width * ratio_h / ratio_w))
    return max(width, 64), max(height, 64)


def _render_one(
    source: Path,
    highlight: Highlight,
    destination: Path,
    *,
    width: int,
    height: int,
) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg 未安装，无法输出真实拆条 MP4")
    duration = max(0.2, highlight.end_s - highlight.start_s)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, highlight.start_s):.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        detail = (proc.stderr or proc.stdout or "unknown ffmpeg error").strip()[-800:]
        raise RuntimeError(f"FFmpeg 拆条失败: {detail}")


def _write_srt(path: Path, highlight: Highlight, segments: list[TranscriptSegment]) -> None:
    rows: list[str] = []
    for index, segment in enumerate(
        item for item in segments if item.end > highlight.start_s and item.start < highlight.end_s
    ):
        start = max(0.0, segment.start - highlight.start_s)
        end = min(highlight.end_s - highlight.start_s, segment.end - highlight.start_s)
        if end <= start:
            continue

        def stamp(seconds: float) -> str:
            millis = round(seconds * 1000)
            hours, millis = divmod(millis, 3_600_000)
            minutes, millis = divmod(millis, 60_000)
            seconds_i, millis = divmod(millis, 1000)
            return f"{hours:02d}:{minutes:02d}:{seconds_i:02d},{millis:03d}"

        rows.extend([str(index + 1), f"{stamp(start)} --> {stamp(end)}", segment.text, ""])
    if not rows:
        rows = ["1", "00:00:00,000 --> 00:00:01,000", highlight.hook_sentence or highlight.title, ""]
    path.write_text("\n".join(rows), encoding="utf-8")


def render_clip_batch(
    video_path: str | Path,
    *,
    output_dir: str | Path,
    target_clips: int = 5,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan and render a batch of Shorts from one local source film."""

    cfg = dict(config or {})
    source = Path(video_path)
    if not source.is_file():
        raise FileNotFoundError(f"输入视频不存在: {source}")
    target = max(1, min(20, int(target_clips)))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    segments = load_transcript(cfg, source)
    highlights = score_highlights(
        segments,
        target_clips=target,
        llm_fn=cfg.get("llm_fn"),
    )
    if not highlights:
        raise RuntimeError("转写为空或没有达到最短时长的可拆候选")
    width, height = _dimensions(cfg)
    rendered: list[dict[str, Any]] = []
    for index, highlight in enumerate(highlights[:target], start=1):
        clip_path = output / f"clip_{index:02d}.mp4"
        subtitle_path = output / f"clip_{index:02d}.srt"
        _render_one(source, highlight, clip_path, width=width, height=height)
        _write_srt(subtitle_path, highlight, segments)
        rendered.append(
            {
                "index": index,
                "path": str(clip_path),
                "subtitle_path": str(subtitle_path),
                "start_s": highlight.start_s,
                "end_s": highlight.end_s,
                "score": highlight.score,
                "title": highlight.title,
                "signals": list(highlight.signals),
            }
        )
    manifest_path = output / "clips.manifest.json"
    payload = {
        "source": str(source),
        "aspect_ratio": str(cfg.get("aspect_ratio") or "9:16"),
        "dimensions": {"width": width, "height": height},
        "transcript_segments": len(segments),
        "clips": rendered,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = [
        Artifact.from_path(
            item["path"],
            kind="video",
            media_type="video/mp4",
            primary=index == 0,
            logical_role="short_clip",
            metadata={k: v for k, v in item.items() if k not in {"path", "subtitle_path"}},
        )
        for index, item in enumerate(rendered)
    ]
    artifacts.extend(
        Artifact.from_path(
            item["subtitle_path"],
            kind="subtitle",
            media_type="application/x-subrip",
            logical_role="clip_subtitle",
            metadata={"clip_index": item["index"]},
        )
        for item in rendered
    )
    artifacts.append(
        Artifact.from_path(
            manifest_path,
            kind="json",
            media_type="application/json",
            logical_role="clip_manifest",
        )
    )
    manifest = ArtifactManifest(artifacts=artifacts)
    from hevi.production.delivery_gate import probe_video

    probes = [probe_video(item["path"]) for item in rendered]
    quality_violations = [
        f"clip[{index}] media probe failed"
        for index, probe in enumerate(probes)
        if probe.duration_s <= 0 or not probe.has_video
    ]
    quality_passed = bool(probes) and not quality_violations
    return {
        "status": "completed",
        "result_video_path": rendered[0]["path"],
        "total_shots": len(rendered),
        "completed_shots": len(rendered),
        "quality": {
            "passed": quality_passed,
            "violations": quality_violations,
            "verdict": "pass" if quality_passed else "fail",
            "checks": {
                "source_exists": source.is_file(),
                "clips_rendered": len(rendered),
                "manifest_exists": manifest_path.is_file(),
                "dimensions": f"{width}x{height}",
                "media_probe": [
                    {
                        "duration": probe.duration_s,
                        "has_video": probe.has_video,
                        "has_audio": probe.has_audio,
                    }
                    for probe in probes
                ],
            },
        },
        "clips": rendered,
        "transcript": [
            {"start": item.start, "end": item.end, "text": item.text}
            for item in segments
        ],
        "config_json": {
            **cfg,
            "artifact_manifest": manifest.model_dump(mode="json"),
            "clip_manifest_path": str(manifest_path),
        },
    }


async def execute_clip_video_task(task: dict[str, Any], _pool: Any) -> dict[str, Any]:
    """Canonical TaskService adapter for ``production_source=clip_video``."""

    config = dict(task.get("config_json") or {})
    request = dict(config.get("clip_request") or {})
    source = str(request.get("video_path") or task.get("topic") or "")
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task["id"]))
    return render_clip_batch(
        source,
        output_dir=output_dir,
        target_clips=int(request.get("max_clips") or 5),
        config={
            **request,
            "transcript_segments": request.get("transcript_segments"),
        },
    )


__all__ = ["execute_clip_video_task", "load_transcript", "render_clip_batch"]
