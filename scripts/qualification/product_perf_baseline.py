#!/usr/bin/env python3
"""D6-K: productization performance baseline (no absolute SLA).

Measures P50/P95 wall time for the product-facing endpoints on the local
test runtime. This establishes a baseline to detect regressions; it does not
assert a hard SLA.
"""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers.tasks import get_repository
from hevi.auth.dependencies import get_current_user

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "research" / "hevi_d6_performance_baseline.json"
ITERATIONS = 30


class _Repo:
    def __init__(self, task: dict):
        self._task = task

    async def get_task(self, _task_id):
        return self._task


def _measure(client: TestClient, method: str, path: str, **kwargs) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        response = getattr(client, method)(path, **kwargs)
        samples.append((time.perf_counter() - start) * 1000.0)
        if response.status_code >= 500:
            raise RuntimeError(f"{method} {path} -> {response.status_code}")
    samples.sort()
    return {
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 3),
        "min_ms": round(samples[0], 3),
        "max_ms": round(samples[-1], 3),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["HEVI_IDENTITY_DB"] = str(Path(tmp) / "identities.db")
        os.environ["HEVI_INCIDENT_DB"] = str(Path(tmp) / "incidents.db")
        os.environ["HEVI_MEMORY_DB"] = str(Path(tmp) / "memory.db")
        app.dependency_overrides[get_current_user] = lambda: {"id": "perf-owner"}
        task = {
            "id": "11111111-1111-1111-1111-111111111111",
            "user_id": "perf-owner",
            "status": "completed",
            "config_json": {
                "artifact_manifest": {
                    "artifacts": [
                        {
                            "kind": "video",
                            "path": "final.mp4",
                            "sha256": "abc",
                            "logical_role": "final_video",
                        }
                    ]
                }
            },
        }
        app.dependency_overrides[get_repository] = lambda: _Repo(task)
        client = TestClient(app)
        try:
            # Seed a few identities + an incident.
            for i in range(5):
                identity = client.post(
                    "/api/identities",
                    json={"canonical_name": f"Perf{i}", "voice_id": f"v{i}"},
                ).json()
                client.post(
                    f"/api/identities/projects/proj-{i}/bindings",
                    json={"identity_id": identity["identity_id"]},
                )
            client.post(
                "/api/incidents/open",
                json={
                    "production_run_id": task["id"],
                    "node_key": "task.run",
                    "failure": "PROVIDER_FAILURE",
                    "evidence": {"signature": "provider temporarily unavailable", "transient": True},
                },
            )

            results = {
                "identity_library_load": _measure(client, "get", "/api/identities"),
                "continuity_summary": _measure(
                    client, "get", "/api/continuity/projects/proj-0/summary"
                ),
                "incident_list": _measure(
                    client, "get", f"/api/incidents?production_run_id={task['id']}"
                ),
                "project_health": _measure(
                    client, "get", f"/api/products/projects/{task['id']}/health"
                ),
                "product_metrics": _measure(client, "get", "/api/products/metrics"),
                "project_load": _measure(
                    client, "get", f"/api/products/projects/{task['id']}/health"
                ),
            }
        finally:
            app.dependency_overrides.clear()

    payload = {
        "phase": "D6-K",
        "iterations": ITERATIONS,
        "note": "Baseline only; no absolute SLA. Re-run to detect regressions.",
        "endpoints": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
