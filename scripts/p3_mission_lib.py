#!/usr/bin/env python3
"""Shared driver for P3 autonomous missions (phase advance, repair, evidence)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.missions.p3_runners import RUNNERS
from hevi.missions.p3_runtime import (
    MissionExecutor,
    MissionStore,
    build_chapters,
    build_plan,
    create_mission,
    invalidate_dependents,
    status_view,
)
from hevi.missions.p3_types import ProductionMission

BOOK_SEGMENTS = [
    "After my father passed away, solitude followed me through every quiet evening. "
    "Empty rooms kept his habits long after he was gone. "
    "Grief arrived without schedule, softening only when I stopped fighting it. "
    "Loneliness taught me to listen instead of running.",
    "Meditations by Marcus Aurelius reached me through a friend who had grieved before. "
    "The emperor wrote that loss belongs to nature, not to punishment. "
    "One paraphrased line stayed with me, that grief softens when we stop fighting what we cannot change. "
    "Reading slowly, my breathing steadied beside his ancient calm.",
    "Acceptance did not erase the missing, but it changed its shape. "
    "I began keeping small evening rituals in his honor. "
    "Solitude became a room I could enter and leave. "
    "I closed the book carrying quiet courage into ordinary days.",
]

SCIENCE_SEGMENTS = [
    "A black hole forms when a massive star collapses under its own gravity. "
    "The core falls inward faster than light can escape. "
    "The event horizon marks the boundary of no return. "
    "What remains warps spacetime itself.",
    "The accretion disk around it glows with intense X-ray emission. "
    "Gas spirals inward, heating as it falls. "
    "Binary black holes spiral together, merging in gravitational waves. "
    "Each merger rings spacetime like a bell.",
    "Orbital visualizations reveal the warped spacetime near the event horizon. "
    "Light bends into glowing rings around shadow. "
    "These images turn mathematics into something eyes can follow. "
    "Wonder remains after explanation ends.",
]

HISTORY_SEGMENTS = [
    "In the seventh century, Tang dynasty Chang'an became a meeting place for merchants and monks. "
    "Porcelain and silk traveled west while ideas traveled east along desert routes. "
    "Sogdian traders settled whole quarters of the capital city. "
    "The empire measured its strength in open roads.",
    "Merchants compared Tang coins with Sogdian silver, weighing value at every market. "
    "Contracts were written in two scripts and sealed twice. "
    "Trust traveled slower than goods but lasted longer. "
    "The market remembered every honest dealer.",
    "When rebellion disrupted the empire, trade shifted and cities declined. "
    "The consequence shaped maps, documents, and memory across centuries. "
    "Routes moved but the exchange never fully stopped. "
    "What survived was written down and kept.",
]

BOOK_META = {"title": "Meditations", "author": "Marcus Aurelius", "verified": True, "note": "PARAPHRASE"}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


async def drive_mission(
    profile_id: str,
    segments: list[str],
    topic: str,
    out_dir: Path,
    book_meta: dict | None = None,
    max_parallel: int = 3,
    crash_after: int = -1,
) -> tuple[ProductionMission, MissionStore, MissionExecutor]:
    out_dir = Path(out_dir)
    mission, store = create_mission(
        out_dir, request=" ".join(segments), profile_id=profile_id,
        production_goal=topic, target_duration_s=60.0, budget_usd=50.0)
    mission.set_status("PLANNING")
    mission.plan = build_plan(mission, " ".join(segments), segments_per_chapter=len(segments))
    build_chapters(mission, " ".join(segments), segments_per_chapter=len(segments))
    # Per-segment narration + book metadata
    for i, _seg in enumerate(segments):
        node = mission.plan.node(f"segment-{i}")
        if node is not None and book_meta:
            node.payload["book_meta"] = book_meta
    store.save(mission)
    ex = MissionExecutor(store, dict(RUNNERS), max_parallel=max_parallel, crash_after=crash_after)
    mission.set_status("RESEARCHING")
    store.save(mission)
    await ex.run(mission, only_kinds={"RESEARCH"})
    mission.set_status("SCRIPTING")
    store.save(mission)
    await ex.run(mission, only_kinds={"SCRIPT"})
    mission.set_status("PLANNED")
    store.save(mission)
    mission.set_status("PRODUCING")
    store.save(mission)
    await ex.run(mission, only_kinds={"RENDER"})
    mission.set_status("QA")
    store.save(mission)
    await ex.run(mission, only_kinds={"EDIT"})
    mission.set_status("FINALIZING")
    store.save(mission)
    await ex.run(mission, only_kinds={"DELIVERY"})
    store.save(mission)
    return mission, store, ex


def collect_gate_summary(mission: ProductionMission) -> dict[str, object]:
    # seg.report is {"gates": {...}}
    flat: dict[str, bool] = {}
    for ch in mission.chapters:
        for seg in ch.segments:
            gates = seg.report.get("gates", {}) if isinstance(seg.report, dict) else {}
            for gate, val in gates.items():
                flat.setdefault(gate, True)
                flat[gate] = flat[gate] and bool(val)
    return flat


def repair_demo(mission: ProductionMission, store: MissionStore, ex: MissionExecutor,
                seg_idx: int, new_narration: str) -> dict[str, object]:
    """Revise one segment's narration, invalidate dependents, resume. Returns evidence."""
    seg = mission.chapters[0].segments[seg_idx]
    before_hashes = {}
    for ch in mission.chapters:
        for s in ch.segments:
            if s.final_mp4 and Path(s.final_mp4).is_file():
                before_hashes[s.segment_index] = _sha(Path(s.final_mp4))
    seg.narration = new_narration
    mission.repair_count += 1
    mission.revision += 1
    reset = invalidate_dependents(mission, (f"segment-{seg_idx}",))
    # Bump segment node revision so idempotency does not skip the re-run
    node = mission.plan.node(f"segment-{seg_idx}") if mission.plan else None
    if node is not None:
        node.idempotency_key = f"{mission.mission_id}:segment-{seg_idx}:v2"
    mission.set_status("REPAIRING")
    store.save(mission)
    return {"reset_nodes": reset, "before_hashes": before_hashes}


def verify_repair_scope(mission: ProductionMission, before: dict[int, str], repaired_idx: int) -> dict[str, object]:
    untouched_ok = True
    for ch in mission.chapters:
        for s in ch.segments:
            if s.segment_index == repaired_idx:
                continue
            if (s.final_mp4 and Path(s.final_mp4).is_file()
                    and before.get(s.segment_index) != _sha(Path(s.final_mp4))):
                untouched_ok = False
    repaired_changed = False
    seg = mission.chapters[0].segments[repaired_idx]
    if seg.final_mp4 and Path(seg.final_mp4).is_file():
        repaired_changed = before.get(repaired_idx) != _sha(Path(seg.final_mp4))
    return {"untouched_ok": untouched_ok, "repaired_changed": repaired_changed}


def write_mission_report(mission: ProductionMission, store: MissionStore, extra: dict | None = None) -> Path:
    gates = collect_gate_summary(mission)
    report = {
        "mission_id": mission.mission_id, "profile_id": mission.profile_id,
        "status": mission.status, "segment_gates": gates,
        "observability": status_view(mission),
        "delivery": mission.delivery.to_dict() if mission.delivery else None,
        "repair_count": mission.repair_count,
        "extra": extra or {},
    }
    path = Path(mission.artifact_root) / "mission_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
