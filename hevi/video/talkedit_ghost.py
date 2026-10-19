"""
Talkedit Ghost Module (inspired by kurbaitaev/ghost-editor)
"""

import os
import json
import logging

logger = logging.getLogger("talkedit_ghost")

def match_brolls_and_subtitles(segments, available_brolls=None):
    if available_brolls is None:
        available_brolls = [
            {"id": "broll_1", "tags": ["code", "programming", "python"], "path": "assets/bcode.mp4"},
            {"id": "broll_2", "tags": ["editing", "timeline", "video"], "path": "assets/bedit.mp4"}
        ]
        
    matched_results = []
    for seg in segments:
        text = seg.get("text", "")
        chosen_broll = None
        for b in available_brolls:
            if any(t in text for t in b["tags"]):
                chosen_broll = b["id"]
                break
        if not chosen_broll and available_brolls:
            chosen_broll = available_brolls[0]["id"]
            
        matched_results.append({
            "segment_text": text,
            "start": seg.get("start"),
            "end": seg.get("end"),
            "assigned_broll": chosen_broll,
            "subtitle_position": {
                "align": "bottom-center",
                "margin_v_percent": 15,
                "avoid_face_region": True
            }
        })
    return matched_results

def generate_ghost_spec(clean_recipe_path, output_spec_path):
    segments = []
    if os.path.exists(clean_recipe_path):
        with open(clean_recipe_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            segments = data.get("segments", [])
            
    results = match_brolls_and_subtitles(segments)
    spec = {
        "module": "talkedit_ghost",
        "matchings": results
    }
    
    os.makedirs(os.path.dirname(os.path.abspath(output_spec_path)), exist_ok=True)
    with open(output_spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    logger.info(f"Ghost editor spec written to {output_spec_path}")
    return spec
