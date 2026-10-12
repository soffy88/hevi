"""发布前套件外观层：成片 + 文稿 → publish_bundle/。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.layer4_legacy.publishkit.omodul_impl.publish import build_publish_bundle
from hevi.layer4_legacy.publishkit.oprim_impl.contracts import (
    PLATFORMS,
    PublishBundleResult,
    PublishError,
)

__all__ = ["PLATFORMS", "PublishBundleResult", "PublishError", "generate_publish_bundle"]


def generate_publish_bundle(
    video_path: Path,
    script_path: Path,
    output_dir: Path,
    config: dict[str, Any] | None = None,
) -> PublishBundleResult:
    """生成完整发布产物包。

    ``script_path`` 必须是真实文稿（JSON 分镜 / timestamps / md / txt）。
    媒体或二进制文件会被拒绝，不会被当成"正文"塞进文案。
    """

    return build_publish_bundle(
        video_path=Path(video_path),
        script_path=Path(script_path),
        output_dir=Path(output_dir),
        config=config,
    )