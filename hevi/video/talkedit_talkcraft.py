"""
Talkedit Talkcraft Wrapper (inspired by Vincentwei1021/video-talkcraft)
"""

import os
import json
import logging

logger = logging.getLogger("talkedit_talkcraft")

def generate_talkcraft_config(script_text: str, output_config_path: str):
    words = script_text.split()
    timed_words = []
    current_time = 0.0
    for w in words:
        duration = max(0.3, len(w) * 0.15)
        timed_words.append({
            "word": w,
            "start": round(current_time, 2),
            "end": round(current_time + duration, 2)
        })
        current_time += duration
        
    config = {
        "title": "Talkcraft Kinetic Video",
        "fps": 30,
        "resolution": "1080x1920",
        "timed_words": timed_words,
        "assets_free_list": [
            "Pexels (Video/Photo)",
            "Pixabay (Audio/SFX)",
            "Iconify (Vector Icons)"
        ]
    }
    
    os.makedirs(os.path.dirname(os.path.abspath(output_config_path)), exist_ok=True)
    with open(output_config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        
    logger.info(f"Talkcraft config generated at {output_config_path}")
    return config
