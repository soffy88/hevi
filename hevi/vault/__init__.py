"""hevi.vault —— 资产库(HEVI-SPEC-03 / EXEC-01 M1)。

角色/风格/场景/声音资产的持久化底座:MinIO(内容寻址 blob)+ PostgreSQL(元数据/血缘)+
pgvector(身份/风格 embedding)。独立于 hevi 主库(见 docker-compose.yml 的 hevi-vault
项目),不与主 app 共享 Postgres 实例,避免触碰已在服务 hevi.kanpan.co 的 hevi-dev 栈。

V-P0(本次实现)范围:manifest schema + DDL + `asset_resolve`/`asset_create`/`asset_verify`
三个 oskill 接口 + 血缘落库。平台绑定懒同步(§5)、稳定性预检自动化、GC 任务是 V-P1;
查重检索/整包导入导出是 V-P2,均未实现。
"""

from hevi.vault.blob_store import get_blob, get_minio_client, put_blob
from hevi.vault.identity_pack import build_identity_pack, lint_shot_prompt
from hevi.vault.pg_pool import get_vault_pg_pool
from hevi.vault.schema_ddl import init_vault_schema
from hevi.vault.schemas import Manifest, ManifestFile, Provenance, StabilityCheck
from hevi.vault.service import (
    asset_create,
    asset_promote,
    asset_resolve,
    asset_verify,
    record_lineage,
    store_embedding,
)

__all__ = [
    "Manifest",
    "ManifestFile",
    "Provenance",
    "StabilityCheck",
    "asset_create",
    "asset_promote",
    "asset_resolve",
    "asset_verify",
    "build_identity_pack",
    "get_blob",
    "get_minio_client",
    "get_vault_pg_pool",
    "init_vault_schema",
    "lint_shot_prompt",
    "put_blob",
    "record_lineage",
    "store_embedding",
]
