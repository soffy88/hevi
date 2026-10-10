"""Omlines free tier 3O wrappers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.omlines.omodul_impl.lines import LINES

_enabled_pillars = {"report", "cost", "decision_trail"}

def omlines_fallback_workflow(config: dict[str, Any], input_data: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    line = input_data.get("line_id")
    if not line or line not in LINES:
        return {"status": "failed", "reason": f"No omlines fallback for {line}"}
    
    try:
        # Run the legacy hevi-zero line implementation
        rec = LINES[line](output_dir=output_dir)
        passed = rec.get("pass") if "pass" in rec else rec.get("qa", {}).get("pass", False)
        
        # We need to copy the final artifact to output_dir if needed, 
        # but lines.py already outputs to OUT/line. Let's just return its paths.
        
        return {
            "status": "succeeded" if passed else "failed",
            "record": rec,
            "result_video_path": rec.get("final") or (rec.get("finals")[0] if rec.get("finals") else None),
            "reason": rec.get("notes") or ""
        }
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}
