from __future__ import annotations

from obase.persistence import PgPool

from hevi.core.config import settings


async def get_vault_pg_pool() -> PgPool:
    """获取(或创建)hevi-vault 专用连接池。enable_vector=True 注册 pgvector 编解码,
    embedding 列可以直接传/取 Python list[float],不用手动转 pgvector 字面量。
    """
    return await PgPool.get_or_create(dsn=settings.vault_database_url, enable_vector=True)
