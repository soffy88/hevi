"""oprim:Voice-Pro 配音无状态原子。不得 import oskill / omodul。"""

from __future__ import annotations

from hevi.voicepro.oprim.cosy_mode import (
    CV3_SYSTEM_PROMPT,
    apply_cv3_prefix,
    cv3_fields_for_mode,
    detect_family,
    needs_cv3_prefix,
    normalize_mode,
    resolve_inference_mode,
)
from hevi.voicepro.oprim.cue_clock import (
    MAX_MERGE_GAP_S,
    MIN_DURATION_S,
    char_weighted_spans,
    complete_sentence,
    detect_lang_hint,
    group_cues,
    is_complete_sentence,
    join_group_text,
    merge_sentence_fragments,
    normalize_text,
    should_break_group,
    split_into_sentences,
)
from hevi.voicepro.oprim.f5_catalog import (
    get_model,
    infer_language,
    list_models,
    load_catalog,
    parse_conversation,
    pick_model_for_language,
)
from hevi.voicepro.oprim.mix_levels import (
    choose_strategy,
    demucs_separate_args,
    ffmpeg_remix_args,
    ffmpeg_replace_args,
    plan_mix,
    remix_filter,
)
from hevi.voicepro.oprim.native_voice import (
    VoiceConditioning,
    normalize_voice_text,
    probe_reference_audio,
    resolve_voice_conditioning,
    split_voice_text,
)
from hevi.voicepro.oprim.timeline_pad import (
    leading_silence_ms,
    place_clips_on_clock,
    s_to_ms,
    total_timeline_ms,
)
from hevi.voicepro.oprim.translate_backoff import (
    MAX_RETRIES,
    merge_batch_and_retries,
    retry_delays,
    should_keep_original,
)

__all__ = [
    "CV3_SYSTEM_PROMPT",
    "MAX_MERGE_GAP_S",
    "MAX_RETRIES",
    "MIN_DURATION_S",
    "apply_cv3_prefix",
    "char_weighted_spans",
    "choose_strategy",
    "complete_sentence",
    "cv3_fields_for_mode",
    "demucs_separate_args",
    "detect_family",
    "detect_lang_hint",
    "ffmpeg_remix_args",
    "ffmpeg_replace_args",
    "get_model",
    "group_cues",
    "infer_language",
    "is_complete_sentence",
    "join_group_text",
    "leading_silence_ms",
    "list_models",
    "load_catalog",
    "merge_batch_and_retries",
    "merge_sentence_fragments",
    "needs_cv3_prefix",
    "normalize_mode",
    "normalize_text",
    "parse_conversation",
    "pick_model_for_language",
    "place_clips_on_clock",
    "plan_mix",
    "remix_filter",
    "resolve_inference_mode",
    "retry_delays",
    "s_to_ms",
    "should_break_group",
    "should_keep_original",
    "split_into_sentences",
    "total_timeline_ms",
    "VoiceConditioning",
    "normalize_voice_text",
    "probe_reference_audio",
    "resolve_voice_conditioning",
    "split_voice_text",
]
