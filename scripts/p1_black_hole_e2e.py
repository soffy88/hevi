#!/usr/bin/env python3
"""P1 Content Production Quality — Black Hole E2E Test.

Runs full P1 pipeline with visual narrative gates on NASA black hole assets.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.production.p1_pipeline import run_p1_adversarial_tests, run_p1_production


async def main() -> int:
    # Black hole narration — semantically grounded with actions
    narration = (
        "A black hole forms when a massive star collapses under its own gravity. "
        "The accretion disk around it glows with intense X-ray emission. "
        "Binary black holes spiral inward, merging in a burst of gravitational waves. "
        "Orbital visualizations reveal the warped spacetime near the event horizon."
    )

    topic = "Black Hole Physics — P1 Content Production Quality"
    output_dir = Path("/data/soffy/projects/hevi/output/p1_black_hole")

    print(f"[P1] Starting production: {topic}")
    print(f"[P1] Output: {output_dir}")

    try:
        state = await run_p1_production(
            narration=narration,
            topic=topic,
            output_dir=output_dir,
            language="en-US",
            voice="en-US-AriaNeural",
            max_proof_seconds=15,
        )

        print("\n=== P0 GATE REPORT ===")
        p0_gates = [
            "AUDIO_LOCK", "TIMELINE_LOCK", "CAPTION_SYNC", "VISUAL_GROUNDING",
            "TEXT_DOMINANCE", "ASSET_RELEVANCE", "MOTION_PURPOSE", "SHOT_PACING",
            "15S_PROOF", "FULL_RENDER", "FINAL_QA", "SOURCE_PROVENANCE"
        ]
        for gate in p0_gates:
            passed = state.report.gates.get(gate, False)
            status = "PASS" if passed else "FAIL"
            print(f"  {gate}: {status}")

        print("\n=== P1 GATE REPORT ===")
        p1_gates = [
            "VISUAL_BEAT_COVERAGE", "SEMANTIC_ACTION_MATCH", "SHOT_ROLE_DIVERSITY",
            "ASSET_COVERAGE", "ASSET_REUSE", "MOTION_PURPOSE", "EDIT_JUSTIFICATION",
            "VISUAL_CONTINUITY", "INFORMATION_GAIN", "NARRATIVE_ARC",
            "TEXT_DOMINANCE", "VISUAL_NARRATIVE_PROOF"
        ]
        for gate in p1_gates:
            passed = state.report.gates.get(gate, False)
            status = "PASS" if passed else "FAIL"
            print(f"  {gate}: {status}")

        if state.report.gate_details:
            print("\n=== GATE DETAILS ===")
            for gate, details in state.report.gate_details.items():
                print(f"  {gate}: {details}")

        # Adversarial checks
        print("\n=== P1 ADVERSARIAL CHECKS ===")
        adversarial = run_p1_adversarial_tests(state)
        for case, result in adversarial.items():
            print(f"  {case}: {result}")

        # P0 regression check
        p0_all_pass = all(state.report.gates.get(g, False) for g in [
            "AUDIO_LOCK", "TIMELINE_LOCK", "CAPTION_SYNC", "VISUAL_GROUNDING",
            "TEXT_DOMINANCE", "ASSET_RELEVANCE", "MOTION_PURPOSE", "SHOT_PACING",
            "15S_PROOF", "FULL_RENDER", "FINAL_QA", "SOURCE_PROVENANCE"
        ])
        
        p1_all_pass = all(state.report.gates.get(g, False) for g in [
            "VISUAL_BEAT_COVERAGE", "SEMANTIC_ACTION_MATCH", "SHOT_ROLE_DIVERSITY",
            "ASSET_COVERAGE", "ASSET_REUSE", "MOTION_PURPOSE", "EDIT_JUSTIFICATION",
            "VISUAL_CONTINUITY", "INFORMATION_GAIN", "NARRATIVE_ARC",
            "TEXT_DOMINANCE", "VISUAL_NARRATIVE_PROOF"
        ])

        all_pass = p0_all_pass and p1_all_pass
        
        print(f"\n=== P0 REGRESSION: {'PASS' if p0_all_pass else 'FAIL'} ===")
        print(f"=== P1 GATES: {'PASS' if p1_all_pass else 'FAIL'} ===")
        print(f"=== FINAL: {'QUALIFIED' if all_pass else 'NOT QUALIFIED'} ===")

        return 0 if all_pass else 1

    except Exception as e:
        print(f"[P1] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
