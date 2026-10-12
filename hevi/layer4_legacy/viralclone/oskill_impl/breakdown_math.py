"""Rhythm, subtitle box detection, and semantic tagging algorithms (oskill layer)."""

from __future__ import annotations

import json
import re
import statistics
import urllib.request
from typing import Any

from hevi.layer4_legacy.viralclone.oprim_impl.specs import (
    RhythmStats,
    SubtitleBox,
    WordToken,
)


def compute_rhythm_stats(
    duration_s: float,
    cut_timestamps_s: list[float],
    words: list[WordToken],
    sentences: list[dict[str, Any]],
    silences: list[dict[str, float]],
) -> RhythmStats:
    """Compute shot rhythm, hook timing, and speech rate statistics."""
    dur = max(0.1, duration_s)
    cuts = sorted(set([0.0] + [t for t in cut_timestamps_s if 0 < t < dur] + [dur]))
    shot_durations = [b - a for a, b in zip(cuts[:-1], cuts[1:]) if b > a]
    if not shot_durations:
        shot_durations = [dur]

    shot_count = len(shot_durations)
    first_shot_duration_s = shot_durations[0] if shot_durations else dur
    mean_shot_duration_s = float(statistics.fmean(shot_durations))
    median_shot_duration_s = float(statistics.median(shot_durations))
    cuts_per_minute = float((shot_count - 1) / (dur / 60.0)) if dur > 0 else 0.0

    # Hook duration: end of first spoken sentence, or first shot duration if no speech
    if sentences:
        hook_duration_s = float(sentences[0].get("end_s") or first_shot_duration_s)
    elif words:
        hook_duration_s = float(words[min(len(words) - 1, 3)].end_s)
    else:
        hook_duration_s = min(3.0, first_shot_duration_s)

    total_speech_text = "".join(w.word for w in words).strip()
    speech_rate_wps = float(len(total_speech_text) / dur) if dur > 0 else 0.0

    return RhythmStats(
        total_duration_s=round(dur, 3),
        shot_count=shot_count,
        first_shot_duration_s=round(first_shot_duration_s, 3),
        hook_duration_s=round(hook_duration_s, 3),
        mean_shot_duration_s=round(mean_shot_duration_s, 3),
        median_shot_duration_s=round(median_shot_duration_s, 3),
        cuts_per_minute=round(cuts_per_minute, 2),
        speech_rate_wps=round(speech_rate_wps, 2),
        silence_intervals=silences,
    )


def detect_subtitle_box_from_frames(
    frames_rgb: list[Any],
    frame_width: int,
    frame_height: int,
) -> SubtitleBox | None:
    """Detect subtitle area, line height, and vertical position using RapidOCR."""
    try:
        from rapidocr_onnxruntime import RapidOCR

        ocr = RapidOCR()
    except Exception:
        return None

    boxes: list[tuple[float, float, float, float, float, str]] = []
    # Crop to lower 45% of frame where subtitles typically live
    y_crop_start = int(frame_height * 0.55)

    for frame in frames_rgb:
        h, w = frame.shape[:2]
        crop = frame[y_crop_start:, :]
        results, _ = ocr(crop)
        if results:
            for r in results:
                pts, text, score = r[0], r[1], float(r[2])
                if score < 0.4 or not text.strip():
                    continue
                y0 = min(p[1] for p in pts) + y_crop_start
                y1 = max(p[1] for p in pts) + y_crop_start
                x0 = min(p[0] for p in pts)
                x1 = max(p[0] for p in pts)
                lh = y1 - y0
                if 12 <= lh <= frame_height * 0.25:
                    boxes.append((x0, y0, x1, y1, lh, text.strip()))

    if not boxes:
        return None

    avg_lh = float(statistics.median([b[4] for b in boxes]))
    avg_y0 = float(statistics.median([b[1] for b in boxes]))
    avg_y1 = float(statistics.median([b[3] for b in boxes]))
    min_x0 = float(min(b[0] for b in boxes))
    max_x1 = float(max(b[2] for b in boxes))
    text_sample = boxes[0][5] if boxes else ""

    return SubtitleBox(
        x0=round(min_x0, 1),
        y0=round(avg_y0, 1),
        x1=round(max_x1, 1),
        y1=round(avg_y1, 1),
        line_height_px=round(avg_lh, 1),
        avg_y_px=round((avg_y0 + avg_y1) / 2.0, 1),
        relative_line_height=round(avg_lh / frame_height, 4),
        text_sample=text_sample,
    )


def classify_sentence_semantic_role(
    text: str,
    index: int,
    total: int,
    *,
    ollama_url: str = "http://127.0.0.1:11434",
    model: str = "llama3.2:1b",
) -> str:
    """Classify sentence into [hook, selling_point, proof, cta].

    Uses local Ollama if available; falls back to deterministic rule-based analysis.
    Zero cloud API usage.
    """
    clean = text.strip()
    if not clean:
        return "selling_point"

    # Position & strong keyword prior
    lower = clean.lower()
    if index == 0:
        return "hook"
    if index == total - 1 or any(
        k in lower
        for k in ("buy", "order", "click", "link", "shop", "cart", "discount", "下", "购", "戳", "买", "立即")
    ):
        return "cta"
    if any(
        k in lower
        for k in (
            "percent",
            "%",
            "tested",
            "test",
            "proven",
            "prove",
            "study",
            "lab",
            "research",
            "certified",
            "用户",
            "实验",
            "实测",
            "数据",
            "权威",
            "好评",
            "评测",
            "报告",
        )
    ):
        return "proof"

    feature_indicators = (
        "feature",
        "design",
        "driver",
        "battery",
        "material",
        "titanium",
        "screen",
        "power",
        "fast",
        "light",
        "weight",
        "durable",
        "equipped",
        "built",
        "mode",
        "color",
        "材质",
        "配置",
        "续航",
        "轻薄",
        "搭载",
        "采用",
        "外观",
        "芯片",
        "音质",
        "功能",
        "手感",
    )
    if any(k in lower for k in feature_indicators):
        return "selling_point"

    # Try local Ollama for ambiguous middle sentences
    try:
        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=json.dumps(
                {
                    "model": model,
                    "prompt": (
                        "Classify this video narration sentence into exactly one of: "
                        "[selling_point, proof]. "
                        f"Sentence: \"{clean}\". "
                        "Respond ONLY with the label name."
                    ),
                    "stream": False,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ans = str(data.get("response", "")).strip().lower()
            if "proof" in ans:
                return "proof"
            if "selling" in ans:
                return "selling_point"
    except Exception:
        pass

    return "selling_point"
