#!/usr/bin/env python3
"""P3 Mission A — EMOTIONAL_BOOK_REVIEW autonomous mission (3 segments)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.missions.p3_runners import RUNNERS
from hevi.missions.p3_runtime import MissionExecutor, status_view
from scripts.p3_mission_lib import (
    BOOK_META,
    BOOK_SEGMENTS,
    collect_gate_summary,
    drive_mission,
    repair_demo,
    verify_repair_scope,
    write_mission_report,
)


async def main() -> int:
    out = Path("/data/soffy/projects/hevi/output/p3/mission-book")
    mission, store, ex = await drive_mission(
        "EMOTIONAL_BOOK_REVIEW", BOOK_SEGMENTS,
        "Solitude into courage — after loss", out, book_meta=BOOK_META)
    # Phase validation
    assert mission.plan is not None
    incomplete = mission.plan.required_incomplete()
    if incomplete:
        print(f"BLOCKED: {[n.node_id for n in incomplete]}")
        mission.set_status("BLOCKED")
        store.save(mission)
        return 1
    mission.set_status("QA")
    store.save(mission)
    # Fan-in/delivery already ran in drive_mission; verify delivery
    if mission.delivery is None or not Path(mission.delivery.final_mp4).is_file():
        print("DELIVERY_MISSING")
        return 1
    # --- Targeted repair proof: revise segment 1, resume, verify scope ---
    before_len = len(mission.plan.required_incomplete())
    evidence = repair_demo(
        mission, store, ex, 1,
        "Meditations by Marcus Aurelius reached me through a friend who had grieved before. "
        "The emperor wrote that loss belongs to nature, not to punishment. "
        "One paraphrased line stayed with me, that grief softens when we accept what we cannot change. "
        "Reading slowly, my breathing steadied beside his ancient calm.")
    mission.chapters[0].segments[1].narration = (
        "Meditations by Marcus Aurelius reached me through a friend who had grieved before. "
        "The emperor wrote that loss belongs to nature, not to punishment. "
        "One paraphrased line stayed with me, that grief softens when we accept what we cannot change. "
        "Reading slowly, my breathing steadied beside his ancient calm.")
    store.save(mission)
    ex2 = MissionExecutor(store, dict(RUNNERS), max_parallel=3)
    mission.set_status("PRODUCING")
    store.save(mission)
    await ex2.run(mission)
    mission.set_status("QA")
    store.save(mission)
    await ex2.run(mission)
    mission.set_status("FINALIZING")
    store.save(mission)
    await ex2.run(mission)
    scope = verify_repair_scope(mission, evidence["before_hashes"], 1)
    from hevi.missions.p3_runtime import assert_completable
    completable, blockers = assert_completable(mission)
    if not completable:
        print(f"COMPLETION_BLOCKED: {blockers}")
        return 1
    mission.set_status("COMPLETED")
    store.save(mission)
    gates = collect_gate_summary(mission)
    report_path = write_mission_report(mission, store, {
        "repair_evidence": {**evidence, **scope},
        "segment_gates": gates,
        "observability": status_view(mission),
        "incomplete_before_repair": before_len,
    })
    print(json.dumps({"mission": mission.mission_id, "status": mission.status,
                      "report": str(report_path), "repair": scope,
                      "p0_p1_p2_gates_pass": all(gates.values()),
                      "delivery": mission.delivery.final_mp4 if mission.delivery else ""}, indent=2))
    return 0 if all(gates.values()) and scope["untouched_ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
