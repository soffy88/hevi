"""oskill:每个技能组合 ≥2 个 oprim 原语。不得 import omodul。"""

from __future__ import annotations

from hevi.layer4_legacy.voicepro.oskill_impl.cosy_payload import (
    bind_cosy_reference,
    build_cosy_line,
    build_engine_script,
    resolve_cosy_reference,
)
from hevi.layer4_legacy.voicepro.oskill_impl.f5_speakers import (
    BoundTurn,
    SpeakerRef,
    conversation_turns,
    pick_catalog_model,
    resolve_turns,
)
from hevi.layer4_legacy.voicepro.oskill_impl.native_voice import (
    NativeAudioChunk,
    NativeVoiceResult,
    native_voice_available,
    stream_native_voice,
    synthesize_native_batch,
    synthesize_native_voice,
    synthesize_native_voice_sync,
)
from hevi.layer4_legacy.voicepro.oskill_impl.subtitle_timeline import (
    merge_and_split_cues,
    plan_timeline,
)
from hevi.layer4_legacy.voicepro.oskill_impl.translate_retry import fill_missing_lines, retry_one
from hevi.layer4_legacy.voicepro.oskill_impl.vocal_remix import (
    mux_args_for_plan,
    plan_vocal_remix,
    stem_split_command,
)

__all__ = [
    "BoundTurn",
    "SpeakerRef",
    "bind_cosy_reference",
    "build_cosy_line",
    "build_engine_script",
    "resolve_cosy_reference",
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
    "NativeAudioChunk",
    "NativeVoiceResult",
    "native_voice_available",
    "stream_native_voice",
    "synthesize_native_batch",
    "synthesize_native_voice",
    "synthesize_native_voice_sync",
]
