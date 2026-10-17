"""Render a pre-voiced reading video with the half-body avatar (offline, CPU)."""
import json, subprocess, sys
from pathlib import Path
import numpy as np
from hevi.live_host.avatar.halfbody import FFMPEG, FPS, SR, HalfBodyAvatar, Segment, encoder, load_wav16k
wav_dir, sents_json, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
title = sys.argv[4] if len(sys.argv) > 4 else ""
sents = json.loads(sents_json.read_text())
av = HalfBodyAvatar()
segs = [Segment("idle", int(1.0 * FPS), caption=title)]
for i, s in enumerate(sents):
    wp = wav_dir / f"s{i:02d}.wav"
    w = load_wav16k(wp)
    w = np.concatenate([w, np.zeros(int(0.35 * SR), dtype=np.float32)])
    segs.append(Segment("talk", max(1, round(len(w) / SR * FPS)), wav=w, caption=s, audio_path=str(wp)))
segs.append(Segment("idle", int(1.5 * FPS), caption=title))
track = []
for s in segs:
    n = round(s.n_frames / FPS * SR); z = np.zeros(n, dtype=np.float32)
    if s.kind == "talk": z[:min(n, len(s.wav))] = s.wav[:n]
    track.append(z)
out.parent.mkdir(parents=True, exist_ok=True)
audio = out.with_suffix(".wav")
subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", str(audio)],
               input=np.concatenate(track).tobytes(), check=True)
enc = encoder(out, audio)
for s in segs:
    for fr in av.frames(s):
        enc.stdin.write(fr.tobytes())
enc.stdin.close(); assert enc.wait() == 0
c, lag = av.lipsync_corr()
print("RENDER DONE", out, "lipsync_corr", round(c, 3), flush=True)

if av.rag is not None:
    cj = out.parent / "rag_choices.json"
    av.rag.dump_choices(cj)
    lat = [c["latency_ms"] for c in av.rag.choices if c.get("latency_ms")]
    print("RAG REPORT choices", len(av.rag.choices), "misses", av.rag.misses,
          "embedder", av.rag.emb.name if av.rag.emb else "cached_queries",
          "query_ms_p50", round(sorted(lat)[len(lat)//2], 1) if lat else 0,
          "query_ms_max", round(max(lat), 1) if lat else 0, "choices_json", cj, flush=True)
