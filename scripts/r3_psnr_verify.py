"""R3 verify G1: whip (and other customs) two-end continuity via PSNR.

Renders testsrc2(A)->smptehdbars(B) two 2s clips with a 1s whip transition,
then measures:
  - first transition frame vs A same-time frame  PSNR (should be >=40 dB)
  - last transition frame vs B same-time frame   PSNR (should be >=40 dB)
Also does it for every custom transition to confirm two-end continuity.
"""

import subprocess
import sys

import numpy as np

sys.path.insert(0, "/data/soffy/projects/hevi-xfadepack")

from hevi.assembly.xfade_transitions import ALL_TRANSITIONS, resolve

FFMPEG = "ffmpeg"
W, H, FPS, D, CLIP = 320, 240, 30, 1.0, 2.0
OFF = int((CLIP - D) * FPS)  # 30 frames offset of transition start


def run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print("CMD FAIL", r.stderr.decode()[-500:])
        raise SystemExit(1)


def make_src(tmp, src, path):
    run([
        FFMPEG, "-y", "-f", "lavfi", "-i",
        f"{src}=duration={CLIP}:size={W}x{H}:rate={FPS}",
        "-pix_fmt", "yuv420p", str(path),
    ])


def render(a, b, trans_id, out):
    from hevi.assembly.assembler import build_xfade_chain
    fc, label, _ = build_xfade_chain([CLIP, CLIP], [trans_id], D)
    run([
        FFMPEG, "-y", "-i", str(a), "-i", str(b),
        "-filter_complex", fc, "-map", label,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", str(out),
    ])


def frames(path):
    r = subprocess.run(
        [FFMPEG, "-y", "-i", str(path), "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, H, W, 3)


def psnr(a, b):
    mse = ((a.astype(np.float64) - b.astype(np.float64)) ** 2).mean()
    if mse == 0:
        return 99.0
    return 10 * np.log10(255.0 ** 2 / mse)


def main():
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    a = tmp / "A.mp4"
    b = tmp / "B.mp4"
    make_src(tmp, "testsrc2", a)
    make_src(tmp, "smptehdbars", b)
    af = frames(a)
    bf = frames(b)
    customs = [t.id for t in ALL_TRANSITIONS if t.kind == "custom"]
    print(f"{'id':12s} {'start_vs_A_dB':>13s} {'end_vs_B_dB':>12s}")
    for cid in customs:
        out = tmp / f"{cid}.mp4"
        render(a, b, cid, out)
        of = frames(out)
        i_start = OFF  # first transition frame, P=1 -> should equal A
        i_end = OFF + int(D * FPS)  # last transition frame, P=0 -> should equal B
        s = psnr(of[i_start], af[i_start])
        # B's matching frame: outline time = transition end = CLIP seconds = frame OFF
        # actually last transition frame corresponds to B's frame at time CLIP - D = OFF
        e = psnr(of[i_end], bf[OFF])
        print(f"{cid:12s} {s:13.2f} {e:12.2f}")


if __name__ == "__main__":
    main()
