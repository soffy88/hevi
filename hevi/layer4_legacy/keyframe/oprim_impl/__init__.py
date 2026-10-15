"""Keyframe engine primitives."""

from hevi.layer4_legacy.keyframe.oprim_impl.character_card import CharacterCard
from hevi.layer4_legacy.keyframe.oprim_impl.cloud_stub_engine import CloudStubKeyframeEngine
from hevi.layer4_legacy.keyframe.oprim_impl.contracts import KeyframeEngine, KeyframeResult
from hevi.layer4_legacy.keyframe.oprim_impl.face_gate import (
    compute_face_cosine,
    detect_faces,
    extract_face_embedding,
    verify_character_face,
)
from hevi.layer4_legacy.keyframe.oprim_impl.fake_engine import FakeKeyframeEngine
from hevi.layer4_legacy.keyframe.oprim_impl.image_score import (
    compute_clip_similarity,
    compute_exposure_score,
    compute_laplacian_sharpness,
    detect_bad_image,
    score_keyframe,
)
from hevi.layer4_legacy.keyframe.oprim_impl.lock import cpu_render_lock
from hevi.layer4_legacy.keyframe.oprim_impl.registry import (
    get_engine,
    register_engine,
    resolve_keyframe_engine,
)
from hevi.layer4_legacy.keyframe.oprim_impl.sdturbo_engine import (
    SDTurboCPUEngine,
    SDXLTurboCPUEngine,
)
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import (
    DEFAULT_STYLE,
    STYLE_PRESETS,
    StylePreset,
    get_style_preset,
    list_style_presets,
)

__all__ = [
    "DEFAULT_STYLE",
    "STYLE_PRESETS",
    "CharacterCard",
    "CloudStubKeyframeEngine",
    "FakeKeyframeEngine",
    "KeyframeEngine",
    "KeyframeResult",
    "SDTurboCPUEngine",
    "SDXLTurboCPUEngine",
    "StylePreset",
    "compute_clip_similarity",
    "compute_exposure_score",
    "compute_face_cosine",
    "compute_laplacian_sharpness",
    "cpu_render_lock",
    "detect_bad_image",
    "detect_faces",
    "extract_face_embedding",
    "get_engine",
    "get_style_preset",
    "list_style_presets",
    "register_engine",
    "resolve_keyframe_engine",
    "score_keyframe",
    "verify_character_face",
]
