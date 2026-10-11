"""Optional digital-human avatar for talkcraft (omodul-private: models + media I/O).

Modes
- ``lipsync``: Wav2Lip-GAN-96 (ONNX, CPU) re-draws the mouth of a still portrait
  from the narration; yoloface-8n finds the face.  Model licence: Wav2Lip is
  research/non-commercial unless licensed from its authors.
- ``lipsync`` + ``engine="musetalk"``: MuseTalk 1.5 (opt-in, out-of-process,
  see ``_musetalk.py``) regenerates the lower face at 256 px; sharper than
  Wav2Lip but ~40x slower than real time on CPU.
- ``still``: no model; the portrait breathes/sways/nods with the voice.  Use
  this when the lip-sync licence is a problem or the weights are absent.

Output is a 512x512 avatar clip composited as a round picture-in-picture: lower
right/left on 16:9, in the free band under the stage on 9:16.  With
``AvatarSpec.layout="host"`` the clip is rendered at presenter-panel size
instead (16:9: ~40% column, 9:16: upper half) and the card stage is placed
beside/below it (:func:`composite_host`).  Every run measures how strongly
mouth motion follows voice loudness (``lipsync_corr``); host outputs are also
re-measured from the delivered MP4 (:func:`measure_host_face`,
:func:`video_mouth_corr`).
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
    HOST_ZOOM,
    SR,
    avatar_square,
    decode_yoloface,
    decode_yoloface_landmarks,
    frame_rms,
    host_crop,
    idle_motion,
    lagged_correlation,
    letterbox,
    mel_chunks,
    melspectrogram,
    mouth_mask,
    musetalk_face_box,
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
    size: tuple[int, int]
    face_in_clip: tuple[int, int, int, int]
    lipsync_corr: float | None
    lipsync_lag_frames: int
    mouth_energy_mean: float
    seconds: float
    engine: str = "wav2lip"
    engine_info: dict[str, Any] | None = None


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


def _detect_face(img: Image.Image, *, sess: Any = None, required: bool = True) -> tuple[float, float, float, float, float] | None:
    sess = sess or _session("yoloface_8n.onnx")
    w, h = img.size
    s, px, py = letterbox(w=w, h=h)
    canvas = Image.new("RGB", (640, 640), (0, 0, 0))
    canvas.paste(img.resize((round(w * s), round(h * s)), Image.BILINEAR), (px, py))
    x = (np.asarray(canvas, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
    out = sess.run(None, {"input": x})[0]
    face = decode_yoloface(output=out, scale=s, pad_x=px, pad_y=py)
    if face is None and required:
        raise MediaError("no face found in avatar portrait")
    return face


def _detect_landmarks(img: Image.Image) -> list[tuple[float, float]]:
    sess = _session("yoloface_8n.onnx")
    w, h = img.size
    s, px, py = letterbox(w=w, h=h)
    canvas = Image.new("RGB", (640, 640), (0, 0, 0))
    canvas.paste(img.resize((round(w * s), round(h * s)), Image.BILINEAR), (px, py))
    x = (np.asarray(canvas, dtype=np.float32) / 255.0).transpose(2, 0, 1)[None]
    lm = decode_yoloface_landmarks(output=sess.run(None, {"input": x})[0], scale=s, pad_x=px, pad_y=py)
    if lm is None:
        raise MediaError("no face landmarks found in avatar portrait")
    return lm


def build_avatar_clip(
    *,
    spec: AvatarSpec,
    voice_wav: Path,
    duration_s: float,
    work: Path,
    size: tuple[int, int] = (SIDE, SIDE),
    face_share: float | None = None,
    name: str = "avatar.mp4",
) -> AvatarResult:
    """Render the presenter clip.  Default = 512 square PiP crop (unchanged);
    with ``face_share`` the crop is ``size``-shaped around the face (host panel)."""
    import time

    t0 = time.monotonic()
    portrait = Path(spec.image) if spec.image else DEFAULT_PORTRAIT
    img = Image.open(portrait).convert("RGB")
    W, H = img.size
    x1, y1, x2, y2, score = _detect_face(img)  # type: ignore[misc]
    OW, OH = size
    if face_share is None:
        sx, sy, side = avatar_square(face=(x1, y1, x2, y2), w=W, h=H)
        cw = ch = side
    else:
        sx, sy, cw, ch = host_crop(face=(x1, y1, x2, y2), w=W, h=H, aspect=OW / OH, face_share=face_share)
    base = img.crop((sx, sy, sx + cw, sy + ch)).resize((OW, OH), Image.LANCZOS)
    kx, ky = OW / cw, OH / ch
    # face box inside the clip (Wav2Lip pads the chin by ~10px)
    fx1, fy1 = (x1 - sx) * kx, (y1 - sy) * ky
    fx2, fy2 = (x2 - sx) * kx, min(OH, (y2 - sy) * ky + 10 * ky)
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
    use_mt = spec.mode == "lipsync" and getattr(spec, "engine", "wav2lip") == "musetalk"
    mt_patches: np.ndarray | None = None
    mt_info: dict[str, Any] | None = None
    if use_mt:
        from hevi.layer4_legacy.talkcraft.omodul_impl._musetalk import render_patches

        lm = _detect_landmarks(img)
        mbox = musetalk_face_box(face=(x1, y1, x2, y2), nose_y=lm[2][1], w=W, h=H)
        wav16 = work / f"{Path(name).stem}_16k.wav"
        sf_ = np.clip(wav, -1, 1)
        import wave

        with wave.open(str(wav16), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes((sf_ * 32767).astype("<i2").tobytes())
        mt_patches, pbox, mt_info = render_patches(portrait=portrait, box=mbox, wav16k=wav16, fps=FPS, frames=n, work=work)
        mt_info["face_box"] = list(mbox)
        src_np = np.asarray(img, dtype=np.uint8)
    elif spec.mode == "lipsync":
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

    clip = work / name
    enc = subprocess.Popen(
        [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(clip)],
        stdin=subprocess.PIPE,
    )
    assert enc.stdin is not None
    mouth_energy = np.zeros(n, dtype=np.float32)
    ref_face_px = base_np[fb[1] : fb[3], fb[0] : fb[2]]
    for i in range(n):
        frame = base_np.copy()
        if mt_patches is not None:
            full = src_np.copy()
            full[pbox[1] : pbox[3], pbox[0] : pbox[2]] = mt_patches[i]
            frame = np.asarray(
                Image.fromarray(full).crop((sx, sy, sx + cw, sy + ch)).resize((OW, OH), Image.LANCZOS), dtype=np.float32
            )
            lower = slice(fb[1] + fh // 2, fb[3])
            mouth_energy[i] = float(np.mean(np.abs(frame[lower, fb[0] : fb[2]] - base_np[lower, fb[0] : fb[2]])))
        elif preds is not None:
            gen = np.asarray(
                Image.fromarray(np.clip(preds[i] * 255, 0, 255).astype(np.uint8)).resize((fw, fh), Image.BICUBIC),
                dtype=np.float32,
            )
            blended = ref_face_px * (1 - mask) + gen * mask
            frame[fb[1] : fb[3], fb[0] : fb[2]] = blended
            lower = slice(fh // 2, fh)
            mouth_energy[i] = float(np.mean(np.abs(blended[lower] - ref_face_px[lower])))
        scale, dx, dy = idle_motion(i=i, fps=FPS, rms=float(rms[i]))
        if face_share is not None:
            scale *= HOST_ZOOM
        im = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8))
        # inverse affine about the centre: zoom + translate
        cx_, cy_ = OW / 2, OH / 2
        a_ = 1 / scale
        im = im.transform((OW, OH), Image.AFFINE, (a_, 0, cx_ - a_ * (cx_ + dx), 0, a_, cy_ - a_ * (cy_ + dy)), resample=Image.BILINEAR)
        enc.stdin.write(im.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise MediaError("avatar encode failed")
    lipsynced = preds is not None or mt_patches is not None
    corr, lag = lagged_correlation(mouth_energy, rms) if lipsynced else (None, 0)
    np.savez_compressed(work / (Path(name).stem + "_metrics.npz"), mouth_energy=mouth_energy, rms=rms)
    return AvatarResult(
        clip=clip, mode=spec.mode, portrait=str(portrait), face_box=(x1, y1, x2, y2), face_score=score,
        frames=n, size=(OW, OH), face_in_clip=fb,  # type: ignore[arg-type]
        lipsync_corr=corr, lipsync_lag_frames=lag,
        mouth_energy_mean=round(float(mouth_energy.mean()), 3), seconds=round(time.monotonic() - t0, 1),
        engine=("musetalk" if use_mt else "wav2lip") if spec.mode == "lipsync" else "none", engine_info=mt_info,
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


# ---------------- host (presenter) layout ----------------
HOST_STYLES: dict[str, dict[str, Any]] = {
    # dark studio: navy backdrop, thin blue divider on the host edge
    "studio": {"bg": "0x0f1724", "accent": "0x3b82f6", "accent_px": 6, "frame": None},
    # brand: warm cream backdrop, thick orange band + framed stage
    "brand": {"bg": "0xf3ece0", "accent": "0xe4572e", "accent_px": 14, "frame": "0x1f2937"},
}


def composite_host(
    *, video: Path, avatar: Path, out: Path, layout: dict[str, tuple[int, int, int, int]],
    frame: tuple[int, int], style: str, side: str, portrait: bool,
) -> dict[str, Any]:
    """Presenter panel + card stage on a styled backdrop (16:9 or 9:16)."""
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import probe

    st = HOST_STYLES[style]
    W, H = frame
    hx, hy, hw, hh = layout["host"]
    sx, sy, sw, sh = layout["stage"]
    dur = float(probe(video)["format"]["duration"])
    a, ap = st["accent"], st["accent_px"]
    if portrait:
        accent = f"drawbox=x=0:y={hy + hh - ap // 2}:w={W}:h={ap}:color={a}:t=fill"
    else:
        ax = hx + hw - ap if side == "left" else hx
        accent = f"drawbox=x={ax}:y=0:w={ap}:h={H}:color={a}:t=fill"
    frame_box = ""
    if st["frame"]:
        b = 6
        frame_box = f",drawbox=x={sx - b}:y={sy - b}:w={sw + 2 * b}:h={sh + 2 * b}:color={st['frame']}:t={b}"
    fc = (
        f"color=c={st['bg']}:s={W}x{H}:r={FPS}:d={dur:.3f}[bg];"
        f"[0:v]scale={sw}:{sh}:flags=lanczos,setsar=1[st];"
        f"[1:v]scale={hw}:{hh},setsar=1[hv];"
        f"[bg][st]overlay={sx}:{sy}[a];[a][hv]overlay={hx}:{hy}:shortest=1,{accent}{frame_box}[v]"
    )
    run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-i", str(avatar), "-filter_complex", fc,
         "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-c:a", "copy", "-t", f"{dur:.3f}", str(out)])
    return {"layout": "host", "style": style, "side": side, "host": list(layout["host"]), "stage": list(layout["stage"])}


def _grab_frame(path: Path, t: float) -> Image.Image | None:
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    if raw.returncode or not raw.stdout:
        return None
    import io

    return Image.open(io.BytesIO(raw.stdout)).convert("RGB")


def measure_host_face(*, path: Path, host: tuple[int, int, int, int], samples: int = 12) -> dict[str, Any]:
    """Re-detect the presenter face on frames of the delivered MP4 (yoloface, CPU).

    A sample counts only if a face (score >= 0.5) is found whose centre lies in
    the host panel.  ``face_height_share`` = median face height / min(frame w, h).
    """
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import probe

    info = probe(path)
    dur = float(info["format"]["duration"])
    sess = _session("yoloface_8n.onnx")
    hx, hy, hw, hh = host
    hits, heights, boxes = 0, [], []
    short = None
    for k in range(samples):
        t = dur * (k + 0.5) / samples
        im = _grab_frame(path, t)
        if im is None:
            continue
        short = min(im.size)
        f = _detect_face(im, sess=sess, required=False)
        ok = False
        if f is not None:
            cx, cy = (f[0] + f[2]) / 2, (f[1] + f[3]) / 2
            ok = hx <= cx <= hx + hw and hy <= cy <= hy + hh
        if ok:
            hits += 1
            heights.append(f[3] - f[1])  # type: ignore[index]
            boxes.append([round(v, 1) for v in f])  # type: ignore[union-attr]
    share = float(np.median(heights)) / short if heights and short else 0.0
    return {"samples": samples, "detected": hits, "detect_rate": round(hits / samples, 3),
            "face_height_share": round(share, 3), "boxes": boxes}


def video_mouth_corr(*, path: Path, box: tuple[int, int, int, int], max_lag: int = 6) -> dict[str, Any]:
    """Lip-sync re-measured from the delivered MP4: darkness of the inner mouth
    crop (an open mouth shows the dark cavity) vs. the MP4's own audio RMS,
    best lagged Pearson r.  ``max_lag`` 6 frames (0.2 s): Wav2Lip's mel window
    starts at the frame time, so mouth shapes lead loudness by ~3-4 frames."""
    x, y, w, h = (int(v) // 2 * 2 for v in box)
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf", f"fps={FPS},crop={w}:{h}:{x}:{y},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w).astype(np.float32)
    inner = frames[:, h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    darkness = -inner.mean(axis=(1, 2))
    wav = _load_wav16k(path)
    rms = frame_rms(wav=wav, fps=FPS, n_frames=len(frames))
    r, lag = lagged_correlation(darkness, rms, max_lag=max_lag)
    return {"corr": r, "lag_frames": lag, "frames": len(frames), "box": [x, y, w, h], "metric": "inner-mouth darkness"}
