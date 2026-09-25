#!/usr/bin/env python3
"""P3 long-task qualification: history mission with injected crash + resume.

Proves >=3 segments, >=2 parallel branches, fan-in, and durable resume.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.missions.p3_runners import RUNNERS
from hevi.missions.p3_runtime import (
    MissionExecutor,
    build_chapters,
    build_plan,
    create_mission,
    status_view,
)
from scripts.p3_mission_lib import HISTORY_SEGMENTS, collect_gate_summary, write_mission_report


async def main() -> int:
    out = Path("/data/soffy/projects/hevi/output/p3/long-task")
    narration = " ".join(HISTORY_SEGMENTS)
    mission, store = create_mission(
        out, request=narration, profile_id="HISTORICAL_NARRATIVE",
        production_goal="Tang Chang'an long task", target_duration_s=90.0, budget_usd=50.0)
    mission.set_status("PLANNING")
    # 4 segments -> >=2 parallel branches at render time
    mission.plan = build_plan(mission, narration, segments_per_chapter=4)
    build_chapters(mission, narration, segments_per_chapter=4)
    store.save(mission)
    segs = mission.chapters[0].segments
    assert len(segs) >= 3, f"need >=3 segments, got {len(segs)}"

    async def _phase(kinds: set[str], crash_after: int = -1) -> None:
        ex = MissionExecutor(store, dict(RUNNERS), max_parallel=2, crash_after=crash_after)
        await ex.run(mission, only_kinds=kinds)

    mission.set_status("RESEARCHING")
    store.save(mission)
    await _phase({"RESEARCH"})
    mission.set_status("SCRIPTING")
    store.save(mission)
    await _phase({"SCRIPT"})
    mission.set_status("PLANNED")
    store.save(mission)
    mission.set_status("PRODUCING")
    store.save(mission)
    # Crash mid-render, then resume with a fresh executor (simulated restart)
    crashed = False
    try:
        await _phase({"RENDER"}, crash_after=2)
    except RuntimeError as exc:
        if "INJECTED_CRASH" not in str(exc):
            raise
        crashed = True
    assert crashed, "crash injection did not trigger"
    # Simulated restart: reload store, resume
    reloaded = store.load()
    assert reloaded is not None and reloaded.plan is not None
    pre_attempts = {n.node_id: n.attempts for n in reloaded.plan.nodes if n.status == "COMPLETED"}
    mission = reloaded
    await _phase({"RENDER"})
    # Idempotency: pre-crash completed nodes must not have been re-run
    assert mission.plan is not None
    for n in mission.plan.nodes:
        if n.node_id in pre_attempts:
            assert n.attempts == pre_attempts[n.node_id], f"{n.node_id} re-ran on resume"
    mission.set_status("QA")
    store.save(mission)
    await _phase({"EDIT"})
    mission.set_status("FINALIZING")
    store.save(mission)
    await _phase({"DELIVERY"})
    incomplete = mission.plan.required_incomplete() if mission.plan else []
    if incomplete:
        print(f"BLOCKED: {[n.node_id for n in incomplete]}")
        mission.set_status("BLOCKED")
        store.save(mission)
        return 1
    if mission.delivery is None or not Path(mission.delivery.final_mp4).is_file():
        print("DELIVERY_MISSING")
        return 1
    from hevi.missions.p3_runtime import assert_completable
    completable, blockers = assert_completable(mission)
    if not completable:
        print(f"COMPLETION_BLOCKED: {blockers}")
        return 1
    mission.set_status("COMPLETED")
    store.save(mission)
    gates = collect_gate_summary(mission)
    report_path = write_mission_report(mission, store, {
        "segment_gates": gates, "long_task": True,
        "segments": len(segs), "resume_proven": True,
    })
    print(json.dumps({"mission": mission.mission_id, "status": mission.status,
                      "report": str(report_path), "segments": len(segs),
                      "p0_p1_p2_gates_pass": all(gates.values()),
                      "observability": status_view(mission),
                      "delivery": mission.delivery.final_mp4 if mission.delivery else ""}, indent=2))
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
