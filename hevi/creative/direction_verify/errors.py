"""P10d verification errors."""

from __future__ import annotations


class VerifyError(ValueError):
    code: str = "VERIFY_INVALID"

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        if code:
            self.code = code
