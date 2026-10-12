"""Continuous half-body live stream: danmaku -> LLM -> TTS -> lip-sync -> ffmpeg (OBS / RTMP).

Three threads:
  ingest  : danmaku sources (local HTTP POST, text file tail, Douyin room) -> question queue
  brain   : question -> ollama sentences -> Piper -> Wav2Lip frames  (pre-rendered per sentence)
  output  : wall-clock paced writer; plays ready talk frames+audio, otherwise idle loop + silence

usage:
  python -m hevi.live_host.live_stream [--out rtmp://127.0.0.1:1935/xiaoya] [--douyin ROOM_ID] [--seconds N]
  A local mediamtx relay (unit hevi-live-relay) fans the stream out; publishing is localhost-only.
  OBS: Sources -> Media Source -> untick Local File -> Input: rtmp://<ubuntu26-ip>:1935/xiaoya
       (or rtsp://<ip>:8554/xiaoya, srt://<ip>:8890?streamid=read:xiaoya)
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

os.environ.setdefault("HEVI_LIVE_FPS", "20")  # CPU lip-sync runs ~21 fps -> 20 fps keeps real time

from hevi.live_host.avatar.halfbody import FFMPEG, FPS, SR, H, W, HalfBodyAvatar, load_wav16k  # noqa: E402
from hevi.live_host.oprim.llm_ollama import OllamaLLM  # noqa: E402
from hevi.live_host.oprim.tts_piper import PiperTTS  # noqa: E402

STAGE = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")
ASK = re.compile(r"[?？吗呢么吧哪谁几]|小雅|主播|怎么|什么|推荐|为什么|多少|是不是|能不能|会不会|有没有|讲讲|说说")
SPF = SR // FPS  # audio samples per video frame


class LiveStreamer:
    def __init__(self, out: str, *, persona: str = "小雅", max_queue: int = 5, log: Path | None = None) -> None:
        self.out = out
        self.av = HalfBodyAvatar()
        self.llm = OllamaLLM(persona=persona, max_reply_chars=60)
        self.tts = PiperTTS()
        self.questions: deque[tuple[str, str, float]] = deque(maxlen=max_queue)  # (user, text, t_recv)
        self.qlock = threading.Lock()
        self.ready: queue.Queue = queue.Queue(maxsize=40)  # (frames, wav, caption, meta)
        self.stop = threading.Event()
        self.caption = ""
        self.events: list[dict] = []
        self.log = log
        self.tmp = Path(tempfile.mkdtemp(prefix="hevi_live_"))
        self.speaking = False
        self.stats = {"frames_out": 0, "late_frames": 0, "danmaku": 0, "answered": 0, "dropped": 0}

    # ---------------- ingest ----------------
    def push(self, user: str, text: str) -> None:
        text = text.strip()
        if not text or len(text) > 60:
            return
        with self.qlock:
            if len(self.questions) == self.questions.maxlen:
                self.stats["dropped"] += 1
            self.questions.append((user, text, time.time()))
        self.stats["danmaku"] += 1
        self._event("danmaku", user=user, text=text)

    def serve_http(self, port: int = 8765) -> None:
        streamer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # body: {"user": "...", "text": "..."} or plain text
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8", "ignore")
                try:
                    d = json.loads(raw)
                    streamer.push(d.get("user", "观众"), d.get("text", ""))
                except ValueError:
                    streamer.push("观众", raw)
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def tail_file(self, path: Path) -> None:
        def run():
            path.touch()
            with path.open(encoding="utf-8") as f:
                f.seek(0, 2)
                while not self.stop.is_set():
                    line = f.readline()
                    if not line:
                        time.sleep(0.2)
                        continue
                    user, _, text = line.partition("\t") if "\t" in line else ("观众", "", line)
                    self.push(user, text)
        threading.Thread(target=run, daemon=True).start()

    # ---------------- brain ----------------
    def _brain(self) -> None:
        t_talk = 0
        n = 0
        while not self.stop.is_set():
            with self.qlock:
                item = None
                if self.questions:  # prefer real questions / mentions over chatter
                    pick = next((x for x in reversed(self.questions) if ASK.search(x[1])), None)
                    if pick is not None:
                        self.questions.remove(pick)
                        item = pick
                    elif time.time() - self.questions[0][2] > 2.5:
                        item = self.questions.pop()  # nobody asked anything: answer the newest line
            if item is None:
                time.sleep(0.1)
                continue
            user, q, t_recv = item
            q = EMOJI.sub("", STAGE.sub("", q)).strip() or q
            self.caption = f"{user}：{q}"
            t0 = time.time()
            reply, first = "", True
            t_mark = time.time()
            for chunk in self.llm.stream_reply(q):
                t_llm = time.time() - t_mark
                s = EMOJI.sub("", STAGE.sub("", chunk)).strip()
                if not s or self.stop.is_set():
                    continue
                n += 1
                wav_p = self.tmp / f"s{n}.wav"
                t1 = time.time()
                self.tts.synthesize(s, wav_p)
                t_tts = time.time() - t1
                wav = load_wav16k(wav_p)
                wav_p.unlink(missing_ok=True)
                nf = max(1, round(len(wav) / SR * FPS))
                clip = self.av.talk
                idxs = [clip.pingpong(t_talk + j) for j in range(nf)]
                t_talk += nf
                t2 = time.time()
                reply += s
                spf = SR // FPS
                a = 0
                self.speaking = True
                for part in self.av.lipsync_iter(clip, idxs, wav, chunk=20, first=24):
                    b = a + len(part)
                    seg = wav[a * spf : (b * spf if b < nf else len(wav))]
                    meta = {"q": q, "sentence": s, "chunk_from": a}
                    if a == 0:
                        meta.update({"audio_s": round(len(wav) / SR, 2), "llm_s": round(t_llm, 2), "tts_s": round(t_tts, 2), "lip_first_s": round(time.time() - t2, 2), "wait_s": round(t0 - t_recv, 2), "qsize": self.ready.qsize()})
                        if first:
                            meta["first_ready_s"] = round(time.time() - t_recv, 2)
                            first = False
                    self.ready.put((part, seg, f"小雅：{reply}", meta))
                    a = b
                self.speaking = False
                t_mark = time.time()
            self.stats["answered"] += 1
            self._event("answer", q=q, reply=reply, total_s=round(time.time() - t0, 2), hold_frames=self.stats.get("hold_frames", 0), late_frames=self.stats["late_frames"])

    # ---------------- output ----------------
    def _ffmpeg(self, audio_fifo: Path) -> subprocess.Popen:
        is_file = "://" not in self.out
        fmt = ["-f", "flv"] if self.out.startswith("rtmp") else (["-f", "mpegts"] if not self.out.endswith(".mp4") else [])
        return subprocess.Popen(
            [FFMPEG, "-y", "-v", "error",
             "-probesize", "32", "-analyzeduration", "0", "-thread_queue_size", "512", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-probesize", "32", "-analyzeduration", "0", "-thread_queue_size", "4096", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", str(audio_fifo),
             "-vf", "scale=1080:1920:flags=bicubic", "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
             "-g", str(FPS * 2), "-b:v", "3500k", "-maxrate", "4000k", "-bufsize", "4000k", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "44100", "-b:a", "128k", *fmt, self.out],
            stdin=subprocess.PIPE,
        )

    def _start_encoder(self) -> dict:
        fifo = self.tmp / f"audio{time.time_ns()}.pcm"
        os.mkfifo(fifo)
        enc = self._ffmpeg(fifo)
        afd = os.fdopen(os.open(fifo, os.O_RDWR), "wb", buffering=0)  # RDWR: open never blocks
        vq: queue.Queue = queue.Queue(maxsize=FPS * 2)
        aq: queue.Queue = queue.Queue(maxsize=FPS * 2)

        def writer(q, fh):
            while True:
                b = q.get()
                if b is None:
                    break
                try:
                    fh.write(b)
                except (BrokenPipeError, ValueError, OSError):
                    break

        wv = threading.Thread(target=writer, args=(vq, enc.stdin), daemon=True)
        wa = threading.Thread(target=writer, args=(aq, afd), daemon=True)
        wv.start()
        wa.start()
        return {"enc": enc, "afd": afd, "vq": vq, "aq": aq, "wv": wv, "wa": wa, "fifo": fifo}

    def _stop_encoder(self, e: dict) -> None:
        for q in (e["vq"], e["aq"]):
            try:
                q.put_nowait(None)
            except queue.Full:
                pass
        for f in (e["enc"].stdin, e["afd"]):
            try:
                f.close()
            except OSError:
                pass
        try:
            e["enc"].wait(timeout=10)
        except subprocess.TimeoutExpired:
            e["enc"].kill()
        e["fifo"].unlink(missing_ok=True)

    def _output(self, seconds: float | None) -> None:
        E = self._start_encoder()
        silence = np.zeros(SPF, dtype=np.int16).tobytes()
        idle = self.av.idle
        t_idle, last, mode = 0, None, "idle"
        overlays: dict[str, Image.Image] = {}
        start = time.perf_counter()
        frame_i = 0

        def emit(fr: np.ndarray, audio: bytes, caption: str):
            nonlocal frame_i, last
            ov = overlays.get(caption) or overlays.setdefault(caption, self.av._overlay(caption))
            if len(overlays) > 64:
                overlays.clear()
            im = Image.fromarray(fr).convert("RGBA")
            im.alpha_composite(ov)
            target = start + frame_i / FPS
            now = time.perf_counter()
            if now < target:
                time.sleep(target - now)
            elif now - target > 1 / FPS:
                self.stats["late_frames"] += 1
            nonlocal E
            if E["enc"].poll() is not None:  # sink dropped (relay restart, network): reconnect, keep streaming
                self._event("encoder_restart", code=E["enc"].returncode)
                self.stats["encoder_restarts"] = self.stats.get("encoder_restarts", 0) + 1
                self._stop_encoder(E)
                time.sleep(1)
                E = self._start_encoder()
            try:
                E["vq"].put(np.asarray(im.convert("RGB")).tobytes(), timeout=2)
                E["aq"].put(audio, timeout=2)
            except queue.Full:
                self.stats["late_frames"] += 1
            frame_i += 1
            last = fr

        def xfade(frames: list[np.ndarray]) -> list[np.ndarray]:
            if last is None:
                return frames
            for j in range(min(6, len(frames))):
                a = (j + 1) / 7
                frames[j] = (last.astype(np.float32) * (1 - a) + frames[j].astype(np.float32) * a).astype(np.uint8)
            return frames

        try:
            while not self.stop.is_set():
                if seconds and frame_i >= seconds * FPS:
                    break
                try:
                    frames, wav, caption, meta = self.ready.get_nowait()
                except queue.Empty:
                    frames = None
                if frames is not None:
                    if mode == "idle":
                        frames = xfade(frames)
                    mode = "talk"
                    pcm = (np.clip(wav, -1, 1) * 32767).astype(np.int16)
                    pcm = np.pad(pcm, (0, max(0, len(frames) * SPF - len(pcm))))
                    self.caption = caption
                    if meta.get("chunk_from", 0) == 0:
                        self._event("play", lag_frames=0, **meta)
                    for k, fr in enumerate(frames):
                        emit(fr, pcm[k * SPF:(k + 1) * SPF].tobytes(), caption)
                    continue
                if mode == "talk" and self.speaking and last is not None:
                    # 句子还在分块合成中：定格最后一帧等下一块，不切回待机
                    self.stats["hold_frames"] = self.stats.get("hold_frames", 0) + 1
                    emit(last, silence[:SPF * 2] if len(silence) >= SPF * 2 else silence, self.caption)
                    continue
                # idle: one second chunks keep latency low
                batch = [idle.frames[idle.pingpong(t_idle + j)] for j in range(FPS // 4)]
                t_idle += len(batch)
                if mode == "talk":
                    batch = xfade(batch)
                    mode = "idle"
                for fr in batch:
                    emit(fr, silence, self.caption)
        finally:
            self.stats["frames_out"] = frame_i
            self.stats["wall_s"] = round(time.perf_counter() - start, 2)
            self.stats["stream_s"] = round(frame_i / FPS, 2)
            self._stop_encoder(E)


    def _event(self, kind: str, **kw) -> None:
        e = {"t": round(time.time(), 2), "kind": kind, **kw}
        self.events.append(e)
        if self.log:
            with self.log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def run(self, seconds: float | None = None) -> dict:
        threading.Thread(target=self._brain, daemon=True).start()
        try:
            self._output(seconds)
        finally:
            self.stop.set()
        return self.stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="rtmp://127.0.0.1:1935/xiaoya")
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--http-port", type=int, default=8765)
    ap.add_argument("--danmaku-file", default=None)
    ap.add_argument("--douyin", default=None, help="Douyin live room id (live.douyin.com/<id>)")
    ap.add_argument("--log", default=None)
    a = ap.parse_args()
    s = LiveStreamer(a.out, log=Path(a.log) if a.log else None)
    s.serve_http(a.http_port)
    if a.danmaku_file:
        s.tail_file(Path(a.danmaku_file))
    if a.douyin:
        from hevi.live_host.ingest.douyin_source import start_douyin
        start_douyin(a.douyin, s.push, s.stop)
    print(json.dumps(s.run(a.seconds), ensure_ascii=False))


if __name__ == "__main__":
    main()
