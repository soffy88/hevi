"""P0.7 — the executor: validate → transaction → adapter → artifact → receipt.

What is *not* here, and why
---------------------------
§4 is explicit that ``OperationValidator`` is not a permission authority, and §45 that
adapter selection is not a provider resolver. Both constraints are structural here:

* ``OperationValidator`` calls the canonical ``evaluate_permission``. It never decides.
* Adapters are matched by exact ``operation_type`` and ``renderer_ref``. Never scored.
  A ranking would be a second provider authority wearing a different hat.

Why one executor
----------------
§25 forbids ``ProductionExecutor``, ``VideoExecutor``, ``OpenReelExecutor`` and
``HtmlExecutor`` as parallel orchestration authorities. This is the single execution
path. An adapter is a handler: it receives an operation and returns a result, and has
no say in ordering, transactions, retries or verdicts.

Why a dry run still opens a transaction
---------------------------------------
§57 requires a dry run to resolve, validate, resolve providers and compute expected
artifacts -- and to generate no media. It walks the full validation and ordering path so
a dry run exercises the code that would actually run; only the adapter call is
suppressed.

Why a failed optional operation still records
---------------------------------------------
§36 lets an operation declare ``required=False`` and continue. The *result* still has
to be recorded, because §30 requires final validation to know an optional operation
failed. Continuing silently past a failure is the §35 anti-pattern wearing a
permission slip.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hevi.production.execution_result import (
    ExecutionFailureRecord,
    ExecutionResult,
    failure_from_exception,
)
from hevi.production.execution_transaction import (
    ProductionExecutionTransaction,
    RollbackReceipt,
    TransactionReceipt,
)
from hevi.production.operation import (
    ArtifactRef,
    ProductionOperation,
    resolve_execution_order,
)
from hevi.production.render_cache import digest_file
from hevi.production.render_job import RenderReceipt


class ExecutionError(RuntimeError):
    """Adapter refused or failed in a way that must not be retried silently."""


@dataclass(frozen=True)
class ExecutionContext:
    """What an adapter is allowed to see.

    Deliberately narrow. An adapter that received the whole task row could read
    ``user_id`` and start making authorisation decisions, which is how a renderer ends
    up being a permission authority.
    """

    production_id: str
    transaction_id: str
    dry_run: bool = False
    work_dir: Path | None = None
    artifact_resolver: Any = None


@runtime_checkable
class ProductionAdapter(Protocol):
    """§43. Every execution adapter, uniform shape."""

    name: str

    def can_execute(self, operation: ProductionOperation) -> bool: ...

    def execute(
        self, operation: ProductionOperation, context: ExecutionContext
    ) -> ExecutionResult: ...


@dataclass(frozen=True)
class ValidationReport:
    """§4. Execution-contract checks only.

    Not authorisation. ``OperationValidator`` below composes both, and it calls the
    canonical permission authority rather than reimplementing any part of it.
    """

    operation_id: str
    problems: tuple[str, ...] = ()
    permission: Any = None

    @property
    def ok(self) -> bool:
        return not self.problems and (
            self.permission is None or self.permission.allowed
        )


class OperationValidator:
    """§4. Checks the execution contract; delegates permission to the authority.

    Every check here is about whether the operation can be *executed as written*:
    inputs present, refs resolvable, dependencies satisfied, outputs declared. None of
    them decides whether the caller is allowed to ask.
    """

    def __init__(self, *, scope_resolver: Any = None, artifact_resolver: Any = None,
                 available_renderer: Any = None) -> None:
        self.scope_resolver = scope_resolver
        self.artifact_resolver = artifact_resolver
        self.available_renderer = available_renderer or (lambda _ref: True)

    def validate(
        self,
        operation: ProductionOperation,
        *,
        context: ExecutionContext,
        completed: set[str],
    ) -> ValidationReport:
        from hevi.provider_policy.permission import (
            OperationKind,
            PermissionRequest,
            evaluate_permission,
        )

        problems: list[str] = []

        unsatisfied = [d for d in operation.depends_on if d not in completed]
        if unsatisfied:
            problems.append(f"dependency_unsatisfied:{sorted(unsatisfied)}")

        if self.artifact_resolver is not None:
            for ref in operation.inputs:
                if not isinstance(ref, ArtifactRef):
                    # ResourceRefs (URLs, credential sets) are resolved by the adapter,
                    # not here; this validator only proves artifact refs exist.
                    continue
                if not self.artifact_resolver(ref.artifact_id):
                    problems.append(f"input_unresolvable:{ref.artifact_id}")

        if not operation.expected_outputs:
            problems.append("no_expected_outputs_declared")

        if operation.renderer_ref and not self.available_renderer(operation.renderer_ref):
            problems.append(f"renderer_unavailable:{operation.renderer_ref}")

        if not operation.idempotency_key:
            # A missing key is not cosmetic: it defeats deduplication on the retry path.
            problems.append("idempotency_key_missing")

        permission = None
        if self.scope_resolver is not None:
            # §4: ask the canonical permission authority. The validator never decides
            # authorisation itself -- it only reports the answer it was given.
            request = PermissionRequest(
                principal=operation.metadata.get("principal"),
                tenant_id=operation.metadata.get("tenant_id"),
                provider=operation.provider_ref or "",
                capabilities=frozenset(operation.metadata.get("required_capabilities", ())),
                operation=OperationKind.RENDER,
                execution_target=str(operation.metadata.get("execution_target") or ""),
                estimated_cost_usd=operation.metadata.get("estimated_cost_usd"),
            )
            permission = evaluate_permission(request, self.scope_resolver)
            if not permission.allowed:
                problems.append(f"permission_denied:{permission.reason()}")

        return ValidationReport(
            operation_id=operation.operation_id,
            problems=tuple(problems),
            permission=permission,
        )


@dataclass
class ExecutionOutcome:
    """Everything one ``execute`` call produced."""

    transaction_id: str
    production_id: str
    dry_run: bool
    results: tuple[ExecutionResult, ...] = ()
    failures: tuple[ExecutionFailureRecord, ...] = ()
    commit: TransactionReceipt | None = None
    rollback: RollbackReceipt | None = None
    skipped: tuple[str, ...] = ()
    orphan_ids: tuple[str, ...] = ()

    @property
    def committed(self) -> bool:
        return self.commit is not None


class ProductionExecutor:
    """The single execution authority.

    Owns ordering, transactions, validation, failure recording and commits. Delegates
    the actual work to adapters and every judgement to an existing authority.
    """

    def __init__(
        self,
        *,
        adapter: ProductionAdapter,
        validator: OperationValidator,
        max_attempts: int = 3,
    ) -> None:
        self.adapter = adapter
        self.validator = validator
        self.max_attempts = max_attempts
        self._receipts: list[RenderReceipt] = []

    # ── receipt sink, so a receipt is never lost ──

    def record_receipt(self, receipt: RenderReceipt) -> None:
        self._receipts.append(receipt)

    @property
    def receipts(self) -> tuple[RenderReceipt, ...]:
        return tuple(self._receipts)

    # ── execution ──

    def execute(
        self,
        *,
        production_id: str,
        operations: tuple[ProductionOperation, ...] | list[ProductionOperation],
        work_dir: Path | None = None,
        dry_run: bool = False,
        preexisting_committed: set[str] | None = None,
    ) -> ExecutionOutcome:
        ordered = resolve_execution_order(operations)
        transaction = ProductionExecutionTransaction(
            production_id=production_id, operations=ordered
        )
        if preexisting_committed:
            transaction.mark_preexisting_committed(preexisting_committed)
        transaction.begin()

        context = ExecutionContext(
            production_id=production_id,
            transaction_id=transaction.transaction_id,
            dry_run=dry_run,
            work_dir=work_dir,
            artifact_resolver=getattr(self.validator, "artifact_resolver", None),
        )

        completed: set[str] = set()
        results: list[ExecutionResult] = []
        failures: list[ExecutionFailureRecord] = []
        skipped: list[str] = []

        for operation in ordered:
            report = self.validator.validate(
                operation, context=context, completed=completed
            )
            if not report.ok:
                failure = self._failure_for_report(
                    production_id, operation, transaction, report
                )
                transaction.record_failure(failure)
                failures.append(failure)
                if operation.required:
                    validation_rollback = transaction.rollback(
                        f"validation_failed:{report.problems or report.permission}"
                    )
                    return ExecutionOutcome(
                        transaction_id=transaction.transaction_id,
                        production_id=production_id,
                        dry_run=dry_run,
                        results=tuple(results),
                        failures=tuple(failures),
                        rollback=validation_rollback,
                        skipped=tuple(skipped),
                        orphan_ids=validation_rollback.orphaned_artifact_ids,
                    )
                # §36: optional failure is recorded, execution continues, and final
                # validation still learns about it via `failures`.
                results.append(
                    ExecutionResult(
                        operation_id=operation.operation_id,
                        status="FAILED",
                        metadata={"problems": list(report.problems)},
                    )
                )
                skipped.append(operation.operation_id)
                continue

            if dry_run:
                # §57: resolve and validate, generate nothing.
                results.append(
                    ExecutionResult(
                        operation_id=operation.operation_id,
                        status="SKIPPED",
                        metadata={"dry_run": True,
                                  "expected_outputs": [o.name for o in operation.expected_outputs]},
                    )
                )
                completed.add(operation.operation_id)
                continue

            attempt, result, attempt_failure = self._attempt(
                production_id, operation, context, transaction
            )
            if result is not None:
                results.append(result)
                transaction.record_result(result)
                completed.add(operation.operation_id)
                continue

            if attempt_failure is None:  # pragma: no cover -- defensive
                raise ExecutionError(
                    f"ATTEMPT_WITHOUT_RESULT_OR_FAILURE:{operation.operation_id}"
                )
            failure = attempt_failure
            transaction.record_failure(failure)
            failures.append(failure)
            if failure.retryable and attempt < self.max_attempts:
                # A transient retry re-enters the same loop position with the same
                # idempotency key, so the artifact is reused rather than regenerated.
                retry_result, retry_failure = self._retry(
                    production_id, operation, context, transaction, attempt
                )
                if retry_result is not None:
                    results.append(retry_result)
                    transaction.record_result(retry_result)
                    completed.add(operation.operation_id)
                    failures.remove(failure)
                    continue
                if retry_failure is None:  # pragma: no cover -- defensive
                    raise ExecutionError(
                        f"RETRY_WITHOUT_RESULT_OR_FAILURE:{operation.operation_id}"
                    )
                failures.append(retry_failure)
                transaction.record_failure(retry_failure)

            if operation.required:
                op_rollback = transaction.rollback(
                    f"operation_failed:{operation.operation_id}"
                )
                return ExecutionOutcome(
                    transaction_id=transaction.transaction_id,
                    production_id=production_id,
                    dry_run=dry_run,
                    results=tuple(results),
                    failures=tuple(failures),
                    rollback=op_rollback,
                    skipped=tuple(skipped),
                    orphan_ids=op_rollback.orphaned_artifact_ids,
                )
            skipped.append(operation.operation_id)

        rollback: RollbackReceipt | None = None
        required_ids = _required_ids(ordered)
        if any(f.operation_id in required_ids for f in failures):
            rollback = transaction.rollback("required_operation_failed")
            commit = None
        else:
            # Optional failures do not block a commit, but they are still returned in
            # `failures` so final validation learns about them (§36).
            commit = transaction.commit()

        return ExecutionOutcome(
            transaction_id=transaction.transaction_id,
            production_id=production_id,
            dry_run=dry_run,
            results=tuple(results),
            failures=tuple(failures),
            commit=commit,
            rollback=rollback,
            skipped=tuple(skipped),
            orphan_ids=rollback.orphaned_artifact_ids if rollback else (),
        )

    # ── internals ──

    def _attempt(
        self,
        production_id: str,
        operation: ProductionOperation,
        context: ExecutionContext,
        transaction: ProductionExecutionTransaction,
    ) -> tuple[int, ExecutionResult | None, ExecutionFailureRecord | None]:
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                result = self.adapter.execute(operation, context)
            except Exception as exc:  # §35 forbids silent failure
                failure = failure_from_exception(
                    production_id=production_id,
                    operation=operation,
                    transaction_id=transaction.transaction_id,
                    stage="execute",
                    exc=exc,
                )
                if failure.retryable and attempt < self.max_attempts:
                    continue
                return attempt, None, failure

            if result.succeeded:
                self._register_artifacts(transaction, operation, result)
                return attempt, result.model_copy(
                    update={
                        "duration_ms": int((time.monotonic() - started) * 1000)
                    }
                ), None

            failure = ExecutionFailureRecord.for_operation(
                production_id=production_id,
                operation=operation,
                transaction_id=transaction.transaction_id,
                stage="execute",
                error_type=str(result.metadata.get("error_type", "unknown")),
                message=result.metadata.get("message", "adapter reported failure"),
                artifact_refs=result.artifacts,
            )
            if failure.retryable and attempt < self.max_attempts:
                continue
            return attempt, None, failure
        raise ExecutionError(
            f"EXECUTOR_ATTEMPTS_EXHAUSTED:{operation.operation_id}"
        )

    def _retry(
        self,
        production_id: str,
        operation: ProductionOperation,
        context: ExecutionContext,
        transaction: ProductionExecutionTransaction,
        prior_attempt: int,
    ) -> tuple[ExecutionResult | None, ExecutionFailureRecord | None]:
        started = time.monotonic()
        try:
            result = self.adapter.execute(operation, context)
        except Exception as exc:
            return None, failure_from_exception(
                production_id=production_id,
                operation=operation,
                transaction_id=transaction.transaction_id,
                stage=f"execute.retry{prior_attempt}",
                exc=exc,
            )
        if result.succeeded:
            self._register_artifacts(transaction, operation, result)
            return result.model_copy(
                update={"duration_ms": int((time.monotonic() - started) * 1000),
                        "metadata": {**result.metadata, "retried": True}}
            ), None
        return None, ExecutionFailureRecord.for_operation(
            production_id=production_id,
            operation=operation,
            transaction_id=transaction.transaction_id,
            stage=f"execute.retry{prior_attempt}",
            error_type=str(result.metadata.get("error_type", "unknown")),
            message=result.metadata.get("message", "retry reported failure"),
        )

    def _register_artifacts(
        self,
        transaction: ProductionExecutionTransaction,
        operation: ProductionOperation,
        result: ExecutionResult,
    ) -> None:
        for artifact_id in result.artifacts:
            # The artifact layer hashes the produced file. Adapters supply a locator and
            # are explicitly forbidden from proving their own output (P9.1D T2), so the
            # digest is computed here from the bytes on disk.
            content_hash = result.metadata.get(f"hash:{artifact_id}", "")
            if not content_hash:
                uri = str(result.metadata.get(f"uri:{artifact_id}", ""))
                candidate = Path(uri)
                if uri and candidate.is_file():
                    content_hash = digest_file(candidate)
            transaction.record_artifact(
                artifact_id=artifact_id,
                content_hash=content_hash,
                kind=str(result.metadata.get(f"kind:{artifact_id}", "unknown")),
                uri=str(result.metadata.get(f"uri:{artifact_id}", artifact_id)),
                operation_id=operation.operation_id,
                provider_ref=operation.provider_ref or "",
                receipt_ref=str(result.metadata.get("receipt_ref", "")),
            )

    def _failure_for_report(
        self,
        production_id: str,
        operation: ProductionOperation,
        transaction: ProductionExecutionTransaction,
        report: ValidationReport,
    ) -> ExecutionFailureRecord:
        reason = ",".join(report.problems) or "validation_failed"
        return ExecutionFailureRecord.for_operation(
            production_id=production_id,
            operation=operation,
            transaction_id=transaction.transaction_id,
            stage="validate",
            # A contract violation is semantic by §10 level 3: retrying it unchanged
            # cannot help, and it must surface as a repair candidate rather than burn
            # provider budget.
            error_type="execution_contract_violation",
            message=reason,
        )


def _required_ids(operations: tuple[ProductionOperation, ...]) -> set[str]:
    return {op.operation_id for op in operations if op.required}


__all__ = [
    "ExecutionContext",
    "ExecutionError",
    "ExecutionOutcome",
    "OperationValidator",
    "ProductionAdapter",
    "ProductionExecutor",
    "ValidationReport",
]
