#!/usr/bin/env python3
# ruff: noqa: E402
"""Real Blender→V2V production E2E (no mocks, real provider plane).

GATE A: BLENDER_TO_V2V_E2E — blender previz → v2v task → MaaS provider → mp4
GATE B: V2V_FAILURE_E2E — invalid model → genuine provider rejection → incident
GATE C: V2V_REPLAY_E2E — re-run completed task → no resubmit, no duplicate
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()  # provider services read os.getenv directly (API main does the same)

from hevi.artifact_store import ArtifactRepository
from hevi.core.config import settings
from hevi.creative.layer4.authority_stores import CallLedgerStore
from hevi.creative.layer4.incident_store import IncidentService
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

settings.debug = True
settings.local_mode = True

RESULTS_FILE = "/tmp/v2v_qualification_results.json"
V2V_OUT = "/tmp/v2v_e2e_result.mp4"
PREVIZ_OUT = "/tmp/v2v_e2e_previz.png"


def make_shot_spec(output_path: str) -> dict:
    return {
        "width": 640,
        "height": 480,
        "fps": 24,
        "frame_start": 1,
        "frame_end": 2,
        "camera_position": [0.0, -5.0, 3.0],
        "camera_rotation": [0.0, 0.0, 0.0],
        "light_position": [0.0, -2.0, 2.0],
        "light_energy": 0.5,
        "objects": [
            {
                "type": "cube",
                "name": "V2VSource",
                "location": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
        ],
        "output_path": output_path,
    }


async def create_task(repo: TaskRepository, config_json: dict, source: str) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    return await repo.create_task(
        {
            "id": uuid.uuid4(),
            "topic": "v2v_qualification",
            "user_id": "v2v_qual",
            "idempotency_key": str(uuid.uuid4()),
            "duration_archetype": "rendering",
            "video_provider": source,
            "audio_provider": "none",
            "status": "pending",
            "progress_pct": 0.0,
            "total_shots": 0,
            "completed_shots": 0,
            "priority": 0,
            "deadline_at": None,
            "resource_class": "any",
            "required_vram_mb": 0,
            "expected_cost_usd": 0.0,
            "tenant_weight": 1.0,
            "warm_provider": "false",
            "created_at": now,
            "updated_at": now,
            "config_json": config_json,
        }
    )


def ledger_submissions(production_id: str) -> int:
    _records, total = CallLedgerStore().list_records(
        provider="dashscope-i2v", project_ref=production_id, limit=100
    )
    return total


async def gate_a_blender_to_v2v() -> dict:
    pool = await get_hevi_pg_pool()
    repo = TaskRepository(pool)
    service = TaskService(repo)
    artifact_repo = ArtifactRepository(pool)

    for p in (PREVIZ_OUT, V2V_OUT):
        if os.path.exists(p):
            os.remove(p)

    production_id = str(uuid.uuid4())
    btask = await create_task(
        repo,
        {
            "shot_spec": make_shot_spec(PREVIZ_OUT),
            "output_path": PREVIZ_OUT,
            "production_source": "blender_previz",
            "production_id": production_id,
            "revision_id": production_id,
        },
        "blender_previz",
    )
    bres = await service.run_task(btask["id"])
    assert bres.get("status") == "completed", f"blender failed: {bres.get('error')}"
    manifest = bres["config_json"]["artifact_manifest"]["artifacts"][0]
    blender_artifact_id = manifest.get("artifact_id")
    blender_sha = manifest.get("sha256")
    print(f"Gate A: blender artifact id={blender_artifact_id} sha={str(blender_sha)[:16]}")

    # Resolve source through the artifact authority (lineage, not temp path).
    db_manifest = await artifact_repo.get_manifest(production_id)
    assert db_manifest is not None and len(db_manifest.artifacts) > 0
    source_art = None
    for art in db_manifest.artifacts:
        if str(art.artifact_id or "") == str(blender_artifact_id):
            source_art = art
            break
    assert source_art is not None, "previz artifact not retrievable by id"

    vtask = await create_task(
        repo,
        {
            "v2v_spec": {
                "prompt": "slow cinematic push-in, keep the ink-wash cube style",
                # MaaS entitlement probe 2026-09-21: wan2.2-i2v-flash → 403
                # AccessDenied.Unpurchased; happyhorse-1.1-r2v submit ACCEPTED.
                "provider": "dashscope-r2v",
                "model": "happyhorse-1.1-r2v",
                "resolution": "720P",
                "duration": 2,
                "timeout_s": 1500.0,
                "source_artifact_id": str(blender_artifact_id),
            },
            "output_path": V2V_OUT,
            "production_source": "v2v",
            "production_id": production_id,
            "revision_id": production_id,  # stale on purpose: invariant overwrites
        },
        "v2v",
    )
    pre = await service._ensure_production_graph(
        await repo.get_task(vtask["id"]) or {}
    )
    from hevi.production_graph.repository import ProductionGraphRepository

    rev_before = await ProductionGraphRepository(pool).revision_exists(pre["revision_id"])
    print(f"Gate A: canonical revision={pre['revision_id']} exists_before={rev_before}")
    subs_before = ledger_submissions(production_id)

    vres = await service.run_task(vtask["id"])
    status = vres.get("status")
    print(f"Gate A: v2v status={status} err={vres.get('error')}")
    cfg = (vres.get("config_json") or {}) if isinstance(vres.get("config_json"), dict) else {}
    db_task = await repo.get_task(vtask["id"])
    db_cfg = (db_task.get("config_json") or {}) if db_task else {}
    merged = {**cfg, **db_cfg}
    subs_after = ledger_submissions(production_id)
    print(f"Gate A: ledger submissions {subs_before}->{subs_after}")

    out_path = vres.get("result_video_path") or ""
    f_exists = bool(out_path) and os.path.exists(out_path)
    f_size = os.path.getsize(out_path) if f_exists else 0
    vmanifest = await artifact_repo.get_manifest(production_id)
    varts = [a for a in (vmanifest.artifacts if vmanifest else []) if a.kind == "video"]
    return {
        "task_id": str(vtask["id"]),
        "production_id": production_id,
        "revision_id": pre["revision_id"],
        "revision_row_exists_before_adapter": rev_before,
        "status": status,
        "db_status": db_task.get("status") if db_task else None,
        "provider": merged.get("v2v_provider"),
        "model": merged.get("v2v_model"),
        "job_id": merged.get("v2v_job_id"),
        "quality_signal": merged.get("v2v_quality_signal"),
        "source_lineage_by_id": merged.get("v2v_source_lineage_by_id"),
        "source_sha_match": merged.get("v2v_source_sha256") == blender_sha,
        "ledger_submissions_before": subs_before,
        "ledger_submissions_after": subs_after,
        "provider_execution_recorded": subs_after > subs_before,
        "output_path": out_path,
        "file_exists": f_exists,
        "file_size": f_size,
        "artifact_registered": len(varts) > 0,
        "artifact_retrievable": len(varts) > 0,
        "artifact_id": str(varts[0].artifact_id) if varts else None,
        "blender_artifact_id": str(blender_artifact_id),
    }


async def gate_b_v2v_failure() -> dict:
    pool = await get_hevi_pg_pool()
    repo = TaskRepository(pool)
    service = TaskService(repo)
    production_id = str(uuid.uuid4())
    fail_out = "/tmp/v2v_e2e_fail.mp4"
    if os.path.exists(fail_out):
        os.remove(fail_out)
    # Deterministic genuine rejection: model does not exist (404, no charge).
    vtask = await create_task(
        repo,
        {
            "v2v_spec": {
                "prompt": "probe",
                "provider": "dashscope-i2v",
                "model": "probe-nonexistent-model-xyz",
                "resolution": "720P",
                "source_path": PREVIZ_OUT,
            },
            "output_path": fail_out,
            "production_source": "v2v",
            "production_id": production_id,
            "revision_id": production_id,
        },
        "v2v",
    )
    pre = await service._ensure_production_graph(await repo.get_task(vtask["id"]) or {})
    from hevi.production_graph.repository import ProductionGraphRepository

    rev_before = await ProductionGraphRepository(pool).revision_exists(pre["revision_id"])
    vres = await service.run_task(vtask["id"])
    status = vres.get("status")
    incidents = IncidentService().list_incidents(production_run_id=str(vtask["id"]))
    print(f"Gate B: status={status} incidents={len(incidents)} rev_before={rev_before}")
    inc = incidents[0] if incidents else None
    return {
        "task_id": str(vtask["id"]),
        "revision_row_exists_before_adapter": rev_before,
        "status": status,
        "db_status": (await repo.get_task(vtask["id"])).get("status"),
        "failure_code": inc.failure_code if inc else None,
        "repair_incident_id": inc.incident_id if inc else None,
        "incidents_count": len(incidents),
    }


async def gate_c_replay(task_id: str, production_id: str) -> dict:
    pool = await get_hevi_pg_pool()
    repo = TaskRepository(pool)
    service = TaskService(repo)
    artifact_repo = ArtifactRepository(pool)
    subs_before = ledger_submissions(production_id)
    m_before = await artifact_repo.get_manifest(production_id)
    arts_before = len(m_before.artifacts) if m_before else 0
    mtime_before = os.path.getmtime(V2V_OUT) if os.path.exists(V2V_OUT) else 0.0
    result = await service.run_task(uuid.UUID(task_id))
    subs_after = ledger_submissions(production_id)
    m_after = await artifact_repo.get_manifest(production_id)
    arts_after = len(m_after.artifacts) if m_after else 0
    mtime_after = os.path.getmtime(V2V_OUT) if os.path.exists(V2V_OUT) else 0.0
    rerendered = mtime_after != mtime_before
    print(f"Gate C: subs {subs_before}->{subs_after} arts {arts_before}->{arts_after}")
    return {
        "subs_before": subs_before,
        "subs_after": subs_after,
        "arts_before": arts_before,
        "arts_after": arts_after,
        "rerendered": rerendered,
        "duplicate_provider_submissions": max(0, subs_after - subs_before),
        "duplicate_artifact_registrations": max(0, arts_after - arts_before),
        "result_status": result.get("status"),
    }


async def main():
    results = {}
    print("GATE A: BLENDER_TO_V2V_E2E")
    try:
        results["gate_a"] = await gate_a_blender_to_v2v()
    except Exception as e:
        import traceback

        traceback.print_exc()
        results["gate_a"] = {"error": str(e)}
    print("GATE B: V2V_FAILURE_E2E")
    try:
        results["gate_b"] = await gate_b_v2v_failure()
    except Exception as e:
        import traceback

        traceback.print_exc()
        results["gate_b"] = {"error": str(e)}
    print("GATE C: V2V_REPLAY_E2E")
    try:
        ga = results.get("gate_a", {})
        if ga.get("status") == "completed":
            results["gate_c"] = await gate_c_replay(ga["task_id"], ga["production_id"])
        else:
            results["gate_c"] = {"skipped": True, "reason": "gate A did not complete"}
    except Exception as e:
        import traceback

        traceback.print_exc()
        results["gate_c"] = {"error": str(e)}
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
