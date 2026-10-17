import numpy as np, subprocess, tempfile, shutil
from pathlib import Path

FFMPEG = "ffmpeg"
W, H, FPS, D, CLIP = 320, 240, 25, 1.0, 2.0
tmp = Path(tempfile.mkdtemp())
a = tmp / "A.mp4"
b = tmp / "B.mp4"
subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", f"testsrc2=duration={CLIP}:size={W}x{H}:rate={FPS}", "-pix_fmt", "yuv420p", str(a)], check=True, capture_output=True)
subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", f"smptehdbars=duration={CLIP}:size={W}x{H}:rate={FPS}", "-pix_fmt", "yuv420p", str(b)], check=True, capture_output=True)

_SAMP_A0 = "if(eq(PLANE\\,0)\\,a0({x}\\,{y})\\,if(eq(PLANE\\,1)\\,a1({x}\\,{y})\\,a2({x}\\,{y})))"
_SAMP_B0 = "if(eq(PLANE\\,0)\\,b0({x}\\,{y})\\,if(eq(PLANE\\,1)\\,b1({x}\\,{y})\\,b2({x}\\,{y})))"

_WHIP_BLUR = "P*(1-P)*14"
s_rem = "clip((P-0.05)/0.9\\,0\\,1)*clip((P-0.05)/0.9\\,0\\,1)*(3-2*clip((P-0.05)/0.9\\,0\\,1))*W"
_WHIP = "if(lt(X\\,{s})\\,({a0}+{a1}+{a2})/3\\,({b0}+{b1}+{b2})/3)".format(
    s=s_rem,
    a0=_SAMP_A0.format(x=f"clip(X+W-({s_rem})\\,0\\,W-1)", y="Y"),
    a1=_SAMP_A0.format(x=f"clip(X+W-({s_rem})-{_WHIP_BLUR}\\,0\\,W-1)", y="Y"),
    a2=_SAMP_A0.format(x=f"clip(X+W-({s_rem})+{_WHIP_BLUR}\\,0\\,W-1)", y="Y"),
    b0=_SAMP_B0.format(x=f"clip(X-({s_rem})\\,0\\,W-1)", y="Y"),
    b1=_SAMP_B0.format(x=f"clip(X-({s_rem})-{_WHIP_BLUR}\\,0\\,W-1)", y="Y"),
    b2=_SAMP_B0.format(x=f"clip(X-({s_rem})+{_WHIP_BLUR}\\,0\\,W-1)", y="Y"),
)

_BURN_R = "hypot(X-W/2\\,Y-H/2)/hypot(W/2\\,H/2)"
_BURN = "A*(1-clip(((1-P)*1.10-{r})*12\\,0\\,1))+B*clip(((1-P)*1.10-{r})*12\\,0\\,1)".format(
    r=_BURN_R
)

_GLITCH_N = "0.5+0.5*sin(floor(Y/32)*12.9898)"
_GLITCH_T = "clip((1-P)*1.15\\,0\\,1)"
_GLITCH_DX = "clip(X+({n}-0.5)*70*4*{t}*(1-{t})\\,0\\,W-1)".format(n=_GLITCH_N, t=_GLITCH_T)
_GLITCH = "if(lt({n}\\,{t})\\,{gb}\\,{ga})".format(
    n=_GLITCH_N,
    t=_GLITCH_T,
    ga=_SAMP_A0.format(x=_GLITCH_DX, y="Y"),
    gb=_SAMP_B0.format(x=_GLITCH_DX, y="Y"),
)

_FLASH_WHITE = "128+eq(PLANE\\,0)*107"
_FLASH_PS = "P*P*(3-2*P)"
_FLASH = "if(gt(P\\,0.5)\\,A*(2*({ps})-1)+({w})*(2-2*({ps}))\\,B*(1-2*({ps}))+({w})*(2*({ps})))".format(
    w=_FLASH_WHITE, ps=_FLASH_PS
)

_ZOOM_VA = "clip((1-P-0.05)/0.45\\,0\\,1)"
_ZOOM_VB = "clip((P-0.05)/0.45\\,0\\,1)"
_ZOOM_KA = f"(1-0.35*{_ZOOM_VA}*{_ZOOM_VA}*(3-2*{_ZOOM_VA}))"
_ZOOM_KB = f"(1-0.35*{_ZOOM_VB}*{_ZOOM_VB}*(3-2*{_ZOOM_VB}))"
_ZOOM = "if(gt(P\\,0.5)\\,{a}\\,{b})".format(
    a=_SAMP_A0.format(
        x=f"clip(W/2+(X-W/2)*{_ZOOM_KA}\\,0\\,W-1)",
        y=f"clip(H/2+(Y-H/2)*{_ZOOM_KA}\\,0\\,H-1)",
    ),
    b=_SAMP_B0.format(
        x=f"clip(W/2+(X-W/2)*{_ZOOM_KB}\\,0\\,W-1)",
        y=f"clip(H/2+(Y-H/2)*{_ZOOM_KB}\\,0\\,H-1)",
    ),
)

_INK_R = "{r}+0.12*sin(X/23)*sin(Y/19)".format(r=_BURN_R)
_INK = "A*(1-clip(((1-P)*1.25-({r}))*5\\,0\\,1))+B*clip(((1-P)*1.25-({r}))*5\\,0\\,1)".format(
    r=_INK_R
)

customs = {
    "whip": _WHIP,
    "burn": _BURN,
    "glitch": _GLITCH,
    "flash": _FLASH,
    "zoom_punch": _ZOOM,
    "ink": _INK,
}

def psnr(x, y):
    mse = ((x.astype(float) - y.astype(float))**2).mean()
    return 10 * np.log10(255**2 / mse) if mse > 0 else 99.0

print(f"{'name':12s} | {'n24->25':10s} | {'n48->49':10s} | {'n49->50':10s} | {'diff':10s} | {'status':6s}")
print("-" * 70)
for name, expr in customs.items():
    fc = f"[0:v][1:v]xfade=transition=custom:expr={expr}:offset=1.0:duration=1.0[vout]"
    out = tmp / f"{name}.mp4"
    r = subprocess.run([FFMPEG, "-y", "-i", str(a), "-i", str(b), "-filter_complex", fc, "-map", "[vout]",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)],
                       capture_output=True)
    if r.returncode != 0:
        print(f"{name} ERROR:", r.stderr.decode()[-200:])
        continue
    r1 = subprocess.run([FFMPEG, "-y", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    arr = np.frombuffer(r1.stdout, dtype=np.uint8).reshape(-1, H, W, 3)
    p_start = psnr(arr[24], arr[25])
    p_penult = psnr(arr[48], arr[49])
    p_last = psnr(arr[49], arr[50])
    diff = p_last - p_penult
    ok = (p_last >= 28.0) and (diff >= -3.0)
    status = "OK" if ok else "FAIL"
    print(f"{name:12s} | {p_start:8.2f} dB | {p_penult:8.2f} dB | {p_last:8.2f} dB | {diff:8.2f} dB | {status:6s}")

shutil.rmtree(tmp)
