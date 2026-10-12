"""Half-body live host sample: viewer questions -> local LLM -> Piper -> half-body Wav2Lip avatar.

Every number in the report is measured on this machine (CPU only).
usage: python -m hevi.live_host.sample_halfbody [outdir]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from hevi.live_host.avatar.halfbody import FFMPEG, FPS, SR, HalfBodyAvatar, Segment, encoder, load_wav16k
from hevi.live_host.oprim.llm_ollama import OllamaLLM
from hevi.live_host.oprim.tts_piper import PiperTTS

QUESTIONS = ["小雅晚上好，今天直播聊点什么？", "可以推荐一本适合睡前看的书吗？"]
STAGE = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")


def clean(s: str) -> str:
    return STAGE.sub("", s).strip()


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "audit/live_host/halfbody")
    out_dir.mkdir(parents=True, exist_ok=True)
    t_load = time.perf_counter()
    av = HalfBodyAvatar()
    load_s = time.perf_counter() - t_load
    llm = OllamaLLM(max_reply_chars=60)
    tts = PiperTTS()

    segs: list[Segment] = [Segment("idle", 2 * FPS, caption="")]
    turns = []
    for qi, q in enumerate(QUESTIONS):
        segs.append(Segment("idle", int(2.0 * FPS), caption=f"观众：{q}"))
        t0 = time.perf_counter()
        first_sent_t = None
        sents = []
        for chunk in llm.stream_reply(q):
            c = clean(chunk)
            if not c:
                continue
            if first_sent_t is None:
                first_sent_t = time.perf_counter() - t0
            sents.append(c)
        llm_total = time.perf_counter() - t0
        tts_t, wavs = [], []
        for si, s in enumerate(sents):
            p = out_dir / f"q{qi + 1}_s{si}.wav"
            a = time.perf_counter()
            tts.synthesize(s, p)
            tts_t.append(time.perf_counter() - a)
            wavs.append(load_wav16k(p))
        reply = ""
        for s, w in zip(sents, wavs):
            reply += s
            segs.append(Segment("talk", max(1, round(len(w) / SR * FPS)), wav=w, caption=f"小雅：{reply}"))
        segs.append(Segment("idle", int(1.0 * FPS), caption=f"小雅：{reply}"))
        turns.append({"question": q, "sentences": sents, "llm_first_sentence_s": round(first_sent_t or 0, 3),
                      "llm_total_s": round(llm_total, 3), "tts_s": [round(x, 3) for x in tts_t],
                      "audio_s": [round(len(w) / SR, 2) for w in wavs]})

    # audio track: silence for idle, speech for talk, frame-exact
    track = []
    for s in segs:
        n = round(s.n_frames / FPS * SR)
        if s.kind == "talk" and s.wav is not None:
            w = np.zeros(n, dtype=np.float32)
            w[: min(n, len(s.wav))] = s.wav[:n]
            track.append(w)
        else:
            track.append(np.zeros(n, dtype=np.float32))
    audio = out_dir / "track.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", str(audio)],
                   input=np.concatenate(track).tobytes(), check=True)

    mp4 = out_dir / "sample.mp4"
    enc = encoder(mp4, audio)
    seg_render = []
    t_r = time.perf_counter()
    for s in segs:
        a = time.perf_counter()
        for fr in av.frames(s):
            enc.stdin.write(fr.tobytes())
        seg_render.append({"kind": s.kind, "frames": s.n_frames, "render_s": round(time.perf_counter() - a, 3)})
    enc.stdin.close()
    assert enc.wait() == 0, "encode failed"
    render_total = time.perf_counter() - t_r

    st = av.stats
    talk_fps = st["talk_frames"] / st["talk_seconds"] if st["talk_seconds"] else 0
    corr, lag = av.lipsync_corr()
    np.savez(out_dir / "lipsync_metrics.npz", mouth=np.array(st["mouth"]), rms=np.array(st["rms"]))
    # first-video latency per turn = LLM first sentence + its TTS + avatar render of that sentence
    talk_iter = iter([r for r in seg_render if r["kind"] == "talk"])
    for t in turns:
        first = next(talk_iter)
        for _ in range(len(t["sentences"]) - 1):
            next(talk_iter)
        t["first_video_latency_s"] = round(t["llm_first_sentence_s"] + t["tts_s"][0] + first["render_s"], 3)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                               capture_output=True, text=True).stdout.strip() or 0)
    rep = {"sample": str(mp4), "duration_s": dur, "avatar_load_s": round(load_s, 2), "render_total_s": round(render_total, 2),
           "talk_render_fps": round(talk_fps, 2), "idle_render_fps": round(st["idle_frames"] / st["idle_seconds"], 1) if st["idle_seconds"] else None,
           "realtime_factor_talk": round(talk_fps / FPS, 3), "lipsync_corr": round(corr, 3), "lipsync_lag_frames": lag,
           "turns": turns, "segments": seg_render, "base_videos": {
               "idle": "https://www.pexels.com/video/woman-is-talking-while-looking-at-camera-8135207/",
               "talk": "https://www.pexels.com/video/woman-looking-at-camera-and-speaking-8135208/",
               "license": "Pexels License (free commercial use, no attribution required)"}}
    (out_dir / "metrics.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    # contact sheet
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(mp4), "-vf", f"fps=1/{max(1, dur / 8):.2f},scale=270:-2,tile=8x1",
                    "-frames:v", "1", str(out_dir / "contact.jpg")], check=False)
    print(json.dumps({k: v for k, v in rep.items() if k != "segments"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
