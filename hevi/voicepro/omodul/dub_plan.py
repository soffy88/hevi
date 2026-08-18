"""把字幕/对话编成 DubPlan(合句时钟 + 混音 + Cosy/F5 模式)。

组合 oskill.subtitle_timeline + vocal_remix + cosy_payload + f5_speakers。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.voicepro.oskill.cosy_payload import build_cosy_line
from hevi.voicepro.oskill.f5_speakers import conversation_turns, pick_catalog_model
from hevi.voicepro.oskill.subtitle_timeline import merge_and_split_cues, plan_timeline
from hevi.voicepro.oskill.vocal_remix import plan_vocal_remix
from hevi.voicepro.schemas import DubPlan, TimedCue


def cues_from_payload(items: list[dict[str, Any]] | list[TimedCue]) -> list[TimedCue]:
    cues: list[TimedCue] = []
    for item in items:
        if isinstance(item, TimedCue):
            cues.append(item)
            continue
        cues.append(
            TimedCue(
                start=float(item.get("start") or 0.0),
                end=float(item.get("end") or 0.0),
                text=str(item.get("text") or ""),
                speaker=str(item.get("speaker") or ""),
                emotion=str(item.get("emotion") or "neutral"),
            )
        )
    return cues


def plan_dub_artifacts(
    cues: list[dict[str, Any]] | list[TimedCue],
    *,
    language: str = "",
    keep_bed: bool = False,
    bed_path: str | Path | None = None,
    inference_mode: str | None = None,
    ref_text: str | None = None,
    instruct_text: str | None = None,
    model_name: str | None = None,
    conversation_text: str = "",
    clip_durations_s: list[float] | None = None,
    sentence_merge: bool = True,
) -> DubPlan:
    normalized = cues_from_payload(cues)
    if sentence_merge:
        merged = merge_and_split_cues(normalized, lang=language or None)
    else:
        merged = normalized
    if clip_durations_s is None:
        clip_durations_s = [max(cue.duration_s, 0.1) for cue in merged]
    count = min(len(merged), len(clip_durations_s))
    slots = plan_timeline(merged[:count], clip_durations_s[:count]) if count else []
    mix = plan_vocal_remix(
        keep_bed=keep_bed,
        bed_path=bed_path,
        bed_from_video=keep_bed and not bed_path,
    )
    first_text = merged[0].text if merged else " "
    cosy = build_cosy_line(
        text=first_text,
        ref_text=ref_text,
        instruct_text=instruct_text,
        requested_mode=inference_mode,
        model_name=model_name,
    )
    speakers = conversation_turns(conversation_text) if conversation_text.strip() else []
    f5_name = None
    if model_name or language:
        f5_name = pick_catalog_model(language, model_name)
    return DubPlan(
        cues=merged,
        slots=slots,
        mix=mix,
        cosy_mode=cosy.inference_mode,
        f5_model=f5_name,
        speakers=speakers,
    )
