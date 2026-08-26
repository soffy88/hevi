import asyncio
import contextlib
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from obase.persistence import PgPool

from hevi.artifact_store import ArtifactRepository, get_object_store
from hevi.core.config import settings
from hevi.cost import (
    HeviCostTracker,
    check_before_run,
    check_daily_budget,
    estimate_cost,
    monitor_during_run,
)
from hevi.credits.billing_service import BillingService
from hevi.monitoring.metrics import productions_started_total
from hevi.observability import log_event, start_trace
from hevi.pipeline import orchestrate_longvideo
from hevi.production.adapters import ProductionAdapterRegistry, default_production_adapters
from hevi.production.artifacts import ArtifactManifest, manifest_from_task
from hevi.production.contracts import ProductionRequest
from hevi.production.execution import execute_standard_operation, execution_binding
from hevi.queue.task_queue import enqueue
from hevi.resilience import RetryPolicy, run_with_fallback
from hevi.tasks.attempt_repository import AttemptRepository
from hevi.tasks.repository import TaskRepository

logger = logging.getLogger(__name__)

# Backpressure for cloud tasks run via FastAPI BackgroundTasks (which otherwise
# spawn unboundedly in the API event loop). Excess submissions wait here instead
# of all running concurrently. Local tasks go through the serial queue worker.
_CLOUD_CONCURRENCY = 8
_cloud_semaphore = asyncio.Semaphore(_CLOUD_CONCURRENCY)


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        billing_svc: BillingService | None = None,
        production_adapters: ProductionAdapterRegistry | None = None,
    ):
        self.repository = repository
        self.billing_svc = billing_svc
        self.production_adapters = production_adapters or default_production_adapters()
        # Attempts/checkpoints are enabled only for the PostgreSQL execution
        # boundary.  Local/fake repositories retain the old unit-test adapter
        # without pretending that an in-memory checkpoint is durable.
        self.attempt_repository = (
            AttemptRepository(repository.pool) if isinstance(repository.pool, PgPool) else None
        )

    async def _start_attempt(self, task: dict[str, Any]) -> dict[str, Any] | None:
        if self.attempt_repository is None:
            return None
        lease_token = str(task.get("lease_token") or "")
        if not lease_token:
            # A production worker must always own a task lease before it can
            # create an attempt.  This also prevents an API retry from
            # manufacturing an execution history without ownership.
            if settings.debug:
                return None
            raise RuntimeError("cannot start attempt without task lease")
        lease_until = task.get("lease_until")
        if isinstance(lease_until, str):
            lease_until = datetime.fromisoformat(lease_until.replace("Z", "+00:00"))
        attempt = await self.attempt_repository.start(
            uuid.UUID(str(task["id"])),
            worker_id=str(task.get("worker_id") or "unknown-worker"),
            lease_token=lease_token,
            lease_until=lease_until,
            metadata={
                "video_provider": task.get("video_provider"),
                "audio_provider": task.get("audio_provider"),
            },
        )
        attempt_id = attempt.get("id")
        if attempt_id is None:
            raise RuntimeError("attempt repository returned no attempt id")
        task["_attempt_id"] = attempt_id
        await self.attempt_repository.mark_running(
            uuid.UUID(str(attempt_id)), lease_token=lease_token
        )
        return attempt

    async def _checkpoint(
        self,
        task: dict[str, Any],
        *,
        stage: str,
        progress_pct: float,
        completed_shots: int = 0,
        total_shots: int = 0,
        state: dict[str, Any] | None = None,
        artifact_manifest: dict[str, Any] | None = None,
    ) -> None:
        if self.attempt_repository is None or not task.get("_attempt_id"):
            return
        await self.attempt_repository.checkpoint(
            attempt_id=uuid.UUID(str(task["_attempt_id"])),
            task_id=uuid.UUID(str(task["id"])),
            stage=stage,
            progress_pct=progress_pct,
            completed_shots=completed_shots,
            total_shots=total_shots,
            state=state,
            artifact_manifest=artifact_manifest,
        )

    async def _finish_attempt(
        self, task: dict[str, Any], *, status: str, error: str | None = None
    ) -> None:
        if self.attempt_repository is None or not task.get("_attempt_id"):
            return
        token = str(task.get("lease_token") or "")
        if not token:
            return
        await self.attempt_repository.finish(
            uuid.UUID(str(task["_attempt_id"])),
            lease_token=token,
            status=status,
            error=error,
        )

    async def _ensure_production_graph(self, task: dict[str, Any]) -> None:
        """Ensure every PostgreSQL task has a durable Production identity."""

        if not isinstance(self.repository.pool, PgPool):
            return
        config = task.setdefault("config_json", {})
        production_id = str(config.get("production_id") or task["id"])
        uuid.UUID(production_id)
        config["production_id"] = production_id
        from hevi.production_graph.repository import ProductionGraphRepository

        graph_repo = ProductionGraphRepository(self.repository.pool)
        if await graph_repo.get(production_id) is not None:
            return
        await graph_repo.create(
            {
                "work_id": production_id,
                "user_id": str(task.get("user_id") or ""),
                "type": str(config.get("production_source") or "task"),
                "status": "draft",
                "topic": str(task.get("topic") or ""),
                "production_source": str(config.get("production_source") or "task"),
                "production_config": config,
                "decision_trail": [],
            }
        )

    async def _apply_provider_policy(self, task: dict[str, Any]) -> None:
        """Resolve and persist the dynamic provider decision at execution time."""

        if not isinstance(self.repository.pool, PgPool):
            return
        from hevi.provider_policy import (
            ProviderPolicy,
            ProviderStateRepository,
            evaluate_provider_policy,
            require_provider,
        )

        config = dict(task.get("config_json") or {})
        requested = str(task.get("video_provider") or "")
        policy = ProviderPolicy(
            mode=str(config.get("provider_mode") or "t2v"),
            duration_archetype=str(task.get("duration_archetype") or "1-5min"),
            audio_provider=str(task.get("audio_provider") or "vibevoice"),
            quality_floor=int(config.get("provider_quality_floor") or 9),
            required_capabilities=set(config.get("required_capabilities") or []),
            candidates=(
                list(config["provider_candidates"])
                if config.get("provider_candidates")
                else ([requested] if requested != "auto" else None)
            ),
            max_estimated_cost_usd=(
                float(config["max_provider_cost_usd"])
                if config.get("max_provider_cost_usd") is not None
                else None
            ),
            exploration_rate=float(
                config.get("provider_exploration_rate", settings.provider_exploration_rate)
            ),
        )
        decision = await evaluate_provider_policy(
            policy, state_repository=ProviderStateRepository(self.repository.pool)
        )
        selected = require_provider(decision)
        task["video_provider"] = selected
        config["provider_policy"] = policy.model_dump(mode="json")
        config["provider_decision"] = decision.model_dump(mode="json")
        config["provider_fallback_candidates"] = decision.eligible
        await self.repository.update_task(
            uuid.UUID(str(task["id"])),
            {
                "video_provider": selected,
                "config_json": config,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        task["config_json"] = config

    async def _record_provider_outcome(
        self,
        task: dict[str, Any],
        provider: str,
        *,
        status: str,
        latency_ms: float | None = None,
        cost_usd: float | None = None,
        quality_score: float | None = None,
        error_code: str | None = None,
    ) -> None:
        """Persist provider outcomes without making telemetry a new failure mode."""

        if not isinstance(self.repository.pool, PgPool):
            return
        try:
            from hevi.provider_policy import ProviderStateRepository

            await ProviderStateRepository(self.repository.pool).record_outcome(
                provider,
                task_class=str(
                    (task.get("config_json") or {}).get("production_source")
                    or task.get("duration_archetype")
                    or "unknown"
                ),
                status=status,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                quality_score=quality_score,
                error_code=error_code,
                metadata={"task_id": str(task.get("id"))},
            )
        except Exception as exc:
            logger.warning("provider outcome persistence failed for %s: %s", provider, exc)

    async def _record_quality_repair(
        self, task: dict[str, Any], quality: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Run the shared gate/repair decision and persist its evidence."""

        config = dict(task.get("config_json") or {})
        if quality is None:
            if not isinstance(self.repository.pool, PgPool):
                return config
            quality = {
                "passed": False,
                "violations": [
                    {
                        "code": "QUALITY_CHECKER_FAILURE",
                        "scope": "production",
                        "message": "required quality evaluator returned no result",
                    }
                ],
            }
        from hevi.quality import (
            GatePolicy,
            QualityEvaluation,
            EvaluationEvidence,
            RepairBudget,
            RepairController,
            RepairRepository,
        )
        from hevi.quality.taxonomy import normalize_failure

        policy = GatePolicy.for_profile(str(config.get("quality_profile") or "standard"))
        evidence = [
            EvaluationEvidence(
                id=str(uuid.uuid4()),
                attempt_id=str(task["id"]),
                artifact_id="",
                constraint_id=str(item.get("code") if isinstance(item, dict) else item),
                evaluator_id=str(normalize_failure(item.get("code") if isinstance(item, dict) else item)),
                evaluator_version="1.0",
                metric=str(item.get("code") if isinstance(item, dict) else item),
                passed=False,
                details=dict(item) if isinstance(item, dict) else {"message": str(item)},
            )
            for item in quality.get("violations") or []
        ]
        evaluation = QualityEvaluation.from_evidence(evidence, policy)
        controller = RepairController(
            RepairBudget(
                max_attempts=int(config.get("auto_rework_rounds", settings.auto_rework_max_rounds)),
                max_cost_usd=float(config.get("repair_budget_usd") or 0.0),
            )
        )
        controller.observe(evaluation)
        decision = controller.decide(evaluation)
        config["quality_evaluation"] = evaluation.model_dump(mode="json")
        config["repair_controller"] = controller.snapshot()
        config["repair_decision"] = decision.model_dump(mode="json")
        if isinstance(self.repository.pool, PgPool):
            production_id = config.get("production_id")
            await RepairRepository(self.repository.pool).save_run(
                task_id=uuid.UUID(str(task["id"])),
                production_id=uuid.UUID(str(production_id)) if production_id else None,
                policy=policy,
                controller=controller,
                decision=decision,
                evaluation=evaluation,
                revision_id=(
                    uuid.UUID(str(config["revision_id"]))
                    if config.get("revision_id")
                    else None
                ),
                attempt_id=str(task.get("_attempt_id") or task.get("id")),
                evidence_artifact_id=str(config.get("evidence_artifact_id") or "") or None,
            )
        # The gate result is intentionally returned to the execution boundary.
        # The worker must get a chance to run the bounded repair controller
        # before it decides whether a Standard/Cinema artifact can be marked
        # deliverable. Raising here used to bypass the repair loop entirely.
        return config

    async def run_task_background(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Compatibility runner for explicitly local/test execution only.

        A debug application is also allowed to execute the compatibility path
        so legacy API integration tests can exercise billing end-to-end.
        Production deployments keep the worker-only PostgreSQL boundary.
        """
        if isinstance(self.repository.pool, PgPool) and not (settings.local_mode or settings.debug):
            raise RuntimeError(
                "PostgreSQL production tasks must be claimed by hevi-worker; "
                "FastAPI BackgroundTasks is not an execution owner"
            )
        async with _cloud_semaphore:
            return await self.run_task(task_id)

    def is_local_provider(self, video_provider: str) -> bool:
        """Determine if a provider requires local GPU resources."""
        # Heuristic: anything not containing 'cloud' or explicitly local
        local_names = {"qwen_local", "wan_local", "ltx2_local", "local"}
        if video_provider in local_names or "_local" in video_provider:
            return True
        return "cloud" not in video_provider.lower() and video_provider in ("wan", "ltx2", "ltx")

    async def _renew_lease(self, task: dict[str, Any]) -> bool:
        token = task.get("lease_token")
        if not token:
            return True
        task_id = uuid.UUID(str(task["id"]))
        alive = await self.repository.heartbeat(
            task_id, str(token), lease_seconds=settings.task_lease_seconds
        )
        attempt_id = task.get("_attempt_id") or task.get("current_attempt_id")
        if not alive or self.attempt_repository is None or not attempt_id:
            return alive
        return await self.attempt_repository.heartbeat(
            uuid.UUID(str(attempt_id)),
            lease_token=str(token),
            lease_seconds=settings.task_lease_seconds,
        )

    async def _lease_heartbeat_loop(self, task_id: uuid.UUID) -> None:
        """Renew task and attempt leases while a provider call is in flight.

        Progress callbacks are not a safe heartbeat: a provider may spend
        minutes in one request with no callback.  The loop is best-effort and
        stops when ownership is lost; terminal writes are fenced by the final
        lease check in the execution paths.
        """

        interval = max(1.0, float(settings.task_heartbeat_interval_s))
        while True:
            await asyncio.sleep(interval)
            task = await self.repository.get_task(task_id)
            if not task or not task.get("lease_token"):
                return
            if not await self._renew_lease(task):
                logger.warning("task %s lease heartbeat lost", task_id)
                return

    async def run_task(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Run a task with an independent durable lease heartbeat."""

        heartbeat_task: asyncio.Task[None] | None = None
        if self.attempt_repository is not None:
            heartbeat_task = asyncio.create_task(self._lease_heartbeat_loop(task_id))
        try:
            return await self._run_task_impl(task_id)
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task

    def _budget_repository(self) -> Any | None:
        """Return the durable budget repository only for a real PostgreSQL pool.

        Unit-test fakes and the legacy in-memory compatibility paths do not
        have a budget database; those paths retain the existing circuit breaker.
        Production requests always use ``PgPool`` and therefore cannot bypass
        an envelope once they carry a ``production_id``.
        """

        if not isinstance(self.repository.pool, PgPool):
            return None
        from hevi.budget import BudgetRepository

        return BudgetRepository(self.repository.pool)

    async def _settle_budget_for_task(
        self,
        task: dict[str, Any],
        *,
        actual_usd: float,
        release: bool = False,
    ) -> None:
        attempt_id = (task.get("config_json") or {}).get("budget_attempt_id")
        budget_repo = self._budget_repository()
        if not attempt_id or budget_repo is None:
            return
        try:
            if release:
                await budget_repo.release_attempt(attempt_id, external_ref=f"{task['id']}:release")
            else:
                await budget_repo.settle_attempt(
                    attempt_id,
                    actual_cost_usd=max(0.0, actual_usd),
                    external_ref=f"{task['id']}:settle",
                )
                estimated = float((task.get("config_json") or {}).get("estimated_usd") or 0.0)
                from hevi.monitoring.metrics import budget_estimate_error_usd

                budget_estimate_error_usd.labels(stage="settle").observe(
                    abs(estimated - max(0.0, actual_usd))
                )
        except Exception as exc:
            # Budget settlement must remain observable, but a completed render
            # must not be turned into a failed delivery because a ledger retry
            # is temporarily unavailable.
            logger.error("budget settlement failed for task %s: %s", task.get("id"), exc)

    async def create_production(
        self,
        request: ProductionRequest,
        *,
        user_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a task from the canonical ProductionRequest boundary."""
        args = request.to_task_args()
        args["execution_binding"] = execution_binding(request.source).model_dump(mode="json")
        topic = str(args.pop("topic"))
        duration = str(args.pop("duration_archetype"))
        video = str(args.pop("video_provider"))
        audio = str(args.pop("audio_provider"))
        return await self.create_task(
            topic=topic,
            duration_archetype=duration,
            video_provider=video,
            audio_provider=audio,
            user_id=user_id,
            idempotency_key=idempotency_key,
            **args,
        )

    async def _run_adapter_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Run an adapter-owned renderer through the shared task lifecycle."""
        task_id = uuid.UUID(str(task["id"]))
        if not await self._renew_lease(task):
            logger.warning("task %s lease lost before adapter execution", task_id)
            return task
        await self.repository.update_task(
            task_id,
            {
                "status": "running",
                "progress_pct": 0.0,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        await self._checkpoint(
            task,
            stage=str((task.get("config_json") or {}).get("production_source") or "adapter"),
            progress_pct=0.0,
            state={"status": "running"},
        )
        try:

            async def operation(
                _config: dict[str, Any], _input_data: dict[str, Any], _output_dir: Path
            ) -> dict[str, Any]:
                legacy_result = await self.production_adapters.execute(task, self.repository.pool)
                legacy_status = str(legacy_result.get("status", "failed"))
                status = {
                    "completed": "succeeded",
                    "cancelled": "cancelled",
                    "awaiting_review": "succeeded",
                }.get(legacy_status, "failed")
                # Human-review checkpoints are a successful transaction from
                # the execution engine's perspective, but must not be treated
                # as a terminal media delivery.  The outer lifecycle turns
                # this marker into a durable ``paused`` task below.
                review_pending = legacy_status == "awaiting_review"
                artifact_path = legacy_result.get("result_video_path")
                legacy_manifest = manifest_from_task(legacy_result)
                artifacts = (
                    legacy_manifest.model_dump(mode="json")["artifacts"]
                    if legacy_manifest is not None
                    else (
                        ArtifactManifest.for_video(artifact_path).model_dump(mode="json")[
                            "artifacts"
                        ]
                        if artifact_path
                        else []
                    )
                )
                return {
                    "status": status,
                    "error": legacy_result.get("error"),
                    "review_pending": review_pending,
                    "artifacts": artifacts,
                    "report": {"legacy_result": legacy_result},
                }

            async def project_event(event: dict[str, Any]) -> None:
                progress = event.get("progress_pct")
                if progress is None:
                    return
                await self.repository.update_task(
                    task_id,
                    {
                        "progress_pct": float(progress),
                        "config_json": {
                            **(task.get("config_json") or {}),
                            "stage": event.get("stage"),
                        },
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    },
                )
                await self._checkpoint(
                    task,
                    stage=str(event.get("stage") or "adapter"),
                    progress_pct=float(progress),
                    completed_shots=int(event.get("completed_shots") or 0),
                    total_shots=int(event.get("total_shots") or 0),
                    state={"stage": event.get("stage")},
                )

            engine_result = await execute_standard_operation(
                operation=operation,
                config={
                    "production_source": (task.get("config_json") or {}).get("production_source")
                },
                input_data={"task_ref": str(task_id)},
                output_dir=Path("output/tasks") / str(task_id),
                event_sink=project_event,
            )
            if engine_result.get("status") != "succeeded":
                error = engine_result.get("error") or {"message": "adapter execution failed"}
                # legacy_result.error(装配等下游 adapter 直接写回的错误)可能是纯字符串,
                # 不是 omodul 标准的 {"code","message"} dict——不能无脑 .get(),
                # 否则真实错误信息会被 'str' object has no attribute 'get' 盖掉。
                message = error.get("message", error) if isinstance(error, dict) else error
                update: dict[str, Any] = {
                    "status": "failed",
                    "error": str(message)[:500],
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                }
                await self.repository.update_task(task_id, update)
                await self._finish_attempt(task, status="failed", error=str(message)[:500])
                await self._settle_budget_for_task(task, actual_usd=0.0, release=True)
                return {**task, **update}
            result = (engine_result.get("report") or {}).get("legacy_result")
            if not isinstance(result, dict):
                error = engine_result.get("error") or {"message": "adapter produced no task result"}
                raise RuntimeError(str(error.get("message", error)))
            config_json = dict(result.get("config_json") or task.get("config_json") or {})
            if result.get("review_pending"):
                update = {
                    "status": "paused",
                    "progress_pct": max(0.0, min(99.0, float(task.get("progress_pct") or 0.0))),
                    "config_json": config_json,
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                }
                await self.repository.update_task(task_id, update)
                await self._checkpoint(
                    task,
                    stage="awaiting_review",
                    progress_pct=float(update["progress_pct"]),
                    state={"status": "awaiting_review"},
                )
                await self._finish_attempt(task, status="paused")
                if task.get("lease_token"):
                    await self.repository.clear_lease(task_id, task["lease_token"])
                return {**result, **update}
            raw_manifest = config_json.get("artifact_manifest")
            if raw_manifest:
                manifest = ArtifactManifest.model_validate(raw_manifest)
            elif engine_result.get("artifacts"):
                manifest = ArtifactManifest.model_validate(
                    {"artifacts": engine_result["artifacts"]}
                )
            elif result.get("result_video_path"):
                manifest = ArtifactManifest.for_video(result["result_video_path"])
            else:
                if not isinstance(self.repository.pool, PgPool):
                    completion = {
                        "status": "completed",
                        "progress_pct": 100.0,
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    }
                    await self.repository.update_task(task_id, completion)
                    return result
                raise RuntimeError("completed adapter task returned no artifact")
            if not await self._renew_lease(task):
                logger.warning("task %s lease lost before adapter completion", task_id)
                return task
            quality_config = await self._record_quality_repair(task, result.get("quality"))
            config_json.update(quality_config)
            manifest = manifest.model_copy(
                update={
                    "production_id": (task.get("config_json") or {}).get("production_id"),
                    "attempt_id": str(task.get("_attempt_id") or task_id),
                }
            )
            if isinstance(self.repository.pool, PgPool):
                manifest = await ArtifactRepository(
                    self.repository.pool, get_object_store()
                ).commit(manifest)
            config_json["artifact_manifest"] = manifest.model_dump(mode="json")
            await self.repository.update_task(task_id, {"config_json": config_json})
            result = {**result, "config_json": config_json}
            artifact_path = result.get("result_video_path") or str(
                manifest.primary_path() or ""
            )
            if not artifact_path:
                raise RuntimeError("artifact manifest has no primary artifact")
            completion = {
                "status": "completed",
                "progress_pct": 100.0,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            }
            if artifact_path:
                completion["result_video_path"] = artifact_path
            if result.get("total_shots") is not None:
                completion["total_shots"] = result["total_shots"]
            if result.get("completed_shots") is not None:
                completion["completed_shots"] = result["completed_shots"]
            await self.repository.update_task(task_id, completion)
            await self._checkpoint(
                task,
                stage="completed",
                progress_pct=100.0,
                completed_shots=int(
                    result.get("completed_shots") or result.get("total_shots") or 0
                ),
                total_shots=int(result.get("total_shots") or 0),
                state={"status": "completed"},
                artifact_manifest=(
                    (result.get("config_json") or {}).get("artifact_manifest")
                    if isinstance(result.get("config_json"), dict)
                    else None
                ),
            )
            await self._finish_attempt(task, status="succeeded")
            await self._record_provider_outcome(
                task,
                str(task.get("video_provider") or "unknown"),
                status="succeeded",
            )
            await self._settle_budget_for_task(
                task,
                actual_usd=float(
                    (result.get("config_json") or {}).get("actual_usd")
                    or (task.get("config_json") or {}).get("estimated_usd")
                    or 0.0
                ),
            )
            if task.get("lease_token"):
                await self.repository.clear_lease(task_id, task["lease_token"])
            shots = result.get("shots")
            if isinstance(shots, list):
                await self.repository.delete_shots(task_id)
                await self._persist_shots(task_id, shots)
            return result
        except Exception as exc:
            logger.exception("adapter task %s failed", task_id)
            update = {
                "status": "failed",
                "error": str(exc)[:500],
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            }
            await self.repository.update_task(task_id, update)
            await self._finish_attempt(task, status="failed", error=str(exc)[:500])
            await self._record_provider_outcome(
                task,
                str(task.get("video_provider") or "unknown"),
                status="failed",
                error_code=type(exc).__name__,
            )
            await self._settle_budget_for_task(task, actual_usd=0.0, release=True)
            if task.get("lease_token"):
                await self.repository.clear_lease(task_id, task["lease_token"])
            return {**task, **update}

    async def create_task(
        self,
        topic: str,
        duration_archetype: str,
        video_provider: str,
        audio_provider: str,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new video task, estimate cost, check credits, and persist it."""
        idempotency_key = kwargs.pop("idempotency_key", None)
        if idempotency_key:
            idempotency_key = str(idempotency_key).strip()
            if not idempotency_key:
                idempotency_key = None
            else:
                existing = await self.repository.get_task_by_idempotency_key(
                    user_id, idempotency_key
                )
                if existing is not None:
                    return existing

        # 1. Estimate cost (USD)
        estimate = await estimate_cost(
            duration_archetype=duration_archetype,
            video_provider=video_provider,
            audio_provider=audio_provider,
            num_characters=kwargs.get("num_characters", 1),
        )

        # 2. Check limits (Circuit Breaker) —— 第1层:单任务上限。
        await check_before_run(estimate)

        # 2b. 三层预算熔断第3层(HEVI 路线图 Phase1 #30):全局每日聚合上限,独立于上面的
        # 单任务上限和下面的用户 credit 余额。daily_budget_usd 未配置(默认 None)时不检查。
        await check_daily_budget(self.repository.pool, additional_usd=estimate.total_usd)

        # 3. Credit Check (SaaS-2): 全本地(cost==0)跳过,含云步才检查余额 —— 第2层。
        credits_needed = 0
        if self.billing_svc and user_id:
            credits_needed = await self.billing_svc.estimate_credits(
                duration_archetype=duration_archetype, video_provider=video_provider, **kwargs
            )

        # 2c. ProductionBudget reservation.  Generate the task id up front so
        # the reservation and the task projection share one stable reference.
        task_id = uuid.uuid4()
        reservation_id = None
        if self.billing_svc and user_id and credits_needed > 0:
            try:
                reservation = await self.billing_svc.reserve(
                    user_id, credits_needed,
                    production_id=kwargs.get("production_id") or "",
                    task_id=str(task_id),
                    attempt_id=None,
                )
                reservation_id = reservation.get("id")
            except Exception as exc:
                from hevi.cost.circuit_breaker import CostLimitExceeded
                raise CostLimitExceeded(f"Credit reservation failed: {exc}") from exc
        budget_repo = self._budget_repository()
        budget_attempt_id: uuid.UUID | None = None
        if budget_repo is not None and kwargs.get("production_id"):
            from hevi.budget import BudgetError

            attempt_key = str(kwargs.get("budget_attempt_key") or f"task:{task_id}")
            try:
                reservation = await budget_repo.reserve_attempt(
                    production_id=str(kwargs["production_id"]),
                    attempt_key=attempt_key,
                    estimated_cost_usd=estimate.total_usd,
                    stage_category=str(kwargs.get("stage_category") or "rendering"),
                    is_retake=bool(kwargs.get("is_retake", False)),
                    allow_borrow=bool(kwargs.get("allow_budget_borrow", False)),
                    task_id=task_id,
                )
                budget_attempt_id = reservation.attempt_id
            except BudgetError as exc:
                from hevi.cost.circuit_breaker import CostLimitExceeded

                raise CostLimitExceeded(f"Production budget rejected: {exc}") from exc

        deadline_at = kwargs.get("deadline_at")
        if isinstance(deadline_at, str):
            deadline_at = datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
            if deadline_at.tzinfo is not None:
                deadline_at = deadline_at.astimezone(UTC).replace(tzinfo=None)
        data = {
            "id": task_id,
            "topic": topic,
            "user_id": user_id,
            "idempotency_key": idempotency_key,
            "duration_archetype": duration_archetype,
            "video_provider": video_provider,
            "audio_provider": audio_provider,
            "status": "pending",
            "progress_pct": 0.0,
            "total_shots": 0,
            "completed_shots": 0,
            "priority": int(kwargs.get("priority") or 0),
            "deadline_at": deadline_at,
            "resource_class": str(kwargs.get("resource_class") or "any"),
            "required_vram_mb": int(kwargs.get("required_vram_mb") or 0),
            "expected_cost_usd": estimate.total_usd,
            "tenant_weight": float(kwargs.get("tenant_weight") or 1.0),
            "warm_provider": kwargs.get("warm_provider"),
            "config_json": {
                **{k: v for k, v in kwargs.items() if v is not None},
                "estimated_usd": estimate.total_usd,
                "credits_reserved": credits_needed,
                "reservation_id": reservation_id or "",
                **(
                    {
                        "budget_attempt_id": str(budget_attempt_id),
                        "budget_reserved_usd": estimate.total_usd,
                    }
                    if budget_attempt_id is not None
                    else {}
                ),
            },
            "created_at": datetime.now(UTC).replace(tzinfo=None),
            "updated_at": datetime.now(UTC).replace(tzinfo=None),
        }
        try:
            created = await self.repository.create_task(data)
            if kwargs.get("production_id"):
                productions_started_total.labels(
                    source=str(kwargs.get("production_source") or "task")
                ).inc()
            return created
        except Exception:
            if idempotency_key:
                existing = await self.repository.get_task_by_idempotency_key(
                    user_id, idempotency_key
                )
                if existing is not None:
                    if budget_repo is not None and budget_attempt_id is not None:
                        await budget_repo.release_attempt(
                            budget_attempt_id, external_ref=f"{task_id}:idempotency_duplicate"
                        )
                    return existing
            if budget_repo is not None and budget_attempt_id is not None:
                try:
                    await budget_repo.release_attempt(
                        budget_attempt_id, external_ref=f"{task_id}:create_failed"
                    )
                except Exception as exc:
                    logger.error("budget release failed after task create failure: %s", exc)
            raise

    async def _run_task_impl(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Run a task using the orchestration pipeline with fallback and cost monitoring."""
        with start_trace(str(task_id)):
            log_event(stage="task_service", event="run_task_start", task_id=str(task_id))

            task = await self.repository.get_task(task_id)
            if not task:
                log_event(
                    stage="task_service",
                    event="task_not_found",
                    level="error",
                    task_id=str(task_id),
                )
                raise ValueError(f"Task {task_id} not found")

            if not await self._renew_lease(task):
                log_event(
                    stage="task_service",
                    event="run_task_skipped_lease_lost",
                    task_id=str(task_id),
                )
                return task

            await self._ensure_production_graph(task)
            if isinstance(self.repository.pool, PgPool):
                await self.repository.update_task(
                    task_id,
                    {
                        "config_json": task.get("config_json") or {},
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    },
                )
            if (task.get("config_json") or {}).get("production_source") not in {
                "director_graph",
                "explainer",
                "shortdrama",
                "tongjian",
                "voice_studio_tts",
                "lot",
                "cinematic_animation",
                "history_animation",
                "director_tongjian",
                "checkpoint_render",
            }:
                await self._apply_provider_policy(task)
            await self._start_attempt(task)
            if self.attempt_repository is not None:
                latest = await self.attempt_repository.latest(uuid.UUID(str(task["id"])))
                if latest and int(latest.get("completed_shots") or 0) > 0:
                    task["_resume_checkpoint"] = latest

            # Guard against double-execution (double dequeue / resume + worker race).
            # Combined with idempotent consume this prevents double-charge AND wasted
            # GPU. A failed task is still resumable (status == "failed" falls through).
            if task.get("status") in ("running", "completed"):
                log_event(
                    stage="task_service",
                    event="run_task_skipped_already_active",
                    task_id=str(task_id),
                    status=task.get("status"),
                )
                return task

            rework_request = (task.get("config_json") or {}).get("rework_request")
            if isinstance(rework_request, dict):
                return await self._run_queued_rework(task, rework_request)

            if (task.get("config_json") or {}).get("production_source") in {
                "director_graph",
                "explainer",
                "shortdrama",
                "tongjian",
                "voice_studio_tts",
                "lot",
                "cinematic_animation",
                "history_animation",
                "director_tongjian",
                "checkpoint_render",
            }:
                return await self._run_adapter_task(task)

            # 成本感知路由 v1(§7-2):video_provider="auto" → 在(能力 mode ∧ 活状态可路由 ∧
            # 质量下限)的 provider 中选最便宜。解析失败回退零成本本地 wan。
            if task.get("video_provider") == "auto":
                try:
                    from hevi.cost.router import route_video_provider

                    _char = await self._resolve_character_reference(task, task_id=task_id)
                    routed = await route_video_provider(
                        duration_archetype=task["duration_archetype"],
                        audio_provider=task["audio_provider"],
                        mode="i2v" if _char else "t2v",
                    )
                except Exception as re:
                    logger.warning(f"cost-aware routing failed → wan_local: {re}")
                    routed = "wan_local"
                task["video_provider"] = routed
                await self.repository.update_task(task_id, {"video_provider": routed})
                log_event(
                    stage="task_service",
                    event="provider_routed",
                    task_id=str(task_id),
                    provider=routed,
                )

            user_id = task.get("user_id")
            credits_reserved = task["config_json"].get("credits_reserved", 0)

            # Update status to running
            await self.repository.update_task(
                task_id, {"status": "running", "updated_at": datetime.now(UTC).replace(tzinfo=None)}
            )

            # 4. Consume credits at the start of execution (SaaS-2)
            if self.billing_svc and user_id and credits_reserved > 0:
                reservation_id = (task.get("config_json") or {}).get("reservation_id", "")
                try:
                    await self.billing_svc.consume(
                        reservation_id,
                        int(credits_reserved),
                        external_ref=f"{task_id}:consume_start"
                    )
                except Exception as exc:
                    logger.error(f"Credit consumption failed for task {task_id}: {exc}")
                    # If consumption fails (e.g. balance changed since creation), fail task
                    credit_update: dict[str, Any] = {
                        "status": "failed",
                        "error": f"Credit settlement failed: {exc}",
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    }
                    await self.repository.update_task(task_id, credit_update)
                    await self._finish_attempt(task, status="failed", error=str(exc)[:500])
                    await self._settle_budget_for_task(task, actual_usd=0.0, release=True)
                    return {**task, **credit_update}

            cost_tracker = HeviCostTracker()

            # SaaS-4 item:逐阶段进度回写。orchestrate 内注入的各阶段函数(分镜/逐镜头/
            # 配音/装配)通过此回调把 stage 文案 + 百分比 + 已完成镜头数写入 DB,SSE 流
            # 据此向前端展示"正在生成第 N 镜头"等实时步骤,取代过去全程 0%→100% 的黑盒。
            _base_cfg = task["config_json"]

            async def progress_cb(
                stage: str,
                pct: float,
                completed_shots: int | None = None,
                total_shots: int | None = None,
            ) -> None:
                data: dict[str, Any] = {
                    "progress_pct": float(pct),
                    "config_json": {**_base_cfg, "stage": stage},
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                }
                if completed_shots is not None:
                    data["completed_shots"] = completed_shots
                if total_shots is not None:
                    data["total_shots"] = total_shots
                try:
                    await self._renew_lease(task)
                    await self.repository.update_task(task_id, data)
                    await self._checkpoint(
                        task,
                        stage=stage,
                        progress_pct=float(pct),
                        completed_shots=int(completed_shots or 0),
                        total_shots=int(total_shots or 0),
                        state={"stage": stage},
                    )
                except Exception as pe:  # 进度回写绝不可拖垮生成
                    logger.debug(f"progress update skipped: {pe}")

            # 角色库(2D 锁定,多角色时合成一张总览图):按 config_json 解析角色参考图路径,
            # 交给 orchestrate 让每个镜头以其做 i2v 参考 → 视频里始终是同一批人。
            # 解析失败不阻断生成。
            character_reference = await self._resolve_character_reference(task, task_id=task_id)
            # shot_verdict 版本快照(HEVI 路线图 Phase1):见 _resolve_subject_version。
            subject_version = await self._resolve_subject_version(task)

            async def runner(provider: str) -> dict[str, Any]:
                # Monitor actual cost before each attempt (if applicable)
                await monitor_during_run(cost_tracker.total_usd)
                provider_started = time.monotonic()

                try:
                    log_event(stage="task_service", event="orchestration_start", provider=provider)
                    from omodul.longvideo_produce import longvideo_produce

                    async def render_legacy_longvideo(
                        _topic: str, output_dir: Path, _config: dict[str, Any]
                    ) -> dict[str, Any]:
                        return await orchestrate_longvideo(
                            topic=task["topic"],
                            duration_archetype=task["duration_archetype"],
                            video_provider=provider,
                            audio_provider=task["audio_provider"],
                            output_dir=output_dir,
                            progress_cb=progress_cb,
                            character_reference=character_reference,
                            subject_version=subject_version,
                            **task["config_json"],
                        )

                    engine_result = await execute_standard_operation(
                        operation=longvideo_produce,
                        config={
                            "duration_archetype": task["duration_archetype"],
                            "video_provider": provider,
                            "audio_provider": task["audio_provider"],
                            "style": task["config_json"].get("style", "cinematic"),
                            "num_characters": task["config_json"].get("num_characters", 1),
                            "language": task["config_json"].get("language", "zh"),
                        },
                        input_data={
                            "schema_version": 1,
                            "topic": task["topic"],
                            "renderer": render_legacy_longvideo,
                        },
                        output_dir=Path("output/tasks") / str(task_id),
                    )
                    if engine_result.get("status") != "succeeded":
                        error = engine_result.get("error") or {
                            "message": "longvideo transaction failed"
                        }
                        raise RuntimeError(str(error.get("message", error)))
                    report = engine_result.get("report") or {}
                    duration_s = float(report.get("duration_s") or 0.0)
                    result = {
                        "url": report.get("video_path"),
                        "duration": duration_s,
                        "metadata": {"shots": int(report.get("shots_generated") or 0)},
                        "shots": report.get("shots") or [],
                        "quality": report.get("quality"),
                    }

                    # Record actual cost after success
                    cost_tracker.record_video(provider, duration_s)
                    cost_tracker.record_audio(task["audio_provider"], duration_s / 60.0)
                    quality_payload = result.get("quality")
                    consistency = (
                        quality_payload.get("consistency")
                        if isinstance(quality_payload, dict)
                        else None
                    )
                    quality_score = (
                        float(consistency)
                        if isinstance(consistency, (int, float))
                        else None
                    )
                    await self._record_provider_outcome(
                        task,
                        provider,
                        status="succeeded",
                        latency_ms=(time.monotonic() - provider_started) * 1000,
                        cost_usd=cost_tracker.total_usd,
                        quality_score=quality_score,
                    )

                    return result
                except Exception as exc:
                    await self._record_provider_outcome(
                        task,
                        provider,
                        status="failed",
                        latency_ms=(time.monotonic() - provider_started) * 1000,
                        error_code=type(exc).__name__,
                    )
                    raise

            async def on_fallback(old_p: str, new_p: str, exc: Exception) -> None:
                log_event(
                    stage="task_service",
                    event="fallback_trigger",
                    old_provider=old_p,
                    new_provider=new_p,
                    error=str(exc),
                )
                # Re-estimate for the new provider
                new_est = await estimate_cost(
                    duration_archetype=task["duration_archetype"],
                    video_provider=new_p,
                    audio_provider=task["audio_provider"],
                )

                logger.warning(
                    f"Task {task_id} fallback: {old_p} -> {new_p}. "
                    f"New estimate: ${new_est.total_usd:.2f}"
                )

                await self.repository.update_task(
                    task_id,
                    {
                        "video_provider": new_p,
                        "error": f"Fallback from {old_p} due to: {exc}",
                        "config_json": {**task["config_json"], "estimated_usd": new_est.total_usd},
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    },
                )

            try:
                result = await run_with_fallback(
                    initial_provider=task["video_provider"],
                    runner=runner,
                    on_fallback=on_fallback,
                    retry_policy=RetryPolicy(),
                    candidates=list(
                        (task.get("config_json") or {}).get("provider_fallback_candidates") or []
                    ),
                )

                # Settle reserved (estimate) vs actual cost. We charged
                # credits_reserved up front; reconcile the difference now so a
                # fallback to a pricier/cheaper provider doesn't leak revenue or
                # over-charge the user. Idempotent via the ":settle" reference.
                if self.billing_svc and user_id and credits_reserved > 0:
                    actual_credits = int(cost_tracker.total_usd * settings.credits_per_usd)
                    delta = actual_credits - credits_reserved
                    settle_ref = f"{task_id}:settle"
                    try:
                        if delta > 0:
                            reservation_id = (task.get("config_json") or {}).get("reservation_id", "")
                            await self.billing_svc.consume(
                                reservation_id,
                                delta,
                                external_ref=f"{task_id}:settle:{delta}"
                            )
                        elif delta < 0:
                            await self.billing_svc.refund_consumed(
                                str(task_id),
                                abs(delta)
                            )
                    except Exception as exc:
                        # Settle-up can fail if the user spent their balance meanwhile;
                        # the video is already produced, so log rather than fail.
                        logger.warning(f"Cost settlement failed for task {task_id}: {exc}")

                # The final lease check fences an old worker before any
                # deliverable is committed. Quality repair runs before the
                # completed state, so Cinema never exposes a failed artifact.
                if not await self._renew_lease(task):
                    logger.warning("task %s lease lost before completion", task_id)
                    return task
                quality = result.get("quality")
                quality_config = await self._record_quality_repair(task, quality)
                await self._persist_shots(task_id, result.get("shots", []))

                rework_rounds = int(
                    task["config_json"].get("auto_rework_rounds", settings.auto_rework_max_rounds)
                )
                done = 0
                if quality is not None and not quality.get("passed", True):
                    try:
                        from hevi.director.agent import _shot_view
                        from hevi.director.editor import review
                        from hevi.quality import RepairDecision, apply_repair_decision

                        while done < rework_rounds:
                            repair_decision = RepairDecision.model_validate(
                                quality_config.get("repair_decision") or {}
                            )
                            if not repair_decision.should_repair:
                                break
                            patch = apply_repair_decision(
                                repair_decision,
                                current_provider=str(task.get("video_provider") or ""),
                                fallback_candidates=list(
                                    (task.get("config_json") or {}).get(
                                        "provider_fallback_candidates"
                                    )
                                    or []
                                ),
                                current_seed=int((task.get("config_json") or {}).get("seed") or 0),
                            )
                            if patch.provider_id:
                                task["video_provider"] = patch.provider_id
                            task["config_json"] = {
                                **dict(task.get("config_json") or {}),
                                **patch.config_updates(),
                            }
                            await self.repository.update_task(
                                task_id,
                                {
                                    "config_json": task["config_json"],
                                    **(
                                        {"video_provider": patch.provider_id}
                                        if patch.provider_id
                                        else {}
                                    ),
                                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                                },
                            )
                            views = [
                                _shot_view(row) for row in await self.repository.get_shots(task_id)
                            ]
                            decision = review(
                                quality=quality,
                                shots=views,
                                consistency_floor=settings.rework_consistency_floor,
                                min_rework_count=settings.rework_min_shots,
                            )
                            shot_ids = list(decision.regenerate_shot_ids) or patch.shot_indexes
                            if not shot_ids:
                                break
                            hints = dict(decision.hints or {})
                            if patch.replace_references:
                                for shot_id in shot_ids:
                                    hints[shot_id] = (
                                        f"{hints.get(shot_id) or ''} replace identity reference"
                                    ).strip()
                            if patch.recompile_prompt:
                                for shot_id in shot_ids:
                                    hints[shot_id] = (
                                        f"{hints.get(shot_id) or ''} recompile continuity prompt"
                                    ).strip()
                            log_event(
                                stage="task_service",
                                event="editor_regenerate_triggered",
                                task_id=str(task_id),
                                shot_ids=shot_ids,
                                diagnosis=decision.diagnosis,
                                repair_actions=[item.kind for item in patch.applied],
                            )
                            reworked = await self.regenerate_task_shots(
                                task_id,
                                shot_ids=shot_ids,
                                hints=hints,
                            )
                            if isinstance(reworked, dict):
                                if isinstance(reworked.get("result_video_path"), str):
                                    result["url"] = reworked["result_video_path"]
                                if isinstance(reworked.get("shots"), list):
                                    result["shots"] = reworked["shots"]
                                    result["metadata"] = {
                                        **dict(result.get("metadata") or {}),
                                        "shots": len(reworked["shots"]),
                                    }
                                if isinstance(reworked.get("quality"), dict):
                                    quality = reworked["quality"]
                            await self._persist_shots(task_id, result.get("shots", []))
                            quality_config = await self._record_quality_repair(task, quality)
                            done += 1
                        if done:
                            log_event(
                                stage="task_service",
                                event="auto_rework_done",
                                task_id=str(task_id),
                                rounds=done,
                            )
                    except Exception as repair_exc:
                        logger.warning("auto-rework failed for %s: %s", task_id, repair_exc)

                quality_evaluation = quality_config.get("quality_evaluation") or {}
                quality_passed = bool(
                    quality_evaluation.get(
                        "passed", quality is not None and quality.get("passed", False)
                    )
                )
                profile = str(task["config_json"].get("quality_profile") or "standard")
                has_quality_contract = quality is not None or "quality_evaluation" in quality_config
                if profile in {"standard", "cinema"} and has_quality_contract and not quality_passed:
                    error = "quality gate failed after bounded repair"
                    failed = {
                        "status": "failed",
                        "progress_pct": 100.0,
                        "error": error,
                        "config_json": {
                            **quality_config,
                            "quality": quality,
                            "auto_rework_rounds_used": done,
                        },
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    }
                    await self.repository.update_task(task_id, failed)
                    await self._checkpoint(
                        task,
                        stage="quality_failed",
                        progress_pct=100.0,
                        state={"status": "failed", "reason": error},
                    )
                    await self._finish_attempt(task, status="failed", error=error)
                    await self._settle_budget_for_task(
                        task, actual_usd=cost_tracker.total_usd, release=False
                    )
                    if task.get("lease_token"):
                        await self.repository.clear_lease(task_id, task["lease_token"])
                    log_event(
                        stage="task_service",
                        event="quality_gate_failed",
                        task_id=str(task_id),
                        violations=(quality or {}).get("violations", []),
                        repair_rounds=done,
                    )
                    return {**task, **failed}

                artifact_manifest = ArtifactManifest.for_video(result["url"]).model_copy(
                    update={
                        "production_id": task["config_json"].get("production_id"),
                        "revision_id": task["config_json"].get("revision_id"),
                        "attempt_id": str(task.get("_attempt_id") or task_id),
                        "tenant_id": str(task.get("user_id") or "anonymous"),
                    }
                )
                update_data: dict[str, Any] = {
                    "status": "completed",
                    "progress_pct": 100.0,
                    "result_video_path": result["url"],
                    "total_shots": result["metadata"].get("shots", 0),
                    "completed_shots": result["metadata"].get("shots", 0),
                    "error": None,
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    "config_json": {
                        **quality_config,
                        "actual_usd": cost_tracker.total_usd,
                        "artifact_manifest": artifact_manifest.model_dump(mode="json"),
                        **({"quality": quality} if quality is not None else {}),
                        "auto_rework_rounds_used": done,
                    },
                }
                if isinstance(self.repository.pool, PgPool):
                    try:
                        committed = await ArtifactRepository(
                            self.repository.pool, get_object_store()
                        ).commit(artifact_manifest)
                    except FileNotFoundError:
                        # Debug API tests commonly return a synthetic remote
                        # URL instead of materialising a worker artifact. Do
                        # not weaken the production artifact gate; only keep
                        # this explicit compatibility lane alive.
                        if not (
                            settings.debug
                            and str(result.get("url") or "").startswith(("http://", "https://"))
                        ):
                            raise
                        logger.warning(
                            "debug task %s returned a synthetic artifact URL; "
                            "skipping object-store commit",
                            task_id,
                        )
                    else:
                        update_data["config_json"]["artifact_manifest"] = committed.model_dump(
                            mode="json"
                        )
                await self.repository.update_task(task_id, update_data)
                await self._checkpoint(
                    task,
                    stage="completed",
                    progress_pct=100.0,
                    completed_shots=int(result["metadata"].get("shots", 0)),
                    total_shots=int(result["metadata"].get("shots", 0)),
                    state={"status": "completed"},
                    artifact_manifest=artifact_manifest.model_dump(mode="json"),
                )
                await self._finish_attempt(task, status="succeeded")
                await self._settle_budget_for_task(
                    task, actual_usd=cost_tracker.total_usd, release=False
                )
                if task.get("lease_token"):
                    await self.repository.clear_lease(task_id, task["lease_token"])
                log_event(
                    stage="task_service", event="run_task_completed", result_url=result["url"]
                )
                return {**task, **update_data}

            except Exception as e:
                log_event(
                    stage="task_service", event="run_task_failed", level="error", error=str(e)
                )
                logger.exception(f"Task {task_id} failed")

                # 5. Refund credits on failure (SaaS-2) — refund the actually-consumed
                # amount, only if consumed (no over-refund if we failed before consume).
                if self.billing_svc and user_id:
                    try:
                        await self.billing_svc.refund_for_task(user_id, str(task_id))
                    except Exception as refund_exc:
                        logger.error(f"Credit refund failed for task {task_id}: {refund_exc}")

                update_data = {
                    "status": "failed",
                    "error": str(e),
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                }
                await self.repository.update_task(task_id, update_data)
                await self._finish_attempt(task, status="failed", error=str(e)[:500])
                await self._settle_budget_for_task(task, actual_usd=0.0, release=True)
                if task.get("lease_token"):
                    await self.repository.clear_lease(task_id, task["lease_token"])
                return {**task, **update_data}

    async def resume_task(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Resume a failed or paused task."""
        task = await self.repository.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if task["status"] in ("completed", "running"):
            return task

        # M8 is currently a black box for shots, so we resume by re-running the task.
        return await self.run_task(task_id)

    async def enqueue_resume(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Requeue a production resume without executing in the API process."""
        task = await self.repository.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if not isinstance(self.repository.pool, PgPool):
            return await self.resume_task(task_id)
        config = dict(task.get("config_json") or {})
        config.pop("rework_request", None)
        await self.repository.update_task(
            task_id,
            {
                "config_json": config,
                "error": None,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        return await self.submit_task(task_id)

    async def enqueue_rework(
        self,
        task_id: uuid.UUID,
        *,
        shot_ids: list[int],
        hints: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        """Persist a scoped rework command and queue it for a worker."""
        task = await self.repository.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if not shot_ids:
            raise ValueError("shot_ids must not be empty")
        if not isinstance(self.repository.pool, PgPool):
            return await self.regenerate_task_shots(
                task_id, shot_ids=shot_ids, hints=hints
            )
        config = dict(task.get("config_json") or {})
        config["rework_request"] = {
            "shot_ids": sorted({int(item) for item in shot_ids}),
            "hints": {str(key): value for key, value in (hints or {}).items()},
            "requested_at": datetime.now(UTC).isoformat(),
        }
        await self.repository.update_task(
            task_id,
            {
                "config_json": config,
                "error": None,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        return await self.submit_task(task_id)

    async def _run_queued_rework(
        self, task: dict[str, Any], request: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a persisted rework command under the current worker lease."""
        task_id = uuid.UUID(str(task["id"]))
        shot_ids = [int(item) for item in request.get("shot_ids") or []]
        raw_hints = request.get("hints") or {}
        hints = {int(key): str(value) for key, value in raw_hints.items()}
        await self.repository.update_task(
            task_id,
            {
                "status": "running",
                "progress_pct": 0.0,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        try:
            result = await self.regenerate_task_shots(
                task_id, shot_ids=shot_ids, hints=hints
            )
            video_path = result.get("result_video_path")
            if not isinstance(video_path, str):
                raise RuntimeError("queued rework returned no video path")
            manifest = ArtifactManifest.for_video(video_path).model_copy(
                update={
                    "production_id": (task.get("config_json") or {}).get("production_id"),
                    "revision_id": (task.get("config_json") or {}).get("revision_id"),
                    "attempt_id": str(task.get("_attempt_id") or task_id),
                    "tenant_id": str(task.get("user_id") or "anonymous"),
                }
            )
            if isinstance(self.repository.pool, PgPool):
                manifest = await ArtifactRepository(
                    self.repository.pool, get_object_store()
                ).commit(manifest)
            refreshed = await self.repository.get_task(task_id) or task
            config = dict(refreshed.get("config_json") or {})
            config.pop("rework_request", None)
            config["artifact_manifest"] = manifest.model_dump(mode="json")
            await self.repository.update_task(
                task_id,
                {
                    "status": "completed",
                    "progress_pct": 100.0,
                    "error": None,
                    "config_json": config,
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                },
            )
            await self._checkpoint(
                task,
                stage="rework_completed",
                progress_pct=100.0,
                state={"status": "completed", "rework": True},
                artifact_manifest=manifest.model_dump(mode="json"),
            )
            await self._finish_attempt(task, status="succeeded")
            if task.get("lease_token"):
                await self.repository.clear_lease(task_id, str(task["lease_token"]))
            return {**task, "status": "completed", "config_json": config}
        except Exception as exc:
            logger.exception("queued rework failed for %s", task_id)
            update = {
                "status": "failed",
                "error": str(exc)[:500],
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            }
            await self.repository.update_task(task_id, update)
            await self._finish_attempt(task, status="failed", error=str(exc)[:500])
            if task.get("lease_token"):
                await self.repository.clear_lease(task_id, str(task["lease_token"]))
            return {**task, **update}

    async def _resolve_character_reference(
        self, task: dict[str, Any], *, task_id: uuid.UUID | None = None
    ) -> str | None:
        """按 config_json 解析角色参考图路径(i2v 锁定)。失败返回 None,不阻断。

        "诚实边界"曾经是(见 director.py::_resolve_character_roster 的 docstring):
        provider 的 i2v 每镜只吃1张参考图,故只有 `subject_id`(首个角色)的脸被锁定,
        其余角色仅入人设文本。2026-07-13 补上多角色合成:`config_json.
        character_subject_ids`(director.py 新存的完整角色列表)有 2 个以上真实建了
        参考图的角色时,用 `qwen_image_edit` 的多图融合(1-3张输入图,阿里云文档
        实测确认,同一个原语已用于 hevi/tongjian/scene_render_avatar.py 的多角色
        同框镜头)把他们的真实长相合成到一张"角色总览图"里,返回这张合成图当
        character_reference——下游 i2v 只需要吃一张图,不需要 provider 支持多图。

        只有 1 个角色(或没有 character_subject_ids,只有旧的单数 subject_id)时,
        走原来的路径,不产生任何多余的合成调用。
        """
        cfg = task["config_json"]
        subject_ids = list(cfg.get("character_subject_ids") or [])
        if not subject_ids:
            subject_ids = list(cfg.get("character_references") or [])
        if not subject_ids:
            legacy = cfg.get("subject_id")
            subject_ids = [legacy] if legacy else []
        if not subject_ids:
            return None

        try:
            from hevi.subjects.repository import SubjectRepository
            from hevi.subjects.subject_service import SubjectService

            svc = SubjectService(SubjectRepository(self.repository.pool))
            ref_paths: list[str] = []
            for sid in subject_ids:
                subj = await svc.get_subject(sid)
                refs = (subj or {}).get("reference_images") or []
                if refs:
                    ref_paths.append(refs[0])

            if len(ref_paths) <= 1:
                return ref_paths[0] if ref_paths else None

            return await self._compose_character_roster(ref_paths, task_id=task_id)
        except Exception as se:
            logger.warning(f"subject reference resolve failed: {se}")
            return None

    async def _compose_character_roster(
        self, ref_paths: list[str], *, task_id: uuid.UUID | None = None
    ) -> str | None:
        """多角色参考图 → 一张合成"角色总览图"(qwen-image-edit 多图融合,硬上限3张,
        超出的角色仍只以文本描述影响 storyboard,不新起一套绕过 API 限制的方案)。

        落盘到 output/tasks/{task_id}/character_roster.png 并缓存——同一 task 可能因
        路由探测(video_provider="auto")+ 实际生成各调一次本函数,不该重复付费合成。
        失败返回 None(调用方已有 try/except 兜底,这里再兜一层不阻断生成)。
        """
        cache_path = (
            Path("output/tasks") / str(task_id) / "character_roster.png"
            if task_id
            else Path("output/tasks/_no_task_id/character_roster.png")
        )
        if cache_path.exists():
            return str(cache_path)

        from hevi.image.qwen_image_service import QwenImageError, qwen_image_edit

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            await qwen_image_edit(
                image_path=[Path(p) for p in ref_paths[:3]],
                instruction=(
                    f"这{min(len(ref_paths), 3)}张图分别是不同角色各自的真实长相,"
                    "把他们排列在同一张图里,每个人物的相貌、服饰都要跟各自对应的"
                    "参考图保持一致,自然站姿,正面半身"
                ),
                output_path=cache_path,
            )
            return str(cache_path)
        except QwenImageError as qe:
            logger.warning(f"character roster composition failed: {qe}")
            return None

    async def _resolve_subject_version(self, task: dict[str, Any]) -> int | None:
        """shot_verdict 版本快照(HEVI 路线图 Phase1):记生成当时 Subject 是第几版,
        而不是"当前版本引用"——Subject 改参考图后,历史校验记录不应该跟着失真。
        失败/无 subject_id 返回 None,不阻断生成。"""
        _subject_id = task["config_json"].get("subject_id")
        if not _subject_id:
            return None
        try:
            from hevi.subjects.repository import SubjectRepository
            from hevi.subjects.subject_service import SubjectService

            _subj = await SubjectService(SubjectRepository(self.repository.pool)).get_subject(
                _subject_id
            )
            return (_subj or {}).get("version")
        except Exception as se:
            logger.warning(f"subject reference resolve failed: {se}")
            return None

    async def _persist_shots(self, task_id: uuid.UUID, shots: list[dict[str, Any]]) -> None:
        """C3 落库:逐镜头选优明细 → shot_states。best-effort(已成片,失败仅告警)。"""
        try:
            for shot in shots:
                await self.repository.create_shot_state(
                    {
                        "task_id": task_id,
                        "shot_index": shot.get("index", 0),
                        "status": "completed" if shot.get("passed", True) else "failed",
                        "output_path": shot.get("path"),
                        "selection_json": {
                            "provider": shot.get("provider"),
                            "variant_chosen": shot.get("variant_chosen"),
                            "consistency_score": shot.get("consistency_score"),
                            "passed": shot.get("passed"),
                            "duration_s": shot.get("duration_s"),
                            # shot_verdict 扩展(HEVI 路线图 Phase1):见
                            # hevi/pipeline/result_mapper.py::map_longvideo_result。
                            # style/vlm 打分尚无实装信号源(#33/#34/#38)时为 None,不是 0。
                            "style_score": shot.get("style_score"),
                            "vlm_score": shot.get("vlm_score"),
                            "vlm_violations": shot.get("vlm_violations"),
                            "diagnosis_category": shot.get("diagnosis_category"),
                            "subject_id": shot.get("subject_id"),
                            "subject_version": shot.get("subject_version"),
                            "style_pack_id": shot.get("style_pack_id"),
                            "style_pack_version": shot.get("style_pack_version"),
                            "model_version": shot.get("model_version"),
                            "tier0_passed": shot.get("tier0_passed"),
                            "tier1_passed": shot.get("tier1_passed"),
                            # 重试次数硬上限(设计文档 §4.3):首次生成落 0,regenerate_task_shots
                            # 在整片删旧落新前把旧计数读出来揉进 shots 里,这里原样透传。
                            "retry_count": shot.get("retry_count", 0),
                        },
                    }
                )
        except Exception as exc:
            logger.warning(f"ShotState 落库 failed for task {task_id}: {exc}")

    async def regenerate_task_shots(
        self,
        task_id: uuid.UUID,
        *,
        shot_ids: list[int],
        hints: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        """C3 verdict→定向返工:只重生成 shot_ids(hints[idx] 并入 prompt),其余复用,重装配。

        闭环下游端:评分卡不及格的镜头 + 失败原因 hints → 这里定向重烧,不必整片重跑。
        需该 task 已跑过一次(output_dir 有 per-shot 边车)。重刷 shot_states(删旧落新)。

        重试次数硬上限(设计文档 §4.3):retry_count 钉在每个镜头的 selection_json 里,
        整片删旧落新时按 shot_index 读旧值带过去,不会因为重刷就清零。已到
        settings.shot_retry_max 的镜头会被剔出本轮请求(不再空耗算力);剔完后
        shot_ids 为空则直接报错——调用方(run_task 的自动返工循环 / regenerate API)
        据此走降级交付,不是无限重试。
        """
        task = await self.repository.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if not shot_ids:
            raise ValueError("shot_ids must not be empty")

        existing_shots = await self.repository.get_shots(task_id)
        retry_by_index: dict[int, int] = {
            s["shot_index"]: int((s.get("selection_json") or {}).get("retry_count") or 0)
            for s in existing_shots
        }
        retry_max = settings.shot_retry_max
        capped = [idx for idx in shot_ids if retry_by_index.get(idx, 0) >= retry_max]
        shot_ids = [idx for idx in shot_ids if idx not in capped]
        if capped:
            logger.warning(
                f"task {task_id}: shots {capped} already at retry cap ({retry_max}), skipping"
            )
        if not shot_ids:
            raise ValueError(f"all requested shots already at retry cap ({retry_max}): {capped}")

        character_reference = await self._resolve_character_reference(task, task_id=task_id)
        subject_version = await self._resolve_subject_version(task)
        from omodul.shot_rework_produce import shot_rework_produce

        retake_budget_repo = self._budget_repository()
        retake_budget_attempt_id: uuid.UUID | None = None
        retake_estimate = float(
            (task.get("config_json") or {}).get("retake_estimated_usd")
            or float((task.get("config_json") or {}).get("estimated_usd") or 0.0) * 0.10
        )
        if retake_budget_repo is not None and (task.get("config_json") or {}).get("production_id"):
            from hevi.budget import BudgetError

            try:
                reservation = await retake_budget_repo.reserve_attempt(
                    production_id=str(task["config_json"]["production_id"]),
                    attempt_key=f"retake:{task_id}:{uuid.uuid4()}",
                    estimated_cost_usd=max(retake_estimate, 0.01),
                    stage_category="retake",
                    is_retake=True,
                    task_id=task_id,
                )
                retake_budget_attempt_id = reservation.attempt_id
                await self.repository.update_task(
                    task_id,
                    {
                        "config_json": {
                            **task["config_json"],
                            "budget_retake_attempt_id": str(retake_budget_attempt_id),
                        },
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    },
                )
            except BudgetError:
                raise

        async def render_legacy_rework(
            output_dir: Path,
            _config: dict[str, Any],
            selected_shot_ids: list[int],
            selected_hints: dict[int, str],
        ) -> dict[str, Any]:
            return await orchestrate_longvideo(
                topic=task["topic"],
                duration_archetype=task["duration_archetype"],
                video_provider=task["video_provider"],
                audio_provider=task["audio_provider"],
                output_dir=output_dir,
                character_reference=character_reference,
                subject_version=subject_version,
                regenerate_shot_ids=selected_shot_ids,
                shot_hints=selected_hints,
                **task["config_json"],
            )

        try:
            engine_result = await execute_standard_operation(
                operation=shot_rework_produce,
                config={
                    "video_provider": task["video_provider"],
                    "audio_provider": task["audio_provider"],
                    "style": task["config_json"].get("style", "cinematic"),
                    "max_shot_retries": task["config_json"].get("max_shot_retries"),
                    "consistency_threshold": task["config_json"].get("consistency_threshold"),
                },
                input_data={
                    "schema_version": 1,
                    "shot_ids": shot_ids,
                    "hints": hints or {},
                    "renderer": render_legacy_rework,
                },
                output_dir=Path("output/tasks") / str(task_id),
            )
        except Exception:
            if retake_budget_repo is not None and retake_budget_attempt_id is not None:
                await retake_budget_repo.release_attempt(
                    retake_budget_attempt_id, external_ref=f"{task_id}:retake:release"
                )
            raise
        if engine_result.get("status") != "succeeded":
            error = engine_result.get("error") or {"message": "shot rework transaction failed"}
            if retake_budget_repo is not None and retake_budget_attempt_id is not None:
                await retake_budget_repo.release_attempt(
                    retake_budget_attempt_id, external_ref=f"{task_id}:retake:release"
                )
            raise RuntimeError(str(error.get("message", error)))
        report = engine_result.get("report") or {}
        video_path = report.get("video_path")
        if not isinstance(video_path, str):
            if retake_budget_repo is not None and retake_budget_attempt_id is not None:
                await retake_budget_repo.release_attempt(
                    retake_budget_attempt_id, external_ref=f"{task_id}:retake:release"
                )
            raise RuntimeError("shot rework transaction returned no video path")
        if retake_budget_repo is not None and retake_budget_attempt_id is not None:
            await retake_budget_repo.settle_attempt(
                retake_budget_attempt_id,
                actual_cost_usd=max(retake_estimate, 0.0),
                external_ref=f"{task_id}:retake:settle",
            )
        raw_shots = report.get("shots")
        shots = (
            cast(list[dict[str, Any]], raw_shots)
            if isinstance(raw_shots, list) and all(isinstance(shot, dict) for shot in raw_shots)
            else []
        )

        # 重生成的镜头 retry_count +1,其余(本轮没点名的)沿用旧值,不是清零重记。
        for shot in shots:
            idx = shot.get("index")
            if isinstance(idx, bool) or not isinstance(idx, int):
                logger.warning("shot rework result omitted invalid shot index: %r", idx)
                continue
            old = retry_by_index.get(idx, 0)
            shot["retry_count"] = old + 1 if idx in shot_ids else old

        # 重刷 shot_states:regenerate 的 result.shots 覆盖全部镜头 → 删旧落新。
        try:
            await self.repository.delete_shots(task_id)
        except Exception as exc:
            logger.warning(f"delete_shots failed for {task_id}: {exc}")
        await self._persist_shots(task_id, shots)
        await self.repository.update_task(
            task_id,
            {
                "result_video_path": video_path,
                "config_json": {
                    **task["config_json"],
                    "artifact_manifest": ArtifactManifest.for_video(video_path).model_dump(
                        mode="json"
                    ),
                },
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        log_event(
            stage="task_service",
            event="regenerate_shots_completed",
            task_id=str(task_id),
            shot_ids=shot_ids,
        )
        return {
            **task,
            "result_video_path": video_path,
            "shots": shots,
            "quality": report.get("quality"),
        }

    async def get_task_status(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Get the current status of a task."""
        return await self.repository.get_task(task_id)

    async def submit_task(self, task_id: uuid.UUID) -> dict[str, Any]:
        """Submit a task to the durable queue in PostgreSQL deployments."""
        task = await self.repository.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Every PostgreSQL task needs a durable lease/attempt; never run it
        # directly from an API BackgroundTask.  The standalone scheduler and
        # worker are the only production execution owners.  Non-PostgreSQL
        # local fakes retain the old cloud/local compatibility behavior.
        if isinstance(self.repository.pool, PgPool) or self.is_local_provider(
            task["video_provider"]
        ):
            await enqueue(self.repository, task_id)
            refreshed = await self.repository.get_task(task_id)
            if refreshed is None:
                raise ValueError(f"Task {task_id} disappeared after enqueue")
            return refreshed

        return task
