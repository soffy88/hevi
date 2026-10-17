"""R3 probe: test a 'settle remap' fix for both-end continuity of custom transitions.

Root cause found: xfade's P does not reach exactly 0 on the last transition frame
(measured ~0.0026), so any P-dependent displacement/blend leaves a sub-pixel
residual -> whip/glitch/zoom_punch/flash end frames differ strongly from B
(15-30 dB) while fade/burn/ink (pure additive) survive (38-60 dB).

Fix: reparametrize progress t = clip((P-h)/(1-2h),0,1) so t is exactly 0 on the
last frames and exactly 1 on the first frames; t(0.5)=0.5 so midpoints are
unchanged.
"""

import subprocess
import sys

import numpy as np

sys.path.insert(0, "/data/soffy/projects/hevi-xfadepack")

FFMPEG = "ffmpeg"
W, H, FPS, D, CLIP = 320, 240, 30, 1.0, 2.0
OFF = int((CLIP - D) * FPS)  # 30

_SAMP_A0 = "if(eq(PLANE\\,0)\\,a0({x}\\,{y})\\,if(eq(PLANE\\,1)\\,a1({x}\\,{y})\\,a2({x}\\,{y})))"
_SAMP_B0 = "if(eq(PLANE\\,0)\\,b0({x}\\,{y})\\,if(eq(PLANE\\,1)\\,b1({x}\\,{y})\\,b2({x}\\,{y})))"


def build_exprs(t):
    """Return dict id->expr using progress token t (a string expression)."""
    white = "128+eq(PLANE\\,0)*107"
    flash = f"if(gt({t}\\,0.5)\\,A*(2*{t}-1)+({white})*(2-2*{t})\\,B*(1-2*{t})+({white})*(2*{t}))"

    r = "hypot(X-W/2\\,Y-H/2)/hypot(W/2\\,H/2)"
    burn = f"A*(1-clip(((1-{t})*1.25-({r}))*12\\,0\\,1))+B*clip(((1-{t})*1.25-({r}))*12\\,0\\,1)"
    ink_r = f"{r}+0.12*sin(X/23)*sin(Y/19)"
    ink = (
        f"A*(1-clip(((1-{t})*1.25-({ink_r}))*5\\,0\\,1))+B*clip(((1-{t})*1.25-({ink_r}))*5\\,0\\,1)"
    )

    blur = f"4*({t})*(1-({t}))*14"
    # A slides left (A_coord = X + (1-t)*W); B slides in from right (B_coord = X - t*W).
    ac = f"clip(X+(1-({t}))*W\\,0\\,W-1)"
    bc = f"clip(X-({t})*W\\,0\\,W-1)"
    a0 = _SAMP_A0.format(x=ac, y="Y")
    a1 = _SAMP_A0.format(x=f"clip(X+(1-({t}))*W-({blur})\\,0\\,W-1)", y="Y")
    a2 = _SAMP_A0.format(x=f"clip(X+(1-({t}))*W+({blur})\\,0\\,W-1)", y="Y")
    b0 = _SAMP_B0.format(x=bc, y="Y")
    b1 = _SAMP_B0.format(x=f"clip(X-({t})*W-({blur})\\,0\\,W-1)", y="Y")
    b2 = _SAMP_B0.format(x=f"clip(X-({t})*W+({blur})\\,0\\,W-1)", y="Y")
    whip = f"if(lt(X\\,({t})*W)\\,({a0}+{a1}+{a2})/3\\,({b0}+{b1}+{b2})/3)"

    n = "0.5+0.5*sin(floor(Y/32)*12.9898)"
    dx = f"clip(X+({n}-0.5)*70*4*({t})*(1-({t}))\\,0\\,W-1)"
    ga = _SAMP_A0.format(x=dx, y="Y")
    gb = _SAMP_B0.format(x=dx, y="Y")
    glitch = f"if(lt({n}\\,1-({t}))\\,{gb}\\,{ga})"

    ka = f"(1-0.35*(1-({t})))"
    kb = f"(1-0.35*({t}))"
    zx = "clip(W/2+(X-W/2)*{k}\\,0\\,W-1)"
    zy = "clip(H/2+(Y-H/2)*{k}\\,0\\,H-1)"
    za = _SAMP_A0.format(x=zx.format(k=ka), y=zy.format(k=ka))
    zb = _SAMP_B0.format(x=zx.format(k=kb), y=zy.format(k=kb))
    zoom = f"if(gt({t}\\,0.5)\\,{za}\\,{zb})"

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


def render(expr, out):
    fc = f"[0:v][1:v]xfade=transition=custom:expr={expr}:duration={D}:offset={CLIP - D}[v]"
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


def main():
    A = frames("output/r3_check/A_ll.mkv")
    B = frames("output/r3_check/B_ll.mkv")
    i0, i1 = OFF, OFF + int(D * FPS) - 1  # 30 .. 59
    for h in [0.0, 0.02, 0.04, 0.06, 0.08, 0.12]:
        t = f"clip((P-{h})/(1-2*{h})\\,0\\,1)"
        exprs = build_exprs(t)
        line = [f"h={h:<4}"]
        for tid in ["whip", "glitch", "flash", "zoom_punch", "burn", "ink"]:
            render(exprs[tid], "output/r3_check/probe.mkv")
            O = frames("output/r3_check/probe.mkv")
            s_start = psnr(O[i0], A[i0])
            s_end = psnr(O[i1], O[i1 + 1])  # last transition frame vs next (=B)
            s_endB = psnr(O[i1], B[i1 - OFF])
            line.append(f"{tid[:5]}:{min(s_start, s_end, s_endB):5.1f}")
        print("  ".join(line))


if __name__ == "__main__":
    main()
