"""P10b content validation errors."""

from __future__ import annotations


class ContentValidationError(ValueError):
    code: str = "CONTENT_INVALID"

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        if code:
            self.code = code
