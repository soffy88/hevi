"""Durable, idempotent side-effect orchestration over the existing runtime.

This module supplies the semantic envelope and a small reference store used by
tests/local workers. Production deployments can implement the same store
protocol with the existing MPT/attempt tables. The ordering is the contract:
intent is persisted before ``send`` and the provider job is persisted before
polling or downloading an artifact.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any, Protocol

from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.compiler.adapters import ProviderAdapter
from hevi.production_graph.domain import CanonicalShot, ExecutionPlan, TaskEnvelope
from hevi.production_graph.ids import new_id
from hevi.production_graph.readiness import assert_dispatchable


class IdempotencyConflictError(RuntimeError):
    """The same idempotency key was presented for a different execution."""


class _RejectDispatch(ValueError):
    """Canonical dispatch rejected because the shot is not READY."""


class DurableExecutionStore(Protocol):
    async def persist_intent(self, envelope: TaskEnvelope) -> TaskEnvelope: ...

    async def save(self, envelope: TaskEnvelope) -> TaskEnvelope: ...

    async def get_by_idempotency(self, key: str) -> TaskEnvelope | None: ...


class DurableExecutionResult(BaseModel):
    status: str
    envelope: TaskEnvelope
    provider_job_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    provider_result: dict[str, Any] = Field(default_factory=dict)


class InMemoryDurableExecutionStore:
    """A deterministic store for contract tests; production uses DB-backed MPT."""

    def __init__(self) -> None:
        self.records: dict[str, TaskEnvelope] = {}
        self.events: list[tuple[str, str]] = []

    async def persist_intent(self, envelope: TaskEnvelope) -> TaskEnvelope:
        current = self.records.get(envelope.idempotency_key)
        if current is not None:
            if current.execution_plan_id != envelope.execution_plan_id:
                raise IdempotencyConflictError(
                    f"idempotency key already belongs to plan {current.execution_plan_id}"
                )
            self.events.append(("intent_reused", envelope.idempotency_key))
            return deepcopy(current)
        saved = deepcopy(envelope)
        self.records[envelope.idempotency_key] = saved
        self.events.append(("intent_persisted", envelope.idempotency_key))
        return deepcopy(saved)

    async def save(self, envelope: TaskEnvelope) -> TaskEnvelope:
        current = self.records.get(envelope.idempotency_key)
        if current is not None and current.execution_plan_id != envelope.execution_plan_id:
            raise IdempotencyConflictError(
                f"idempotency key already belongs to plan {current.execution_plan_id}"
            )
        self.records[envelope.idempotency_key] = deepcopy(envelope)
        self.events.append((f"envelope:{envelope.status}", envelope.idempotency_key))
        return deepcopy(envelope)

    async def get_by_idempotency(self, key: str) -> TaskEnvelope | None:
        record = self.records.get(key)
        return deepcopy(record) if record is not None else None


class PostgresDurableExecutionStore:
    """Persist envelopes in the canonical entity index beside MPT attempts.

    MPT/AttemptRepository remains the worker-attempt authority. This store is
    the semantic envelope layer and uses the same PostgreSQL transaction
    boundary, so a restart can recover the provider job ID before polling.
    """

    def __init__(self, pool: PgPool) -> None:
        self.pool = pool
        self._notices: list[str] = []

    @property
    def notices(self) -> list[str]:
        return list(self._notices)

    def _emit_notice(self, message: str) -> None:
        self._notices.append(message)

    async def persist_intent(self, envelope: TaskEnvelope) -> TaskEnvelope:
        async with self.pool.acquire() as conn, conn.transaction():
            self._emit_notice(f"persist_intent:{envelope.idempotency_key}")
            row = await conn.fetchrow(
                """
                SELECT payload FROM production_graph_entities
                WHERE project_id = $1 AND entity_type = 'task_envelope'
                  AND payload->>'idempotency_key' = $2
                FOR UPDATE
                """,
                _as_uuid(envelope.project_id),
                envelope.idempotency_key,
            )
            if row is not None:
                current = TaskEnvelope.model_validate(row["payload"])
                if current.execution_plan_id != envelope.execution_plan_id:
                    raise IdempotencyConflictError(
                        "idempotency key belongs to another execution plan"
                    )
                self._emit_notice(f"intent_reused:{envelope.idempotency_key}")
                return current
            await self._insert(conn, envelope)
            self._emit_notice(f"intent_persisted:{envelope.idempotency_key}")
            return envelope

    async def save(self, envelope: TaskEnvelope) -> TaskEnvelope:
        async with self.pool.acquire() as conn, conn.transaction():
            self._emit_notice(f"save:{envelope.idempotency_key}")
            await self._insert(conn, envelope, upsert=True)
        self._emit_notice(f"save_complete:{envelope.idempotency_key}")
        return envelope

    async def get_by_idempotency(self, key: str) -> TaskEnvelope | None:
        async with self.pool.acquire() as conn:
            self._emit_notice(f"get_by_idempotency:{key}")
            row = await conn.fetchrow(
                """
                SELECT payload FROM production_graph_entities
                WHERE entity_type = 'task_envelope' AND payload->>'idempotency_key' = $1
                LIMIT 1
                """,
                key,
            )
        result = TaskEnvelope.model_validate(row["payload"]) if row else None
        self._emit_notice(f"get_by_idempotency_result:{key}:{result is not None}")
        return result

    async def _insert(self, conn: Any, envelope: TaskEnvelope, *, upsert: bool = False) -> None:
        conflict = (
            "ON CONFLICT (revision_id, entity_type, entity_id) DO UPDATE SET payload = EXCLUDED.payload"
            if upsert
            else "ON CONFLICT DO NOTHING"
        )
        await conn.execute(
            f"""
            INSERT INTO production_graph_entities
                (project_id, revision_id, entity_type, entity_id, payload)
            VALUES ($1, $2, 'task_envelope', $3, $4)
            {conflict}
            """,
            _as_uuid(envelope.project_id),
            _as_uuid(envelope.revision_id),
            envelope.id,
            envelope.model_dump(mode="json"),
        )


def _as_uuid(value: str) -> Any:
    import uuid

    return uuid.UUID(value)


def envelope_from_execution_plan(
    plan: ExecutionPlan, *, stage: str = "video_generation"
) -> TaskEnvelope:
    """Map a compiled plan to the canonical durable task identity."""

    project_id = plan.project_id or str(plan.production_id or "")
    if not project_id or not plan.idempotency_key:
        raise ValueError("execution plan requires project and idempotency identity")
    return TaskEnvelope(
        id=new_id(),
        project_id=project_id,
        revision_id=str(plan.revision_id),
        shot_id=plan.shot_id,
        stage=stage,
        execution_plan_id=plan.id,
        idempotency_key=plan.idempotency_key,
    )


class DurableExecutionCoordinator:
    """Run one external side effect with restart-safe ordering."""

    def __init__(
        self,
        store: DurableExecutionStore,
        *,
        readiness_gate: Callable[[TaskEnvelope], None] | None = None,
    ) -> None:
        self.store = store
        self.readiness_gate = readiness_gate

    async def _gate_ready(self, envelope: TaskEnvelope, shot: CanonicalShot | None = None) -> None:
        """Reject dispatch when the canonical shot is not READY.

        The readiness gate is mandatory at the canonical dispatch boundary. In a
        production caller it is wired from the shot's readiness_state so that only
        a READY shot may invoke a provider side-effect. The default built-in gate
        enforces that the envelope carries a READY readiness signal when present,
        and never allows a LOCKED shot to regenerate outside the documented QA path.
        """
        if shot is not None:
            assert_dispatchable(shot)
        if self.readiness_gate is not None:
            self.readiness_gate(envelope)
        else:
            state = envelope.checkpoint.get("readiness_state")
            if state and state != "READY":
                from hevi.production_graph.durable_execution import _RejectDispatch  # type: ignore

                raise _RejectDispatch(state)
            if envelope.checkpoint.get("locked"):
                raise _RejectDispatch("LOCKED")

    async def execute(
        self,
        envelope: TaskEnvelope,
        adapter: ProviderAdapter,
        request: dict[str, Any],
        *,
        shot: CanonicalShot | None = None,
        destination: str = "",
        register_artifact: Callable[[str, dict[str, Any]], Awaitable[str] | str] | None = None,
    ) -> DurableExecutionResult:
        # Gate: reject any non-READY shot at the canonical dispatch boundary
        await self._gate_ready(envelope, shot)

        current = await self.store.persist_intent(envelope)
        if current.status == "completed":
            return DurableExecutionResult(
                status=current.status,
                envelope=current,
                provider_job_id=current.provider_job_id,
                artifact_ids=current.artifact_ids,
            )
        if current.status == "cancelled":
            return DurableExecutionResult(status=current.status, envelope=current)

        if not current.provider_job_id:
            current = current.model_copy(update={"status": "submitted"})
            # Persisting submitted is useful for recovery diagnostics. The
            # stable provider idempotency key is passed to every send.
            await self.store.save(current)
            provider_job_id = await adapter.send(request, idempotency_key=current.idempotency_key)
            current = current.model_copy(
                update={"status": "running", "provider_job_id": str(provider_job_id)}
            )
            await self.store.save(current)

        try:
            result = await adapter.poll(current.provider_job_id)
        except Exception as exc:
            # Keep the provider job identity durable across a transient poll
            # outage.  A later worker can call execute again and resume polling
            # without entering the create/send branch.
            current = await self.store.save(
                current.model_copy(update={"status": "interrupted", "error": str(exc)})
            )
            return DurableExecutionResult(
                status="interrupted",
                envelope=current,
                provider_job_id=current.provider_job_id,
                provider_result={"error": str(exc), "retryable": True},
            )
        provider_status = str(result.get("status") or "running").lower()
        if provider_status in {"pending", "queued", "running", "processing"}:
            current = current.model_copy(update={"status": "running", "checkpoint": dict(result)})
            current = await self.store.save(current)
            return DurableExecutionResult(
                status="running",
                envelope=current,
                provider_job_id=current.provider_job_id,
                provider_result=dict(result),
            )
        if provider_status in {"failed", "error"}:
            current = await self.store.save(
                current.model_copy(
                    update={
                        "status": "failed",
                        "error": str(result.get("error") or "provider failed"),
                    }
                )
            )
            return DurableExecutionResult(
                status="failed",
                envelope=current,
                provider_job_id=current.provider_job_id,
                provider_result=dict(result),
            )
        if provider_status in {"cancelled", "canceled"}:
            current = await self.store.save(current.model_copy(update={"status": "cancelled"}))
            return DurableExecutionResult(
                status="cancelled",
                envelope=current,
                provider_job_id=current.provider_job_id,
                provider_result=dict(result),
            )

        artifact_ids = list(current.artifact_ids)
        artifact_path = str(result.get("artifact_path") or "")
        if artifact_path and destination:
            artifact_path = await adapter.download(current.provider_job_id, destination)
        if artifact_path:
            if register_artifact is None:
                artifact_ids.append(artifact_path)
            else:
                registered = register_artifact(artifact_path, dict(result))
                if hasattr(registered, "__await__"):
                    registered = await registered
                artifact_ids.append(str(registered))
        current = await self.store.save(
            current.model_copy(update={"status": "completed", "artifact_ids": artifact_ids})
        )
        return DurableExecutionResult(
            status="completed",
            envelope=current,
            provider_job_id=current.provider_job_id,
            artifact_ids=artifact_ids,
            provider_result=dict(result),
        )

    async def cancel(self, envelope: TaskEnvelope, adapter: ProviderAdapter) -> TaskEnvelope:
        current = await self.store.persist_intent(envelope)
        if current.status in {"completed", "cancelled"}:
            return current
        if current.provider_job_id and current.cancelable:
            await adapter.cancel(current.provider_job_id)
        return await self.store.save(current.model_copy(update={"status": "cancelled"}))

    async def retry(self, envelope: TaskEnvelope) -> TaskEnvelope:
        current = await self.store.persist_intent(envelope)
        if not current.retryable:
            raise RuntimeError("task envelope is not retryable")
        if current.status not in {"failed", "interrupted", "paused"}:
            raise RuntimeError(f"task envelope cannot retry from {current.status}")
        return await self.store.save(
            current.model_copy(
                update={"status": "pending", "attempt": current.attempt + 1, "error": None}
            )
        )


__all__ = [
    "DurableExecutionCoordinator",
    "DurableExecutionResult",
    "DurableExecutionStore",
    "IdempotencyConflictError",
    "InMemoryDurableExecutionStore",
    "PostgresDurableExecutionStore",
    "envelope_from_execution_plan",
]
