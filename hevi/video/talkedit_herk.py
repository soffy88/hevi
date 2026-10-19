"""
Talkedit Herk Module (inspired by nateherkai/herk-edit-kit)
"""

import os
import json
import logging

logger = logging.getLogger("talkedit_herk")

def analyze_slips_and_plan(transcript_segments, target_aspect="9:16"):
    flagged_issues = []
    for idx, seg in enumerate(transcript_segments):
        text = seg.get("text", "")
        if "..." in text or len(text) < 2:
            flagged_issues.append({
                "index": idx,
                "text": text,
                "issue": "Possible stutter or incomplete phrase",
                "action": "review_or_cut"
            })
            
    plan = {
        "aspect_ratio": target_aspect,
        "resolution": "1080x1920" if target_aspect == "9:16" else "1920x1080",
        "flagged_issues": flagged_issues,
        "narrative_structure": [
            {"phase": "hook", "duration_sec": 3.0, "style": "dynamic_zoom_in"},
            {"phase": "body", "duration_sec": 15.0, "style": "kinetic_subtitles"},
            {"phase": "cta", "duration_sec": 4.0, "style": "end_card"}
        ]
    }
    return plan

def export_herk_pkg(transcript_path, output_path):
    segments = []
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            segments = data.get("segments", data)
            
    plan = analyze_slips_and_plan(segments)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    logger.info(f"Herk edit package generated at {output_path}")
    return plan
