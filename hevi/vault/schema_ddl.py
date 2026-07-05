"""L-Meta 元数据 DDL —— 见 HEVI-SPEC-03 §3。

hevi-vault 用独立的 Postgres 实例(docker-compose.yml 的 hevi-vault 项目),不与主 app
共享 alembic revision 链——共享会导致要么主库被灌入 vault_* 表,要么 vault 库被灌入
全部主 app 表(video_tasks/subjects/...),两者都违背"资产库独立于主库"的设计初衷。
所以这里用一个幂等(IF NOT EXISTS)的建表脚本,不走 alembic。

用裸 asyncpg 连接而不是 `hevi.vault.pg_pool.get_vault_pg_pool()` 的池:那个池
`enable_vector=True`,连接时就会注册 pgvector 编解码器,而编解码器要求 `vector`
类型已存在——在扩展还没建之前拿这个池会直接报错(先有鸡还是先有蛋)。所以这里必须
先用普通连接把 `CREATE EXTENSION vector` 建出来,之后再由 `get_vault_pg_pool()`
拿带 vector 编解码的池。
"""

from __future__ import annotations

import asyncpg  # type: ignore[import-untyped]

_DDL_STATEMENTS: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS vault_packs (
      pack_id TEXT PRIMARY KEY,
      pack_type TEXT NOT NULL,
      name TEXT NOT NULL,
      canonical_version TEXT,
      lifecycle TEXT NOT NULL DEFAULT 'draft',
      created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vault_versions (
      pack_id TEXT REFERENCES vault_packs,
      version TEXT NOT NULL,
      manifest JSONB NOT NULL,
      manifest_hash TEXT NOT NULL,
      stability_passed BOOLEAN DEFAULT false,
      created_at TIMESTAMPTZ DEFAULT now(),
      PRIMARY KEY (pack_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vault_files (
      sha256 TEXT PRIMARY KEY,
      bucket TEXT NOT NULL,
      bytes BIGINT,
      mime TEXT,
      ref_count INT DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vault_embeddings (
      pack_id TEXT,
      version TEXT,
      kind TEXT,
      embedding vector(512),
      PRIMARY KEY (pack_id, version, kind)
    )
    """,
    "CREATE INDEX IF NOT EXISTS vault_embeddings_hnsw ON vault_embeddings "
    "USING hnsw (embedding vector_cosine_ops)",
    """
    CREATE TABLE IF NOT EXISTS vault_platform_bindings (
      pack_id TEXT,
      version TEXT,
      platform TEXT NOT NULL,
      remote_ref_id TEXT NOT NULL,
      remote_kind TEXT,
      synced_files JSONB,
      status TEXT DEFAULT 'active',
      last_verified TIMESTAMPTZ,
      PRIMARY KEY (pack_id, version, platform)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vault_lineage (
      derived_sha256 TEXT NOT NULL,
      run_id UUID,
      shot_id TEXT,
      pack_id TEXT,
      version TEXT,
      PRIMARY KEY (derived_sha256, pack_id)
    )
    """,
]


async def init_vault_schema(dsn: str) -> None:
    """幂等建表。本地/CI 初始化 hevi-vault 数据库时调用一次即可,须早于
    `get_vault_pg_pool()` 首次被调用(建扩展 → 才能拿带 vector 编解码的池)。
    """
    conn = await asyncpg.connect(dsn=dsn)
    try:
        for stmt in _DDL_STATEMENTS:
            await conn.execute(stmt)
    finally:
        await conn.close()
