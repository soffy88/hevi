#!/usr/bin/env python3
"""P4 long-form E2E: one 120s EMOTIONAL_BOOK_REVIEW video via P3 mission runtime.

Ten coherent segments share one emotional arc (solitude into courage),
one voice, one profile. Duration controlled by DurationController.
Uses P3 MissionExecutor for multi-segment fan-out/fan-in.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.ops.p4_duration import DurationController
from hevi.missions.p3_runners import RUNNERS
from hevi.missions.p3_runtime import (
    MissionExecutor,
    create_mission,
    MissionStore,
)
from hevi.missions.p3_types import (
    PlanNode,
    ProductionChapter,
    ProductionMission,
    ProductionPlan,
    ProductionSegment,
)

ROOT = Path("/data/soffy/projects/hevi/output/p4/longform")
TARGET_S = 300.0

SEGMENTS = [
    "After my father passed away, solitude followed me through every quiet evening. Empty rooms kept his habits long after he was gone. I set his place at the table for weeks without thinking. Grief arrived without schedule, softening only when I stopped fighting it. Loneliness taught me to listen instead of running. Silence, I learned, is also a kind of company.",
    "Meditations by Marcus Aurelius reached me through a friend who had grieved before. The emperor wrote that loss belongs to nature, not to punishment. One paraphrased line stayed with me, that grief softens when we accept what we cannot change. Reading slowly, my breathing steadied beside his ancient calm. A dead emperor became an unlikely evening companion. Two thousand years collapsed into one lamplit room.",
    "Mornings were the hardest, when the house expected two voices at breakfast. I began writing unsent letters to say what silence had swallowed. Each page carried a little of the weight out of my chest. Solitude slowly changed from punishment into practice. The quiet house stopped accusing and started holding. Even the ticking clock sounded like accompaniment.",
    "Marcus wrote that we suffer more in imagination than in reality. I tested this claim against my own spiraling evening thoughts. Most fears dissolved when examined under a lamp with pen in hand. What remained was simpler and smaller than dread had promised. Fear shrinks the moment you look at it directly. Courage is only fear that kept breathing steadily.",
    "Anger arrived next, sharp and embarrassing in its direction. I resented the doctors, the calendar, even the indifferent spring weather. The book suggested anger is grief wearing armor for battle. Naming it honestly loosened its grip within weeks. I apologized to no one and forgave nearly everyone. Forgiveness turned out to be a gift to myself.",
    "Nature became my second teacher after the book had opened the door. Walks along the river showed me Heraclitus was right about constant change. No wave returns the same, yet the river remains itself. I practiced letting feelings of grief pass like water under bridges. The river asked nothing and explained nothing back. I walked home lighter nearly every single time. Hope returned with each step.",
    "Gratitude felt impossible until it arrived uninvited one October morning. Sunlight on ordinary rooftops looked generous for no reason at all. I listed small mercies: warm bread, a neighbor's nod, rain. Thankfulness did not erase loss, but it widened the room. Grief and gratitude learned to share the same chair. Both of them, I realized, are forms of love.",
    "Time behaved strangely, stretching dull afternoons into deserts. Marcus reminded me that the present moment is all we ever truly own. I stopped rehearsing futures and replaying final hospital weeks. Attention to now became my daily discipline and refuge. The present moment never once abandoned me. It waited patiently while I learned to arrive. Courage grew in the waiting.",
    "Acceptance did not erase the missing, but it changed its shape. I began keeping small evening rituals in his honor. Solitude became a room I could enter and leave freely. Memory turned from wound into companion over slow months. I visit him now instead of bleeding there. Love outlasts the sharp edges of every goodbye.",
    "I closed the book carrying quiet courage into ordinary days. Solitude no longer frightens the person I have become. Loss taught acceptance, and acceptance taught gentle strength. The final page felt less like an ending than a beginning. Morning light does the rest of the explaining. Each dawn practices the same quiet resurrection.",
    "The journey through grief has no map but the footsteps of those who walked before. Each step forward is measured not in distance but in moments of peace reclaimed. The book remains open on the nightstand, its pages worn smooth by returning fingers. Grief and hope walk together now.",
    "Dawn breaks differently now, the light finding corners that were shadow for so long. The empty chair at the table no longer accuses but holds space for memory. This is not an ending but a continuing, each day written in the same quiet ink. Courage grows in the morning light.",
    "In the end, courage was not the absence of fear but the decision to keep breathing through it. The meditation continues, not in pages but in mornings that arrive one after another, each one a practice of the same quiet resurrection. Loss taught acceptance, and acceptance taught gentle strength.",
]


def _build_plan_from_segments(mission: ProductionMission, segments: list[str], book_meta: dict) -> ProductionPlan:
    """Build plan with explicit segments from the SEGMENTS array."""
    plan = ProductionPlan(plan_id=f"{mission.mission_id}:plan")
    plan.nodes.append(PlanNode(
        node_id="research", kind="RESEARCH", label="research + verification",
        estimated_cost_usd=0.0, idempotency_key=f"{mission.mission_id}:research:v1"))
    plan.nodes.append(PlanNode(
        node_id="script", kind="SCRIPT", label="script document",
        dependencies=("research",), estimated_cost_usd=0.0,
        idempotency_key=f"{mission.mission_id}:script:v1"))
    for i, seg in enumerate(segments):
        plan.nodes.append(PlanNode(
            node_id=f"segment-{i}", kind="RENDER", label=f"segment {i} render",
            dependencies=("script",), estimated_cost_usd=1.0,
            idempotency_key=f"{mission.mission_id}:segment-{i}:v1",
            segment_index=i, payload={"narration": seg, "book_meta": book_meta}))
    plan.nodes.append(PlanNode(
        node_id="fanin", kind="EDIT", label="segment fan-in + master QA",
        dependencies=tuple(f"segment-{i}" for i in range(len(segments))),
        estimated_cost_usd=0.0, idempotency_key=f"{mission.mission_id}:fanin:v1"))
    plan.nodes.append(PlanNode(
        node_id="delivery", kind="DELIVERY", label="delivery manifest",
        dependencies=("fanin",), estimated_cost_usd=0.0,
        idempotency_key=f"{mission.mission_id}:delivery:v1"))
    return plan


def _build_chapters_from_segments(mission: ProductionMission, segments: list[str]) -> None:
    """Build chapters with explicit segments from the SEGMENTS array."""
    ch = ProductionChapter(chapter_index=0, title=mission.production_goal or "chapter-0")
    for i, seg in enumerate(segments):
        ch.segments.append(ProductionSegment(
            segment_index=i, chapter_index=0, narration=seg,
            segment_run_dir=str(Path(mission.artifact_root) / f"segment-{i}")))
    mission.chapters = [ch]


async def main() -> int:
    dc = DurationController(chars_per_s=10.9, tolerance=0.15)
    narration = " ".join(SEGMENTS)
    plan = dc.plan(TARGET_S)
    est = dc.estimate(narration, plan)
    print(f"planned chars/seg: {plan.chars_per_segment:.0f} estimated_s: {est:.1f} target: {TARGET_S}")

    mission, store = create_mission(
        ROOT / "mission", request=narration, profile_id="EMOTIONAL_BOOK_REVIEW",
        production_goal="Solitude into courage — long meditation", target_duration_s=TARGET_S, budget_usd=50.0)
    mission.set_status("PLANNING")
    
    # Use explicit SEGMENTS array for reliable QA gates
    book_meta = {"title": "Meditations", "author": "Marcus Aurelius", "verified": True, "note": "PARAPHRASE"}
    mission.plan = _build_plan_from_segments(mission, SEGMENTS, book_meta)
    _build_chapters_from_segments(mission, SEGMENTS)
    store.save(mission)
    segs = mission.chapters[0].segments
    assert len(segs) >= 3, f"need >=3 segments, got {len(segs)}"
    print(f"Created {len(segs)} segments")

    async def _phase(kinds: set[str], crash_after: int = -1) -> None:
        ex = MissionExecutor(store, dict(RUNNERS), max_parallel=1, crash_after=crash_after)
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
    await _phase({"RENDER"})
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

    final = mission.delivery.final_mp4
    actual = 0.0
    if final and Path(final).is_file():
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", final],
                           capture_output=True, text=True, check=False)
        try:
            actual = float((r.stdout or "0").strip() or 0)
        except ValueError:
            actual = 0.0

    rep = dc.report(TARGET_S, actual)
    out = {
        "mission": mission.mission_id,
        "status": mission.status,
        "target_s": TARGET_S,
        "actual_s": actual,
        "duration_error": rep.error_ratio,
        "within_tolerance": rep.within_tolerance,
        "final_mp4": final,
        "segments": len(segs),
    }
    (ROOT / "longform_report.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    ok = (mission.status == "COMPLETED" and rep.within_tolerance
          and bool(final and Path(final).is_file()))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))