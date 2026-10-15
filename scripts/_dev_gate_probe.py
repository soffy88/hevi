#!/usr/bin/env python3
"""Dev-only: render one spec at low fps and report film_gate. Not part of the product."""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "hevi/layer4_legacy/artmotion/omodul_impl/scripts/engine"
SCRIPTS = ROOT / "hevi/layer4_legacy/artmotion/omodul_impl/scripts"
sys.path.insert(0, str(SCRIPTS))

spec_path = Path(sys.argv[1])
fps = int(sys.argv[2]) if len(sys.argv) > 2 else 12
out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "output/_dev/probe.mp4"

spec = json.loads(spec_path.read_text())
spec["fps"] = fps
tmp = spec_path.parent / f"_probe_{fps}.json"
tmp.write_text(json.dumps(spec, ensure_ascii=False))

out.parent.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, PATH="/home/soffy/.local/bin:" + os.environ.get("PATH", ""))
subprocess.run([str(ROOT / ".venv/bin/python"), str(ENGINE / "render.py"), "--spec", str(tmp), "--out", str(out)], check=True, env=env)

import film_gate
res, rows = film_gate.measure(str(out), vertical="yes" if spec["height"] > spec["width"] else "no")
print(json.dumps({k: res[k] for k in ("duration_s", "fast_ratio", "still_ratio", "drift_ratio", "blank_run_s", "blue_purple_share", "event_rate", "max_event_gap_s", "dead_bg", "gate_light", "verdict", "fast_ratio_by_10s")}, ensure_ascii=False, indent=1))
print("explain:", res["explain"]["summary"])
print("lights:", json.dumps(res["lights"], ensure_ascii=False))
