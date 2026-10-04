"""Generation contract errors. Fail-closed codes (spec §14)."""

from __future__ import annotations


class GenerationError(RuntimeError):
    code: str = "GENERATION_FAILED"

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        if code:
            self.code = code


class CapabilityUnsupported(GenerationError):
    code = "CAPABILITY_UNSUPPORTED"


class ContinuationStateMissing(GenerationError):
    """continuation_required=True 但无 state —— 不得降级为独立 T2V(spec §12)。"""

    code = "CONTINUATION_STATE_MISSING"


class ConditioningWindowInvalid(GenerationError):
    code = "CONDITIONING_WINDOW_INVALID"


class SilentFallbackDetected(GenerationError):
    """provider 声称 continuation 却静默退回 T2V(spec §14)。"""

    code = "SILENT_FALLBACK"


class MediaIntegrityError(GenerationError):
    code = "MEDIA_INTEGRITY_FAILED"


class ValidationArtifactMissing(GenerationError):
    code = "VALIDATION_ARTIFACT_MISSING"