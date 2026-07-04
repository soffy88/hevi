from __future__ import annotations

import os
import re
from pathlib import Path


class ReferenceStore:
    """Abstracts reference-image path management + persistence (local volume).

    存储根目录默认 ``output/reference_images`` —— output/ 在 docker 里已挂载到宿主机
    (持久,镜像重建不丢);可经 ``HEVI_REFERENCE_DIR`` 覆盖。生产亦可换 minio 前缀。
    In tests, pass a tmp_path fixture value.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(
            base_dir or os.getenv("HEVI_REFERENCE_DIR", "output/reference_images")
        )

    def path_for(self, subject_id: str, filename: str) -> str:
        return str(self._base_dir / subject_id / filename)

    def validate_refs(self, refs: list[str]) -> list[str]:
        """Return refs with empty/whitespace-only entries stripped."""
        return [r for r in refs if r.strip()]

    def subject_dir(self, subject_id: str) -> Path:
        return self._base_dir / subject_id

    @staticmethod
    def _safe_name(filename: str) -> str:
        """防路径穿越:只保留 basename 里的安全字符。"""
        base = os.path.basename(filename or "").strip() or "upload"
        base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
        return base[-128:] or "upload"

    def save_upload(self, subject_id: str, filename: str, data: bytes) -> str:
        """把上传的照片字节落盘到 subject 目录,返回可读回的相对路径。

        用于"上传一张照片 → 角色参考图"。路径既被 subject.reference_images 记录,
        也被生成链路作为 i2v 参考图读取(相对 app cwd,与成片输出同一挂载区)。
        """
        safe = self._safe_name(filename)
        target = self.subject_dir(subject_id) / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)
