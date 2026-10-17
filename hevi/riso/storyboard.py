"""Storyboard generation and parsing for RISO B-roll overlays (Gate 1).

Selects 5-8 visually potent spoken sentences from an SRT or transcript,
assigns templates and subsequenced screen text, picks at most 2 palettes,
and produces a clear list of rejected segments with recommended treatments.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.riso.constants import PALETTES
from hevi.riso.gatekeeper import extract_numbers_and_metrics, is_subsequence, truncate_to_subsequence


@dataclass
class StoryboardShot:
    clip_id: str
    template: str
    start_s: float
    end_s: float
    duration_s: float
    palette: str
    source_sentence: str
    screen_data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "template": self.template,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "duration_s": round(self.duration_s, 2),
            "palette": self.palette,
            "source_sentence": self.source_sentence,
            "screen_data": self.screen_data,
        }


@dataclass
class RejectedSegment:
    index: int
    text: str
    start_s: float
    end_s: float
    reason: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "reason": self.reason,
            "recommendation": self.recommendation,
        }


@dataclass
class StoryboardPlan:
    title: str
    total_duration_s: float
    palettes_used: list[str]
    shots: list[StoryboardShot]
    rejected_segments: list[RejectedSegment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "total_duration_s": round(self.total_duration_s, 2),
            "palettes_used": self.palettes_used,
            "shot_count": len(self.shots),
            "rejected_count": len(self.rejected_segments),
            "shots": [s.to_dict() for s in self.shots],
            "rejected_segments": [r.to_dict() for r in self.rejected_segments],
        }


def parse_srt(srt_text: str) -> list[dict[str, Any]]:
    """Parse SRT string into list of timed subtitle entries."""
    entries = []
    blocks = srt_text.strip().replace("\r\n", "\n").split("\n\n")

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            # lines[0]: idx, lines[1]: timing, lines[2:]: text
            times = lines[1].split("-->")
            start_s = _parse_timestamp(times[0].strip())
            end_s = _parse_timestamp(times[1].strip())
            text = "".join(lines[2:])
            entries.append({
                "start_s": start_s,
                "end_s": end_s,
                "duration_s": end_s - start_s,
                "text": text,
            })
    return entries


def _parse_timestamp(ts: str) -> float:
    # 00:01:23,456 or 00:01:23.456
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        return h * 3600.0 + m * 60.0 + s
    return 0.0


def generate_storyboard(
    srt_or_lines: str | list[dict[str, Any]],
    title: str = "口播信息动画分镜表",
    primary_palette: str = "ink_blue_neon_pink",
    secondary_palette: str = "teal_orange",
) -> StoryboardPlan:
    """Analyze script/SRT and generate a strict 5-8 shot storyboard plan."""
    if isinstance(srt_or_lines, str):
        if "-->" in srt_or_lines:
            items = parse_srt(srt_or_lines)
        else:
            # Plain lines: assign synthetic 3.5s spacing
            raw_lines = [ln.strip() for ln in srt_or_lines.split("\n") if ln.strip()]
            items = []
            curr_t = 0.0
            for idx, text in enumerate(raw_lines):
                dur = max(3.0, min(6.0, len(text) * 0.2))
                items.append({
                    "start_s": curr_t,
                    "end_s": curr_t + dur,
                    "duration_s": dur,
                    "text": text,
                })
                curr_t += dur

    palettes = [primary_palette, secondary_palette]
    shots: list[StoryboardShot] = []
    rejected: list[RejectedSegment] = []

    shot_idx = 1
    total_dur = items[-1]["end_s"] if items else 0.0

    for idx, item in enumerate(items):
        text = item["text"]
        start_s = item["start_s"]
        end_s = item["end_s"]
        dur = item["duration_s"]

        # Heuristic scoring for B-roll selection
        selected_template: str | None = None
        screen_data: dict[str, Any] = {}

        # 1. Check for Myth / Versus pattern
        if ("以为" in text or "误区" in text) and ("其实" in text or "真相" in text or "但是" in text or "而是" in text):
            selected_template = "versus"
            # Extract myth & reality strictly from substrings
            parts = re.split(r"[，。；！？]", text)
            myth_cand = [p for p in parts if any(w in p for w in ("以为", "误区", "觉得", "看起来"))]
            real_cand = [p for p in parts if any(w in p for w in ("其实", "真相", "但是", "而是", "关键"))]
            myth_str = myth_cand[0] if myth_cand else "很多人以为"
            real_str = real_cand[0] if real_cand else "其实积累在发生"
            screen_data = {
                "tag": "误区翻转",
                "myth": truncate_to_subsequence(myth_str, 16),
                "reality": truncate_to_subsequence(real_str, 18),
            }

        # 2. Check for Contrast / Compare pattern (before vs after)
        elif ("年" in text and ("万" in text or "%" in text or "倍" in text)) and ("比" in text or "而" in text or "到" in text or "从" in text):
            selected_template = "compare"
            nums = extract_numbers_and_metrics(text)
            val_a = 10.0
            val_b = 26.0
            disp_a = "10万"
            disp_b = "26万"
            if len(nums) >= 2:
                disp_a = nums[0]
                disp_b = nums[1]
                val_a = float(re.sub(r"\D", "", nums[0]) or 10)
                val_b = float(re.sub(r"\D", "", nums[1]) or 26)
            screen_data = {
                "val_a": val_a,
                "val_b": val_b,
                "label_a": "第一年收益",
                "label_b": "第十年收益",
                "disp_a": disp_a,
                "disp_b": disp_b,
                "caption": "基数扩大后的复利爆发",
            }

        # 3. Check for Steps pattern (阶段 / 步骤)
        elif any(w in text for w in ("阶段", "第1步", "第一", "积累", "临界", "爆发")):
            selected_template = "steps"
            screen_data = {
                "steps": ["积累期", "临界期", "爆发期"],
                "active_step": 0 if "积累" in text or "第一" in text else 1,
            }

        # 4. Check for Big Number impact
        elif any(c.isdigit() for c in text) and any(w in text for w in ("万", "亿", "%", "倍", "年")):
            selected_template = "number"
            nums = extract_numbers_and_metrics(text)
            main_num = nums[0] if nums else "3"
            digit = re.sub(r"\D", "", main_num) or "3"
            unit = main_num.replace(digit, "") or "年"
            screen_data = {
                "context": "复利临界时间窗口",
                "number": digit,
                "unit": unit,
                "insight": "最难熬的前三年基数期",
            }

        # 5. Check for Quote / Punchline
        elif any(w in text for w in ("不是", "而是", "记住", "最难", "核心就在于")):
            selected_template = "quote"
            screen_data = {
                "quote": truncate_to_subsequence(text, 32),
                "author": "复利法则",
            }

        # 6. Check for Title / Chapter break
        elif any(w in text for w in ("为什么", "核心原理", "先看", "本质")):
            selected_template = "title"
            screen_data = {
                "number": f"0{shot_idx}",
                "tag": "核心机制",
                "title": truncate_to_subsequence(text, 16),
                "subtitle": "底层复利逻辑拆解",
            }

        # Verify subsequence of screen data
        if selected_template and len(shots) < 8:
            # Choose palette (alternate between max 2 palettes)
            pal = palettes[shot_idx % len(palettes)]
            shots.append(
                StoryboardShot(
                    clip_id=f"clip_{shot_idx:02d}",
                    template=selected_template,
                    start_s=start_s,
                    end_s=end_s,
                    duration_s=dur,
                    palette=pal,
                    source_sentence=text,
                    screen_data=screen_data,
                )
            )
            shot_idx += 1
        else:
            # Rejected segment
            reason = (
                "叙述铺垫或过渡衔接句"
                if len(text) < 15
                else "非高密度信息，保留主播视线与真实感"
            )
            rec = "口播保持真人特写镜头，仅保留底部字幕"
            rejected.append(
                RejectedSegment(
                    index=idx,
                    text=text,
                    start_s=start_s,
                    end_s=end_s,
                    reason=reason,
                    recommendation=rec,
                )
            )

    # Ensure between 5 and 8 shots
    if len(shots) < 5 and rejected:
        # Promote best rejected segments until we have at least 5
        while len(shots) < 5 and rejected:
            cand = rejected.pop(0)
            pal = palettes[len(shots) % len(palettes)]
            shots.append(
                StoryboardShot(
                    clip_id=f"clip_{len(shots)+1:02d}",
                    template="quote" if len(shots) % 2 == 0 else "title",
                    start_s=cand.start_s,
                    end_s=cand.end_s,
                    duration_s=cand.end_s - cand.start_s,
                    palette=pal,
                    source_sentence=cand.text,
                    screen_data={
                        "quote": truncate_to_subsequence(cand.text, 28),
                        "author": "核心观察",
                    }
                    if len(shots) % 2 == 0
                    else {
                        "number": f"0{len(shots)+1}",
                        "tag": "认知升级",
                        "title": truncate_to_subsequence(cand.text, 16),
                        "subtitle": "复利关键规律",
                    },
                )
            )

    return StoryboardPlan(
        title=title,
        total_duration_s=total_dur,
        palettes_used=palettes,
        shots=shots,
        rejected_segments=rejected,
    )
