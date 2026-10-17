"""R5: 打印修正后连续性测试的真实 PSNR 数值(6 custom + R3 反例)。"""
import subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, "/data/soffy/projects/hevi-xfadepack")
sys.path.insert(0, "/data/soffy/projects/hevi-xfadepack/tests")
import numpy as np
import test_xfade_pack as tx
from hevi.assembly.xfade_transitions import (
    ALL_TRANSITIONS, _SAMP_A0, _SAMP_B0, _WHIP_BLUR,
)

FFMPEG = "/home/soffy/.local/bin/ffmpeg"
W, H, FPS, D, CLIP = 320, 240, 30, 1.0, 2.0
OFF = CLIP - D


def frames(p):
    return tx._f3_frames(Path(p))


def psnr(x, y):
    mse = ((x.astype(np.float64) - y.astype(np.float64)) ** 2).mean()
    return 99.0 if mse == 0 else float(10 * np.log10(255.0 ** 2 / mse))


def measure(of):
    i0 = int(OFF * FPS)
    i_pre, i_start = i0 - 1, i0
    i_prev = i0 + round(D * FPS) - 2
    i_last = i0 + round(D * FPS) - 1
    i_next = i0 + round(D * FPS)
    return dict(pre=psnr(of[i_start], of[i_pre]),
                penult=psnr(of[i_prev], of[i_last]),
                end=psnr(of[i_last], of[i_next]),
                next_pair=psnr(of[i_next], of[i_next + 1]))


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    a, b = tx._f3_sources(td)  # 与测试完全相同的源(testsrc2/smptehdbars mp4)

    def render(expr, out):
        tx._f3_render_expr(a, b, expr, out, codec="ffv1")

    print(f"fps={FPS} res={W}x{H} codec=ffv1  i_pre=29 i_start=30 i_prev=58 i_last=59 i_next=60")
    print(f"{'custom':<12}{'pre(30vs29)':>12}{'penult(58->59)':>16}{'end(59->60)':>13}{'next_pair':>11}")
    for t in ALL_TRANSITIONS:
        if t.kind != "custom":
            continue
        out = td / f"{t.id}.mkv"
        render(t.ffmpeg, out)
        m = measure(frames(out))
        print(f"{t.id:<12}{m['pre']:>12.2f}{m['penult']:>16.2f}{m['end']:>13.2f}{m['next_pair']:>11.2f}")

    r3 = "if(lt(X\\,W-(1-P)*W)\\,({a0}+{a1}+{a2})/3\\,({b0}+{b1}+{b2})/3)".format(
        a0=_SAMP_A0.format(x="clip(X+(1-P)*W\\,0\\,W-1)", y="Y"),
        a1=_SAMP_A0.format(x="clip(X+(1-P)*W-{bl}\\,0\\,W-1)".format(bl=_WHIP_BLUR), y="Y"),
        a2=_SAMP_A0.format(x="clip(X+(1-P)*W+{bl}\\,0\\,W-1)".format(bl=_WHIP_BLUR), y="Y"),
        b0=_SAMP_B0.format(x="clip(X-W+(1-P)*W\\,0\\,W-1)", y="Y"),
        b1=_SAMP_B0.format(x="clip(X-W+(1-P)*W-{bl}\\,0\\,W-1)".format(bl=_WHIP_BLUR), y="Y"),
        b2=_SAMP_B0.format(x="clip(X-W+(1-P)*W+{bl}\\,0\\,W-1)".format(bl=_WHIP_BLUR), y="Y"),
    )
    out = td / "r3whip.mkv"
    render(r3, out)
    m = measure(frames(out))
    print(f"{'R3_linear_whip':<12}{m['pre']:>12.2f}{m['penult']:>16.2f}{m['end']:>13.2f}{m['next_pair']:>11.2f}  (反例, 必须 <28)")
