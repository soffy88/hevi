#!/usr/bin/env python3
"""Run one real free-local second-provider case reproduction (Track 4).

Creates (or reuses) a durable case_reproduction for provider=manim, enqueues
the task through TaskService.submit_task so the production scheduler + worker
claim path executes it, then polls until a terminal status. Writes an evidence
JSON with the reproduction id, task id, verdict, and artifact path.

Free local only — never spends owner budget.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Match the existing corpus generation_parameters size budget.
DEFAULT_PARAMS = {"width": 320, "height": 240, "duration_s": 1.0, "mode": "code_scene"}
TERMINAL_STATUSES = frozenset({"completed", "failed", "interrupted", "canceled"})


async def _pick_case(pool: Any) -> tuple[str, str, str]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT c.id::text AS case_id, a.id::text AS analysis_id, c.original_prompt "
            "FROM video_cases c "
            "JOIN video_case_analyses a ON a.case_id=c.id AND a.status='succeeded' "
            "WHERE c.analysis_status='completed' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM case_reproductions r "
            "  WHERE r.case_id=c.id AND r.provider_id='manim' AND r.status='succeeded'"
            ") "
            "ORDER BY c.created_at LIMIT 1"
        )
        if row is None:
            raise RuntimeError("NO_CASE_WITHOUT_MANIM_REPRO")
        return str(row["case_id"]), str(row["analysis_id"]), str(row["original_prompt"] or "")


async def _find_open_manim_repro(pool: Any) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id::text AS id, case_id::text AS case_id, status, provider_id, "
            "task_id::text AS task_id "
            "FROM case_reproductions "
            "WHERE provider_id='manim' AND status IN ('pending','running','failed')"
            "ORDER BY created_at LIMIT 1"
        )
        return dict(row) if row else None


async def _poll_task(
    repo: Any, task_id: str, *, timeout_s: float, interval_s: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = dict(await repo.get_task(uuid.UUID(task_id)) or {})
        status = str(last.get("status") or "")
        if status in TERMINAL_STATUSES:
            return last
        await asyncio.sleep(interval_s)
    return last


async def _poll_or_run(
    service: Any,
    repo: Any,
    task_id: str,
    status: str,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    """Execute under our claim lease, or poll if another owner already has it."""
    current = dict(await repo.get_task(uuid.UUID(task_id)) or {})
    worker = str(current.get("worker_id") or "")
    if str(current.get("status")) == "claimed" and worker == "second-provider-repro":
        return dict(await service.run_task(uuid.UUID(task_id)))
    if str(current.get("status")) in TERMINAL_STATUSES:
        return current
    if status == "claimed":
        refreshed = dict(await repo.get_task(uuid.UUID(task_id)) or {})
        if str(refreshed.get("worker_id") or "") == "second-provider-repro":
            return dict(await service.run_task(uuid.UUID(task_id)))
    return await _poll_task(repo, task_id, timeout_s=timeout_s, interval_s=1.0)


async def run_one(*, workspace_id: str, key: str, timeout_s: float) -> dict[str, Any]:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.production.composition import configure_application_adapters
    from hevi.providers.registry import register_all_providers
    from hevi.tasks.repository import TaskRepository
    from hevi.tasks.task_service import TaskService
    from hevi.video_intelligence.runtime_repository import (
        CaseAnalysisRepository,
        CaseReproductionRepository,
    )

    register_all_providers()
    configure_application_adapters()
    pool = await get_hevi_pg_pool()
    try:
        case_id, analysis_id, prompt = await _pick_case(pool)
        analysis_repo = CaseAnalysisRepository(pool)
        analysis = await analysis_repo.get_owned(analysis_id, user_id=_seed_user())
        if analysis is None or analysis.get("status") != "succeeded":
            raise RuntimeError("ANALYSIS_NOT_SUCCEEDED")
        user_id = str(analysis["user_id"])

        repro_repo = CaseReproductionRepository(pool)
        task_repo = TaskRepository(pool)
        service = TaskService(task_repo)

        open_repro = await _find_open_manim_repro(pool)
        if open_repro and open_repro.get("task_id"):
            reproduction = open_repro
            task_id = str(reproduction["task_id"])
            task = await task_repo.get_task(uuid.UUID(task_id))
            if task is None:
                raise RuntimeError("OPEN_REPRO_TASK_MISSING")
            task = dict(task)
            reused = True
        else:
            existing = await repro_repo.find_idempotent(
                case_id=case_id, user_id=user_id, key=key
            )
            if existing and existing.get("status") == "succeeded":
                out = Path("output/case_reproductions") / str(existing["id"]) / "reproduction.mp4"
                return {
                    "idempotent_replay": True,
                    "case_id": case_id,
                    "analysis_id": analysis_id,
                    "user_id": user_id,
                    "reproduction_id": str(existing["id"]),
                    "task_id": str(existing.get("task_id") or ""),
                    "task_status": str(existing.get("status") or ""),
                    "task_error": None,
                    "reproduction_status": str(existing["status"]),
                    "provider_id": str(existing["provider_id"]),
                    "verdict_id": str(existing.get("verdict_id") or "") or None,
                    "failure_code": existing.get("failure_code"),
                    "failure_detail": existing.get("failure_detail"),
                    "artifact_path": str(out) if out.is_file() else None,
                    "artifact_bytes": out.stat().st_size if out.is_file() else 0,
                    "elapsed_ms": 0,
                    "generation_parameters": dict(DEFAULT_PARAMS),
                    "prompt": prompt[:200],
                }
            task = await service.create_task(
                topic=f"case-reproduction:{case_id}",
                duration_archetype="1-5min",
                video_provider="manim",
                audio_provider="vibevoice",
                user_id=user_id,
                idempotency_key=f"case-reproduction:{key}",
                production_source="case_reproduction",
                case_id=case_id,
                analysis_id=analysis_id,
                provider_id="manim",
                model_id="manim",
            )
            reproduction = await repro_repo.create_pending(
                case_id=case_id,
                user_id=user_id,
                workspace_id=workspace_id,
                key=key,
                provider_id="manim",
                model_id="manim",
                model_version=None,
                generation_mode="exact_structure",
                compiled_prompt=prompt,
                reference_bindings=[],
                parameters=dict(DEFAULT_PARAMS),
                task_id=str(task["id"]),
            )
            config = dict(task.get("config_json") or {})
            config.update(
                {
                    "reproduction_id": str(reproduction["id"]),
                    "provider_id": "manim",
                    "model_id": "manim",
                }
            )
            await task_repo.update_task(task["id"], {"config_json": config})
            task_id = str(task["id"])
            reused = False

        status = str(task.get("status") or "")
        if status in {"pending", "queued"}:
            task = await service.submit_task(uuid.UUID(task_id))
            status = str(task.get("status") or "")

        started = time.perf_counter()
        if status in TERMINAL_STATUSES:
            finished = task
        else:
            claimed = await task_repo.claim_next_queued_task(
                worker_id="second-provider-repro",
                scheduled_only=False,
            )
            if claimed and str(claimed["id"]) == task_id:
                status = "claimed"
            finished = await _poll_or_run(service, task_repo, task_id, status, timeout_s=timeout_s)
        elapsed_ms = round((time.perf_counter() - started) * 1000)

        refreshed = await repro_repo.get_owned(str(reproduction["id"]), user_id=user_id)
        out_path = Path("output/case_reproductions") / str(reproduction["id"]) / "reproduction.mp4"
        return {
            "reused_open_repro": reused,
            "case_id": case_id,
            "analysis_id": analysis_id,
            "user_id": user_id,
            "reproduction_id": str(reproduction["id"]),
            "task_id": task_id,
            "task_status": str(finished.get("status") or ""),
            "task_error": finished.get("error"),
            "reproduction_status": str((refreshed or {}).get("status") or ""),
            "provider_id": str((refreshed or {}).get("provider_id") or ""),
            "verdict_id": str((refreshed or {}).get("verdict_id") or "") or None,
            "failure_code": (refreshed or {}).get("failure_code"),
            "failure_detail": (refreshed or {}).get("failure_detail"),
            "artifact_path": str(out_path) if out_path.is_file() else None,
            "artifact_bytes": out_path.stat().st_size if out_path.is_file() else 0,
            "elapsed_ms": elapsed_ms,
            "generation_parameters": dict(DEFAULT_PARAMS),
            "prompt": prompt[:200],
        }
    finally:
        await pool.close()


def _seed_user() -> str:
    return "7914fd9b-2bf6-403e-8384-fb4c29e362e0"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="closure-smoke")
    parser.add_argument("--key", default=None, help="idempotency key (default: time-based)")
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("artifacts/qualification/second-provider-manim-repro.json"),
    )
    args = parser.parse_args()
    key = args.key or f"manim-second-provider-{int(time.time())}"
    report = asyncio.run(
        run_one(workspace_id=args.workspace, key=key, timeout_s=args.timeout_s)
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    ok = report.get("reproduction_status") == "succeeded" and bool(report.get("artifact_bytes"))
    print(f"second_provider_real_run={'PASS' if ok else 'FAIL'}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
