"""R3 probe 3: measure P at last transition frame, and test one-sided snap remap.

Root cause hypothesis: xfade P does not reach 0 at the last transition frame, so
spatial terms (whip/glitch/zoom_punch) and amplitude terms (flash) leave a
residual -> end frame != B -> pop. Fix: remap progress so it hits 0 over a small
band at the end: t = clip((P-h)/(1-h), 0, 1). One-sided: start (P=1) already exact.
"""

import subprocess
import sys

import numpy as np

sys.path.insert(0, "/data/soffy/projects/hevi-xfadepack")

FFMPEG = "ffmpeg"
W, H, FPS, CLIP = 320, 240, 30, 2.0
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


def frames(p, pf="yuv420p"):
    r = subprocess.run(
        [FFMPEG, "-y", "-i", p, "-f", "rawvideo", "-pix_fmt", pf, "-"], capture_output=True
    )
    if pf == "gray":
        return np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, H, W).astype(np.float64)
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
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=duration={CLIP}:size={W}x{H}:rate={FPS}",
            "-f",
            "lavfi",
            "-i",
            f"smptehdbars=duration={CLIP}:size={W}x{H}:rate={FPS}",
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


def measure_plast(d):
    """Bisect P threshold at the last transition frame."""
    i1 = int((CLIP - d) * FPS) + int(d * FPS) - 1
    lo, hi = 0.0, 0.5
    for _ in range(20):
        mid = (lo + hi) / 2
        render(f"if(gt(P\\,{mid:.6f})\\,255\\,0)", d, "output/r3_check/bis.mkv")
        g = frames("output/r3_check/bis.mkv", "gray")
        on = (g[i1] > 128).mean()
        if on > 0.5:
            lo = mid  # P > mid at last frame
        else:
            hi = mid
    return lo


def main():
    A = frames("output/r3_check/ll_A.mkv")
    B = frames("output/r3_check/ll_B.mkv")
    print("== P at last transition frame (bisection) ==")
    for d in [0.3, 0.4, 0.6, 1.0, 1.5]:
        n = round(d * FPS)
        pl = measure_plast(d)
        print(f"  d={d}: n={n} frames, P_last ≈ {pl:.5f}  (1/n={1 / n:.5f})")

    print("\n== one-sided hold remap: t=clip((P-h)/(1-h),0,1) ==")
    for h in [0.0, 0.06, 0.10, 0.15]:
        print(f"-- h={h} --")
        for d in [0.4, 0.6, 1.0]:
            n = int(d * FPS)
            i0 = int((CLIP - d) * FPS)
            i1 = i0 + n - 1
            t = f"clip((P-{h})/(1-{h})\\,0\\,1)"
            e = exprs(t)
            row = []
            for tid in ["whip", "glitch", "flash", "zoom_punch", "burn", "ink"]:
                render(e[tid], d, "output/r3_check/p3.mkv")
                O = frames("output/r3_check/p3.mkv")
                s_s = psnr(O[i0], A[i0])
                s_e = psnr(O[i1], O[i1 + 1])
                s_eB = psnr(O[i1], B[i1 - i0])
                row.append(f"{tid[:5]}:{min(s_s, s_e, s_eB):5.1f}")
            print(f"   d={d}: " + "  ".join(row))


if __name__ == "__main__":
    main()
