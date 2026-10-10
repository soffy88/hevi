"""Optional digital-human avatar for talkcraft (omodul-private: models + media I/O).

Modes
- ``lipsync``: Wav2Lip-GAN-96 (ONNX, CPU) re-draws the mouth of a still portrait
  from the narration; yoloface-8n finds the face.  Model licence: Wav2Lip is
  research/non-commercial unless licensed from its authors.
- ``still``: no model; the portrait breathes/sways/nods with the voice.  Use
  this when the lip-sync licence is a problem or the weights are absent.

Output is a 512x512 avatar clip composited as a round picture-in-picture: lower
right/left on 16:9, in the free band under the stage on 9:16.  Every run
measures how strongly mouth motion follows voice loudness (``lipsync_corr``).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG, MediaError, run
from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AvatarSpec
from hevi.layer4_legacy.talkcraft.oskill_impl.avatar_math import (
    FACE,
    SR,
    avatar_square,
    decode_yoloface,
    frame_rms,
    idle_motion,
    lagged_correlation,
    letterbox,
    mel_chunks,
    melspectrogram,
    mouth_mask,
    overlay_layout,
)

MODEL_DIR = Path(os.environ.get("HEVI_TALKCRAFT_AVATAR_MODELS", "/home/soffy/models/wav2lip"))
DEFAULT_PORTRAIT = Path(__file__).resolve().parents[1] / "assets" / "presenter_default.jpg"
SIDE = 512
FPS = 30


@dataclass
class AvatarResult:
    clip: Path
    mode: str
    portrait: str
    face_box: tuple[float, float, float, float]
    face_score: float
    frames: int
    lipsync_corr: float | None
    lipsync_lag_frames: int
    mouth_energy_mean: float
    seconds: float


def _session(name: str) -> Any:
    import onnxruntime as ort

    path = MODEL_DIR / name
    if not path.is_file():
        raise MediaError(f"avatar model missing: {path}")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = int(os.environ.get("HEVI_TALKCRAFT_THREADS", "8"))
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


def _load_wav16k(path: Path) -> np.ndarray:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def _detect_face(img: Image.Image) -> tuple[float, float, float, float, float]:
    sess = _session("yoloface_8n.onnx")
    w, h = img.size
    s, px, py = letterbox(w=w, h=h)
    canvas = Image.new("RGB", (640, 640), (0, 0, 0))
    canvas.paste(img.resize((round(w * s), round(h * s)), Image.BILINEAR), (px, py))
    x = (np.asarray(canvas, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
    out = sess.run(None, {"input": x})[0]
    face = decode_yoloface(output=out, scale=s, pad_x=px, pad_y=py)
    if face is None:
        raise MediaError("no face found in avatar portrait")
    return face


def build_avatar_clip(*, spec: AvatarSpec, voice_wav: Path, duration_s: float, work: Path) -> AvatarResult:
    import time

    t0 = time.monotonic()
    portrait = Path(spec.image) if spec.image else DEFAULT_PORTRAIT
    img = Image.open(portrait).convert("RGB")
    W, H = img.size
    x1, y1, x2, y2, score = _detect_face(img)
    sx, sy, side = avatar_square(face=(x1, y1, x2, y2), w=W, h=H)
    base = img.crop((sx, sy, sx + side, sy + side)).resize((SIDE, SIDE), Image.LANCZOS)
    k = SIDE / side
    # face box inside the avatar square (Wav2Lip pads the chin by ~10px)
    fx1, fy1 = (x1 - sx) * k, (y1 - sy) * k
    fx2, fy2 = (x2 - sx) * k, min(SIDE, (y2 - sy) * k + 10 * k)
    fb = tuple(round(v) for v in (fx1, fy1, fx2, fy2))
    fw, fh = fb[2] - fb[0], fb[3] - fb[1]

    wav = _load_wav16k(voice_wav)
    n = round(duration_s * FPS)
    rms = frame_rms(wav=wav, fps=FPS, n_frames=n)
    base_np = np.asarray(base, dtype=np.float32)
    face_ref = base.crop(fb).resize((FACE, FACE), Image.BILINEAR)
    ref_bgr = np.asarray(face_ref, dtype=np.float32)[..., ::-1] / 255.0
    mask = mouth_mask(w=fw, h=fh)[..., None]

    preds: np.ndarray | None = None
    if spec.mode == "lipsync":
        sess = _session("wav2lip_gan_96.onnx")
        mels = mel_chunks(mel=melspectrogram(wav=wav), fps=FPS, n_frames=n)
        masked = ref_bgr.copy()
        masked[FACE // 2 :] = 0
        target = np.concatenate([masked, ref_bgr], axis=2).transpose(2, 0, 1)[None]
        preds = np.empty((n, FACE, FACE, 3), dtype=np.float32)
        bs = 64
        for a in range(0, n, bs):
            b = min(n, a + bs)
            out = sess.run(None, {"source": mels[a:b, None], "target": np.repeat(target, b - a, axis=0).astype(np.float32)})[0]
            preds[a:b] = out.transpose(0, 2, 3, 1)[..., ::-1]  # BGR -> RGB, 0..1

    clip = work / "avatar.mp4"
    enc = subprocess.Popen(
        [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{SIDE}x{SIDE}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(clip)],
        stdin=subprocess.PIPE,
    )
    assert enc.stdin is not None
    mouth_energy = np.zeros(n, dtype=np.float32)
    ref_face_px = base_np[fb[1] : fb[3], fb[0] : fb[2]]
    for i in range(n):
        frame = base_np.copy()
        if preds is not None:
            gen = np.asarray(
                Image.fromarray(np.clip(preds[i] * 255, 0, 255).astype(np.uint8)).resize((fw, fh), Image.BICUBIC),
                dtype=np.float32,
            )
            blended = ref_face_px * (1 - mask) + gen * mask
            frame[fb[1] : fb[3], fb[0] : fb[2]] = blended
            lower = slice(fh // 2, fh)
            mouth_energy[i] = float(np.mean(np.abs(blended[lower] - ref_face_px[lower])))
        scale, dx, dy = idle_motion(i=i, fps=FPS, rms=float(rms[i]))
        im = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8))
        # inverse affine about the centre: zoom + translate
        c = SIDE / 2
        a_ = 1 / scale
        im = im.transform((SIDE, SIDE), Image.AFFINE, (a_, 0, c - a_ * (c + dx), 0, a_, c - a_ * (c + dy)), resample=Image.BILINEAR)
        enc.stdin.write(im.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise MediaError("avatar encode failed")
    corr, lag = lagged_correlation(mouth_energy, rms) if preds is not None else (None, 0)
    np.savez_compressed(work / "avatar_metrics.npz", mouth_energy=mouth_energy, rms=rms)
    return AvatarResult(
        clip=clip, mode=spec.mode, portrait=str(portrait), face_box=(x1, y1, x2, y2), face_score=score,
        frames=n, lipsync_corr=corr, lipsync_lag_frames=lag,
        mouth_energy_mean=round(float(mouth_energy.mean()), 3), seconds=round(time.monotonic() - t0, 1),
    )


def _ring_assets(work: Path, d: int, ring: int) -> tuple[Path, Path]:
    big = d * 4
    m = Image.new("L", (big, big), 0)
    ImageDraw.Draw(m).ellipse((0, 0, big - 1, big - 1), fill=255)
    m = m.resize((d, d), Image.LANCZOS)
    mask = work / f"avatar_mask_{d}.png"
    m.save(mask)
    D = d + 2 * ring
    r = Image.new("RGBA", (D * 4, D * 4), (0, 0, 0, 0))
    dr = ImageDraw.Draw(r)
    dr.ellipse((0, 0, D * 4 - 1, D * 4 - 1), fill=(255, 255, 255, 255))
    dr.ellipse((ring * 4, ring * 4, (ring + d) * 4 - 1, (ring + d) * 4 - 1), fill=(0, 0, 0, 0))
    r = r.resize((D, D), Image.LANCZOS)
    shadow = Image.new("RGBA", (D + 40, D + 40), (0, 0, 0, 0))
    sh = Image.new("L", (D, D), 0)
    ImageDraw.Draw(sh).ellipse((0, 0, D - 1, D - 1), fill=90)
    shadow.paste((0, 0, 0, 255), (20, 26), sh)
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    shadow.alpha_composite(r, (20, 20))
    ring_p = work / f"avatar_ring_{d}.png"
    shadow.save(ring_p)
    return mask, ring_p


def composite(*, video: Path, avatar: Path, out: Path, position: str, portrait: bool, work: Path) -> dict[str, int]:
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import probe

    info = probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    W, H = int(v["width"]), int(v["height"])
    x, y, d = overlay_layout(frame_w=W, frame_h=H, position=position, portrait=portrait)
    ring = max(4, d // 50)
    mask, ring_png = _ring_assets(work, d, ring)
    fc = (
        f"[1:v]scale={d}:{d},format=rgba[av];[2:v]format=gray[m];[av][m]alphamerge[avm];"
        f"[0:v][3:v]overlay={x - ring - 20}:{y - ring - 20}[b];[b][avm]overlay={x}:{y}:shortest=1[v]"
    )
    run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-i", str(avatar), "-loop", "1", "-i", str(mask),
         "-loop", "1", "-i", str(ring_png), "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "copy",
         "-t", str(float(info["format"]["duration"])), str(out)])
    return {"x": x, "y": y, "diameter": d}
