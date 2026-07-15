"""subject_embed — 身份/视觉向量原语(hevi 参考实现,待回迁 oprim.embedding)。

3O manifest §C1。给一张参考图/帧算 L2-归一化视觉向量(CLIP ViT-B/32),用于:
  - L2:建 Subject 时离线算 identity_embedding(存 subjects.identity_embedding)。
  - L3:审片时算"当前帧 vs Subject 基准"(身份)/"vs StylePack 基准帧"(风格)距离。

后端选型:hevi 的 subject 多为**风格化/AI 生成角色**(非真人脸),CLIP 通用视觉向量比
人脸 ArcFace 更贴域(ArcFace 是真人脸几何训练出来的,对插画/二次元风格角色经常检测
失败或区分度很差)——HEVI 路线图 Phase2 #34 明确评估过 ArcFace/InsightFace,决定
**不引入**,继续用 CLIP,理由同上。CPU 运行,避免与 stratum/wan/vibevoice 抢 3080。

多区域(#34):`kind="face"` 现在会先按几何比例裁剪出"人像框常见的脸部区域"(图片
上半部、居中)再算 CLIP 向量,`kind="style"`/其余取值仍是全图向量。这是**纯几何
裁剪启发式,不是真的人脸检测**——不保证裁到的区域里真的有脸(背影/侧身镜头裁出来
的可能是头发或背景),所以下游(scorecard.py)拿两个区域的向量都算一遍距离、取
更像的那个,而不是假装能可靠判断"这帧到底有没有露脸"。
"""

from __future__ import annotations

import logging
import math
import os
import threading
from pathlib import Path
from typing import Any

# 人像框裁剪启发式(#34):正面半身/证件照式参考图里,脸部通常在上半部、水平居中。
# 高度比例更大(0.55)是因为常见参考图是"半身像"而非纯头像特写,裁太窄容易连下巴
# 都切掉;宽度收窄到中间 70% 避免裁进两侧背景。
_FACE_CROP_TOP_RATIO = 0.55
_FACE_CROP_WIDTH_RATIO = 0.7

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
            logger.info("subject_embed: loading CLIP %s (CPU, local_files_only)", _CLIP_MODEL_ID)
            # 只读本地缓存,绝不联网——2026-07-12 真实撞见:曾经"本地未命中就回退联网
            # 下载"的分支,在没有 huggingface.co 出口的容器里会卡在 huggingface_hub
            # 自己的重试退避里(每个文件 5 次重试、总计 20+ 秒),而且**这发生在
            # asyncio.to_thread 起的后台线程里,上层的超时只会让调用方不再等,并不能
            # 杀掉这个线程**——线程会一直重试到 huggingface_hub 自己放弃为止(可能是
            # 几分钟),期间占着进程默认线程池的一个 worker 槽位不放。角色一多、
            # 反复重试几次,线程池被这些"值不了班但也下不了班"的僵尸线程占满,连
            # dispatch_season 这种完全不碰 CLIP 的后续步骤都会因为拿不到线程池 worker
            # 陪着一起卡住(2026-07-12 真实撞见:客户卡在"派发剧集..."半小时,这才是
            # 真正 root cause,不是 20s 超时不够长)。身份向量本来就是"增强,非必需"
            # (见模块顶部注释),本地没缓存就该直接放弃,不该临时现下载一个 600MB 模型。
            try:
                _model = CLIPModel.from_pretrained(_CLIP_MODEL_ID, local_files_only=True).eval()
                _processor = CLIPProcessor.from_pretrained(_CLIP_MODEL_ID, local_files_only=True)
            except Exception as e:
                raise SubjectEmbedError(
                    f"CLIP 模型本地缓存未命中且不联网下载(见本函数注释): {e}"
                ) from e
    return _model, _processor


def _crop_face_region(img: Any) -> Any:
    """几何裁剪启发式(#34):图片上半部、水平居中 —— 见模块顶部常量注释。"""
    w, h = img.size
    top = 0
    bottom = int(h * _FACE_CROP_TOP_RATIO)
    side_margin = int(w * (1 - _FACE_CROP_WIDTH_RATIO) / 2)
    return img.crop((side_margin, top, w - side_margin, bottom))


def _embed_image(img: Any, model: Any, processor: Any) -> list[float]:
    import torch

    with torch.no_grad():
        feats = model.get_image_features(**processor(images=img, return_tensors="pt"))
    v = feats[0]
    norm = v.norm()
    if float(norm) == 0.0:
        raise SubjectEmbedError("zero-norm embedding")
    return (v / norm).tolist()


def subject_embed(
    *, image_path: Path | str, kind: str = "face", config: dict[str, Any] | None = None
) -> list[float]:
    """一张图 → L2-归一化视觉向量(list[float],CLIP ViT-B/32 = 512 维)。

    kind="face":先按几何裁剪启发式取上半部/居中区域再算 CLIP 向量(#34,多区域
    embedding 的"脸部"信号)。kind="style" 或其它取值:全图向量,不裁剪。
    抛 SubjectEmbedError:图不存在/不可读/模型不可用。
    """
    p = Path(image_path)
    if not p.exists():
        raise SubjectEmbedError(f"image not found: {p}")
    try:
        from PIL import Image
    except ImportError as e:  # pragma: no cover
        raise SubjectEmbedError(f"subject_embed 需要 Pillow+torch: {e}") from e

    model, processor = _ensure_model()
    try:
        img = Image.open(p).convert("RGB")
        if kind == "face":
            img = _crop_face_region(img)
        return _embed_image(img, model, processor)
    except SubjectEmbedError:
        raise
    except Exception as e:
        raise SubjectEmbedError(f"embed failed for {p}: {e}") from e


def text_embed(text: str) -> list[float]:
    """一段文字 → L2-归一化 CLIP 文本向量(与 subject_embed 同一 512 维空间,可直接
    与图像向量算余弦相似度 —— tongjian L6 G6 门的 CLIP 相似度检查(生成帧 vs
    visual_prompt)用这个,不需要额外模型)。
    """
    if not text:
        raise SubjectEmbedError("text must not be empty")
    try:
        import torch
    except ImportError as e:  # pragma: no cover
        raise SubjectEmbedError(f"text_embed 需要 torch: {e}") from e

    model, processor = _ensure_model()
    try:
        with torch.no_grad():
            inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True)
            feats = model.get_text_features(**inputs)
        v = feats[0]
        norm = v.norm()
        if float(norm) == 0.0:
            raise SubjectEmbedError("zero-norm embedding")
        return (v / norm).tolist()
    except SubjectEmbedError:
        raise
    except Exception as e:
        raise SubjectEmbedError(f"text embed failed for {text!r}: {e}") from e


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
