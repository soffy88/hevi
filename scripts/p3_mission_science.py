#!/usr/bin/env python3
"""P3 Mission B — SCIENCE_EXPLAINER autonomous mission (3 segments)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from scripts.p3_mission_lib import (
    SCIENCE_SEGMENTS,
    collect_gate_summary,
    drive_mission,
    write_mission_report,
)


async def main() -> int:
    out = Path("/data/soffy/projects/hevi/output/p3/mission-science")
    mission, store, _ex = await drive_mission(
        "SCIENCE_EXPLAINER", SCIENCE_SEGMENTS,
        "Black holes: formation, accretion, orbits", out)
    assert mission.plan is not None
    incomplete = mission.plan.required_incomplete()
    if incomplete:
        print(f"BLOCKED: {[n.node_id for n in incomplete]}")
        mission.set_status("BLOCKED")
        store.save(mission)
        return 1
    mission.set_status("QA")
    store.save(mission)
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
    report_path = write_mission_report(mission, store, {"segment_gates": gates})
    from hevi.missions.p3_runtime import status_view
    print(json.dumps({"mission": mission.mission_id, "status": mission.status,
                      "report": str(report_path),
                      "p0_p1_p2_gates_pass": all(gates.values()),
                      "observability": status_view(mission),
                      "delivery": mission.delivery.final_mp4 if mission.delivery else ""}, indent=2))
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
