"""Half-body live avatar for the Hevi live host (CPU only, zero paid calls).

LiveTalking-style: a real half-body base video (idle clip + talking/gesture
clip, ping-pong looped so motion never jumps) is lip-synced to the TTS audio
with Wav2Lip-GAN-96 (ONNX, CPU).  yoloface-8n tracks the face per frame.
Every frame carries an "AI生成" label (China AIGC labelling rules).

Reuses Hevi talkcraft's audio/face maths (mel, rms, yoloface decode, mouth mask).
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hevi.layer4_legacy.talkcraft.oskill_impl.avatar_math import (
    FACE,
    SR,
    decode_yoloface,
    frame_rms,
    lagged_correlation,
    letterbox,
    mel_chunks,
    melspectrogram,
    mouth_mask,
)

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
MODEL_DIR = Path(os.environ.get("HEVI_LIVE_AVATAR_MODELS", "/home/soffy/models/wav2lip"))
CACHE = Path(os.environ.get("HEVI_LIVE_AVATAR_CACHE", str(Path.home() / ".cache/hevi/live_halfbody")))
ASSETS = Path(__file__).resolve().parents[3] / "assets" / "halfbody"
W, H, FPS = 720, 1280, 25
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in FONT_CANDIDATES:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _session(name: str):
    import onnxruntime as ort

    path = MODEL_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"avatar model missing: {path}")
    o = ort.SessionOptions()
    o.intra_op_num_threads = int(os.environ.get("HEVI_LIVE_THREADS", "12"))
    return ort.InferenceSession(str(path), sess_options=o, providers=["CPUExecutionProvider"])


def load_wav16k(path: Path) -> np.ndarray:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


@dataclass
class BaseClip:
    """A base video decoded to WxH frames plus a smoothed per-frame face box."""

    path: Path
    frames: np.ndarray = field(repr=False)  # (N,H,W,3) uint8
    boxes: np.ndarray = field(repr=False)  # (N,4) float  x1,y1,x2,y2

    @classmethod
    def load(cls, path: Path, *, yolo=None, max_s: float = 13.0) -> "BaseClip":
        CACHE.mkdir(parents=True, exist_ok=True)
        key = CACHE / f"{path.stem}_{W}x{H}_{FPS}_boxes.npy"
        raw = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(path), "-t", str(max_s), "-vf",
             f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=True,
        ).stdout
        frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, H, W, 3)
        if key.is_file() and key.stat().st_mtime >= path.stat().st_mtime:
            boxes = np.load(key)
            if len(boxes) == len(frames):
                return cls(path=path, frames=frames, boxes=boxes)
        yolo = yolo or _session("yoloface_8n.onnx")
        s, px, py = letterbox(w=W, h=H)
        n = len(frames)
        det = np.full((n, 4), np.nan)
        for i in range(0, n, 2):
            canvas = Image.new("RGB", (640, 640))
            canvas.paste(Image.fromarray(frames[i]).resize((round(W * s), round(H * s)), Image.BILINEAR), (px, py))
            x = (np.asarray(canvas, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
            f = decode_yoloface(output=yolo.run(None, {"input": x})[0], scale=s, pad_x=px, pad_y=py)
            if f is not None:
                det[i] = f[:4]
        ok = ~np.isnan(det[:, 0])
        if ok.sum() < n * 0.3:
            raise RuntimeError(f"face not tracked in {path.name} ({ok.sum()}/{n})")
        idx = np.arange(n)
        for c in range(4):
            det[:, c] = np.interp(idx, idx[ok], det[ok, c])
        k = 5  # temporal smoothing kills box jitter (mouth patch would shimmer)
        pad = np.pad(det, ((k, k), (0, 0)), mode="edge")
        boxes = np.stack([pad[i : i + 2 * k + 1].mean(0) for i in range(n)])
        np.save(key, boxes)  # only boxes are cached; frames decode in ~1 s
        return cls(path=path, frames=frames, boxes=boxes)

    def __len__(self) -> int:
        return len(self.frames)

    def pingpong(self, t: int) -> int:
        n = len(self)
        p = t % (2 * n - 2)
        return p if p < n else 2 * n - 2 - p


@dataclass
class Segment:
    kind: str  # "idle" | "talk"
    n_frames: int
    wav: np.ndarray | None = None
    caption: str = ""


class HalfBodyAvatar:
    """Renders idle / talking segments of a half-body host into one frame stream."""

    def __init__(self, idle: Path | None = None, talk: Path | None = None, *, label: str = "AI生成") -> None:
        self.yolo = _session("yoloface_8n.onnx")
        self.w2l = _session("wav2lip_gan_96.onnx")
        self.idle = BaseClip.load(idle or ASSETS / "8135207.mp4", yolo=self.yolo)
        self.talk = BaseClip.load(talk or ASSETS / "8135208.mp4", yolo=self.yolo)
        self.label = label
        self.t = 0  # global clock: motion stays continuous across segments
        self.prev_kind = "idle"
        self._overlay_cache: dict[str, Image.Image] = {}
        self.stats = {"talk_frames": 0, "talk_seconds": 0.0, "idle_frames": 0, "idle_seconds": 0.0, "mouth": [], "rms": []}

    # ---- overlays -------------------------------------------------------
    def _overlay(self, caption: str) -> Image.Image:
        if caption in self._overlay_cache:
            return self._overlay_cache[caption]
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        f = _font(30)
        tw = d.textlength(self.label, font=f)
        d.rounded_rectangle((W - tw - 44, 24, W - 16, 74), radius=12, fill=(0, 0, 0, 150))
        d.text((W - tw - 30, 30), self.label, font=f, fill=(255, 255, 255, 235))
        if caption:
            cf = _font(34)
            lines, cur = [], ""
            for ch in caption:
                if d.textlength(cur + ch, font=cf) > W - 90:
                    lines.append(cur)
                    cur = ""
                cur += ch
            lines.append(cur)
            lines = lines[-3:]
            y0 = H - 70 - 50 * len(lines)
            d.rounded_rectangle((30, y0 - 16, W - 30, H - 60), radius=18, fill=(0, 0, 0, 140))
            for j, ln in enumerate(lines):
                d.text((48, y0 + 50 * j), ln, font=cf, fill=(255, 255, 255, 255))
        self._overlay_cache[caption] = ov
        return ov

    # ---- lip-sync -------------------------------------------------------
    def _lipsync(self, clip: BaseClip, idxs: list[int], wav: np.ndarray) -> list[np.ndarray]:
        n = len(idxs)
        mels = mel_chunks(mel=melspectrogram(wav=wav), fps=FPS, n_frames=n)
        crops, boxes = [], []
        for i in idxs:
            x1, y1, x2, y2 = clip.boxes[i]
            hh = y2 - y1
            b = (int(max(0, x1)), int(max(0, y1)), int(min(W, x2)), int(min(H, y2 + 0.10 * hh)))
            boxes.append(b)
            crop = Image.fromarray(clip.frames[i][b[1] : b[3], b[0] : b[2]]).resize((FACE, FACE), Image.BILINEAR)
            crops.append(np.asarray(crop, dtype=np.float32)[..., ::-1] / 255.0)
        ref = np.stack(crops)
        masked = ref.copy()
        masked[:, FACE // 2 :] = 0
        target = np.concatenate([masked, ref], axis=3).transpose(0, 3, 1, 2).astype(np.float32)
        preds = np.empty((n, FACE, FACE, 3), dtype=np.float32)
        for a in range(0, n, 64):
            b = min(n, a + 64)
            out = self.w2l.run(None, {"source": mels[a:b, None].astype(np.float32), "target": target[a:b]})[0]
            preds[a:b] = out.transpose(0, 2, 3, 1)[..., ::-1]
        frames = []
        for k, i in enumerate(idxs):
            fr = clip.frames[i].astype(np.float32)
            bx = boxes[k]
            fw, fh = bx[2] - bx[0], bx[3] - bx[1]
            gen = np.asarray(Image.fromarray(np.clip(preds[k] * 255, 0, 255).astype(np.uint8)).resize((fw, fh), Image.BICUBIC), dtype=np.float32)
            m = mouth_mask(w=fw, h=fh)[..., None]
            orig = fr[bx[1] : bx[3], bx[0] : bx[2]].copy()
            blend = orig * (1 - m) + gen * m
            fr[bx[1] : bx[3], bx[0] : bx[2]] = blend
            self.stats["mouth"].append(float(np.mean(np.abs(blend[fh // 2 :] - orig[fh // 2 :]))))
            frames.append(fr.astype(np.uint8))
        return frames

    # ---- segments -------------------------------------------------------
    def frames(self, seg: Segment) -> Iterator[np.ndarray]:
        clip = self.talk if seg.kind == "talk" else self.idle
        idxs = [clip.pingpong(self.t + j) for j in range(seg.n_frames)]
        t0 = time.perf_counter()
        if seg.kind == "talk" and seg.wav is not None:
            out = self._lipsync(clip, idxs, seg.wav)
            self.stats["rms"].extend(frame_rms(wav=seg.wav, fps=FPS, n_frames=seg.n_frames).tolist())
        else:
            out = [clip.frames[i] for i in idxs]
        # crossfade 8 frames when switching idle<->talk so the cut is invisible-ish
        if seg.kind != self.prev_kind and hasattr(self, "_last"):
            for j in range(min(8, len(out))):
                a = (j + 1) / 9
                out[j] = (self._last.astype(np.float32) * (1 - a) + out[j].astype(np.float32) * a).astype(np.uint8)
        ov = self._overlay(seg.caption)
        for fr in out:
            im = Image.fromarray(fr).convert("RGBA")
            im.alpha_composite(ov)
            yield np.asarray(im.convert("RGB"))
        self._last = out[-1]
        dt = time.perf_counter() - t0
        key = "talk" if seg.kind == "talk" else "idle"
        self.stats[f"{key}_frames"] += seg.n_frames
        self.stats[f"{key}_seconds"] += dt
        self.t += seg.n_frames
        self.prev_kind = seg.kind

    def lipsync_corr(self) -> tuple[float, int]:
        if not self.stats["mouth"]:
            return 0.0, 0
        return lagged_correlation(self.stats["mouth"], self.stats["rms"], max_lag=6)


def encoder(out: Path, audio: Path, *, size: str = "1080x1920") -> subprocess.Popen:
    """Encode frames (stdin rawvideo) + audio to an MP4.  For OBS/RTMP swap the
    output for: -f flv rtmp://<server>/<key>  (or -f mpegts udp://127.0.0.1:1234
    and add it in OBS as a Media Source)."""
    return subprocess.Popen(
        [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(audio), "-vf", f"scale={size.replace('x', ':')}:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
