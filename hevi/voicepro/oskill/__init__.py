"""oskill:每个技能组合 ≥2 个 oprim 原语。不得 import omodul。"""

from __future__ import annotations

from hevi.voicepro.oskill.cosy_payload import build_cosy_line, build_engine_script
from hevi.voicepro.oskill.f5_speakers import (
    BoundTurn,
    SpeakerRef,
    conversation_turns,
    pick_catalog_model,
    resolve_turns,
)
from hevi.voicepro.oskill.subtitle_timeline import merge_and_split_cues, plan_timeline
from hevi.voicepro.oskill.translate_retry import fill_missing_lines, retry_one
from hevi.voicepro.oskill.vocal_remix import mux_args_for_plan, plan_vocal_remix, stem_split_command

__all__ = [
    "BoundTurn",
    "SpeakerRef",
    "build_cosy_line",
    "build_engine_script",
    "conversation_turns",
    "fill_missing_lines",
    "merge_and_split_cues",
    "mux_args_for_plan",
    "pick_catalog_model",
    "plan_timeline",
    "plan_vocal_remix",
    "resolve_turns",
    "retry_one",
    "stem_split_command",
]
