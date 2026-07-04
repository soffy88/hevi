"""subject_embed — 身份/视觉向量原语(hevi 参考实现,待回迁 oprim.embedding)。

3O manifest §C1。给一张参考图/帧算 L2-归一化视觉向量(CLIP ViT-B/32),用于:
  - L2:建 Subject 时离线算 identity_embedding(存 subjects.identity_embedding)。
  - L3:审片时算"当前帧 vs Subject 基准"(身份)/"vs StylePack 基准帧"(风格)距离。

后端选型:hevi 的 subject 多为**风格化/AI 生成角色**(非真人脸),CLIP 通用视觉向量比
人脸 ArcFace 更贴域,且 transformers+torch 已在 .venv、无新重依赖、CPU 可跑(不抢 GPU)。
`kind` 现记录用途但 face/style 同用 CLIP 全图向量;后续可为 kind="face" 接 insightface
+ 人脸裁剪。CPU 运行,避免与 stratum/wan/vibevoice 抢 3080。
"""

from __future__ import annotations

import logging
import math
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CLIP_MODEL_ID = os.getenv("SUBJECT_EMBED_MODEL", "openai/clip-vit-base-patch32")

_lock = threading.Lock()
_model: Any = None
_processor: Any = None


class SubjectEmbedError(Exception):
    """身份/视觉向量计算失败。"""


def _ensure_model() -> tuple[Any, Any]:
    """懒加载 CLIP(进程内单例,线程安全)。首次会下载/加载 ~600MB 权重。"""
    global _model, _processor
    if _model is not None and _processor is not None:
        return _model, _processor
    with _lock:
        if _model is None or _processor is None:
            try:
                import torch  # noqa: F401
                from transformers import CLIPModel, CLIPProcessor
            except ImportError as e:  # pragma: no cover - env guard
                raise SubjectEmbedError(f"subject_embed 需要 torch+transformers: {e}") from e
            logger.info("subject_embed: loading CLIP %s (CPU)", _CLIP_MODEL_ID)
            _model = CLIPModel.from_pretrained(_CLIP_MODEL_ID).eval()
            _processor = CLIPProcessor.from_pretrained(_CLIP_MODEL_ID)
    return _model, _processor


def subject_embed(
    *, image_path: Path | str, kind: str = "face", config: dict[str, Any] | None = None
) -> list[float]:
    """一张图 → L2-归一化视觉向量(list[float],CLIP ViT-B/32 = 512 维)。

    kind: "face"(身份)| "style"(风格)—— 现同用 CLIP 全图向量,语义留待后端分化。
    抛 SubjectEmbedError:图不存在/不可读/模型不可用。
    """
    p = Path(image_path)
    if not p.exists():
        raise SubjectEmbedError(f"image not found: {p}")
    try:
        import torch
        from PIL import Image
    except ImportError as e:  # pragma: no cover
        raise SubjectEmbedError(f"subject_embed 需要 Pillow+torch: {e}") from e

    model, processor = _ensure_model()
    try:
        img = Image.open(p).convert("RGB")
        with torch.no_grad():
            feats = model.get_image_features(**processor(images=img, return_tensors="pt"))
        v = feats[0]
        norm = v.norm()
        if float(norm) == 0.0:
            raise SubjectEmbedError("zero-norm embedding")
        return (v / norm).tolist()
    except SubjectEmbedError:
        raise
    except Exception as e:
        raise SubjectEmbedError(f"embed failed for {p}: {e}") from e


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """两个(已归一化)向量的余弦相似度。维度不匹配/空 → 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def embedding_distance(a: list[float], b: list[float]) -> float:
    """余弦距离 = 1 - 余弦相似度(越小越像)。供 L3 审片身份/风格评分。"""
    return 1.0 - cosine_similarity(a, b)
