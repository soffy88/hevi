"""QA 检查。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def probe(path: Path) -> dict[str, Any]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,r_frame_rate,codec_name", "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        )
        import json

        data = json.loads(out.stdout or "{}")
        streams = data.get("streams", [])
        s = streams[0] if streams else {}
        return {"width": s.get("width"), "height": s.get("height"), "codec": s.get("codec_name"), "fps": s.get("r_frame_rate")}
    except Exception as e:
        return {"error": str(e)}


def run_qa(gif_path: Path, mp4_path: Path, still_path: Path | None = None) -> dict[str, Any]:
    g = probe(gif_path)
    m = probe(mp4_path)
    checks = {
        "gif_exists": Path(gif_path).exists(),
        "mp4_exists": Path(mp4_path).exists(),
        "mp4_size": (Path(mp4_path).stat().st_size if Path(mp4_path).exists() else 0),
        "mp4_resolution_ok": (m.get("width") == 720 and m.get("height") == 1280),
    }
    return {"gif": g, "mp4": m, "checks": checks, "passed": all(checks.values())}
