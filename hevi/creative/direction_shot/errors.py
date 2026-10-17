"""P10-E ShotSpec error model: typed codes, no silent fallback."""

from __future__ import annotations


class ShotSpecError(ValueError):
    code: str = "SHOT_SPEC_INVALID"

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        if code:
            self.code = code


class ShotSpecImmutableError(ShotSpecError):
    """A revision's spec payload is written once and never rewritten."""

    code = "SHOT_REVISION_IMMUTABLE"


class ShotSpecNotFoundError(ShotSpecError):
    code = "SHOT_REVISION_NOT_FOUND"


class ChainBrokenError(ShotSpecError):
    """Recomputed hash disagrees with the stored one: tampering or drift."""

    code = "SHOT_CHAIN_BROKEN"
