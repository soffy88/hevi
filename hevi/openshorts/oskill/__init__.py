"""Deprecated compatibility shim; HEVI business orchestration lives in Layer4."""

from hevi.layer4_legacy.openshorts.oprim_impl import (
    detect_scenes_gemini,
    extract_transcript_with_words,
)
from hevi.openshorts.layer4_oskill import *  # noqa: F403
