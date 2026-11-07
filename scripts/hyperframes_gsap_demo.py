"""HyperFrames GSAP 逐帧驱动样例：GSAP 文字 + rough.js 手绘框 + three.js 立方体 + p5 粒子。

    .venv/bin/python scripts/hyperframes_gsap_demo.py [out_dir]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hevi.video.hyperframes_service import p5_layer, render_gsap_video, rough_layer, three_layer  # noqa: E402

HTML = """
<div id="title" style="position:absolute;left:0;top:96px;width:100%;text-align:center;z-index:5;
  font:bold 30px sans-serif;color:#fff;opacity:0">HyperFrames × GSAP</div>
<div id="bar" style="position:absolute;left:40px;bottom:30px;height:8px;width:0;background:#ffcc33;z-index:5"></div>
"""
GSAP = """
tl.to('#title', {opacity: 1, y: -20, duration: 0.6, ease: 'power2.out'})
  .to('#bar', {width: 400, duration: 1.4, ease: 'none'}, 0)
  .to('#title', {scale: 1.15, duration: 0.6, yoyo: true, repeat: 1}, 0.6);
"""
ROUGH = """
rc.rectangle(30, 30, 420, 210, {seed: seed, roughness: 2.2, stroke: '#ffffff', strokeWidth: 2});
rc.circle(60 + t * 160, 200, 30, {seed: seed, fill: '#ff5577', fillStyle: 'hachure', stroke: '#ff5577'});
"""
THREE = """
const geo = new THREE.BoxGeometry(1.2, 1.2, 1.2);
const mesh = new THREE.Mesh(geo, new THREE.MeshNormalMaterial());
mesh.position.set(2.2, -0.2, 0);
ctx.scene.add(mesh);
return function(t){ mesh.rotation.x = t * 1.5; mesh.rotation.y = t * 2.0; };
"""
P5 = """
p.clear(); p.noStroke();
for (let i = 0; i < 40; i++) {
  const x = (p.noise(i * 0.3, t * 0.6) * p.width);
  const y = (p.noise(i * 0.3 + 50, t * 0.6) * p.height);
  p.fill(80, 200, 255, 160); p.circle(x, y, 6);
}
"""


async def main(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    layers = [p5_layer("dots", P5, z=1), three_layer("cube", THREE, z=2), rough_layer("sketch", ROUGH, reseed_every=3, z=3)]
    kw = dict(width=480, height=270, fps=12, duration=2.0, gsap_script=GSAP, layers=layers, background="#1d2433")
    r1 = await render_gsap_video(HTML, out_dir / "hyperframes_gsap_demo.mp4", keep_frames=out_dir / "frames", **kw)
    r2 = await render_gsap_video(HTML, out_dir / "hyperframes_gsap_demo_run2.mp4", **kw)
    import hashlib
    info = {
        "success": r1.success and r2.success, "error": r1.error or r2.error,
        "frames": r1.frame_count, "sequence_hash_run1": r1.sequence_hash, "sequence_hash_run2": r2.sequence_hash,
        "deterministic": r1.frame_hashes == r2.frame_hashes,
        "mp4_sha256_run1": hashlib.sha256((out_dir / "hyperframes_gsap_demo.mp4").read_bytes()).hexdigest(),
        "mp4_sha256_run2": hashlib.sha256((out_dir / "hyperframes_gsap_demo_run2.mp4").read_bytes()).hexdigest(),
    }
    (out_dir / "frame_hashes.json").write_text(json.dumps({**info, "frame_hashes": r1.frame_hashes}, indent=1))
    (out_dir / "hyperframes_gsap_demo_run2.mp4").unlink(missing_ok=True)
    return info


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "output" / "codevideo" / "hyperframes"
    print(json.dumps(asyncio.run(main(out)), indent=1))
