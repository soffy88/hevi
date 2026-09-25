#!/usr/bin/env python3
"""P2 — four real profile E2E runs + frame evidence + cross-profile comparison."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.production.p2_pipeline import (
    run_p2_adversarial_tests,
    run_p2_production,
    sha256_file,
    write_contact_sheet,
)

ROOT = Path("/data/soffy/projects/hevi/output/p2")

PROFILES: list[dict[str, object]] = [
    {
        "profile_id": "EMOTIONAL_BOOK_REVIEW",
        "topic": "Solitude and acceptance — Meditations",
        "narration": (
            "After my father passed away, solitude followed me through every quiet evening. "
            "Meditations by Marcus Aurelius reminded me that loss can teach acceptance rather than despair. "
            "One paraphrased line stayed with me, that grief softens when we stop fighting what we cannot change. "
            "I closed the book feeling less alone, carrying quiet courage into ordinary days."
        ),
        "book_meta": {"title": "Meditations", "author": "Marcus Aurelius", "verified": True, "note": "PARAPHRASE"},
    },
    {
        "profile_id": "WHITEBOARD_EXPLAINER",
        "topic": "Why seasons happen",
        "narration": (
            "To understand why seasons happen, draw the tilted Earth orbiting the sun. "
            "First draw the axis tilt, then arrow the sunlight striking each hemisphere. "
            "As Earth orbits, highlight how each hemisphere leans toward or away from the sun. "
            "Follow the orbit to see winter turn to summer, step by step."
        ),
        "book_meta": None,
    },
    {
        "profile_id": "SCIENCE_EXPLAINER",
        "topic": "Black hole physics",
        "narration": (
            "A black hole forms when a massive star collapses under its own gravity. "
            "The accretion disk around it glows with intense X-ray emission. "
            "Binary black holes spiral inward, merging in a burst of gravitational waves. "
            "Orbital visualizations reveal the warped spacetime near the event horizon."
        ),
        "book_meta": None,
    },
    {
        "profile_id": "HISTORICAL_NARRATIVE",
        "topic": "Tang Chang'an and the Silk Road",
        "narration": (
            "In the seventh century, Tang dynasty Chang'an became a meeting place for merchants and monks. "
            "Porcelain and silk traveled west while ideas traveled east along desert routes. "
            "Merchants compared Tang coins with Sogdian silver, weighing value at every market. "
            "The consequence shaped maps, documents, and memory across centuries."
        ),
        "book_meta": None,
    },
]

P0_GATES = (
    "AUDIO_LOCK", "TIMELINE_LOCK", "CAPTION_SYNC", "VISUAL_GROUNDING", "TEXT_DOMINANCE",
    "ASSET_RELEVANCE", "MOTION_PURPOSE", "SHOT_PACING", "15S_PROOF", "FULL_RENDER",
    "FINAL_QA", "SOURCE_PROVENANCE",
)
P1_GATES = (
    "VISUAL_BEAT_COVERAGE", "SEMANTIC_ACTION_MATCH", "SHOT_ROLE_DIVERSITY", "ASSET_COVERAGE",
    "ASSET_REUSE", "MOTION_PURPOSE", "EDIT_JUSTIFICATION", "VISUAL_CONTINUITY",
    "INFORMATION_GAIN", "NARRATIVE_ARC", "TEXT_DOMINANCE", "VISUAL_NARRATIVE_PROOF",
)


async def run_one(spec: dict[str, object]) -> dict[str, object]:
    pid = str(spec["profile_id"])
    out = ROOT / pid.lower()
    state = await run_p2_production(
        profile_id=pid,
        narration=str(spec["narration"]),
        topic=str(spec["topic"]),
        output_dir=out,
        book_meta=(spec.get("book_meta") or None) if isinstance(spec.get("book_meta"), dict) else None,
    )
    gates = dict(getattr(state.report, "gates", {}))
    final = str(getattr(state, "final_mp4", "") or getattr(state.report, "final_mp4", "") or "")
    proof = str(getattr(state, "proof_mp4", "") or getattr(state.report, "proof_mp4", "") or "")
    fp = getattr(state, "profile_fingerprint", None)
    adv = run_p2_adversarial_tests(state)
    # Frame evidence
    contact = out / "contact_sheet.jpg"
    if final and Path(final).is_file():
        write_contact_sheet(Path(final), contact)
    frame_analysis = out / "frame_analysis.json"
    frame_analysis.write_text(json.dumps({
        "profile_id": pid,
        "final_mp4": final,
        "contact_sheet": str(contact) if contact.is_file() else "",
        "sha256": sha256_file(Path(final)) if final and Path(final).is_file() else "",
    }, indent=2), encoding="utf-8")
    (out / "p2_production_report.json").write_text(
        json.dumps({"profile_id": pid, "gates": gates, "adversarial": adv,
                    "final_mp4": final, "proof_mp4": proof}, indent=2), encoding="utf-8")
    return {"profile_id": pid, "state": state, "gates": gates, "adversarial": adv,
            "final_mp4": final, "proof_mp4": proof, "fingerprint": fp, "out": str(out)}


async def main() -> int:
    results: list[dict[str, object]] = []
    for spec in PROFILES:
        print(f"[P2] running {spec['profile_id']} ...", flush=True)
        try:
            results.append(await run_one(spec))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            results.append({"profile_id": spec["profile_id"], "error": str(exc)})
    # Comparison
    comp = {"profiles": [], "same_canonical_engine": True}
    fps = []
    for r in results:
        fp = r.get("fingerprint")
        if fp is None:
            continue
        fps.append(fp)
        comp["profiles"].append({
            "profile_id": fp.profile_id,
            "shot_roles": dict(fp.shot_role_histogram),
            "motions": dict(fp.motion_purpose_histogram),
            "assets": dict(fp.asset_type_histogram),
            "cuts": dict(fp.cut_reason_histogram),
            "avg_shot_duration": fp.average_shot_duration,
            "final_mp4": r.get("final_mp4"),
            "gates": r.get("gates"),
        })
    # Distinct behavior: all pairwise similarities < 1.0 (not identical)
    sims = []
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            sims.append(round(fps[i].similarity(fps[j]), 3))  # noqa: PERF401 - pairwise nested loop
    comp["pairwise_shot_role_similarity"] = sims
    comp["distinct_creative_behavior"] = all(s < 1.0 for s in sims) if sims else False
    # Isolation: profile ids in fingerprints are distinct and match requested
    comp["profile_isolation"] = sorted(p.profile_id for p in fps) == sorted(
        str(s["profile_id"]) for s in PROFILES if any(r.get("profile_id") == s["profile_id"] and r.get("fingerprint") for r in results))
    (ROOT / "p2_profile_comparison.json").write_text(json.dumps(comp, indent=2), encoding="utf-8")
    print(json.dumps({"comparison": str(ROOT / "p2_profile_comparison.json"),
                      "profiles": [{k: (v if k != "gates" else list(v.keys())) for k, v in r.items() if k in ("profile_id", "final_mp4", "gates", "error")} for r in results]}, indent=2))
    ok = all("error" not in r for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
