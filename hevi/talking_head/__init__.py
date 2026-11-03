"""Talking-head pipeline (portrait + script -> lip-synced MP4, gated).

Sibling of ``hevi.storyfilm``: a preset-free, single-presenter line.
See :mod:`hevi.talking_head.pipeline` for the orchestration, failure
policy and CLI.  Imports here are deliberately light — the heavy stage
dependencies (LuxTTS HTTP, faster-whisper, Wav2Lip/MuseTalk ONNX,
earshot) load inside the stage functions, never at package import.
"""

from __future__ import annotations

from hevi.talking_head.gates import (
    earshot_gate,
    is_black_luma,
    normalize_for_compare,
    run_all_gates,
    summarize_frames,
    text_similarity,
    visual_gate,
    whisper_gate,
)
from hevi.talking_head.pipeline import TalkingHeadConfig, main, run_talking_head
from hevi.talking_head.preflight import (
    assess_frontal,
    check_voice_sample_metadata,
    estimate_script_seconds,
    run_preflight,
    validate_portrait,
    validate_script,
    validate_voice_sample,
)
from hevi.talking_head.state import Ledger, finalize_status, new_ledger, validate_ledger

__all__ = [
    "Ledger",
    "TalkingHeadConfig",
    "assess_frontal",
    "check_voice_sample_metadata",
    "earshot_gate",
    "estimate_script_seconds",
    "finalize_status",
    "is_black_luma",
    "main",
    "new_ledger",
    "normalize_for_compare",
    "run_all_gates",
    "run_preflight",
    "run_talking_head",
    "summarize_frames",
    "text_similarity",
    "validate_ledger",
    "validate_portrait",
    "validate_script",
    "validate_voice_sample",
    "visual_gate",
    "whisper_gate",
]
