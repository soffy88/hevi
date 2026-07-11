"""StylePack 创建入口:参考视频/图片 → VLM 拆解 → 草稿(HEVI 路线图 Phase3 #38)。

给没有自己视觉语言的新用户一个"我要这种感觉"的入口,不必先理解 20 个内置预设
分类体系。这里只产出**草稿**(style/lighting/camera/color_grade 短语),不直接
落库建 StylePack——用户在前端确认/编辑后再调 StylePackService.create_pack。

参考素材是视频时先抽一帧代表画面(复用 hevi.verdict.frame_extract 的既有实现),
再走跟图片一样的 VLM 拆解流程。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi"}

_STYLE_DRAFT_PROMPT = """分析这张参考图片的视觉风格,用简短的英文短语描述以下四个
维度(每项一两个短语,不要写完整句子,风格同"cinematic, filmic"这类):

- style: 整体视觉风格/氛围
- lighting: 光线特点
- camera: 构图/运镜感(静态图片也可以合理推测拍摄手法)
- color_grade: 色彩/调色特点

只输出 JSON:{"style": "...", "lighting": "...", "camera": "...", "color_grade": "..."}"""


class StyleDraftError(Exception):
    """StylePack 草稿拆解失败。"""


async def draft_style_from_reference(reference_path: Path | str, *, vlm: Any) -> dict[str, str]:
    """参考图/视频 → {style, lighting, camera, color_grade} 草稿(供用户确认后
    再调 StylePackService.create_pack,不直接落库)。

    vlm 不可用/调用失败/解析失败 → 抛 StyleDraftError(这是用户主动触发的一次性
    操作,不是后台 best-effort 流程,失败该让调用方知道并重试,而不是静默返回
    空/占位内容误导用户"生成好了但其实什么都没测出来")。
    """
    p = Path(reference_path)
    if not p.exists():
        raise StyleDraftError(f"reference file not found: {p}")

    image_path = p
    if p.suffix.lower() in _VIDEO_SUFFIXES:
        import tempfile

        from hevi.verdict.frame_extract import FrameExtractError, extract_representative_frame

        with tempfile.TemporaryDirectory(prefix="style_draft_") as td:
            try:
                image_path = extract_representative_frame(p, Path(td) / "frame.png")
                return await _analyze_image(image_path, vlm=vlm)
            except FrameExtractError as e:
                raise StyleDraftError(f"failed to extract frame from {p}: {e}") from e

    return await _analyze_image(image_path, vlm=vlm)


async def _analyze_image(image_path: Path, *, vlm: Any) -> dict[str, str]:
    try:
        resp = await vlm(
            messages=[{"role": "user", "content": _STYLE_DRAFT_PROMPT}],
            image_paths=[str(image_path)],
            max_tokens=300,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            raise StyleDraftError(f"VLM response had no JSON: {content!r}")
        data = json.loads(m.group(0))
    except StyleDraftError:
        raise
    except Exception as e:
        raise StyleDraftError(f"style draft failed: {e}") from e

    return {k: str(data.get(k, "")).strip() for k in ("style", "lighting", "camera", "color_grade")}
