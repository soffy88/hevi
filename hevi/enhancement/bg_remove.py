"""背景移除 —— rembg(U2Net/ISNet)。

本地推理,不走云端。模型首次使用时自动下载。
输入:任意图像。输出:透明背景 PNG(带 alpha 通道)。

用法:
    remove_background(Path("character.jpg"), Path("character_nobg.png"))
    remove_background(Path("shot.png"), Path("shot_nobg.png"), model="isnet-general")
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MODELS = ["u2net", "u2netp", "u2net_human_seg", "isnet-general", "isnet-anime"]


def remove_background(
    src: Path,
    dst: Path,
    *,
    model: str = "u2net",
    alpha_matting: bool = False,
) -> Path:
    """移除图像背景,输出透明 PNG。

    Args:
        src: 输入图像路径
        dst: 输出图像路径(.png,带 alpha)
        model: u2net / u2netp / u2net_human_seg / isnet-general / isnet-anime
        alpha_matting: 启用 alpha matting(头发等细节更好,但更慢)

    Returns:
        输出路径
    """
    if model not in _MODELS:
        raise ValueError(f"Unknown model: {model}. Choose from {_MODELS}")

    try:
        return _remove_python(src, dst, model=model, alpha_matting=alpha_matting)
    except ImportError:
        return _remove_cli(src, dst, model=model)


def _remove_python(src: Path, dst: Path, *, model: str, alpha_matting: bool) -> Path:
    """用 rembg Python API。"""
    import io

    from PIL import Image
    from rembg import new_session, remove

    session = new_session(model)
    with open(src, "rb") as f:
        input_data = f.read()

    output_data = remove(
        input_data,
        session=session,
        alpha_matting=alpha_matting,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
    )

    dst.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(output_data))
    img.save(dst, "PNG")
    return dst


def _remove_cli(src: Path, dst: Path, *, model: str) -> Path:
    """回退到 rembg CLI。"""
    import subprocess

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["rembg", "i", "-m", model, str(src), str(dst)]
    subprocess.run(cmd, check=True, timeout=120)
    return dst
