#!/usr/bin/env python
"""Build the motion-RAG index for the Xiaoya half-body avatar.

Cuts every `assets/halfbody/<avatar>_*.mp4` clip into overlapping segments
(1.0-3.0 s, stride 0.5 s), embeds them with EmbeddingGemma 2, and writes a
local npz the renderer loads (`LocalIndex`).  Optionally syncs the whole
library to / from the AII/Stratum media-asset store (`--push-stratum` /
`--pull-stratum`; see /data/soffy/motionrag/stratum_contract.md).

    PYTHONPATH=. python scripts/build_motion_index.py \
        --assets assets/halfbody --avatar xiaoya_e \
        --out /data/soffy/motionrag/index.npz

Efficiency: each sampled clip frame is embedded ONCE; a segment's video
embedding is the mean of the frame embeddings that fall in its range.  A
12-clip library therefore costs ~240 image encodings, not thousands.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

# Load motionrag.py by path: importing `hevi.live_host` would drag in the whole
# live-host package (onnxruntime, wav2lip), which this build venv does not have.
# motionrag itself only needs numpy at import time.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "motionrag", ROOT / "hevi/live_host/avatar/motionrag.py"
)
_mr = importlib.util.module_from_spec(_spec)
sys.modules["motionrag"] = _mr
_spec.loader.exec_module(_mr)

Config, LocalIndex, Seg, StratumIndex = _mr.Config, _mr.LocalIndex, _mr.Seg, _mr.StratumIndex
_l2, get_embedder = _mr._l2, _mr.get_embedder

FFMPEG = "ffmpeg"
# Frames/second sampled for embedding.  EmbeddingGemma 2 image encoding is ~10 s
# per frame on this CPU (the shared GPU service would be ~1 s), so this is a
# deliberate trade: 2 fps gives 10 frames/clip, ~18 min for an 11-clip library.
EMB_FPS = 2.0
POSE_W, POSE_H = 16, 28  # pose-proxy thumbnail (grayscale)


def _decode(path: Path, fps: float, w: int, h: int) -> np.ndarray:
    raw = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps={fps},scale={w}:{h}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def _pose(frame: np.ndarray) -> np.ndarray:
    """Cheap pose proxy: downsampled grayscale, mean-centred, L2-normalised."""
    from PIL import Image

    g = Image.fromarray(frame).convert("L").resize((POSE_W, POSE_H), Image.BILINEAR)
    t = np.asarray(g, dtype=np.float32) / 255.0
    t = t.reshape(-1) - t.mean()
    return t / max(np.linalg.norm(t), 1e-6)


def _energy(frames20: np.ndarray) -> np.ndarray:
    """Per-frame motion energy = mean |Δ| to the previous frame (at 20 fps)."""
    d = np.abs(np.diff(frames20.astype(np.float32), axis=0)).mean(axis=(1, 2, 3))
    return np.concatenate([[0.0], d]).astype(np.float32)


def _windows(
    n: int, fps: float, min_s: float, max_s: float, stride_s: float
) -> list[tuple[int, int]]:
    lo, hi, st = int(round(min_s * fps)), int(round(max_s * fps)), int(round(stride_s * fps))
    out: list[tuple[int, int]] = []
    for start in range(0, max(1, n - lo + 1), st):
        for length in (lo, (lo + hi) // 2, hi):
            end = min(n, start + length)
            if end - start >= max(lo // 2, 5):
                out.append((start, end))
    # dedupe, keep order
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


def build(
    assets: Path,
    avatar: str,
    cfg: Config,
    *,
    fps: float,
    min_s: float,
    max_s: float,
    stride_s: float,
    only: list[str] | None = None,
) -> LocalIndex:
    from PIL import Image

    tags_path = assets / "motion_tags.yaml"
    import yaml

    tags = yaml.safe_load(tags_path.read_text())["clips"]
    clips = sorted(p for p in assets.glob(f"{avatar}_*.mp4"))
    if (assets / f"{avatar}_talk.mp4").is_file() and (assets / f"{avatar}_talk_a.mp4").is_file():
        clips = [p for p in clips if p.stem != f"{avatar}_talk"]
    clips = [p for p in clips if p.stem[len(avatar) + 1 :] in tags]
    if only:
        keep = set(only)
        clips = [p for p in clips if p.stem[len(avatar) + 1 :] in keep]
    print(f"[build] {len(clips)} clips, embedder={cfg.emb_mode}", flush=True)
    emb = get_embedder(cfg)

    # 1) embed every sampled frame of every clip ONCE
    frame_emb: dict[str, np.ndarray] = {}
    frame_pose: dict[str, np.ndarray] = {}
    energy20: dict[str, np.ndarray] = {}
    nframes: dict[str, int] = {}
    t_all = time.time()
    for p in clips:
        name = p.stem[len(avatar) + 1 :]
        fs = _decode(p, EMB_FPS, 216, 384)
        f20 = _decode(p, fps, 180, 320)
        t0 = time.time()
        e = emb.images([Image.fromarray(x) for x in fs])
        frame_emb[name] = _l2(e)
        frame_pose[name] = np.stack([_pose(x) for x in fs])
        energy20[name] = _energy(f20)
        nframes[name] = len(f20)
        print(
            f"[build]   {name:12s} {len(fs)} frames → {e.shape} in {time.time() - t0:.1f}s "
            f"({nframes[name]} @ {fps:g}fps)",
            flush=True,
        )

    # 2) text descriptions
    desc = {k: f"{v['zh']} {v['en']}" for k, v in tags.items()}
    names = [p.stem[len(avatar) + 1 :] for p in clips]
    temb = _l2(emb.text([desc[n] for n in names], query=False))

    # 3) segments
    segs: list[Seg] = []
    for i, p in enumerate(clips):
        name = names[i]
        n = nframes[name]
        fe, fp, en = frame_emb[name], frame_pose[name], energy20[name]
        for start, end in _windows(n, fps, min_s, max_s, stride_s):
            a = min(len(fe) - 1, int(start / fps * EMB_FPS))
            b = max(a + 1, min(len(fe), int(np.ceil(end / fps * EMB_FPS))))
            video = _l2(fe[a:b].mean(axis=0))
            ep = int(np.argmax(en[start:end])) if end > start else 0
            segs.append(
                Seg(
                    idx=len(segs),
                    clip=name,
                    start=start,
                    end=end,
                    kinds=tuple(tags[name].get("kinds", ["talk"])),
                    text=desc[name],
                    energy_peak=ep,
                    video=video,
                    text_emb=temb[i],
                    pose_first=fp[min(a, len(fp) - 1)],
                    pose_last=fp[min(b - 1, len(fp) - 1)],
                )
            )
    meta = {
        "avatar": avatar,
        "fps": fps,
        "emb_fps": EMB_FPS,
        "dim": int(segs[0].video.shape[0]) if segs else 0,
        "embedder": emb.name,
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "segments": len(segs),
        "clips": names,
        "window_s": [min_s, max_s],
        "stride_s": stride_s,
    }
    print(
        f"[build] {len(segs)} segments from {len(clips)} clips in {time.time() - t_all:.1f}s",
        flush=True,
    )
    return LocalIndex(segs, meta)


# --------------------------------------------------------------------------
# Stratum sync
# --------------------------------------------------------------------------


def push_stratum(
    index: LocalIndex, cfg: Config, emb, *, wav_dir: Path | None, sents_json: Path | None
) -> None:
    """Ingest every motion segment (and every rendered sentence as an utterance).

    Vectors are precomputed here (the local index already has the media ones), so
    the AII backend needs no EmbeddingGemma gateway access for the ingest.
    """
    st = StratumIndex(cfg)
    assets: list[dict] = []
    import uuid

    for s in index.segs:
        aid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"motionseg/{cfg.owner}/{s.clip}/{s.start}/{s.end}")
        )
        assets.append(
            {
                "id": aid,
                "kind": "motion_segment",
                "owner": cfg.owner,
                "text": s.text,
                "clip": s.clip,
                "start_ms": int(s.start / index.meta["fps"] * 1000),
                "end_ms": int(s.end / index.meta["fps"] * 1000),
                "uri": str(
                    Path(index.meta.get("assets_dir", "")) / f"{index.meta['avatar']}_{s.clip}.mp4"
                ),
                "meta": {"kinds": list(s.kinds), "energy_peak_frame": s.energy_peak},
                "emb_text": s.text_emb.tolist(),
                "emb_media": s.video.tolist(),
            }
        )
    print(f"[stratum] pushing {len(assets)} motion segments…", flush=True)
    res = st.push(assets)
    print(
        f"[stratum] ingested={res.get('ingested')} errors={len(res.get('errors', []))}", flush=True
    )

    if wav_dir and sents_json and sents_json.is_file():
        sents = json.loads(sents_json.read_text())
        utext = emb.text(sents, query=False)
        utts = []
        for i, text in enumerate(sents):
            wav = wav_dir / f"s{i:02d}.wav"
            uid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"utterance/{cfg.owner}/{i}"))
            utts.append(
                {
                    "id": uid,
                    "kind": "utterance",
                    "owner": cfg.owner,
                    "text": text,
                    "lang": "zh",
                    "uri": str(wav) if wav.is_file() else None,
                    "meta": {"sentence_id": f"s{i:02d}"},
                    "emb_text": utext[i].tolist(),
                }
            )
        print(f"[stratum] pushing {len(utts)} utterances…", flush=True)
        r2 = st.push(utts)
        print(
            f"[stratum] utterances ingested={r2.get('ingested')} errors={len(r2.get('errors', []))}",
            flush=True,
        )


def pull_stratum(cfg: Config, *, out: Path, meta: Path) -> None:
    """Rebuild the local npz cache from the Stratum media store."""
    st = StratumIndex(cfg)
    rows = st.search(kind="motion_segment", owner=cfg.owner, top_k=1000, w_text=1.0, w_media=0.0)
    if not rows:
        rows = st.search(
            kind="motion_segment", owner=cfg.owner, top_k=1000, w_text=0.0, w_media=1.0
        )
    print(f"[stratum] pulled {len(rows)} motion segments", flush=True)
    fps = 20.0
    segs = []
    for r in rows:
        fps = r["meta"].get("fps", fps) if isinstance(r.get("meta"), dict) else fps
        segs.append(
            Seg(
                idx=len(segs),
                clip=r["clip"] or r["uri"].split("/")[-1],
                start=0,
                end=0,
                kinds=tuple(r["meta"].get("kinds", ["talk"]))
                if isinstance(r.get("meta"), dict)
                else ("talk",),
                text=r["text"] or "",
                energy_peak=0,
                video=np.asarray(r.get("emb_media") or np.zeros(768), np.float32),
                text_emb=np.asarray(r.get("emb_text") or np.zeros(768), np.float32),
                pose_first=np.zeros(1, np.float32),
                pose_last=np.zeros(1, np.float32),
            )
        )
    meta_d = {
        "avatar": cfg.owner.split("/")[-1],
        "fps": fps,
        "dim": 768,
        "source": "stratum",
        "segments": len(segs),
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    LocalIndex(segs, meta_d).save(out, meta)
    print(f"[stratum] wrote {out} ({len(segs)} segments)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", type=Path, default=ROOT / "assets/halfbody")
    ap.add_argument("--avatar", default="xiaoya_e")
    ap.add_argument("--out", type=Path, default=Config().index)
    ap.add_argument("--meta", type=Path, default=Config().meta)
    ap.add_argument("--fps", type=float, default=20.0)
    ap.add_argument("--min-s", type=float, default=1.0)
    ap.add_argument("--max-s", type=float, default=3.0)
    ap.add_argument("--stride-s", type=float, default=0.5)
    ap.add_argument(
        "--only", nargs="*", default=None, help="clip names (without avatar prefix) to index"
    )
    ap.add_argument("--push-stratum", action="store_true")
    ap.add_argument("--pull-stratum", action="store_true")
    ap.add_argument("--wav-dir", type=Path, default=Path("/data/soffy/cosyvoice/reading/huozhe"))
    ap.add_argument(
        "--sents-json", type=Path, default=Path("/data/soffy/cosyvoice/reading/huozhe.json")
    )
    args = ap.parse_args()
    cfg = Config()

    if args.pull_stratum:
        pull_stratum(cfg, out=args.out, meta=args.meta)
        return 0

    index = build(
        args.assets,
        args.avatar,
        cfg,
        fps=args.fps,
        min_s=args.min_s,
        max_s=args.max_s,
        stride_s=args.stride_s,
        only=args.only,
    )
    index.meta["assets_dir"] = str(args.assets)
    index.save(args.out, args.meta)
    print(f"[build] wrote {args.out}", flush=True)

    if args.push_stratum:
        push_stratum(
            index, cfg, get_embedder(cfg), wav_dir=args.wav_dir, sents_json=args.sents_json
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
