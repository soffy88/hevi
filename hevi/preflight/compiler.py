"""preflight.compiler —— 分镜节拍 → 各模型专用 prompt。

设计：编译结果永远是“结构化 JSON ＋可读文本”双份，可审；
画风锁定段、人物锁定段、无文字段由编译器自动拼，不靠手写；
beat 没给的字段不编造——缺定妆／缺描述只出 warning，不替用户写脸。

三种输出：
- veo_fast / omni_flash：分段式单 prompt（OUTPUT／STYLE／CHARACTER／
  ACTION／AUDIO／NEGATIVE），窗口分别为 8 秒／10 秒。
- svi_film：prompt-stream：每 5 秒一段 {start_s, duration_s, text}，
  另附 style_lock 与 first_frame 引用（SVI-Film 的“每文本 5 秒”契约）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from hevi.preflight.beats import Beat, get_model_spec
from hevi.preflight.budget import estimate_cost
from hevi.preflight.dialogue_fit import CLEAR_CPS

DEFAULT_STYLE_LOCK = (
    "cinematic Chinese historical illustration, painterly, muted earthy "
    "palette, soft film grain"
)

NEGATIVE_BLOCK = (
    "NEGATIVE CONSTRAINTS: no text, no subtitles, no watermark, "
    "no pseudo-characters or garbled glyphs on signs, plaques or banners, "
    "no speech bubbles, no morphing faces, no detached limbs. "
    "（无文字、无字幕、无水印、无伪文字）"
)

_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；])")


@dataclass
class CompiledPrompt:
    model: str
    prompt_text: str
    sections: dict[str, Any]
    estimated_cost: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_text": self.prompt_text,
            "sections": self.sections,
            "estimated_cost": self.estimated_cost,
            "warnings": self.warnings,
        }


def _style_lock(beat: Beat) -> str:
    return beat.style_lock or DEFAULT_STYLE_LOCK


def _character_lock(beat: Beat) -> tuple[str, list[str]]:
    lines: list[str] = []
    warnings: list[str] = []
    for ch in beat.characters:
        if ch.sheet_path:
            lines.append(f"{ch.char_id}: use attached character sheet {ch.sheet_path}")
        elif ch.description:
            lines.append(f"{ch.char_id}: {ch.description}")
        else:
            lines.append(f"{ch.char_id}: (no sheet, no description — fill before generation)")
            warnings.append(f"人物 {ch.char_id} 无定妆、无描述：编译结果须人工补人物锁定段")
    return "\n".join(lines), warnings


def _dialogue_block(beat: Beat) -> str:
    if beat.kind != "dialogue":
        return ""
    lines = beat.dialogue_lines or []
    if lines:
        spoken = " / ".join(f"{ln.speaker}: “{ln.text}”" for ln in lines)
    else:
        spoken = f"“{beat.text}”"
    return (
        f"AUDIO SPOKEN DIALOGUE (Mandarin Chinese, clear steady pace): {spoken}. "
        "Dialogue is spoken audio only, strictly NO speech bubbles or subtitle text boxes."
    )


def _single_prompt(beat: Beat, model: str) -> CompiledPrompt:
    spec = get_model_spec(model)
    window = spec.window_s or beat.duration_s
    char_lock, warnings = _character_lock(beat)
    aspect = beat.aspect
    res = "1280x720 (16:9)" if aspect == "16:9" else "720x1280 (9:16)"
    sections: dict[str, Any] = {
        "output_spec": (
            f"{window:g} seconds duration, {res}, target 720p. Model target: {model}."
        ),
        "style_lock": _style_lock(beat),
        "character_lock": char_lock,
        "action": f"SCENE {beat.scene}: {beat.text}" if beat.kind != "dialogue" else f"SCENE {beat.scene}: dramatic dialogue performance.",
        "audio": _dialogue_block(beat),
        "negative": NEGATIVE_BLOCK,
    }
    if beat.first_frame:
        sections["first_frame"] = f"Frames to Video: use first frame {beat.first_frame}."
    parts = [f"{k.upper()}: {v}" for k, v in sections.items() if v]
    if beat.kind == "dialogue" and not beat.dialogue_text.strip():
        warnings.append("演绎段无对白：编译结果无 AUDIO 段")
    return CompiledPrompt(
        model=model,
        prompt_text="\n\n".join(parts),
        sections=sections,
        estimated_cost=estimate_cost(model, window),
        warnings=warnings,
    )


def _svi_stream(beat: Beat) -> CompiledPrompt:
    """SVI-Film prompt-stream：每 5 秒一段，文本按句切分、按语速配额填充。"""
    char_lock, warnings = _character_lock(beat)
    chars_per_seg = int(CLEAR_CPS * 5)  # 5 秒约 22 字
    sentences = [s for s in _SENT_SPLIT_RE.split(beat.text) if s.strip()]
    if not sentences and beat.text.strip():
        sentences = [beat.text]
    segments: list[dict[str, Any]] = []
    current = ""
    start = 0.0
    for sent in sentences:
        if current and len(current) + len(sent) > chars_per_seg:
            segments.append({"start_s": start, "duration_s": 5.0, "text": current})
            start += 5.0
            current = sent
        else:
            current += sent
    if current:
        segments.append({"start_s": start, "duration_s": 5.0, "text": current})
    if not segments:
        segments.append({"start_s": 0.0, "duration_s": 5.0, "text": ""})
        warnings.append("节拍无文本：SVI-Film 流为空段，须人工填动作")
    sections: dict[str, Any] = {
        "style_lock": _style_lock(beat),
        "character_lock": char_lock,
        "prompt_stream": segments,
        "segment_rule": "5 seconds per text segment (SVI-Film contract)",
    }
    if beat.first_frame:
        sections["first_frame"] = f"Image-to-video: start from first frame {beat.first_frame}."
    stream_text = "\n".join(
        f"[{s['start_s']:g}s +{s['duration_s']:g}s] {s['text']}" for s in segments
    )
    prompt_text = (
        f"STYLE LOCK: {sections['style_lock']}\n"
        f"CHARACTER LOCK:\n{char_lock}\n"
        f"PROMPT STREAM:\n{stream_text}"
    )
    return CompiledPrompt(
        model="svi_film",
        prompt_text=prompt_text,
        sections=sections,
        estimated_cost=estimate_cost("svi_film", beat.duration_s),
        warnings=warnings,
    )


def compile_beat(beat: Beat, model: str) -> CompiledPrompt:
    """编译一个 beat。未知模型抛 ValueError（不许静默出通用 prompt）。"""
    get_model_spec(model)  # 校验模型名
    if model == "svi_film":
        return _svi_stream(beat)
    if model in ("veo_fast", "veo_lite", "veo_quality", "omni_flash", "pixstag"):
        return _single_prompt(beat, model)
    raise ValueError(f"no compiler for model: {model!r}")


def compile_beat_json(beat: Beat, model: str) -> str:
    return json.dumps(compile_beat(beat, model).to_dict(), indent=2, ensure_ascii=False)
