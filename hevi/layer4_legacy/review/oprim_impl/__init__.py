"""Atomic review primitives (oprim layer, local-only, keyword-only public API)."""

from hevi.layer4_legacy.review.oprim_impl.contracts import (
    FrameCheck,
    ProbeReport,
    ReviewVerdict,
)
from hevi.layer4_legacy.review.oprim_impl.frames import (
    build_contact_sheet,
    dense_sample_frames,
    frame_phash,
    frame_stats,
    hamming_distance,
    interframe_delta,
    sample_frames,
)
from hevi.layer4_legacy.review.oprim_impl.media import (
    FFMPEG,
    FFPROBE,
    MediaError,
    probe_media,
    run_ffmpeg,
)

__all__ = [
    "FFMPEG",
    "FFPROBE",
    "FrameCheck",
    "MediaError",
    "ProbeReport",
    "ReviewVerdict",
    "build_contact_sheet",
    "dense_sample_frames",
    "frame_phash",
    "frame_stats",
    "hamming_distance",
    "interframe_delta",
    "probe_media",
    "run_ffmpeg",
    "sample_frames",
]
