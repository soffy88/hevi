from hevi.audio.audio_config import AudioProvider
from hevi.audio.audio_router import (
    AudioRoutingError,
    route_and_stitch_master_audio,
    route_single_cue,
)
from hevi.audio.avatar_service import generate_avatar_clip
from hevi.audio.bgm_library import BGMLibrary
from hevi.audio.funasr_verify import (
    FunASRUnavailableError,
    chunk_by_punctuation_with_limit,
    funasr_timestamp_generator,
    merge_chunks_with_asr_results,
)
from hevi.audio.tts_service import synthesize_dialogue

# VoiceBox 集成新增
from hevi.audio.effects import (
    EffectsChain,
    EffectConfig,
    apply_effects,
    apply_effects_to_array,
    list_presets as list_effect_presets,
)
from hevi.audio.paralinguistic import (
    ParaTag,
    TaggedSegment,
    parse_tags,
    strip_tags,
    generate_tag_audio,
    apply_paralinguistic_to_audio,
)
from hevi.audio.personality import (
    VoicePersona,
    PersonaResult,
    PersonalityEngine,
    get_preset_persona,
    list_preset_personas,
)
from hevi.audio.chatterbox_service import (
    ChatterboxConfig,
    ChatterboxService,
    create_chatterbox_multilingual,
    create_chatterbox_turbo,
)
from hevi.audio.kokoro_service import (
    KokoroConfig,
    KokoroService,
    create_kokoro,
)

# --- OmniVoice local pipeline ---
from hevi.audio.omnivoice_service import (
    OmniVoiceTaskType,
    VoiceCloneRequest,
    VoiceCloneResult,
    DubRequest,
    DubResult,
    AudiobookRequest,
    AudiobookResult,
    DictationRequest,
    DictationResult,
    DiarizeRequest,
    DiarizeResult,
    VoiceDesignRequest,
    VoiceDesignResult,
    clone_voice,
    dub_video,
    generate_audiobook,
    dictate,
    diarize,
    design_voice,
    list_local_voices,
    get_voice_info,
)
from hevi.audio.watermark import (
    AudioWatermarker,
    embed_watermark,
    detect_watermark,
)

__all__ = [
    "AudioProvider",
    "AudioRoutingError",
    "BGMLibrary",
    "FunASRUnavailableError",
    "chunk_by_punctuation_with_limit",
    "funasr_timestamp_generator",
    "generate_avatar_clip",
    "merge_chunks_with_asr_results",
    "route_and_stitch_master_audio",
    "route_single_cue",
    "synthesize_dialogue",
    # Effects
    "EffectsChain",
    "EffectConfig",
    "apply_effects",
    "apply_effects_to_array",
    "list_effect_presets",
    # Paralinguistic
    "ParaTag",
    "TaggedSegment",
    "parse_tags",
    "strip_tags",
    "generate_tag_audio",
    "apply_paralinguistic_to_audio",
    # Personality
    "VoicePersona",
    "PersonaResult",
    "PersonalityEngine",
    "get_preset_persona",
    "list_preset_personas",
    # Chatterbox
    "ChatterboxConfig",
    "ChatterboxService",
    "create_chatterbox_multilingual",
    "create_chatterbox_turbo",
    # Kokoro
    "KokoroConfig",
    "KokoroService",
    "create_kokoro",
    # OmniVoice
    "OmniVoiceTaskType",
    "VoiceCloneRequest",
    "VoiceCloneResult",
    "DubRequest",
    "DubResult",
    "AudiobookRequest",
    "AudiobookResult",
    "DictationRequest",
    "DictationResult",
    "DiarizeRequest",
    "DiarizeResult",
    "VoiceDesignRequest",
    "VoiceDesignResult",
    "clone_voice",
    "dub_video",
    "generate_audiobook",
    "dictate",
    "diarize",
    "design_voice",
    "list_local_voices",
    "get_voice_info",
    "AudioWatermarker",
    "embed_watermark",
    "detect_watermark",
]
