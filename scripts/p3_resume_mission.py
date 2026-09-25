#!/usr/bin/env python3
"""Resume a durable P3 mission from disk (crash recovery path).

Usage:
  p3_resume_mission.py <mission_dir> [--repair-seg N --repair-text TEXT]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.missions.p3_runners import RUNNERS
from hevi.missions.p3_runtime import (
    MissionExecutor,
    MissionStore,
    assert_completable,
    reap_stale_running_nodes,
)
from scripts.p3_mission_lib import (
    collect_gate_summary,
    repair_demo,
    verify_repair_scope,
    write_mission_report,
)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mission_dir", type=str)
    ap.add_argument("--repair-seg", type=int, default=-1)
    ap.add_argument("--repair-text", type=str, default="")
    ap.add_argument("--retry-failed", type=str, default="",
                    help="comma-separated node kinds to reset from FAILED to PENDING (operator retry)")
    args = ap.parse_args()

    store = MissionStore(Path(args.mission_dir))
    mission = store.load()
    if mission is None or mission.plan is None:
        print("NO_MISSION_STATE")
        return 1
    reaped = reap_stale_running_nodes(mission)
    print(f"reaped stale RUNNING nodes: {reaped}")
    retried: list[str] = []
    if args.retry_failed and mission.plan is not None:
        kinds = {k.strip() for k in args.retry_failed.split(",") if k.strip()}
        for n in mission.plan.nodes:
            if n.status == "FAILED" and n.kind in kinds:
                if n.attempts >= n.max_attempts:
                    print(f"RETRY_BUDGET_EXHAUSTED: {n.node_id}")
                    return 1
                n.status = "PENDING"
                n.error = ""
                retried.append(n.node_id)
        print(f"operator retry reset: {retried}")
    store.save(mission)

    async def _phase(kinds: set[str], parallel: int = 3) -> None:
        ex = MissionExecutor(store, dict(RUNNERS), max_parallel=parallel)
        await ex.run(mission, only_kinds=kinds)
        store.save(mission)

    # Continue from wherever the graph stands.
    if any(n.status in ("PENDING", "RUNNING", "FAILED") and n.kind == "RENDER"
           for n in mission.plan.nodes):
        mission.set_status("PRODUCING")
        store.save(mission)
        await _phase({"RENDER"})
    if any(n.status in ("PENDING", "RUNNING") and n.kind == "EDIT" for n in mission.plan.nodes):
        mission.set_status("QA")
        store.save(mission)
        await _phase({"EDIT"})
    if any(n.status in ("PENDING", "RUNNING") and n.kind == "DELIVERY" for n in mission.plan.nodes):
        mission.set_status("FINALIZING")
        store.save(mission)
        await _phase({"DELIVERY"})

    extra: dict[str, object] = {"resumed": True, "reaped": reaped}
    if mission.plan is not None and any(n.attempts > 1 for n in mission.plan.nodes):
        extra["resume_proven"] = True
    if args.repair_seg >= 0 and args.repair_text:
        ex2 = MissionExecutor(store, dict(RUNNERS), max_parallel=3)
        evidence = repair_demo(mission, store, ex2, args.repair_seg, args.repair_text)
        store.save(mission)
        await ex2.run(mission)
        mission.set_status("QA")
        store.save(mission)
        await ex2.run(mission)
        mission.set_status("FINALIZING")
        store.save(mission)
        await ex2.run(mission)
        scope = verify_repair_scope(mission, evidence["before_hashes"], args.repair_seg)
        extra["repair_evidence"] = {**evidence, **scope}

    completable, blockers = assert_completable(mission)
    if not completable:
        print(f"COMPLETION_BLOCKED: {blockers}")
        mission.set_status("BLOCKED")
        store.save(mission)
        return 1
    mission.set_status("COMPLETED")
    store.save(mission)
    gates = collect_gate_summary(mission)
    report_path = write_mission_report(mission, store, extra)
    print(json.dumps({"mission": mission.mission_id, "status": mission.status,
                      "report": str(report_path), "gates_pass": all(gates.values()),
                      "delivery": mission.delivery.final_mp4 if mission.delivery else ""}, indent=2))
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
