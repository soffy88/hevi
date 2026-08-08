"""v9.1 素材质检:数字人底图(presenter_image_url)的合法性前置拦截。

在用户确认阶段 / 装配入队前对图片做三层校验:
  1. 可访问性 —— URL 能下载且是合法图片格式;
  2. 尺寸合理性 —— 像素总量上限(防止超大图爆显存) + 最小尺寸下限;
  3. 人脸占比(尽力而为) —— 检测到且恰好一张人脸,bbox 面积占比在
     [min_face_ratio, max_face_ratio] 区间(拒绝无脸/全身远景/大头贴)。

人脸检测依赖 opencv-python(haarcascade,轻量级);未安装时降级为仅做
1+2 校验并在报告里标注 ``face_check: "skipped"``,绝不阻断主流程。
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 显存风控:单张底图 ≤ 40M 像素(如 8000×5000),超出拒绝 —— 防止 Talking Face
# 渲染阶段把超大图怼进显存导致 OOM。
MAX_PIXELS = 40_000_000
# 太小的图(< 128×128)没信息量,直接拒绝。
MIN_PIXELS = 128 * 128
# 人脸 bbox 面积占整图比例下限/上限:过滤全身远景照(占比过小)与
# 大头贴/怼脸照(占比过大)。工业经验区间:5%~60%。
DEFAULT_MIN_FACE_RATIO = 0.05
DEFAULT_MAX_FACE_RATIO = 0.60
# 单张下载上限 20MB,防恶意超大文件。
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
_DOWNLOAD_TIMEOUT = httpx.Timeout(30.0)


@dataclass
class AssetVerdict:
    """质检结果:通过为 True,否则带明确原因(前端可直接展示)。"""

    valid: bool
    width: int | None = None
    height: int | None = None
    face_count: int | None = None
    face_ratio: float | None = None
    face_check: str = "skipped"  # "ok" | "unavailable"
    errors: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "；".join(self.errors) if self.errors else "校验通过"


async def validate_presenter_image(
    image_url: str,
    *,
    min_face_ratio: float = DEFAULT_MIN_FACE_RATIO,
    max_face_ratio: float = DEFAULT_MAX_FACE_RATIO,
    client: httpx.AsyncClient | None = None,
    face_detector: Any = None,
) -> AssetVerdict:
    """校验数字人底图 URL(或本地已落盘的相对路径)。

    ``image_url`` 可以是以 http(s):// 开头的远端 URL,也可以是上传接口
    返回的本地路径(如 ``output/presenter_images/xxx.jpg``)——后者直接读盘,
    不再走网络。``face_detector`` 可注入(测试友好);缺省时懒加载 cv2。
    """
    errors: list[str] = []
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True)
    try:
        # 本地路径(上传产物/缓存):不联网,直接读字节。
        if not image_url.startswith(("http://", "https://")):
            path = Path(image_url)
            if not path.exists():
                return AssetVerdict(valid=False, errors=[f"图片文件不存在: {image_url}"])
            content = path.read_bytes()
            return _validate_bytes(
                content,
                min_face_ratio=min_face_ratio,
                max_face_ratio=max_face_ratio,
                face_detector=face_detector,
            )
        response = await http.get(image_url)
        if response.status_code != 200:
            return AssetVerdict(valid=False, errors=[f"图片不可访问(HTTP {response.status_code})"])
        content = response.content
        if len(content) > MAX_DOWNLOAD_BYTES:
            return AssetVerdict(valid=False, errors=["图片超过 20MB 上限,请压缩后重试"])
        return _validate_bytes(
            content,
            min_face_ratio=min_face_ratio,
            max_face_ratio=max_face_ratio,
            face_detector=face_detector,
        )
    except httpx.HTTPError as exc:
        errors.append(f"图片下载失败: {exc.__class__.__name__}")
        return AssetVerdict(valid=False, errors=errors)
    finally:
        if own_client:
            await http.aclose()


def validate_presenter_bytes(
    content: bytes,
    *,
    min_face_ratio: float = DEFAULT_MIN_FACE_RATIO,
    max_face_ratio: float = DEFAULT_MAX_FACE_RATIO,
) -> AssetVerdict:
    """校验已上传到内存的底图字节(上传接口用,与 URL 校验同一套逻辑)。"""
    return _validate_bytes(
        content,
        min_face_ratio=min_face_ratio,
        max_face_ratio=max_face_ratio,
        face_detector=_load_default_detector(),
    )


def _validate_bytes(
    content: bytes,
    *,
    min_face_ratio: float,
    max_face_ratio: float,
    face_detector: Any = None,
) -> AssetVerdict:
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps_exif(image)
        width, height = image.size
    except Exception:
        return AssetVerdict(valid=False, errors=["图片格式无法解析,请上传 JPG/PNG"])
    pixels = width * height
    if pixels > MAX_PIXELS:
        return AssetVerdict(
            valid=False,
            width=width,
            height=height,
            errors=[f"图片尺寸过大({width}×{height} ≈ {pixels // 1_000_000}M 像素),请压缩后再试"],
        )
    if pixels < MIN_PIXELS:
        return AssetVerdict(
            valid=False,
            width=width,
            height=height,
            errors=["图片分辨率过低,请上传清晰的半身照"],
        )

    detector = face_detector or _load_default_detector()
    if detector is None:
        # 无 opencv:只做 1+2 层校验,人脸检测标注 skipped,不阻断。
        return AssetVerdict(valid=True, width=width, height=height, face_check="unavailable")

    try:
        import numpy as np

        rgb = image.convert("RGB")
        arr = np.asarray(rgb)
        gray = cv2_gray(arr)
        faces = detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(64, 64)
        )
    except Exception as exc:
        logger.warning("face detection failed: %s", exc)
        return AssetVerdict(
            valid=True, width=width, height=height, face_check="unavailable",
            errors=[f"人脸检测不可用(已跳过): {exc}"],
        )

    count = len(faces)
    if count == 0:
        return AssetVerdict(
            valid=False, width=width, height=height, face_count=0, face_ratio=0.0,
            face_check="ok", errors=["未检测到清晰人脸,请上传正脸半身照"],
        )
    if count > 1:
        return AssetVerdict(
            valid=False, width=width, height=height, face_count=count,
            face_check="ok", errors=[f"检测到 {count} 张人脸,请上传单人照"],
        )
    _x, _y, w, h = faces[0]
    ratio = (w * h) / (width * height)
    if ratio < min_face_ratio:
        return AssetVerdict(
            valid=False, width=width, height=height, face_count=1, face_ratio=round(ratio, 4),
            face_check="ok",
            errors=["面部占画面比例过小(全身远景),请上传人物占画面 50%-70% 的半身照"],
        )
    if ratio > max_face_ratio:
        return AssetVerdict(
            valid=False, width=width, height=height, face_count=1, face_ratio=round(ratio, 4),
            face_check="ok", errors=["面部占画面比例过大(大头贴),请退后拍摄半身照"],
        )
    return AssetVerdict(
        valid=True, width=width, height=height, face_count=1,
        face_ratio=round(ratio, 4), face_check="ok",
    )


def _load_default_detector() -> Any | None:
    """懒加载 opencv haarcascade(约 900KB,加载失败返回 None 降级)。"""
    try:
        import cv2

        cascade = (
            Path(cv2.__file__).resolve().parent
            / "data"
            / "haarcascade_frontalface_default.xml"
        )
        if not cascade.is_file():
            return None
        return cv2.CascadeClassifier(str(cascade))
    except Exception:
        return None


def ImageOps_exif(image: Any) -> Any:
    """按 EXIF 方向纠正(手机竖拍图常见);无 EXIF 原样返回。"""
    try:
        from PIL import ImageOps

        return ImageOps.exif_transpose(image)
    except Exception:
        return image


def cv2_gray(arr: Any) -> Any:
    import cv2

    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


__all__ = [
    "DEFAULT_MAX_FACE_RATIO",
    "DEFAULT_MIN_FACE_RATIO",
    "AssetVerdict",
    "validate_presenter_image",
]
