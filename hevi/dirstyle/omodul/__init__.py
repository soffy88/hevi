"""Deprecated compatibility shim; canonical HEVI implementation is Layer4-owned."""
from hevi.layer4_legacy.dirstyle.omodul_impl.grade import (  # noqa: F401
    GradeResult,
    build_filter_chain,
    probe_video,
    run_style_grade,
    sha256_file,
    signalstats_mean,
)

__all__ = [
    "GradeResult",
    "build_filter_chain",
    "probe_video",
    "run_style_grade",
    "sha256_file",
    "signalstats_mean",
]
