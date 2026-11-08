"""Daily output retention for the media pipelines.

The renderers write per-sentence intermediates (TTS wav, segment mp4, frame
pngs, evidence jpgs) next to the final deliverable.  Without a policy the
output tree grows forever.  This module keeps:

* ``verify_*`` directories — manual verification evidence, never touched;
* ``_archive`` directories — archived, removed canvas branches;
* final deliverables for ``HEVI_OUTPUT_FINAL_DAYS`` days (default 30);
* everything else for ``HEVI_OUTPUT_INTERMEDIATE_DAYS`` days (default 7).

Configured through env so the scheduler can be tuned without a rebuild::

    HEVI_OUTPUT_RETENTION_ENABLED=1
    HEVI_OUTPUT_ROOT=output
    HEVI_OUTPUT_INTERMEDIATE_DAYS=7
    HEVI_OUTPUT_FINAL_DAYS=30
    HEVI_OUTPUT_RETENTION_INTERVAL_S=86400

Everything is best-effort: permission errors are counted, never raised.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_PROTECTED_DIR_PREFIXES = ("verify_", "_archive")
_MEDIA_SUFFIXES = frozenset(
    {
        ".mp4", ".mov", ".webm", ".mkv",
        ".wav", ".mp3", ".m4a", ".aac", ".flac",
        ".png", ".jpg", ".jpeg", ".webp",
        ".srt", ".ass", ".vtt", ".fcpxml", ".txt", ".json", ".csv", ".log",
    }
)
_FINAL_STEMS = frozenset({"final", "film", "film_v2", "koubo_cut", "clip"})


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _roots() -> list[Path]:
    raw = os.getenv("HEVI_OUTPUT_ROOT", "output")
    return [Path(part.strip()) for part in raw.split(",") if part.strip()]


def _is_final(path: Path) -> bool:
    stem = path.stem.lower()
    return stem in _FINAL_STEMS or stem.startswith("final") or stem.endswith(".final")


@dataclass
class RetentionSummary:
    roots: list[str] = field(default_factory=list)
    deleted_files: int = 0
    deleted_bytes: int = 0
    kept_finals: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "roots": self.roots,
            "deleted_files": self.deleted_files,
            "deleted_bytes": self.deleted_bytes,
            "kept_finals": self.kept_finals,
            "errors": self.errors,
        }


def purge_intermediate_outputs(
    *,
    now: float | None = None,
    intermediate_days: float | None = None,
    final_days: float | None = None,
) -> RetentionSummary:
    """Delete stale intermediates under the configured output roots."""
    summary = RetentionSummary()
    if os.getenv("HEVI_OUTPUT_RETENTION_ENABLED", "1").strip() in ("0", "false", "False"):
        return summary
    current = time.time() if now is None else now
    intermediate_cutoff = current - 86400 * (
        _env_float("HEVI_OUTPUT_INTERMEDIATE_DAYS", 7.0)
        if intermediate_days is None
        else intermediate_days
    )
    final_cutoff = current - 86400 * (
        _env_float("HEVI_OUTPUT_FINAL_DAYS", 30.0) if final_days is None else final_days
    )
    for root in _roots():
        summary.roots.append(str(root))
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            current_dir = Path(dirpath)
            # Never descend into verification or archive evidence.
            dirnames[:] = [
                name for name in dirnames
                if not name.startswith(_PROTECTED_DIR_PREFIXES)
            ]
            for filename in filenames:
                path = current_dir / filename
                if path.suffix.lower() not in _MEDIA_SUFFIXES:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    summary.errors += 1
                    continue
                cutoff = final_cutoff if _is_final(path) else intermediate_cutoff
                if stat.st_mtime > cutoff:
                    if _is_final(path):
                        summary.kept_finals += 1
                    continue
                try:
                    path.unlink()
                except OSError:
                    summary.errors += 1
                    continue
                summary.deleted_files += 1
                summary.deleted_bytes += stat.st_size

    if summary.deleted_files:
        logger.info(
            "output retention removed %d file(s), %.1f MB",
            summary.deleted_files,
            summary.deleted_bytes / 1048576,
        )
    return summary


__all__ = ["RetentionSummary", "purge_intermediate_outputs"]
