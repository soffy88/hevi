"""R3 probe 2: compare endpoint-exactness remaps across durations, correct coords."""

import subprocess
import sys

import numpy as np

sys.path.insert(0, "/data/soffy/projects/hevi-xfadepack")

FFMPEG = "ffmpeg"
W, H, FPS = 320, 240, 30
CLIP = 2.0

_SA = "if(eq(PLANE\\,0)\\,a0({x}\\,{y})\\,if(eq(PLANE\\,1)\\,a1({x}\\,{y})\\,a2({x}\\,{y})))"
_SB = "if(eq(PLANE\\,0)\\,b0({x}\\,{y})\\,if(eq(PLANE\\,1)\\,b1({x}\\,{y})\\,b2({x}\\,{y})))"


def exprs(t):
    white = "128+eq(PLANE\\,0)*107"
    flash = f"if(gt({t}\\,0.5)\\,A*(2*{t}-1)+({white})*(2-2*{t})\\,B*(1-2*{t})+({white})*(2*{t}))"
    r = "hypot(X-W/2\\,Y-H/2)/hypot(W/2\\,H/2)"
    burn = f"A*(1-clip(((1-{t})*1.25-({r}))*12\\,0\\,1))+B*clip(((1-{t})*1.25-({r}))*12\\,0\\,1)"
    inkr = f"{r}+0.12*sin(X/23)*sin(Y/19)"
    ink = f"A*(1-clip(((1-{t})*1.25-({inkr}))*5\\,0\\,1))+B*clip(((1-{t})*1.25-({inkr}))*5\\,0\\,1)"
    blur = f"4*({t})*(1-({t}))*14"
    ac = f"clip(X+(1-({t}))*W\\,0\\,W-1)"
    bc = f"clip(X-({t})*W\\,0\\,W-1)"
    a0 = _SA.format(x=ac, y="Y")
    a1 = _SA.format(x=f"clip(X+(1-({t}))*W-({blur})\\,0\\,W-1)", y="Y")
    a2 = _SA.format(x=f"clip(X+(1-({t}))*W+({blur})\\,0\\,W-1)", y="Y")
    b0 = _SB.format(x=bc, y="Y")
    b1 = _SB.format(x=f"clip(X-({t})*W-({blur})\\,0\\,W-1)", y="Y")
    b2 = _SB.format(x=f"clip(X-({t})*W+({blur})\\,0\\,W-1)", y="Y")
    whip = f"if(lt(X\\,({t})*W)\\,({a0}+{a1}+{a2})/3\\,({b0}+{b1}+{b2})/3)"
    n = "0.5+0.5*sin(floor(Y/32)*12.9898)"
    dx = f"clip(X+({n}-0.5)*70*4*({t})*(1-({t}))\\,0\\,W-1)"
    glitch = f"if(lt({n}\\,1-({t}))\\,{_SB.format(x=dx, y='Y')}\\,{_SA.format(x=dx, y='Y')})"
    ka = f"(1-0.35*(1-({t})))"
    kb = f"(1-0.35*({t}))"
    zx = "clip(W/2+(X-W/2)*{k}\\,0\\,W-1)"
    zy = "clip(H/2+(Y-H/2)*{k}\\,0\\,H-1)"
    zoom = f"if(gt({t}\\,0.5)\\,{_SA.format(x=zx.format(k=ka), y=zy.format(k=ka))}\\,{_SB.format(x=zx.format(k=kb), y=zy.format(k=kb))})"
    return {
        "whip": whip,
        "burn": burn,
        "glitch": glitch,
        "flash": flash,
        "zoom_punch": zoom,
        "ink": ink,
    }


def frames(path):
    r = subprocess.run(
        [FFMPEG, "-y", "-i", path, "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
        capture_output=True,
    )
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, H * 3 // 2, W).astype(np.float64)


def psnr(a, b):
    mse = ((a - b) ** 2).mean()
    return float("inf") if mse == 0 else 10 * np.log10(255 * 255 / mse)


def render(expr, d, out):
    fc = f"[0:v][1:v]xfade=transition=custom:expr={expr}:duration={d}:offset={CLIP - d}[v]"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            "output/r3_check/A_ll.mkv",
            "-i",
            "output/r3_check/B_ll.mkv",
            "-filter_complex",
            fc,
            "-map",
            "[v]",
            "-c:v",
            "ffv1",
            out,
        ],
        check=True,
        capture_output=True,
    )


REMAPS = {
    "ident": "P",
    "hold.04": "clip((P-0.04)/0.92\\,0\\,1)",
    "smoothstep": "P*P*(3-2*P)",
    "smoother": "P*P*P*(P*(P*6-15)+10)",
}


def main():
    A = frames("output/r3_check/A_ll.mkv")
    B = frames("output/r3_check/B_ll.mkv")
    for d in [0.4, 0.6, 1.0]:
        n = int(d * FPS)
        i0, i1 = int((CLIP - d) * FPS), int((CLIP - d) * FPS) + n - 1
        print(f"\n=== d={d}s  window frames {i0}..{i1} ===")
        for rn, rexpr in REMAPS.items():
            row = [f"{rn:11s}"]
            for tid in ["whip", "glitch", "flash", "zoom_punch", "burn", "ink"]:
                render(exprs(rexpr)[tid], d, "output/r3_check/p2.mkv")
                O = frames("output/r3_check/p2.mkv")
                s_s = psnr(O[i0], A[i0])  # start vs A
                s_e = psnr(O[i1], O[i1 + 1])  # last trans vs next(=B)
                s_eB = psnr(O[i1], B[i1 - i0])  # last trans vs B
                row.append(f"{tid[:5]}:{min(s_s, s_e, s_eB):5.1f}")
            print("  ".join(row))


if __name__ == "__main__":
    main()
