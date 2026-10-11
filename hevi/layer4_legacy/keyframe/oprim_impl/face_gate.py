"""OpenCV YuNet + SFace face consistency gate oprim.

3O Pillar: oprim.face_gate
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

YUNET_MODEL_PATH = Path(
    os.environ.get(
        "HEVI_YUNET_PATH",
        "/data/soffy/models/opencv/face_detection_yunet_2023mar.onnx",
    )
)
SFACE_MODEL_PATH = Path(
    os.environ.get(
        "HEVI_SFACE_PATH",
        "/data/soffy/models/opencv/face_recognition_sface_2021dec.onnx",
    )
)

_DETECTOR: Any = None
_RECOGNIZER: Any = None


def _get_models() -> tuple[Any, Any]:
    global _DETECTOR, _RECOGNIZER
    if _DETECTOR is not None and _RECOGNIZER is not None:
        return _DETECTOR, _RECOGNIZER

    if not YUNET_MODEL_PATH.is_file():
        raise FileNotFoundError(f"YuNet ONNX model not found: {YUNET_MODEL_PATH}")
    if not SFACE_MODEL_PATH.is_file():
        raise FileNotFoundError(f"SFace ONNX model not found: {SFACE_MODEL_PATH}")

    # Initialize with default 512x512 resolution (can be adjusted per image)
    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL_PATH),
        "",
        (512, 512),
        score_threshold=0.6,
        nms_threshold=0.3,
        top_k=5,
    )
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL_PATH), "")

    _DETECTOR = detector
    _RECOGNIZER = recognizer
    return _DETECTOR, _RECOGNIZER


def detect_faces(
    image_path: Path | str,
    *,
    score_threshold: float = 0.6,
) -> np.ndarray | None:
    """Detect faces using YuNet. Returns array of detected faces or None."""
    p = Path(image_path)
    if not p.is_file():
        return None

    img = cv2.imread(str(p))
    if img is None:
        return None

    h, w = img.shape[:2]
    detector, _ = _get_models()
    detector.setInputSize((w, h))
    detector.setScoreThreshold(score_threshold)

    _, faces = detector.detect(img)
    return faces


def extract_face_embedding(
    image_path: Path | str,
    *,
    face_idx: int = 0,
) -> np.ndarray | None:
    """Extract 128-dimensional L2-normalized SFace embedding from detected face."""
    p = Path(image_path)
    if not p.is_file():
        return None

    img = cv2.imread(str(p))
    if img is None:
        return None

    h, w = img.shape[:2]
    detector, recognizer = _get_models()
    detector.setInputSize((w, h))

    _, faces = detector.detect(img)
    if faces is None or len(faces) == 0:
        return None

    target_face = faces[min(face_idx, len(faces) - 1)]
    aligned_face = recognizer.alignCrop(img, target_face)
    feat = recognizer.feature(aligned_face)

    # Normalize embedding
    norm = np.linalg.norm(feat)
    if norm > 1e-6:
        feat = feat / norm
    return feat.flatten()


def compute_face_cosine(
    embedding_a: np.ndarray | list[float],
    *,
    embedding_b: np.ndarray | list[float],
) -> float:
    """Compute cosine similarity between two 128-d face embeddings."""
    arr_a = np.asarray(embedding_a, dtype=np.float32).flatten()
    arr_b = np.asarray(embedding_b, dtype=np.float32).flatten()

    norm_a = np.linalg.norm(arr_a)
    norm_b = np.linalg.norm(arr_b)
    if norm_a < 1e-6 or norm_b < 1e-6:
        return 0.0

    dot = float(np.dot(arr_a, arr_b) / (norm_a * norm_b))
    return round(dot, 4)


def verify_character_face(
    image_path: Path | str,
    *,
    ref_embedding: np.ndarray | list[float] | None,
    threshold: float = 0.35,
) -> tuple[bool, float, bool]:
    """Verify candidate keyframe face against reference portrait face embedding.

    Returns:
        (passed: bool, similarity: float, face_detected: bool)
    """
    if ref_embedding is None:
        # No reference face available; default pass
        return True, 1.0, False

    emb = extract_face_embedding(image_path)
    if emb is None:
        # Far shot, back view, or scenery without face; pass gate
        return True, 0.0, False

    sim = compute_face_cosine(emb, embedding_b=ref_embedding)
    passed = sim >= threshold
    return passed, sim, True
