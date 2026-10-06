"""The single media validation authority, seen from the legacy qualification surface.

P9.0.1 consolidation
--------------------
Two media validation contracts existed:

    hevi/qualification/media.py   path in, `passed` declared   (pre-existing)
    hevi/artifact + hevi/validation   bytes in, `passed` derived (P8.4)

Both answered "is this media usable", and a caller had no way to know which one was
production truth. That is the same shape as the ``ExecutionReceipt`` and
``AcquisitionState`` collisions P8.2 and P8.3 resolved: two answers, one question.

So this module is no longer an authority. It is a **view** over P8.4:

* observation comes from ``hevi.artifact.probes`` — bytes, read and hashed
* ``passed`` is **derived**, never supplied
* non-emptiness is proven by **reading the bytes**, not by ``stat()``
* :meth:`MediaValidation.to_validation_result` returns the one canonical result

``validate_media(path)`` keeps its signature and its error vocabulary because it has
live consumers (``scripts/real_line_qualification.py``,
``tests/qualification/test_framework.py``). A path is accepted only as a *locator* for
reading bytes; it is never itself the proof. That distinction is the whole point —
``artifact_exists() != production_success``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.artifact.probes import probe_containerised
from hevi.evidence.acquisition import checksum_bytes
from hevi.validation.artifact import CheckOperator, ValidationCheck, ValidationResult


@dataclass(frozen=True)
class MediaValidation:
    """A validation result, in the shape legacy qualification consumers expect.

    ``passed`` is a property, not a field. It was a field before P9.0.1, which meant a
    caller could assert a verdict without anything being observed — the exact defect
    P8.4 removed from ``ValidationCheck``.
    """

    path: str
    exists: bool
    nonzero: bool
    ffprobe_valid: bool
    duration_s: float | None
    video_stream: bool
    audio_stream: bool
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    errors: list[str] = field(default_factory=list)
    checksum: str = ""
    observed_checksum: str = ""

    @property
    def passed(self) -> bool:
        """Derived from the observations. There is no way to declare this true."""
        return (
            self.exists
            and self.nonzero
            and self.ffprobe_valid
            and not self.errors
        )

    def to_validation_result(self) -> ValidationResult:
        """The canonical P8.4 result behind this view."""
        checks = (
            ValidationCheck("exists", observed=self.exists, expected=True),
            ValidationCheck("nonempty", observed=self.nonzero, expected=True),
            ValidationCheck("probeable", observed=self.ffprobe_valid, expected=True),
            ValidationCheck(
                "no_errors", observed=not self.errors, expected=True,
                detail=", ".join(self.errors),
            ),
        )
        return ValidationResult(
            validator="qualification.media",
            checks=checks,
            observed_checksum=self.observed_checksum or self.checksum,
            artifact_id=Path(self.path).name,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "nonzero": self.nonzero,
            "ffprobe_valid": self.ffprobe_valid,
            "duration_s": self.duration_s,
            "video_stream": self.video_stream,
            "audio_stream": self.audio_stream,
            "codec": self.codec,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "errors": list(self.errors),
            "checksum": self.checksum,
            # derived, so included explicitly rather than via asdict()
            "passed": self.passed,
        }


def _result(**kwargs: Any) -> MediaValidation:
    defaults: dict[str, Any] = {
        "path": "", "exists": False, "nonzero": False, "ffprobe_valid": False,
        "duration_s": None, "video_stream": False, "audio_stream": False,
        "codec": None, "width": None, "height": None, "fps": None, "errors": [],
        "checksum": "", "observed_checksum": "",
    }
    defaults.update(kwargs)
    return MediaValidation(**defaults)


def validate_media(path: str | Path, *, require_audio: bool = False) -> MediaValidation:
    """Validate media at ``path``.

    The path is a locator. The proof is the bytes behind it: they are read, hashed, and
    measured through the shared byte probe. A file that exists but cannot be read is
    reported as such, where the previous version inferred content from ``stat()``.
    """
    target = Path(path)
    errors: list[str] = []

    if not target.exists():
        errors.append("artifact_missing")
        return _result(path=str(path), exists=False, errors=errors)

    try:
        payload = target.read_bytes()
    except OSError as exc:
        errors.append(f"artifact_unreadable:{type(exc).__name__}")
        return _result(path=str(path), exists=True, errors=errors)

    # non-emptiness proven by reading, not by stat()
    if not payload:
        errors.append("artifact_empty")
        return _result(
            path=str(path), exists=True, nonzero=False,
            checksum=checksum_bytes(payload),
            observed_checksum=checksum_bytes(payload), errors=errors,
        )

    observed = probe_containerised(payload)
    codec = observed.get("codec")
    width, height = observed.get("width"), observed.get("height")
    duration = observed.get("duration")
    has_audio = bool(observed.get("has_audio"))
    probeable = bool(codec)

    if not probeable:
        errors.append("ffprobe_parse_failed")
    if require_audio and not has_audio:
        errors.append("audio_missing")

    return _result(
        path=str(path),
        exists=True,
        nonzero=True,
        ffprobe_valid=probeable,
        duration_s=float(duration) if duration is not None else None,
        video_stream=bool(width and height),
        audio_stream=has_audio,
        codec=codec,
        width=width,
        height=height,
        fps=observed.get("fps"),
        errors=errors,
        checksum=checksum_bytes(payload),
        observed_checksum=observed.get("checksum", checksum_bytes(payload)),
    )


__all__ = ["CheckOperator", "MediaValidation", "ValidationResult", "validate_media"]
