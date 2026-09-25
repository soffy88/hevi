#!/usr/bin/env python3
"""P2 cross-profile comparison from saved real runs.

Re-derives beats deterministically with canonical builders (no TTS/render)
using each profile's real narration + real audio duration, then compares
structural fingerprints. Same engine => comparable; distinct profiles =>
distinct histograms.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/data/soffy/projects/hevi")

from hevi.production.p1_pipeline import build_edit_plan, build_visual_beat_plan
from hevi.production.p2_pipeline import build_fingerprint
from scripts.p2_all_profiles_e2e import PROFILES

ROOT = Path("/data/soffy/projects/hevi/output/p2")


def audio_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False)
    try:
        return float((r.stdout or "0").strip() or 0)
    except ValueError:
        return 0.0


def main() -> int:
    comp: dict[str, object] = {"profiles": [], "same_canonical_engine": True}
    fps = []
    for spec in PROFILES:
        pid = str(spec["profile_id"])
        out = ROOT / pid.lower()
        narration = str(spec["narration"])
        tts = out / "tts_master.wav"
        dur = audio_duration(tts) if tts.is_file() else 0.0
        sentences = [s.strip() for s in narration.replace("。", ".").split(".") if s.strip()]
        seg = dur / len(sentences) if sentences and dur > 0 else 0.0
        from hevi.production.p0_pipeline import VisualIntent
        intents = [VisualIntent(
            intent_id=f"{pid}:intent-{i}", timeline_lock_id=f"{pid}:tl",
            narration_segment=s, start_s=i * seg, end_s=(i + 1) * seg,
            required_entities=(), required_concepts=(),
            visual_purpose=f"Visualize: {s[:80]}", motion_purpose=f"Motion: {s[:80]}",
        ) for i, s in enumerate(sentences)]
        state = SimpleNamespace(production_id=pid, audio_lock=SimpleNamespace(duration_s=dur))
        plan = build_visual_beat_plan(state, narration, intents)
        edit = build_edit_plan(plan)
        mini = SimpleNamespace(visual_beat_plan=plan, edit_plan=edit, asset_fitnesses=[])
        fp = build_fingerprint(pid, "1.0", mini)
        fps.append(fp)
        rep = json.loads((out / "p2_production_report.json").read_text())
        comp["profiles"].append({
            "profile_id": pid,
            "duration_s": round(dur, 2),
            "shot_count": len(plan.beats),
            "shot_roles": dict(fp.shot_role_histogram),
            "motions": dict(fp.motion_purpose_histogram),
            "cuts": dict(fp.cut_reason_histogram),
            "avg_shot_duration": fp.average_shot_duration,
            "final_mp4": rep.get("final_mp4"),
            "gates_pass": all(rep.get("gates", {}).values()),
        })
    sims = []
    sims = [round(fps[i].similarity(fps[j]), 3) for i in range(len(fps)) for j in range(i + 1, len(fps))]
    comp["pairwise_shot_role_similarity"] = sims
    comp["distinct_creative_behavior"] = all(s < 1.0 for s in sims) if sims else False
    comp["profile_isolation"] = len({p.profile_id for p in fps}) == 4
    (ROOT / "p2_profile_comparison.json").write_text(json.dumps(comp, indent=2), encoding="utf-8")
    print(json.dumps(comp, indent=2))
    ok = bool(comp["distinct_creative_behavior"]) and bool(comp["profile_isolation"])
    print("COMPARISON_QUALIFIED" if ok else "COMPARISON_NOT_QUALIFIED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
