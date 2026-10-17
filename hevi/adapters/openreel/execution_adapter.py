"""P0.8 — the OpenReel execution adapter (§22, §54).

This is the boundary object §22 describes: ``OpenReelExecutionAdapter`` is a handler,
not an orchestration authority. It holds no ordering, no transaction, no verdict, and
no retry policy -- ``ProductionExecutor`` owns all of those.

Unavailable OpenReel fails loudly
----------------------------------
§54 requires HEVI core tests to pass with OpenReel absent, and §35 forbids swallowing
a failure. Both are satisfied by *raising a specific, named* exception rather than
returning an empty result: HEVI core never imports this module, so its absence cannot
break anything, and a caller that explicitly chose this adapter gets told exactly why
it cannot run.
"""

from __future__ import annotations

from hevi.adapters.openreel import (
    OpenReelAction,
    OpenReelArtifact,
    OpenReelRunner,
    OpenReelUnavailable,
)
from hevi.adapters.openreel.operation_mapper import map_operation
from hevi.production.execution_executor import ExecutionContext
from hevi.production.execution_result import AdapterError, ProductionExecutionResult
from hevi.production.operation import ProductionOperation


class OpenReelExecutionAdapter:
    """Maps a HEVI operation onto OpenReel and runs it through an injected runner.

    The runner is injected rather than imported, which is what makes this module
    importable with no OpenReel present -- the seam is real either way.
    """

    name = "openreel"

    def __init__(self, runner: OpenReelRunner | None = None) -> None:
        self.runner = runner

    def can_execute(self, operation: ProductionOperation) -> bool:
        from hevi.adapters.openreel.operation_mapper import UnsupportedOperation

        if self.runner is None or not self.runner.available():
            return False
        try:
            return bool(map_operation(operation))
        except UnsupportedOperation:
            return False

    def execute(
        self, operation: ProductionOperation, context: ExecutionContext
    ) -> ProductionExecutionResult:
        if self.runner is None or not self.runner.available():
            # Named and loud. Returning an empty successful result here would let a
            # production commit having produced nothing (§35).
            raise OpenReelUnavailable(
                f"OPENREEL_RUNTIME_UNAVAILABLE:{operation.operation_id}; the OpenReel "
                "runner is not available. HEVI core does not depend on it; this adapter "
                "is the only thing that does."
            )

        try:
            actions = map_operation(operation)
        except Exception as exc:
            raise AdapterError("capability_mismatch", str(exc)) from exc

        try:
            artifacts: tuple[OpenReelArtifact, ...] = self.runner.run_actions(
                actions, work_dir=context.work_dir
            )
        except Exception as exc:
            raise AdapterError("provider_unavailable", f"openreel run failed: {exc}") from exc

        return ProductionExecutionResult(
            operation_id=operation.operation_id,
            status="SUCCEEDED",
            artifacts=tuple(a.artifact_id for a in artifacts),
            metadata={
                f"hash:{a.artifact_id}": a.content_hash for a in artifacts
            }
            | {f"kind:{a.artifact_id}": a.kind for a in artifacts}
            | {f"uri:{a.artifact_id}": a.uri for a in artifacts},
        )

    @staticmethod
    def actions_for(operation: ProductionOperation) -> tuple[OpenReelAction, ...]:
        """The mapping, exposed for inspection and testing without a runner."""
        return map_operation(operation)


__all__ = ["OpenReelExecutionAdapter", "OpenReelUnavailable"]
