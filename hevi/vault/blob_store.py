"""L-Blob —— MinIO 内容寻址存储。见 HEVI-SPEC-03 §1。

文件名即 sha256:同内容自动去重、引用永不失效、天然可校验。`minio` 客户端是同步 I/O
(官方包没有 async 版本),V-P0 阶段直接同步调用,调用方(异步 service 层)按需自行
`asyncio.to_thread` 包装——不在这一层引入不必要的线程池抽象。
"""

from __future__ import annotations

import hashlib
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from hevi.core.config import settings


def get_minio_client() -> Minio:
    return Minio(
        settings.vault_minio_endpoint,
        access_key=settings.vault_minio_access_key,
        secret_key=settings.vault_minio_secret_key,
        secure=settings.vault_minio_secure,
    )


def put_blob(
    client: Minio, *, bucket: str, data: bytes, mime: str = "application/octet-stream"
) -> str:
    """写入内容寻址对象,返回 sha256(即对象名)。已存在同哈希对象则跳过上传(去重)。"""
    sha256 = hashlib.sha256(data).hexdigest()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    try:
        client.stat_object(bucket, sha256)
    except S3Error:
        client.put_object(bucket, sha256, BytesIO(data), length=len(data), content_type=mime)
    return sha256


def get_blob(client: Minio, *, bucket: str, sha256: str) -> bytes:
    resp = client.get_object(bucket, sha256)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()
