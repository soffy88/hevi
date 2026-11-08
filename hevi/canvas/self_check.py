"""Per-node self-check for the canvas MVP.

After a node produces its artifact the executor calls this module and writes
the verdict back to ``Node.review`` (red / yellow / green).  It reuses hevi's
existing judges rather than adding a model service:

* video: ``hevi.judge.hard_checks.run_hard_checks`` (ffprobe / audio / black /
  frozen / duration) plus ``hevi.avcraft.obase.vision.analyze_frames`` signals
  and a small ffmpeg contact sheet.  A vision/LLM backend is optional and off
  by default; no paid call is made by this MVP.
* audio: duration + loudness from the same hard checks.
* image / text / script: file and structure checks.  Text accepts an injected
  LLM reviewer (the port is there); the default offline rule reviewer keeps the
  MVP free and deterministic.

Verdict: ``pass`` (green) / ``warn`` (yellow) / ``fail`` (red).  Only a failing
node is retried, and the retry injects ``suggested_prompt`` into a copy of the
node config without changing the graph topology.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

PASS = "pass"
WARN = "warn"
FAIL = "fail"

Reviewer = Callable[[str, dict[str, Any]], dict[str, Any] | None]

_BANNED_TEXT = ("TODO", "PLACEHOLDER", "lorem ipsum", "待补", "占位")


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _first_path(output: Any, suffixes: tuple[str, ...]) -> Path | None:
    out = output if isinstance(output, dict) else {}
    candidates: list[str] = []
    explicit = out.get("artifacts")
    if isinstance(explicit, list):
        for item in explicit:
            if isinstance(item, dict) and item.get("path"):
                candidates.append(str(item["path"]))
            elif isinstance(item, str):
                candidates.append(item)
    for key in ("output", "mp4", "video", "audio", "image", "path", "subtitle"):
        value = out.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    for value in candidates:
        path = Path(value)
        if path.suffix.lower() in suffixes:
            return path
        if path.is_file() and not suffixes:
            return path
    return None


def _mmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:d}:{seconds % 60:02d}"


def _video_contact_sheet(path: Path, out_path: Path, *, frames: int = 9) -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vf = f"fps=1/1,scale=320:-1,tile=3x3:padding=4:margin=4"
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", str(path), "-vf", vf, "-frames:v", "1", str(out_path)],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0 or not out_path.is_file():
        return None
    return str(out_path)


def _check_text(
    node: dict[str, Any],
    output: Any,
    *,
    upstream_text: str = "",
    llm_reviewer: Reviewer | None = None,
) -> dict[str, Any]:
    cfg = node.get("config") or {}
    out = output if isinstance(output, dict) else {}
    text = str(out.get("output") or out.get("content") or cfg.get("content") or "").strip()
    reasons: list[str] = []
    result = PASS
    if not text:
        return {
            "result": FAIL,
            "reasons": ["节点没有产出文本"],
            "suggested_prompt": "补全该节点的文本内容，至少包含一句完整的话。",
        }
    min_chars = int(cfg.get("min_chars") or 12)
    max_chars = int(cfg.get("max_chars") or 6000)
    if len(text) < min_chars:
        result = WARN
        reasons.append(f"文本过短（{len(text)} 字，建议 ≥{min_chars}）")
    if len(text) > max_chars:
        result = WARN
        reasons.append(f"文本过长（{len(text)} 字，建议 ≤{max_chars}）")
    for word in _BANNED_TEXT:
        if word.lower() in text.lower():
            result = FAIL
            reasons.append(f"含占位/未完成标记：{word}")
    required = [str(w) for w in (cfg.get("require_keywords") or []) if str(w).strip()]
    missing = [w for w in required if w.lower() not in text.lower()]
    if missing:
        result = WARN if result == PASS else result
        reasons.append("缺少要点：" + "、".join(missing[:5]))
    if upstream_text:
        overlap = set(upstream_text.lower().split()) & set(text.lower().split())
        if len(upstream_text) > 40 and not overlap:
            result = WARN if result == PASS else result
            reasons.append("与上游内容几乎无重合，可能答非所问")
    if llm_reviewer is not None and result != FAIL:
        try:
            extra = llm_reviewer(text, cfg)
        except Exception as exc:  # a broken reviewer never fails a good node
            extra = None
            reasons.append(f"LLM 审稿不可用：{type(exc).__name__}")
        if isinstance(extra, dict):
            verdict = str(extra.get("result") or "").lower()
            if verdict in (PASS, WARN, FAIL):
                if verdict == FAIL or (verdict == WARN and result == PASS):
                    result = verdict
                reasons.extend(str(r) for r in (extra.get("reasons") or []))
            if extra.get("suggested_prompt"):
                cfg = {**cfg, "_suggested_prompt": extra["suggested_prompt"]}
    suggestion = str(cfg.get("_suggested_prompt") or "")
    if not suggestion and result == FAIL:
        suggestion = "重写该节点文本，去掉占位/未完成标记并补全内容。"
    return {
        "result": result,
        "reasons": reasons,
        "suggested_prompt": suggestion,
        "signals": {"chars": len(text)},
    }


def _check_video(node: dict[str, Any], output: Any, *, backend: Any = None) -> dict[str, Any]:
    path = _first_path(output, (".mp4", ".mov", ".webm", ".mkv"))
    if path is None:
        return {
            "result": FAIL,
            "reasons": ["视频节点没有产出视频文件"],
            "suggested_prompt": "重新生成该视频节点，确认输出路径存在且可播放。",
        }
    if not path.is_file() or path.stat().st_size == 0:
        return {
            "result": FAIL,
            "reasons": [f"视频文件缺失或为空：{path}"],
            "suggested_prompt": "重新生成该视频节点，输出文件为空，可能渲染中断。",
        }
    cfg = node.get("config") or {}
    reasons: list[str] = []
    signals: dict[str, Any] = {"path": str(path), "size_bytes": path.stat().st_size}
    result = PASS
    try:
        from hevi.judge.hard_checks import probe_video, run_hard_checks

        probe = probe_video(str(path))
        signals["probe"] = probe
        # Only an explicit expectation is enforced; ``duration_s`` on a koubo
        # node is its input target, not a promise that the render lands on it.
        expected = cfg.get("expected_duration_s")
        report = run_hard_checks(
            str(path),
            expected_duration_s=float(expected) if expected else None,
            backend=backend,
        )
        signals["hard_checks_passed"] = bool(report.passed)
        signals["findings"] = [
            {"name": f.name, "severity": f.severity, "detail": f.detail}
            for f in report.findings
        ]
        step = str((cfg or {}).get("koubo_step") or "")
        audio_required = bool(cfg.get("require_audio", step in ("edit", "final")))
        for finding in report.findings:
            if finding.name in ("no_audio_track", "silent_audio") and not audio_required:
                # An avatar/evidence intermediate clip has no narration track by
                # design; the final mux carries the audio.
                continue
            if finding.name in ("frozen_frames", "repetition"):
                # A talking-head/evidence shot may legitimately hold a stable
                # frame; flag it yellow for a human look, never red.
                if result == PASS:
                    result = WARN
                reasons.append(f"{finding.name}: {finding.detail}")
                continue
            if finding.name == "first_last_frames" and step in ("avatar", "evidence"):
                continue
            if finding.severity == "blocker":
                result = FAIL
                reasons.append(f"{finding.name}: {finding.detail}")
            elif finding.severity == "major" and result != FAIL:
                result = FAIL
                reasons.append(f"{finding.name}: {finding.detail}")
            elif finding.severity == "minor" and result == PASS:
                result = WARN
                reasons.append(f"{finding.name}: {finding.detail}")
    except Exception as exc:
        result = WARN if result == PASS else result
        reasons.append(f"硬性检查未完成：{type(exc).__name__}: {exc}")

    try:
        from hevi.avcraft.obase.vision import analyze_frames

        analysis = analyze_frames(path, sample_fps=1.0, scale_w=320, faces=False)
        motions = [float(s.get("motion") or 0) for s in analysis.get("samples") or []]
        signals["motion_max"] = max(motions) if motions else 0.0
        signals["motion_mean"] = round(sum(motions) / len(motions), 4) if motions else 0.0
        signals["frames_sampled"] = len(motions)
        if len(motions) >= 3 and max(motions) < 0.0015 and result != FAIL:
            result = WARN
            reasons.append("画面几乎完全静止（疑似冻帧）")
    except Exception as exc:
        signals["vision_error"] = f"{type(exc).__name__}: {exc}"

    try:
        sheet = _video_contact_sheet(path, path.parent / f"{path.stem}.contact.jpg")
        if sheet:
            signals["contact_sheet"] = sheet
    except Exception as exc:
        signals["contact_sheet_error"] = f"{type(exc).__name__}: {exc}"

    return {
        "result": result,
        "reasons": reasons,
        "suggested_prompt": ""
        if result == PASS
        else "修正视频：保持主体清晰、画面有运动、音轨与时长完整。",
        "signals": signals,
    }


def _check_audio(node: dict[str, Any], output: Any) -> dict[str, Any]:
    path = _first_path(output, (".wav", ".mp3", ".m4a", ".aac", ".flac"))
    if path is None:
        return {
            "result": FAIL,
            "reasons": ["音频节点没有产出音频文件"],
            "suggested_prompt": "重新合成音频，确认文本非空且 TTS 可用。",
        }
    if not path.is_file() or path.stat().st_size == 0:
        return {
            "result": FAIL,
            "reasons": [f"音频文件缺失或为空：{path}"],
            "suggested_prompt": "重新合成音频，输出文件为空。",
        }
    reasons: list[str] = []
    result = PASS
    signals: dict[str, Any] = {"path": str(path), "size_bytes": path.stat().st_size}
    try:
        from hevi.judge.hard_checks import _mean_volume, _run, probe_video

        probe = probe_video(str(path))
        signals["duration"] = probe.get("duration")
        if not probe.get("duration"):
            proc = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                         "json", str(path)], timeout=30)
            try:
                signals["duration"] = float(json.loads(proc.stdout)["format"]["duration"])
            except Exception:
                pass
        if not signals.get("duration"):
            result = FAIL
            reasons.append("无法读取音频时长")
        volume = _mean_volume(str(path)) if result != FAIL else None
        if volume is not None:
            signals["mean_volume_db"] = volume
            if volume < -45:
                result = WARN if result == PASS else result
                reasons.append(f"音量过低（{volume:.1f} dB）")
    except Exception as exc:
        result = WARN if result == PASS else result
        reasons.append(f"音频检查未完成：{type(exc).__name__}: {exc}")
    return {
        "result": result,
        "reasons": reasons,
        "suggested_prompt": "" if result == PASS else "重新合成音频，检查音量与时长。",
        "signals": signals,
    }


def _check_image(node: dict[str, Any], output: Any) -> dict[str, Any]:
    path = _first_path(output, (".png", ".jpg", ".jpeg", ".webp"))
    if path is None:
        return {
            "result": FAIL,
            "reasons": ["图片节点没有产出图片"],
            "suggested_prompt": "重新生成图片并确认输出路径。",
        }
    if not path.is_file() or path.stat().st_size == 0:
        return {
            "result": FAIL,
            "reasons": [f"图片文件缺失或为空：{path}"],
            "suggested_prompt": "重新生成图片，输出文件为空。",
        }
    signals: dict[str, Any] = {"path": str(path), "size_bytes": path.stat().st_size}
    reasons: list[str] = []
    result = PASS
    try:
        from PIL import Image

        with Image.open(path) as img:
            signals["width"], signals["height"] = img.size
            if img.width < 64 or img.height < 64:
                result = WARN
                reasons.append(f"图片尺寸过小：{img.width}x{img.height}")
    except Exception as exc:
        result = FAIL
        reasons.append(f"图片无法解码：{type(exc).__name__}")
    return {
        "result": result,
        "reasons": reasons,
        "suggested_prompt": "" if result == PASS else "重新生成图片。",
        "signals": signals,
    }


def _check_subtitle(node: dict[str, Any], output: Any) -> dict[str, Any]:
    path = _first_path(output, (".srt",))
    if path is None or not path.is_file():
        return {
            "result": FAIL,
            "reasons": ["字幕节点没有产出 SRT 文件"],
            "suggested_prompt": "重新生成字幕，确认上游分句结果非空。",
        }
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows = [line for line in text.splitlines() if "-->" in line]
    if not rows:
        return {
            "result": FAIL,
            "reasons": ["SRT 没有任何时间轴条目"],
            "suggested_prompt": "重新生成字幕时间轴。",
        }
    return {
        "result": PASS,
        "reasons": [],
        "suggested_prompt": "",
        "signals": {"path": str(path), "cues": len(rows)},
    }


def review_node(
    node: dict[str, Any],
    output: Any,
    *,
    upstream_text: str = "",
    llm_reviewer: Reviewer | None = None,
    vision_backend: Any = None,
) -> dict[str, Any]:
    """Return the review dict written back to ``Node.review``."""
    node_type = str(node.get("node_type") or "text")
    step = str((node.get("config") or {}).get("koubo_step") or "")
    model = "hevi.canvas.self_check/offline"
    if step == "subtitle":
        payload = _check_subtitle(node, output)
    elif step == "avatar" or step == "evidence" or step == "edit" or step == "final":
        payload = _check_video(node, output, backend=vision_backend)
    elif node_type in ("text", "script"):
        payload = _check_text(
            node, output, upstream_text=upstream_text, llm_reviewer=llm_reviewer
        )
    elif node_type == "video":
        payload = _check_video(node, output, backend=vision_backend)
    elif node_type == "audio":
        payload = _check_audio(node, output)
    elif node_type == "image":
        payload = _check_image(node, output)
    else:
        payload = {
            "result": PASS,
            "reasons": [],
            "suggested_prompt": "",
            "signals": {"note": f"{node_type} 节点无需媒体检查"},
        }
    if llm_reviewer is not None and node_type in ("text", "script"):
        model = "hevi.canvas.self_check/text+llm"
    return {
        "result": payload["result"],
        "reasons": payload.get("reasons") or [],
        "suggested_prompt": payload.get("suggested_prompt") or "",
        "signals": payload.get("signals") or {},
        "model": model,
        "ts": _ts(),
    }


def status_for_review(review: dict[str, Any] | None) -> str:
    verdict = str((review or {}).get("result") or "pass")
    return {"pass": "ok", "warn": "warn", "fail": "fail"}.get(verdict, "warn")


def retry_config(node: dict[str, Any], review: dict[str, Any]) -> dict[str, Any] | None:
    """Config copy for the one automatic retry, or None if nothing to change."""
    if review.get("result") != FAIL:
        return None
    cfg = dict(node.get("config") or {})
    suggestion = str(review.get("suggested_prompt") or "").strip()
    for key in ("prompt", "content", "script_text", "text"):
        if key in cfg and isinstance(cfg[key], str):
            cfg[key] = (cfg[key] + "\n\n" + suggestion).strip() if suggestion else cfg[key]
            return cfg
    if suggestion:
        cfg["prompt"] = suggestion
        return cfg
    return cfg or None
