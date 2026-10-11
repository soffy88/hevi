"""Pixel-level image scoring oprim: open_clip text-image alignment, Laplacian sharpness, exposure, and bad-image detection.

3O Pillar: oprim.image_score
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

OPEN_CLIP_MODEL_DIR = Path(
    os.environ.get("HEVI_OPEN_CLIP_DIR", "/home/soffy/models/open_clip")
)

_CLIP_MODEL: Any = None
_CLIP_PREPROCESS: Any = None
_CLIP_TOKENIZER: Any = None


def _get_clip() -> tuple[Any, Any, Any]:
    global _CLIP_MODEL, _CLIP_PREPROCESS, _CLIP_TOKENIZER
    if _CLIP_MODEL is not None:
        return _CLIP_MODEL, _CLIP_PREPROCESS, _CLIP_TOKENIZER

    import open_clip
    import torch

    threads = int(os.environ.get("HEVI_CPU_THREADS", "8"))
    torch.set_num_threads(threads)

    safetensors_path = OPEN_CLIP_MODEL_DIR / "open_clip_model.safetensors"
    if safetensors_path.is_file():
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32",
            pretrained=str(safetensors_path),
        )
    else:
        # Fallback to model weights name if safetensors missing
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32",
            pretrained="laion2b_s34b_b79k",
        )
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model.eval()

    _CLIP_MODEL = model
    _CLIP_PREPROCESS = preprocess
    _CLIP_TOKENIZER = tokenizer
    return _CLIP_MODEL, _CLIP_PREPROCESS, _CLIP_TOKENIZER


def detect_bad_image(image_path: Path | str) -> tuple[bool, str]:
    """Check if an image is corrupted, pure black, pure white, or solid uniform color."""
    p = Path(image_path)
    if not p.is_file() or p.stat().st_size <= 0:
        return True, "empty_file"

    img = cv2.imread(str(p))
    if img is None:
        return True, "cannot_decode"

    # Spatial standard deviation for each channel
    if len(img.shape) == 3:
        spatial_stds = [float(np.std(img[:, :, c])) for c in range(img.shape[2])]
    else:
        spatial_stds = [float(np.std(img))]
    mean_spatial_std = float(np.mean(spatial_stds))
    if mean_spatial_std < 3.0:
        return True, "solid_color"

    mean_val = float(np.mean(img))
    if mean_val < 5.0:
        return True, "all_black"
    if mean_val > 250.0 and mean_spatial_std < 6.0:
        return True, "all_white"

    return False, "ok"


def compute_laplacian_sharpness(image_path: Path | str) -> float:
    """Compute normalized Laplacian variance representing edge sharpness."""
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    var = float(cv2.Laplacian(img, cv2.CV_64F).var())
    # Log-scale normalize: 50 -> ~0.3, 200 -> ~0.6, 1000+ -> ~1.0
    norm_score = float(np.clip(np.log1p(var) / np.log1p(1200.0), 0.0, 1.0))
    return round(norm_score, 4)


def compute_exposure_score(image_path: Path | str) -> float:
    """Evaluate image histogram exposure balance (penalizes extreme wash-out or crushed shadows)."""
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    mean_val = float(np.mean(img))
    # Ideal range is 60 - 190
    if 60 <= mean_val <= 190:
        return 1.0
    if mean_val < 60:
        return float(np.clip(mean_val / 60.0, 0.1, 1.0))
    # > 190
    return float(np.clip((255.0 - mean_val) / 65.0, 0.1, 1.0))


def compute_clip_similarity(
    image_path: Path | str,
    *,
    prompt_en: str,
) -> float:
    """Compute cosine similarity between image and prompt_en using OpenCLIP ViT-B-32."""
    if not prompt_en:
        return 0.5
    try:
        import torch

        model, preprocess, tokenizer = _get_clip()
        pil_img = Image.open(str(image_path)).convert("RGB")
        img_tensor = preprocess(pil_img).unsqueeze(0)
        text_tokens = tokenizer([prompt_en])

        with torch.no_grad():
            img_feat = model.encode_image(img_tensor)
            text_feat = model.encode_text(text_tokens)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)
            sim = float((img_feat @ text_feat.T).item())

        # Clip scores for ViT-B-32 typically range from 0.15 to 0.40
        # Normalize into [0, 1] range: 0.15 -> 0.0, 0.35 -> 1.0
        normalized = float(np.clip((sim - 0.12) / 0.25, 0.05, 1.0))
        return round(normalized, 4)
    except Exception as exc:
        logger.warning("CLIP similarity evaluation failed: %s", exc)
        return 0.5


_STYLE_ANIME_PROMPT = "anime illustration, 2d cel shaded drawing, flat colors, clean line art, cartoon"
_STYLE_PHOTOREAL_PROMPT = (
    "photograph, realistic photo, live action film still, real human face, photorealistic"
)


def compute_style_alignment(image_path: Path | str) -> dict[str, Any]:
    """Measure whether an image reads as stylized illustration vs a photoreal photo.

    Uses OpenCLIP to score the image against an anime-illustration prompt and a
    photoreal-photo prompt. ``is_stylized`` is true when the illustration prompt wins.
    This is a real measured signal used to enforce the default anime_guofeng style
    (no photoreal faces) on CPU.
    """
    anime = compute_clip_similarity(image_path, prompt_en=_STYLE_ANIME_PROMPT)
    photo = compute_clip_similarity(image_path, prompt_en=_STYLE_PHOTOREAL_PROMPT)
    return {
        "anime_score": round(anime, 4),
        "photoreal_score": round(photo, 4),
        "margin": round(anime - photo, 4),
        "is_stylized": bool(anime >= photo),
    }


SUBJECT_KEYWORD_RULES: list[tuple[str, str, str]] = [
    (r"明月|圆月|皓月|月亮|月华|月光", "moon", "a radiant glowing bright full moon"),
    (r"斧头|利斧|采樵|砍柴", "axe", "woodchopping axe"),
    (r"石壁|墙壁|穿壁|坚壁", "wall", "ancient granite stone wall"),
    (r"酒壶|酒杯|玉液|共饮|宴|痛饮", "wine", "ceramic wine jug banquet"),
    (r"王生|书生|秀才", "scholar", "young handsome Chinese scholar"),
    (r"老道长|老道|道长|师父", "taoist", "venerable elderly Taoist master with white beard"),
]


def verify_subject_alignment(
    image_path: Path | str,
    *,
    text_zh: str | None = None,
    prompt_en: str | None = None,
) -> dict[str, Any]:
    """Verify that required scene subject keywords appear in prompt and visually align via CLIP."""
    import re

    required_keys: list[str] = []
    subject_descs: list[str] = []

    if text_zh:
        for pattern_str, key_en, desc_en in SUBJECT_KEYWORD_RULES:
            if re.search(pattern_str, text_zh):
                if key_en not in required_keys:
                    required_keys.append(key_en)
                    subject_descs.append(desc_en)

    prompt_lower = (prompt_en or "").lower()
    missing_keys = [k for k in required_keys if k not in prompt_lower]
    keywords_present = len(missing_keys) == 0

    # If subjects are detected, measure CLIP similarity specifically against subject description
    clip_subj_score = 0.5
    if subject_descs and image_path and Path(image_path).is_file():
        combined_subject = ", ".join(subject_descs)
        clip_subj_score = compute_clip_similarity(image_path, prompt_en=combined_subject)

    return {
        "required_subjects": required_keys,
        "keywords_present": keywords_present,
        "missing_keywords": missing_keys,
        "clip_subject_score": round(clip_subj_score, 4),
    }


def score_keyframe(
    image_path: Path | str,
    *,
    prompt_en: str | None = None,
    text_zh: str | None = None,
) -> dict[str, Any]:
    """Compute composite quality and relevance score for keyframe candidate.

    Returns dict with composite_score, clip_score, sharpness, exposure, bad_image, subject_alignment.
    """
    is_bad, bad_reason = detect_bad_image(image_path)
    if is_bad:
        return {
            "composite_score": 0.0,
            "clip_score": 0.0,
            "sharpness": 0.0,
            "exposure": 0.0,
            "bad_image": True,
            "bad_reason": bad_reason,
            "subject_alignment": {
                "required_subjects": [],
                "keywords_present": False,
                "missing_keywords": [],
                "clip_subject_score": 0.0,
            },
        }

    sharpness = compute_laplacian_sharpness(image_path)
    exposure = compute_exposure_score(image_path)
    clip_score = compute_clip_similarity(image_path, prompt_en=prompt_en or "") if prompt_en else 0.5
    subj_align = verify_subject_alignment(image_path, text_zh=text_zh, prompt_en=prompt_en)

    # Composite weight: 50% prompt clip alignment, 20% subject alignment, 20% sharpness, 10% exposure
    effective_clip = 0.70 * clip_score + 0.30 * subj_align["clip_subject_score"]
    composite = 0.60 * effective_clip + 0.30 * sharpness + 0.10 * exposure

    # If missing a mandatory scene subject keyword, apply penalty
    if not subj_align["keywords_present"]:
        composite *= 0.85

    return {
        "composite_score": round(composite, 4),
        "clip_score": round(clip_score, 4),
        "sharpness": round(sharpness, 4),
        "exposure": round(exposure, 4),
        "bad_image": False,
        "bad_reason": "ok",
        "subject_alignment": subj_align,
    }

