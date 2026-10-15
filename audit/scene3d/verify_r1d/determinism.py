"""R1D independent verifier: re-render one shipped clip at 1080 and compare SHA-256.

Uses the same preset build path as the unit's script but a fresh workdir, so a
matching hash proves the shipped deliverable is reproducible from source.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import sys

ROOT = Path("/data/soffy/projects/hevi-scene3d")
sys.path.insert(0, str(ROOT / "scripts"))
from scene3d_r1d_render import build_spec  # noqa: E402

from hevi.layer4_legacy.scene3d import renderer as R  # noqa: E402

A = ROOT / "audit" / "scene3d" / "verify_r1d"
W = ROOT / ".tmp" / "verify_r1d_det"
W.mkdir(parents=True, exist_ok=True)


def sha(p: Path) -> str:
    d = hashlib.sha256()
    with p.open("rb") as s:
        for c in iter(lambda: s.read(1 << 20), b""):
            d.update(c)
    return d.hexdigest()


CLIP = os.environ.get("VERIFY_CLIP", "star_sea_9x16")
MAP = {
    "star_sea_9x16": ("scene3d.star_sea", "9:16", "through_star_sea.json"),
    "fox_wheat_9x16": ("scene3d.fox_wheat", "9:16", "fox_in_wheat.json"),
    "planet_orbit_16x9": ("scene3d.planet_orbit", "16:9", "little_planet_orbit.json"),
}
cap, aspect, preset = MAP[CLIP]
spec = build_spec(cap, aspect, preset)
d = W / CLIP
if d.exists():
    shutil.rmtree(d)
t0 = time.time()
m = R.SceneRenderer(spec, d).render()
dt = time.time() - t0
mine = Path(m["video"])
mine_sha = sha(mine)
shipped = next((ROOT / "output" / "scene3d_r1d" / CLIP).glob("*.mp4"))
ship_sha = sha(shipped)
rec = {
    "clip": CLIP,
    "resolution": f"{spec.width}x{spec.height}",
    "render_s": round(dt, 1),
    "verifier_sha256": mine_sha,
    "shipped_sha256": ship_sha,
    "match": mine_sha == ship_sha,
    "ffprobe": R.ffprobe_frames(mine),
}
(A / "determinism.json").write_text(json.dumps(rec, indent=1))
print(json.dumps(rec, indent=1), flush=True)
print("DETDONE", flush=True)
