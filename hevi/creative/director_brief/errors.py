"""S1 director-brief error model: typed codes, no silent default.

Every contract violation raises. A malformed or ambiguous direction input is a
hard failure, never a defaulted field — a silent default erases creative intent.
"""

from __future__ import annotations


class DirectorBriefError(ValueError):
    code: str = "DIRECTOR_BRIEF_INVALID"

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        if code:
            self.code = code