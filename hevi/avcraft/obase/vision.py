"""画面/音频逐窗信号（CPU、无新模型）：音量能量、帧差运动量+运动质心、人脸框。

人脸检测只用本机已有文件：YuNet onnx（env HEVI_YUNET_MODEL → /data/soffy/models/opencv →
hevi/motion_fx/models）→ OpenCV 自带 Haar（若 cv2.data 有）→ 都没有则 faces 为空（下游回退运动/中心）。
不下载任何权重。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hevi.avcraft.obase.media import ffmpeg_bin, probe_duration

_YUNET_CANDIDATES = (
    "/data/soffy/models/opencv/face_detection_yunet_2023mar.onnx",
    str(Path(__file__).resolve().parents[2] / "motion_fx/models/face_detection_yunet_2023mar.onnx"),
)


def audio_energy(path: str | Path, *, hop: float = 0.5, sr: int = 16000) -> list[tuple[float, float]]:
    """每 hop 秒一个 RMS dBFS：[(t_center, db)]。ffmpeg 解码到 s16le 单声道管道，numpy 计算。"""
    import numpy as np

    p = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                        "-f", "s16le", "-"], capture_output=True)
    a = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = max(1, int(sr * hop))
    out = []
    for i in range(0, len(a) - n // 2, n):
        seg = a[i:i + n]
        rms = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0
        out.append((round((i + len(seg) / 2) / sr, 3), round(20 * np.log10(max(rms, 1e-5)), 2)))
    return out


def _face_detector(model: str | None):
    import cv2

    for m in [model, os.environ.get("HEVI_YUNET_MODEL"), *_YUNET_CANDIDATES]:
        if m and Path(m).is_file() and hasattr(cv2, "FaceDetectorYN"):
            try:
                det = cv2.FaceDetectorYN.create(m, "", (320, 320), 0.6, 0.3, 50)
            except Exception:
                continue

            def run(img, det=det):
                det.setInputSize((img.shape[1], img.shape[0]))
                _, f = det.detect(img)
                return [] if f is None else [(float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[14]))
                                             for r in f]
            return "yunet", run
    haar = Path(getattr(getattr(cv2, "data", None), "haarcascades", "") or "") / "haarcascade_frontalface_default.xml"
    if haar.is_file():
        cc = cv2.CascadeClassifier(str(haar))

        def run(img, cc=cc):
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return [(float(x), float(y), float(w), float(h), 0.8)
                    for x, y, w, h in cc.detectMultiScale(g, 1.1, 5, minSize=(24, 24))]
        return "haar", run
    return "none", None


def analyze_frames(
    path: str | Path,
    *,
    sample_fps: float = 4.0,
    scale_w: int = 480,
    faces: bool = True,
    face_model: str | None = None,
) -> dict:
    """按 sample_fps 抽帧：运动能量（相邻采样帧灰度差均值 0..1）、运动质心（归一化 x,y）、人脸框（源像素）。

    返回 {"w","h","fps","duration","detector","samples":[{"t","motion","mx","my","faces":[(x,y,w,h,score,mouth_act)]}]}
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    dur = probe_duration(path)
    s = scale_w / W if scale_w < W else 1.0
    name, det = _face_detector(face_model) if faces else ("off", None)
    step = max(1, round(fps / sample_fps))
    prev, samples, i = None, [], 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, fr = cap.retrieve()
            if not ok:
                break
            sm = cv2.resize(fr, (int(W * s), int(H * s))) if s != 1.0 else fr
            g = cv2.GaussianBlur(cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY), (5, 5), 0)
            rec = {"t": round(i / fps, 3), "motion": 0.0, "mx": 0.5, "my": 0.5, "faces": []}
            if prev is not None:
                d = cv2.absdiff(g, prev).astype(np.float32)
                rec["motion"] = round(float(d.mean()) / 255.0, 4)
                m = d * (d > 18)
                tot = float(m.sum())
                if tot > 0:
                    ys, xs = np.indices(m.shape)
                    rec["mx"] = round(float((m * xs).sum() / tot) / m.shape[1], 4)
                    rec["my"] = round(float((m * ys).sum() / tot) / m.shape[0], 4)
            if det is not None:
                fs = []
                for x, y, w, h, sc in det(sm):
                    act = 0.0  # 嘴部活动：脸框下半部帧差均值（无模型的“谁在说话”近似）
                    if prev is not None:
                        y1, y2 = int(y + h * 0.55), int(y + h * 1.05)
                        x1, x2 = int(x + w * 0.2), int(x + w * 0.8)
                        y1, x1 = max(0, y1), max(0, x1)
                        if y2 > y1 and x2 > x1:
                            act = float(cv2.absdiff(g[y1:y2, x1:x2], prev[y1:y2, x1:x2]).mean()) / 255.0
                    fs.append((round(x / s, 1), round(y / s, 1), round(w / s, 1), round(h / s, 1), round(sc, 3),
                               round(act, 4)))
                rec["faces"] = fs
            prev = g
            samples.append(rec)
        i += 1
    cap.release()
    return {"w": W, "h": H, "fps": round(fps, 3), "duration": dur, "detector": name, "samples": samples}
