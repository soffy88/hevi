"""python -m hevi.layercraft.demo OUT_DIR [IMAGE] -- render the four samples (480x270, low cost)."""
import math, sys, time
from pathlib import Path
from hevi.layercraft.omodul import render as R

SIG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 270">
<rect x="40" y="40" width="120" height="80" rx="0" fill="#f2c14e" stroke="#222" stroke-width="4"/>
<circle cx="260" cy="80" r="45" fill="#6cb4c4" stroke="#222" stroke-width="4"/>
<path d="M330 130 C 360 30 440 30 440 110 S 380 170 340 130" fill="none" stroke="#c0392b" stroke-width="5"/>
<path d="M40 210 Q 120 150 200 210 T 360 210 T 440 200" fill="none" stroke="#222" stroke-width="4"/>
<path d="M60 250 A 60 30 0 0 1 180 250" fill="none" stroke="#2e7d32" stroke-width="4"/>
<polyline points="220,250 250,225 280,250 310,225 340,250" fill="none" stroke="#6a1b9a" stroke-width="4"/>
</svg>'''

def main(out, image=None):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    R.svg_draw_on(SIG, out / "svg_draw_on.mp4", size=(480, 270), duration=3.0)
    R.layered_reveal(R.default_landscape_svg(), out / "layered_reveal.mp4", size=(480, 270), duration=4.0, bpm=100)
    star = [[240 + (90 if k % 2 == 0 else 38) * math.cos(-math.pi / 2 + k * math.pi / 5),
             135 + (90 if k % 2 == 0 else 38) * math.sin(-math.pi / 2 + k * math.pi / 5)] for k in range(11)]
    wave = [[30 + x * 4, 240 + 10 * math.sin(x / 6)] for x in range(106)]
    R.boiling_lines([star, wave], out / "boiling_lines.mp4", duration=3.0, hold=3, draw_on=1.2, roughness=2.0)
    if image is None:  # fall back to a frame of the layered sample as the "existing image"
        fr = list(R.layered_reveal_frames(R.default_landscape_svg(), size=(480, 270), duration=4.0, bpm=100))[-1]
        image = out / "paper_cut_input.png"; fr.convert("RGB").save(image)
    R.paper_cut(image, out / "paper_cut.mp4", k=5, duration=4.0)
    print(f"done {time.time()-t:.1f}s -> {out}")

if __name__ == "__main__":
    main(*sys.argv[1:])
