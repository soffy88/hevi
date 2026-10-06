"""P9.1.d — Remotion adapter: execute only.

Delegates to ``hevi/providers/remotion/driver.py`` so the npx invocation has exactly
one site. Returns a locator; the framework proves the artifact.
"""

from __future__ import annotations

from hevi.qualification.models import (
    AdapterAvailability,
    AdapterFailure,
    Availability,
    ExecutionResult,
    ExecutionState,
    QualificationRequest,
    RuntimeUnavailable,
)
from hevi.qualification.providers._shared import check_locator, result_for, unavailable


class RemotionAdapter:
    """Executes `npx remotion render`. Returns a locator."""

    provider_id = "remotion"

    def available(self) -> AdapterAvailability:
        from hevi.providers.remotion import probe_runtime

        reason = probe_runtime()
        return unavailable(reason) if reason else AdapterAvailability(Availability.AVAILABLE)

    def execute(self, request: QualificationRequest) -> ExecutionResult:
        from hevi.providers.remotion import RemotionUnavailable, render

        composition = str(request.params.get("composition", "MotionGraphics"))
        try:
            locator = render(
                composition, request.output_path, timeout_s=request.timeout_s,
            )
        except RemotionUnavailable as exc:
            raise RuntimeUnavailable(str(exc)) from exc
        except RuntimeError as exc:
            raise AdapterFailure(ExecutionState.FAILED, str(exc)) from exc
        check_locator(request, self.provider_id)
        return result_for(
            request,
            {"runtime_class": "local_process", "composition": composition,
             "exit_code": "0", "props_path": locator.props_path},
        )


__all__ = ["RemotionAdapter"]
