"""图像超分辨率 —— Real-ESRGAN(4x) / ESRGAN(2x)。

本地 GPU 推理,不走云端。模型不存在时自动下载(~65MB)。
输入:任意图像(JPG/PNG)。输出:放大后 PNG。

用法:
    upscale(Path("shot.png"), Path("shot_4x.png"), scale=4)
    upscale(Path("shot.png"), Path("shot_2x.png"), scale=2, model="esrgan")
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_MODELS = {
    "realesrgan": {
        "repo": "xinntao/Real-ESRGAN",
        "weights": "weights/RealESRGAN_x4plus.pth",
        "scale": 4,
    },
    "esrgan": {
        "repo": "xinntao/ESRGAN",
        "weights": "weights/RRDB_ESRGAN_x4.pth",
        "scale": 4,
    },
}


def _ensure_model(model_name: str) -> Path:
    """确保模型权重存在,不存在则下载。返回权重路径。"""
    info = _MODELS[model_name]
    weights = Path(info["weights"])
    if weights.exists():
        return weights

    weights.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{info['repo']}/releases/download/v0.1.0/{weights.name}"
    logger.info("Downloading %s weights from %s", model_name, url)
    subprocess.run(
        ["curl", "-sL", "-o", str(weights), url],
        check=True, timeout=120,
    )
    return weights


def upscale(
    src: Path,
    dst: Path,
    *,
    scale: int = 4,
    model: str = "realesrgan",
    tile_size: int = 256,
) -> Path:
    """超分辨率放大图像。

    Args:
        src: 输入图像路径
        dst: 输出图像路径
        scale: 放大倍数(2 或 4)
        model: realesrgan / esrgan
        tile_size: 分块大小(VRAM 不够时调小)

    Returns:
        输出路径
    """
    if model not in _MODELS:
        raise ValueError(f"Unknown model: {model}. Choose from {list(_MODELS.keys())}")

    weights = _ensure_model(model)

    # 尝试 Python API,回退到 CLI
    try:
        return _upscale_python(src, dst, scale=scale, weights=weights, tile_size=tile_size)
    except ImportError:
        logger.info("Real-ESRGAN Python API not available, falling back to CLI")
        return _upscale_cli(src, dst, scale=scale, weights=weights, tile_size=tile_size)


def _upscale_python(
    src: Path, dst: Path, *, scale: int, weights: Path, tile_size: int
) -> Path:
    """用 Real-ESRGAN Python API 推理。"""
    import cv2
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Cannot read image: {src}")

    model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
    upsampler = RealESRGANer(
        scale=4, model_path=str(weights), model=model,
        tile=tile_size, tile_pad=10, pre_pad=0, half=True,
    )

    output, _ = upsampler.enhance(img, outscale=scale)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dst), output)
    return dst


def _upscale_cli(
    src: Path, dst: Path, *, scale: int, weights: Path, tile_size: int
) -> Path:
    """用 Real-ESRGAN CLI 推理(回退)。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "realesrgan-ncnn-vulkan",
        "-i", str(src),
        "-o", str(dst),
        "-s", str(scale),
        "-n", weights.stem.replace("_plus", ""),
        "-t", str(tile_size),
    ]
    if not shutil.which("realesrgan-ncnn-vulkan"):
        raise RuntimeError(
            "realesrgan-ncnn-vulkan not found. Install: pip install realesrgan "
            "or download binary from https://github.com/xinntao/Real-ESRGAN/releases"
        )
    subprocess.run(cmd, check=True, timeout=300)
    return dst
