"""Local piper + faster-whisper Story Builder for HyperFrames explainers.

Synthesises Chinese narration with zero API cost using local piper and
extracts precise word-level timestamps using faster-whisper (large-v3-turbo CPU int8).
Builds standard `story.json` and `audio/narration.wav` fully compatible with the
Lanshu HyperFrames runtime contract.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"
PIPER = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
PIPER_VOICE = "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx"
WHISPER_MODEL_PATH = "/home/soffy/models/faster-whisper-large-v3-turbo"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    env["PATH"] = f"/home/soffy/.local/bin:{env.get('PATH', '')}"
    return env


def synth_narration_line(text: str, out_wav: Path, *, speed: float = 1.05) -> float:
    """Synthesise one line using local piper with loudnorm filter."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    raw = out_wav.with_suffix(".raw.wav")
    proc = subprocess.run(
        [PIPER, "-m", PIPER_VOICE, "-f", str(raw), "--length_scale", str(1.0 / speed), "--sentence_silence", "0.2"],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr[-400:]}")
    proc = subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(raw), "-af", "highpass=f=75,loudnorm=I=-16:TP=-1.5", "-ar", "44100", "-ac", "1", str(out_wav)],
        capture_output=True,
        text=True,
    )
    raw.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg loudnorm failed: {proc.stderr[-400:]}")
    out = subprocess.check_output([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_wav)]).decode().strip()
    return float(out)


def build_story_package(
    *,
    spec: dict[str, Any],
    dest_dir: Path,
    whisper_model: Any = None,
) -> Path:
    """Build story.json and audio/narration.wav in dest_dir."""
    dest_dir = dest_dir.resolve()
    audio_dir = dest_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    lines_spec = spec["lines"]
    head_pad = 0.4
    line_gap = 0.38
    tail_pad = 0.5

    part_wavs: list[Path] = []
    line_cues: list[tuple[float, float]] = []
    curr_t = head_pad

    for i, line in enumerate(lines_spec, start=1):
        text = line["text"]
        part_wav = audio_dir / f"vo_{i:02d}.wav"
        dur = synth_narration_line(text, part_wav)
        line_cues.append((curr_t, curr_t + dur))
        part_wavs.append(part_wav)
        curr_t += dur + line_gap

    # Build full narration.wav with silence gaps
    filter_inputs = []
    filter_complex_parts = []
    # 1. Lead silence
    filter_complex_parts.append(f"aevalsrc=0:d={head_pad}:s=44100[s0]")
    last_label = "[s0]"

    for i, part in enumerate(part_wavs):
        filter_inputs.extend(["-i", str(part)])
        filter_complex_parts.append(f"aevalsrc=0:d={line_gap}:s=44100[gap{i}]")
        filter_complex_parts.append(f"{last_label}[{i}:a][gap{i}]concat=n=3:v=0:a=1[cat{i}]")
        last_label = f"[cat{i}]"

    # tail silence
    filter_complex_parts.append(f"aevalsrc=0:d={tail_pad}:s=44100[stail]")
    filter_complex_parts.append(f"{last_label}[stail]concat=n=2:v=0:a=1[outa]")

    full_narration = audio_dir / "narration.wav"
    cmd = [FFMPEG, "-y", "-loglevel", "error"] + filter_inputs + [
        "-filter_complex", ";".join(filter_complex_parts),
        "-map", "[outa]",
        "-ar", "44100", "-ac", "1",
        str(full_narration),
    ]
    subprocess.run(cmd, env=_env(), check=True)
    narration_dur = float(
        subprocess.check_output([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(full_narration)]).decode().strip()
    )

    # Run faster-whisper for word-level alignment
    if whisper_model is None:
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel(WHISPER_MODEL_PATH, device="cpu", compute_type="int8")

    segments, _ = whisper_model.transcribe(
        str(full_narration),
        language="zh",
        word_timestamps=True,
    )

    all_whisper_words: list[tuple[str, float, float]] = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                all_whisper_words.append((w.word.strip(), round(w.start, 2), round(w.end, 2)))

    # Distribute words to each line based on cues
    built_lines = []
    for i, line_def in enumerate(lines_spec):
        li = line_def.get("i", i + 1)
        text = line_def["text"]
        start_t, end_t = line_cues[i]
        matched_words = [
            [w[0], w[1]]
            for w in all_whisper_words
            if w[1] >= start_t - 0.25 and w[1] <= end_t + 0.35
        ]
        # Fallback if whisper segmented differently: generate character-level times
        if not matched_words or len(matched_words) < 2:
            chars = [c for c in text if c not in " ，。！？；：、"]
            char_dur = (end_t - start_t) / max(1, len(chars))
            matched_words = [
                [c, round(start_t + j * char_dur, 2)]
                for j, c in enumerate(chars)
            ]

        built_lines.append({
            "i": li,
            "text": text,
            "start": round(start_t, 3),
            "end": round(end_t, 3),
            "words": matched_words,
            "chapter": line_def.get("chapter", "main"),
        })

    # Build chapters
    chap_specs = spec.get("chapters", [])
    built_chapters = []
    for ch in chap_specs:
        key = ch["key"]
        ch_lines = [L for L in built_lines if L["chapter"] == key]
        if ch_lines:
            ch_start = max(0.0, ch_lines[0]["start"] - 0.2)
            ch_end = ch_lines[-1]["end"] + 0.2
        else:
            ch_start = 0.0
            ch_end = narration_dur
        built_chapters.append({
            "n": ch.get("n", len(built_chapters) + 1),
            "key": key,
            "title": ch["title"],
            "start": round(ch_start, 2),
            "end": round(ch_end, 2),
        })

    # Recap
    recap_spec = dict(spec.get("recap", {}))
    recap_len = float(recap_spec.get("length", 4.7))
    recap_start = narration_dur + 0.2
    recap_end = recap_start + recap_len
    recap_spec["start"] = round(recap_start, 2)
    recap_spec["end"] = round(recap_end, 2)

    total_duration = round(recap_end + 0.5, 2)

    end_spec = dict(spec.get("end", {}))
    if "line" in end_spec:
        end_line_obj = next((L for L in built_lines if L["i"] == end_spec["line"]), built_lines[-1])
        end_spec["start"] = end_line_obj["start"]

    story_dict = {
        "title": spec["title"],
        "subtitle": spec.get("subtitle", ""),
        "duration": total_duration,
        "narration": "audio/narration.wav",
        "voice": "piper huayan · zh_CN-huayan-medium",
        "timing": "faster-whisper-large-v3-turbo",
        "lines": built_lines,
        "chapters": built_chapters,
        "end": end_spec,
        "recap": recap_spec,
        "notes": spec.get("notes", {}),
        "facts": spec.get("facts", {}),
    }

    story_file = dest_dir / "story.json"
    story_file.write_text(json.dumps(story_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Built story package at %s (duration: %.1fs)", dest_dir, total_duration)
    return dest_dir


# Pre-defined two real non-KV Chinese topics
TOPIC_STATIC_ELECTRICITY: dict[str, Any] = {
    "title": "为什么冬天静电多",
    "subtitle": "干燥空气电荷无处释放，接触瞬间火花放电",
    "chapters": [
        {"n": 1, "key": "phenomenon", "title": "现象 · 处处触电"},
        {"n": 2, "key": "physics", "title": "原理 · 干燥电荷"},
        {"n": 3, "key": "solution", "title": "化解 · 增加湿度"},
    ],
    "lines": [
        {"i": 1, "text": "到了冬天，脱毛衣噼里啪啦，摸门把手冷不丁被电一下。", "chapter": "phenomenon"},
        {"i": 2, "text": "其实静电的核心原因，是摩擦产生了电子转移。", "chapter": "physics"},
        {"i": 3, "text": "冬天气温低空气干燥，缺少导电水汽，电荷无处释放越积越多。", "chapter": "physics"},
        {"i": 4, "text": "当你突然接触金属导体，数千伏电压瞬间击穿空气放电。", "chapter": "physics"},
        {"i": 5, "text": "解决办法很简单：室内放加湿器，穿纯棉衣物，电荷自然溜走。", "chapter": "solution"},
        {"i": 6, "text": "保持空气湿润，向冬日静电轻松说再见。", "chapter": "solution"},
    ],
    "end": {
        "line": 6,
        "emphasis": ["空气湿润", "冬日静电", "轻松说再见"],
    },
    "recap": {
        "center": "静电成因",
        "tagline": "干燥聚集 · 瞬间放电",
        "length": 4.8,
        "points": [
            {"n": 1, "title": "摩擦起电", "text": "不同材质摩擦产生微观电子转移"},
            {"n": 2, "title": "干燥聚集", "text": "空气湿度低导致电荷无法及时导走"},
            {"n": 3, "title": "瞬间放电", "text": "人体接触金属导体产生微型电弧"},
            {"n": 4, "title": "科学防范", "text": "使用加湿器增加湿度，穿纯棉衣物"},
        ],
    },
    "notes": {
        "phenomenon": ["冬天毛衣摩擦起电，门把手触电火花"],
        "physics": [
            "摩擦让电子在绝缘物体表面转移",
            "干燥空气电阻极大，电荷难以泄漏",
            "接触金属导体引发数千伏瞬间电击",
        ],
        "solution": [
            "提升空气相对湿度到百分之五十以上",
            "消除静电困扰，保持舒适生活",
        ],
    },
    "facts": {
        "voltage": "冬季静电火花电压可高达数千甚至上万伏特，但电荷量微小",
        "humidity": "当空气相对湿度超过50%时，静电不易聚集",
    },
}

TOPIC_WHALE_CANCER: dict[str, Any] = {
    "title": "为什么蓝鲸很少得癌症",
    "subtitle": "庞大体型与万亿细胞背后的演化奇迹",
    "chapters": [
        {"n": 1, "key": "paradox", "title": "佩托悖论"},
        {"n": 2, "key": "mechanism", "title": "多重防线"},
    ],
    "lines": [
        {"i": 1, "text": "蓝鲸拥有千万亿个细胞，但患癌几率却远低于渺小的人类。", "chapter": "paradox"},
        {"i": 2, "text": "这就是生物学上著名的佩托悖论：体型越大，反而越不得癌症。", "chapter": "paradox"},
        {"i": 3, "text": "科学家发现，蓝鲸体内演化出了多套抑癌基因副本。", "chapter": "mechanism"},
        {"i": 4, "text": "一旦细胞发生危险突变，免疫防线就会迅速将其修复或清除。", "chapter": "mechanism"},
        {"i": 5, "text": "大自然的基因备份智慧，为生命筑起了坚不可摧的防线。", "chapter": "mechanism"},
    ],
    "end": {
        "line": 5,
        "emphasis": ["基因备份", "生命防线"],
    },
    "recap": {
        "center": "佩托悖论",
        "tagline": "庞大身躯 · 基因守护",
        "length": 4.5,
        "points": [
            {"n": 1, "title": "体型悖论", "text": "万亿细胞庞大体型但极低患癌率"},
            {"n": 2, "title": "多重副本", "text": "抑癌基因冗余备份阻断恶性突变"},
        ],
    },
    "notes": {
        "paradox": [
            "蓝鲸体型巨大细胞极多，患癌率却显著低于人类",
            "打破了细胞越多癌变越多的传统直觉",
        ],
        "mechanism": [
            "演化出大量抑癌基因多重拷贝",
            "精准的DNA损伤修复与细胞凋亡机制",
            "生命演化的深层智慧",
        ],
    },
    "facts": {
        "cells": "蓝鲸细胞数量是人类的上千倍",
        "genes": "蓝鲸拥有多个TP53等抑癌基因家族的多份重复副本",
    },
}


__all__ = [
    "TOPIC_STATIC_ELECTRICITY",
    "TOPIC_WHALE_CANCER",
    "build_story_package",
    "synth_narration_line",
]
