"""平台绑定懒同步(最小版)—— HEVI-SPEC-02 §11.3、HEVI-EXEC-01 M3 item 4。

`vault_platform_bindings` 表(`hevi/vault/schema_ddl.py`)已经建好、`asset_resolve`
也已经会按 platform 读 `remote_ref_id`,但一直没有写入路径——这个模块补上。

**范围说明(计划阶段就想清楚的,不是留到实现时才发现)**:没有确认过 Vidu 官方是否有
独立的"上传参考图一次、拿 remote_ref_id 反复引用"的 API 端点;现有
`hevi.video.vidu_service.vidu_reference_to_video` 本身直接接受 inline base64/URL,
不需要先"上传"才能用。所以这里的"懒同步"实际做的是:给每张参考图算 sha256、把
"这批图片被这个平台用过"记一条 bookkeeping 记录到 `vault_platform_bindings`
(`remote_ref_id` 暂时就是本地 sha256,不是真的平台侧 ID),返回值仍然是 base64
内联数据本身。以后如果确认 Vidu 有真正的持久化上传端点,只需要替换这个函数内部
"生成要喂给 API 的图片表示"这一步,调用方(C6 video_gen.py)的调用约定不用改。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

from hevi.vault.service import get_platform_binding, upsert_platform_binding

logger = logging.getLogger(__name__)

_MIME_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _data_uri(path: Path) -> tuple[str, str]:
    """返回 (data URI, sha256)。"""
    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    mime = _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}", sha256


async def ensure_platform_binding(
    pool,
    *,
    pack_id: str,
    version: str,
    platform: str,
    image_paths: list[Path],
) -> list[str]:
    """确保 image_paths 这些参考图在 platform 上"已同步"(见模块 docstring 的范围
    说明),返回可以直接喂给该平台生成 API 的图片数据(这里是 base64 data URI 列表,
    跟 image_paths 顺序一一对应)。

    每次调用都会更新 bookkeeping 记录(即便这批图之前同步过)——这不是重新"上传",
    只是刷新 `synced_files`/`last_verified`,代价可忽略。
    """
    existing = await get_platform_binding(pool, pack_id=pack_id, version=version, platform=platform)
    synced_files: dict[str, str] = {}
    if existing and existing.get("synced_files"):
        raw = existing["synced_files"]
        synced_files = json.loads(raw) if isinstance(raw, str) else dict(raw)

    uris: list[str] = []
    for path in image_paths:
        uri, sha256 = _data_uri(path)
        uris.append(uri)
        synced_files[str(path)] = sha256

    # remote_ref_id 是这批参考图里第一张的 sha256(占位标识,不是真平台侧 ID——见
    # 模块 docstring),主要目的是让 (pack_id, version, platform) 这一行"有没有
    # 同步过"这个判断有据可查,而不是每次都当作全新的。
    primary_ref = next(iter(synced_files.values()), "")
    await upsert_platform_binding(
        pool,
        pack_id=pack_id,
        version=version,
        platform=platform,
        remote_ref_id=primary_ref,
        remote_kind="reference_image",
        synced_files=synced_files,
    )
    logger.debug(
        "ensure_platform_binding: %s@%s/%s 同步了 %d 张参考图",
        pack_id,
        version,
        platform,
        len(uris),
    )
    return uris
