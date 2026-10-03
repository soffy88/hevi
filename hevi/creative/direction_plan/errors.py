"""P10c plan validation errors."""

from __future__ import annotations


class PlanValidationError(ValueError):
    code: str = "PLAN_INVALID"

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        if code:
            self.code = code
