"""visual-spec.json 构建。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_visual_spec(metaphor: dict[str, Any], out_path: Path | None = None) -> dict[str, Any]:
    spec = {
        "script_meaning": metaphor.get("core_meaning", ""),
        "visual_metaphor": metaphor.get("visual_proposition", ""),
        "style_signature": "flat bold color field, mixed black-and-white halftone cut-outs and colored cardstock accents, crisp cut edges, cream keylines, soft paper shadows, editorial paper collage",
        "aspect_ratio": "9:16",
        "color_field": {
            "background_hex": metaphor.get("background_hex", "#E86A33"),
            "accent_colors": metaphor.get("accent_colors", ["#F5EFE0", "#2B2B2B"]),
            "paper_grain": "fine uncoated-paper fiber",
        },
        "elements": [
            {"what": o, "role": "key object", "motion": "slide in", "placement": "center"}
            for o in metaphor.get("key_objects", [])
        ],
        "composition": {
            "layout": "central 70%",
            "negative_space": "generous color field",
            "final_frame": "completed collage",
        },
        "motion_plan": metaphor.get("assembly_order", "structure first, subject second, action last"),
        "avoid": "typography, readable letters, numerals, logos, watermark, UI, subtitles, glossy 3D, photoreal environment",
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return spec
