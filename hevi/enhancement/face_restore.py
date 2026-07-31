"""人脸修复 —— CodeFormer / GFPGAN。

本地 GPU 推理。AI 生成人脸常见的模糊/变形/瑕疵,用修复模型后处理比重生成高效得多。
输入:含人脸的图像。输出:修复后图像(同分辨率)。

用法:
    restore_face(Path("blurry_face.png"), Path("restored_face.png"))
    restore_face(Path("shot.png"), Path("shot_fixed.png"), model="gfpgan", fidelity=0.7)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def restore_face(
    src: Path,
    dst: Path,
    *,
    model: str = "codeformer",
    fidelity: float = 0.7,
    upscale: int = 1,
) -> Path:
    """修复人脸图像。

    Args:
        src: 输入图像
        dst: 输出图像
        model: codeformer / gfpgan
        fidelity: 保真度 0-1(越高越接近原图,越低修复越强)
        upscale: 同时放大倍数(1=不放大)

    Returns:
        输出路径
    """
    if model == "codeformer":
        return _codeformer(src, dst, fidelity=fidelity, upscale=upscale)
    if model == "gfpgan":
        return _gfpgan(src, dst, upscale=upscale)
    raise ValueError(f"Unknown model: {model}. Choose codeformer or gfpgan.")


def _codeformer(src: Path, dst: Path, *, fidelity: float, upscale: int) -> Path:
    try:
        import importlib

        importlib.import_module("basicsr.utils")
        importlib.import_module("facelib.utils.face_restoration_helper")
        return _codeformer_python(src, dst, fidelity=fidelity, upscale=upscale)
    except (ImportError, ModuleNotFoundError):
        return _codeformer_cli(src, dst, fidelity=fidelity, upscale=upscale)


def _codeformer_python(src: Path, dst: Path, *, fidelity: float, upscale: int) -> Path:
    """CodeFormer Python API(需要 basicsr + facelib)。"""
    # 简化的 Python 推理路径,完整版需要 CodeFormer 仓库
    raise ImportError("CodeFormer Python API requires codeformer package")


def _codeformer_cli(src: Path, dst: Path, *, fidelity: float, upscale: int) -> Path:
    """CodeFormer CLI 推理。"""
    if not shutil.which("codeformer"):
        # 回退:用 inference_codeformer.py 脚本
        script = Path("CodeFormer/inference_codeformer.py")
        if not script.exists():
            msg = (
                "CodeFormer not found. Install: "
                "git clone https://github.com/sczhou/CodeFormer "
                "&& pip install -r requirements.txt"
            )
            raise RuntimeError(msg)
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                "python", str(script),
                "--input_path", str(src),
                "--output_path", tmpdir,
                "--fidelity_ratio", str(fidelity),
                "--upscale", str(upscale),
                "--bg_upsampler", "realesrgan",
            ]
            subprocess.run(cmd, check=True, timeout=300)
            # 找到输出文件
            outputs = list(Path(tmpdir).glob("*.png"))
            if outputs:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(outputs[0], dst)
                return dst
        msg = "CodeFormer produced no output"
        raise RuntimeError(msg)

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "codeformer", "-i", str(src), "-o", str(dst),
        "--fidelity", str(fidelity), "--upscale", str(upscale),
    ]
    subprocess.run(cmd, check=True, timeout=300)
    return dst


def _gfpgan(src: Path, dst: Path, *, upscale: int) -> Path:
    """GFPGAN 推理。"""
    try:
        import cv2
        from gfpgan import GFPGANer

        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Cannot read: {src}")

        restorer = GFPGANer(
            model_path="GFPGANv1.4.pth",
            upscale=upscale,
            arch="clean",
            channel_multiplier=2,
            bg_upsampler=None,
        )
        _, _, output = restorer.enhance(
            img, has_aligned=False, only_center_face=False, paste_back=True,
        )

        dst.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(dst), output)
        return dst
    except ImportError as exc:
        if not shutil.which("gfpgan"):
            msg = (
                "GFPGAN not found. Install: pip install gfpgan "
                "or download from https://github.com/TencentARC/GFPGAN"
            )
            raise RuntimeError(msg) from exc
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["gfpgan", "-i", str(src), "-o", str(dst), "-s", str(upscale)]
        subprocess.run(cmd, check=True, timeout=300)
        return dst
