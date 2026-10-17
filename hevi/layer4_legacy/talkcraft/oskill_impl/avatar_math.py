"""Digital-human avatar math (oskill layer: pure numpy, no model, no I/O).

Wav2Lip conditioning is reproduced exactly (16 kHz, n_fft 800, hop 200,
80 mels 55-7600 Hz, preemphasis 0.97, ref 20 dB, min -100 dB, symmetric
[-4, 4]); face detection decoding is the yoloface-8n (YOLOv8) layout.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

SR = 16000
N_FFT = 800
HOP = 200
N_MELS = 80
MEL_STEP = 16  # mel frames per Wav2Lip window
FACE = 96  # Wav2Lip face size


def _mel_basis() -> np.ndarray:
    import librosa  # pure DSP helper, no model

    return librosa.filters.mel(sr=SR, n_fft=N_FFT, n_mels=N_MELS, fmin=55, fmax=7600)


def melspectrogram(*, wav: np.ndarray) -> np.ndarray:
    import librosa

    pre = np.append(wav[0], wav[1:] - 0.97 * wav[:-1]).astype(np.float32)
    spec = np.abs(librosa.stft(y=pre, n_fft=N_FFT, hop_length=HOP, win_length=N_FFT))
    mel = _mel_basis() @ spec
    db = 20.0 * np.log10(np.maximum(1e-5, mel)) - 20.0
    return np.clip(8.0 * ((db + 100.0) / 100.0) - 4.0, -4.0, 4.0).astype(np.float32)


def mel_chunks(*, mel: np.ndarray, fps: float, n_frames: int) -> np.ndarray:
    """One (80, 16) window per video frame, as in Wav2Lip inference."""
    out = np.empty((n_frames, N_MELS, MEL_STEP), dtype=np.float32)
    T = mel.shape[1]
    for i in range(n_frames):
        start = int(N_MELS * i / fps)
        if start + MEL_STEP > T:
            start = max(0, T - MEL_STEP)
        chunk = mel[:, start : start + MEL_STEP]
        if chunk.shape[1] < MEL_STEP:
            chunk = np.pad(chunk, ((0, 0), (0, MEL_STEP - chunk.shape[1])), mode="edge")
        out[i] = chunk
    return out


def frame_rms(*, wav: np.ndarray, fps: float, n_frames: int) -> np.ndarray:
    hop = SR / fps
    out = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        a, b = int(i * hop), int((i + 1) * hop)
        seg = wav[a:b]
        out[i] = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0
    return out


def letterbox(*, w: int, h: int, size: int = 640) -> tuple[float, int, int]:
    """(scale, pad_x, pad_y) mapping an image into a size x size square."""
    s = min(size / w, size / h)
    return s, (size - round(w * s)) // 2, (size - round(h * s)) // 2


def decode_yoloface(
    *, output: np.ndarray, scale: float, pad_x: int, pad_y: int, min_score: float = 0.5
) -> tuple[float, float, float, float, float] | None:
    """Best face (x1, y1, x2, y2, score) in source pixels from a [1, 20, 8400] output."""
    pred = output[0]
    scores = pred[4]
    k = int(np.argmax(scores))
    if float(scores[k]) < min_score:
        return None
    cx, cy, bw, bh = (float(v) for v in pred[:4, k])
    x1 = (cx - bw / 2 - pad_x) / scale
    y1 = (cy - bh / 2 - pad_y) / scale
    x2 = (cx + bw / 2 - pad_x) / scale
    y2 = (cy + bh / 2 - pad_y) / scale
    return x1, y1, x2, y2, float(scores[k])


def decode_yoloface_landmarks(
    *, output: np.ndarray, scale: float, pad_x: int, pad_y: int, min_score: float = 0.5
) -> list[tuple[float, float]] | None:
    """5 landmarks (left eye, right eye, nose, left/right mouth corner) of the best
    face, in source pixels; rows 5..19 of the [1, 20, 8400] yoloface output."""
    pred = output[0]
    k = int(np.argmax(pred[4]))
    if float(pred[4][k]) < min_score or pred.shape[0] < 20:
        return None
    return [((float(pred[5 + 3 * i, k]) - pad_x) / scale, (float(pred[6 + 3 * i, k]) - pad_y) / scale) for i in range(5)]


def musetalk_face_box(*, face: Sequence[float], nose_y: float, w: int, h: int) -> tuple[int, int, int, int]:
    """Face crop MuseTalk was trained on: from the 68-point landmarks it keeps the
    jaw width and chin, and puts the top as far above the nose as the chin is
    below it (mouth sits at ~2/3 height).  Approximated from the yoloface box
    (width, chin) and its nose landmark.  A forehead-to-chin box instead leaves
    the mouth too high in the 256 crop and the model barely opens it."""
    x1, _, x2, y2 = face[:4]
    top = nose_y - (y2 - nose_y)
    return (max(0, round(x1)), max(0, round(top)), min(w, round(x2)), min(h, round(y2)))


def avatar_square(*, face: Sequence[float], w: int, h: int, factor: float = 1.7) -> tuple[int, int, int]:
    """Square crop (x, y, side) around the face, framed slightly below centre."""
    x1, y1, x2, y2 = face[:4]
    side = int(min(max(x2 - x1, y2 - y1) * factor, w, h))
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2 + 0.12 * side
    x = int(min(max(0, cx - side / 2), w - side))
    y = int(min(max(0, cy - side / 2), h - side))
    return x, y, side


def mouth_mask(*, w: int, h: int, top: float = 0.5, feather: float = 0.12) -> np.ndarray:
    """Soft mask over the lower part of the face box (1 = take generated pixels)."""
    ys = np.linspace(0, 1, h)[:, None]
    xs = np.linspace(0, 1, w)[None, :]
    vert = np.clip((ys - top) / feather, 0, 1)
    side = np.clip(np.minimum(xs, 1 - xs) / feather, 0, 1)
    bottom = np.clip((1 - ys) / (feather / 2), 0, 1)
    return (vert * side * bottom).astype(np.float32)


def idle_motion(*, i: int, fps: float, rms: float) -> tuple[float, float, float]:
    """(scale, dx, dy) for a living presenter: slow breathing, sway, tiny nod on stress."""
    t = i / fps
    scale = 1.0 + 0.012 * math.sin(2 * math.pi * t / 4.3) + 0.01 * min(1.0, rms * 12)
    dx = 3.0 * math.sin(2 * math.pi * t / 6.1)
    dy = 2.5 * math.sin(2 * math.pi * t / 3.7) - 3.0 * min(1.0, rms * 12)
    return scale, dx, dy


def lagged_correlation(a: Sequence[float], b: Sequence[float], *, max_lag: int = 4, smooth: int = 3) -> tuple[float, int]:
    """Best Pearson r of a vs b over lags in [-max_lag, max_lag] after a box smooth.

    Mouth shapes lead/lag loudness by a few frames, so a zero-lag r underrates real sync.
    Returns (r, lag) with lag > 0 meaning ``a`` trails ``b``.
    """
    k = np.ones(smooth) / smooth
    x = np.convolve(np.asarray(a, dtype=np.float64), k, mode="same")
    y = np.convolve(np.asarray(b, dtype=np.float64), k, mode="same")
    best = (0.0, 0)
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            r = correlation(x[lag:], y[:-lag])
        elif lag < 0:
            r = correlation(x[:lag], y[-lag:])
        else:
            r = correlation(x, y)
        if r > best[0]:
            best = (r, lag)
    return round(best[0], 3), best[1]


def correlation(a: Sequence[float], b: Sequence[float]) -> float:
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def overlay_layout(*, frame_w: int, frame_h: int, position: str, portrait: bool) -> tuple[int, int, int]:
    """(x, y, diameter) of the round avatar.  Portrait uses the free band under the stage."""
    if portrait:
        stage_h = round(frame_w * 9 / 16)
        free_top = (frame_h + stage_h) // 2
        d = min(440, frame_h - free_top - 80)
        return (frame_w - d) // 2, free_top + (frame_h - free_top - d) // 2, d
    d = round(frame_h * 0.28)
    margin = round(frame_w * 0.03)
    x = frame_w - d - margin if position == "right" else margin
    y = frame_h - d - round(frame_h * 0.06)
    return x, y, d


# ---------------- host (presenter) layout ----------------
HOST_SHARE = 0.40  # 16:9: presenter column width / frame width
HOST_FACE_SHARE = {"landscape": 0.38, "portrait": 0.46}  # face height / host panel height
HOST_ZOOM = 1.03  # host clips are always slightly zoomed so idle sway never shows an edge


def _even(v: float) -> int:
    return int(v) // 2 * 2


def host_layout(*, frame_w: int, frame_h: int, portrait: bool, side: str = "left") -> dict[str, tuple[int, int, int, int]]:
    """Host + stage rectangles ``(x, y, w, h)`` for the presenter layout.

    16:9: presenter column of ~40% frame width on ``side``; the 16:9 card stage
    is fitted (with margin) into the other 60%, vertically centred.
    9:16: presenter fills the upper half; the full-width 16:9 stage is centred
    in the lower half.  All values are even (yuv420p-safe).
    """
    if portrait:
        hh = _even(frame_h / 2)
        host = (0, 0, frame_w, hh)
        sw = frame_w
        sh = _even(sw * 9 / 16)
        sy = _even(hh + (frame_h - hh - sh) / 2)
        return {"host": host, "stage": (0, sy, sw, sh)}
    hw = _even(frame_w * HOST_SHARE)
    margin = _even(frame_w * 0.016)
    area_w = frame_w - hw
    sw = _even(area_w - 2 * margin)
    sh = _even(sw * 9 / 16)
    if sh > frame_h - 2 * margin:
        sh = _even(frame_h - 2 * margin)
        sw = _even(sh * 16 / 9)
    sy = _even((frame_h - sh) / 2)
    if side == "right":
        host = (frame_w - hw, 0, hw, frame_h)
        sx = _even((area_w - sw) / 2)
    else:
        host = (0, 0, hw, frame_h)
        sx = _even(hw + (area_w - sw) / 2)
    return {"host": host, "stage": (sx, sy, sw, sh)}


def host_crop(*, face: Sequence[float], w: int, h: int, aspect: float, face_share: float) -> tuple[int, int, int, int]:
    """Crop ``(x, y, cw, ch)`` of aspect ``aspect`` (w/h) around ``face`` so the face
    is ~``face_share`` of the crop height, clamped to the image (face kept in the upper-middle)."""
    x1, y1, x2, y2 = face[:4]
    fh = max(1.0, y2 - y1)
    ch = fh / face_share
    cw = ch * aspect
    if cw > w:
        cw, ch = float(w), w / aspect
    if ch > h:
        ch, cw = float(h), h * aspect
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2 + 0.14 * ch
    x = min(max(0.0, cx - cw / 2), w - cw)
    y = min(max(0.0, cy - ch / 2), h - ch)
    return round(x), round(y), round(cw), round(ch)
