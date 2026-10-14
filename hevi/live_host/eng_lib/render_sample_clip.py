"""Render short 480p sample clips for the English 陪练 pilot.

For 2–3 chosen library items, lip-sync the pre-generated EN audio (Xiaoya voice)
onto the half-body avatar and encode a short portrait clip.  Mirrors
render_reading.py exactly; renders at 480p (270x480) for quick audit.

Usage (env mirrors /data/soffy/cosyvoice/reading/render.sh):
    cd /data/soffy/projects/hevi-live && export PATH=$HOME/.local/bin:$PATH \\
    PYTHONPATH=$PWD FFMPEG=$(command -v ffmpeg) HEVI_LIVE_THREADS=8 HEVI_LIVE_FPS=20 \\
    HEVI_LIVE_MOUTH=v2 HEVI_LIVE_AVATAR=xiaoya_e \\
    /data/soffy/projects/hevi/.venv/bin/python -W ignore \\
        hevi/live_host/eng_lib/render_sample_clip.py \\
        --unit /data/soffy/englib/pep-g7a/u1 --ids k01 k06 d01
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from hevi.live_host.avatar.halfbody import FPS, SR, HalfBodyAvatar, Segment, encoder, load_wav16k


def render_one(av: HalfBodyAvatar, item: dict, unit_dir: Path, out_path: Path) -> float:
    wav = unit_dir / item["wav"]
    w = load_wav16k(wav)
    w = np.concatenate([w, np.zeros(int(0.35 * SR), dtype=np.float32)])
    segs = [
        Segment("idle", int(0.6 * FPS), caption=item.get("text", "")),
        Segment(
            "talk",
            max(1, round(len(w) / SR * FPS)),
            wav=w,
            caption=item.get("text", ""),
            audio_path=str(wav),
        ),
        Segment("idle", int(0.8 * FPS), caption=item.get("text", "")),
    ]
    track = []
    for s in segs:
        n = round(s.n_frames / FPS * SR)
        z = np.zeros(n, dtype=np.float32)
        if s.kind == "talk" and s.wav is not None:
            z[: min(n, len(s.wav))] = s.wav[:n]
        track.append(z)
    audio = out_path.with_suffix(".wav")
    subprocess.run(
        [
            av.FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "f32le",
            "-ar",
            str(SR),
            "-ac",
            "1",
            "-i",
            "-",
            str(audio),
        ],
        input=np.concatenate(track).tobytes(),
        check=True,
    )
    enc = encoder(out_path, audio, size="270x480")
    for s in segs:
        for fr in av.frames(s):
            enc.stdin.write(fr.tobytes())
    enc.stdin.close()
    assert enc.wait() == 0, "encoder failed"
    c, lag = av.lipsync_corr()
    print(f"rendered {out_path.name} lipsync_corr={round(c, 3)}", flush=True)
    return float(c)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="/data/soffy/englib/pep-g7a/u1")
    ap.add_argument("--ids", nargs="+", default=["k01", "k06", "d01"])
    ap.add_argument("--out", default="audit/live_host/englib")
    args = ap.parse_args()

    unit_dir = Path(args.unit)
    manifest = json.loads((unit_dir / "manifest.json").read_text(encoding="utf-8"))
    by_id = {i["id"]: i for i in manifest["items"]}
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    av = HalfBodyAvatar()  # default xiaoya_e clips
    corrs = []
    for iid in args.ids:
        it = by_id.get(iid)
        if it is None or not (unit_dir / it["wav"]).exists():
            print(f"skip {iid}: not generated yet", flush=True)
            continue
        out_path = out_dir / f"sample_{iid}.mp4"
        corrs.append(render_one(av, it, unit_dir, out_path))
    print(
        f"SAMPLES DONE n={len(corrs)} avg_lipsync_corr={round(float(np.mean(corrs)), 3) if corrs else 0.0}",
        flush=True,
    )


if __name__ == "__main__":
    main()
