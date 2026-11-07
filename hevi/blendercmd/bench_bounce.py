"""Bench presets at 480p on the 2s clay bounce; render full sample with the chosen preset.
usage: python -m hevi.blendercmd.bench_bounce OUTDIR [presets...]"""
import json
import sys
from pathlib import Path

from hevi.blendercmd.obase_runner import run_ops
from hevi.blendercmd.oskill_ops import bounce_ball_ops

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
presets = sys.argv[2:] or ["workbench", "eevee", "cycles_fast", "cycles"]
rows = []
for p in presets:
    ops = bounce_ball_ops(2.0, 24, p, (854, 480))
    ops += [{"op": "render_frame", "frame": 13, "out": f"still_{p}.png"},
            {"op": "render_animation", "out": f"bounce_{p}.mp4"}]
    r = run_ops(ops, str(out), timeout=3000)
    a = next((o for o in r.get("outputs", []) if o["kind"] == "animation"), None)
    row = {"preset": p, "ok": r["ok"], "wall": r["wall_seconds"], "error": (r.get("error") or {}).get("message")}
    if a:
        row.update(render_s=a["seconds"], sec_per_video_sec=a["sec_per_video_sec"], engine=a["engine"],
                   sec_per_frame=round(a["seconds"] / a["frames"], 2), mp4=a["path"])
    rows.append(row)
    print(json.dumps(row), flush=True)
(out / "bench.json").write_text(json.dumps(rows, indent=1))
