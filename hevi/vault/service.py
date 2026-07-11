"""HEVI-SPEC-03 §6 oskill 接口(V-P0 三个 + `asset_promote`)+ 血缘落库。

服务层零业务逻辑(EXEC-01 执行红线):manifest 结构校验交给 pydantic;embedding 距离
比对是纯数学;`asset_promote` 只做"stability_check.passed 才允许 draft→validated"
这一条状态机判断,真正的稳定性预检(生成 N 次候选 + 挑选)在 hevi.vault.identity_pack
(EXEC-01 M2,业务逻辑层)。平台绑定懒同步(§5)的读路径(`asset_resolve` 按 platform
读 `remote_ref_id`)V-P0 就有;写路径(`get_platform_binding`/`upsert_platform_binding`)
EXEC-01 M3 补上,"要不要同步""同步成什么"这类业务判断在
hevi.cinematic.platform_binding,这里仍然只是纯 CRUD。

`obase.persistence.query()` 会在没写 LIMIT 的 SQL 后面自动追加 `LIMIT n`——对 SELECT
没问题,但 `INSERT ... RETURNING * LIMIT n` 是非法语法(实测验证过)。所以本文件里所有
写操作都显式传 `limit=0` 关掉这个自动追加。
"""

from __future__ import annotations

import hashlib
import json

from obase.persistence import PgPool, query

from hevi.vault.schemas import Manifest, ManifestFile, StabilityCheck

_BUCKET_BY_PACK_TYPE = {
    "identity": "vault-identity",
    "style": "vault-style",
    "scene": "vault-scene",
    "voice": "vault-audio",
}


def _bucket_for_pack_type(pack_type: str) -> str:
    return _BUCKET_BY_PACK_TYPE.get(pack_type, "vault-derived")


def _manifest_hash(manifest: Manifest) -> str:
    """整包指纹(§3 注释:"全文件哈希的默克尔根")。这里用"排序后 relpath:sha256 拼接
    再哈希"的扁平摘要,不是严格二叉默克尔树,但同样满足"任何文件变化 → 指纹必变"的
    完整性校验目的,V-P0 够用;真要做增量证明再升级成真正的树结构。
    """
    parts = sorted(f"{path}:{info.sha256}" for path, info in manifest.files.items())
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


async def asset_create(
    pool: PgPool,
    minio_client,
    *,
    pack_id: str,
    pack_type: str,
    name: str,
    version: str,
    files: dict[str, bytes],
    file_roles: dict[str, str] | None = None,
    **manifest_extra,
) -> Manifest:
    """files: 相对路径 → 原始字节。写入 MinIO(内容寻址)+ 落库为 draft 版本。"""
    from hevi.vault.blob_store import put_blob

    bucket = _bucket_for_pack_type(pack_type)
    file_roles = file_roles or {}
    manifest_files: dict[str, ManifestFile] = {}
    for rel_path, data in files.items():
        sha256 = put_blob(minio_client, bucket=bucket, data=data)
        manifest_files[rel_path] = ManifestFile(sha256=sha256, role=file_roles.get(rel_path, ""))
        await query(
            pool,
            sql=(
                "INSERT INTO vault_files (sha256, bucket, bytes, ref_count) VALUES ($1,$2,$3,1) "
                "ON CONFLICT (sha256) DO UPDATE SET ref_count = vault_files.ref_count + 1"
            ),
            params=[sha256, bucket, len(data)],
            limit=0,
        )

    manifest = Manifest(
        pack_id=pack_id,
        pack_type=pack_type,
        version=version,
        name=name,
        files=manifest_files,
        lifecycle="draft",
        **manifest_extra,
    )
    manifest_hash = _manifest_hash(manifest)

    await query(
        pool,
        sql=(
            "INSERT INTO vault_packs (pack_id, pack_type, name) VALUES ($1,$2,$3) "
            "ON CONFLICT (pack_id) DO NOTHING"
        ),
        params=[pack_id, pack_type, name],
        limit=0,
    )
    await query(
        pool,
        sql=(
            "INSERT INTO vault_versions (pack_id, version, manifest, manifest_hash) "
            "VALUES ($1,$2,$3::jsonb,$4) ON CONFLICT (pack_id, version) DO NOTHING"
        ),
        params=[pack_id, version, manifest.model_dump_json(), manifest_hash],
        limit=0,
    )
    await query(
        pool,
        sql="UPDATE vault_packs SET canonical_version = $2 WHERE pack_id = $1",
        params=[pack_id, version],
        limit=0,
    )
    return manifest


async def asset_resolve(pool: PgPool, *, pack_id: str, platform: str | None = None) -> dict:
    """取用某资产包当前 canonical 版本的 manifest(+ 有 platform 且已绑定则带 remote_ref_id)。"""
    pack_rows = await query(
        pool, sql="SELECT canonical_version FROM vault_packs WHERE pack_id = $1", params=[pack_id]
    )
    if not pack_rows:
        raise KeyError(f"vault pack not found: {pack_id!r}")
    version = pack_rows[0]["canonical_version"]
    if version is None:
        raise ValueError(f"vault pack {pack_id!r} has no canonical_version yet")

    version_rows = await query(
        pool,
        sql="SELECT manifest FROM vault_versions WHERE pack_id = $1 AND version = $2",
        params=[pack_id, version],
    )
    if not version_rows:
        raise KeyError(f"vault version not found: {pack_id!r} @ {version!r}")
    # asyncpg 没注册 jsonb 编解码器时,JSONB 列原样返回 JSON 文本(str),不是 dict。
    manifest = Manifest.model_validate_json(version_rows[0]["manifest"])

    remote_ref_id = None
    if platform:
        binding_rows = await query(
            pool,
            sql=(
                "SELECT remote_ref_id FROM vault_platform_bindings "
                "WHERE pack_id=$1 AND version=$2 AND platform=$3 AND status='active'"
            ),
            params=[pack_id, version, platform],
        )
        if binding_rows:
            remote_ref_id = binding_rows[0]["remote_ref_id"]

    return {
        "pack_id": pack_id,
        "version": version,
        "manifest": manifest,
        "remote_ref_id": remote_ref_id,
    }


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


async def asset_verify(
    pool: PgPool,
    *,
    pack_id: str,
    version: str,
    frame_embedding: list[float],
    threshold: float = 0.35,
) -> dict:
    """门调用:身份 embedding 距离比对。distance 越小越像,<= threshold 判定通过。"""
    rows = await query(
        pool,
        sql="SELECT embedding FROM vault_embeddings WHERE pack_id=$1 AND version=$2 AND kind='identity'",
        params=[pack_id, version],
    )
    if not rows:
        return {
            "passed": False,
            "distance": None,
            "threshold": threshold,
            "reason": "no reference embedding stored",
        }
    distance = float(_cosine_distance(list(rows[0]["embedding"]), frame_embedding))
    return {"passed": bool(distance <= threshold), "distance": distance, "threshold": threshold}


async def store_embedding(
    pool: PgPool, *, pack_id: str, version: str, kind: str, embedding: list[float]
) -> None:
    await query(
        pool,
        sql=(
            "INSERT INTO vault_embeddings (pack_id, version, kind, embedding) VALUES ($1,$2,$3,$4) "
            "ON CONFLICT (pack_id, version, kind) DO UPDATE SET embedding = EXCLUDED.embedding"
        ),
        params=[pack_id, version, kind, embedding],
        limit=0,
    )


async def get_platform_binding(
    pool: PgPool, *, pack_id: str, version: str, platform: str
) -> dict | None:
    """查一条平台绑定记录(有没有就直接返回 None,不抛异常——"没绑定过"是正常状态,
    不是错误)。"""
    rows = await query(
        pool,
        sql=(
            "SELECT remote_ref_id, remote_kind, synced_files, status, last_verified "
            "FROM vault_platform_bindings WHERE pack_id=$1 AND version=$2 AND platform=$3"
        ),
        params=[pack_id, version, platform],
    )
    return dict(rows[0]) if rows else None


async def upsert_platform_binding(
    pool: PgPool,
    *,
    pack_id: str,
    version: str,
    platform: str,
    remote_ref_id: str,
    remote_kind: str | None = None,
    synced_files: dict | None = None,
    status: str = "active",
) -> None:
    """写/更新一条平台绑定记录。业务判断("要不要同步""同步成什么")在调用方
    (hevi.cinematic.platform_binding)——这里只是纯 CRUD。"""
    await query(
        pool,
        sql=(
            "INSERT INTO vault_platform_bindings "
            "(pack_id, version, platform, remote_ref_id, remote_kind, synced_files, status, last_verified) "
            "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,now()) "
            "ON CONFLICT (pack_id, version, platform) DO UPDATE SET "
            "remote_ref_id=EXCLUDED.remote_ref_id, remote_kind=EXCLUDED.remote_kind, "
            "synced_files=EXCLUDED.synced_files, status=EXCLUDED.status, last_verified=now()"
        ),
        params=[
            pack_id,
            version,
            platform,
            remote_ref_id,
            remote_kind,
            json.dumps(synced_files) if synced_files is not None else None,
            status,
        ],
        limit=0,
    )


async def record_lineage(
    pool: PgPool,
    *,
    derived_sha256: str,
    run_id: str | None,
    shot_id: str | None,
    pack_id: str,
    version: str,
) -> None:
    """任何生成物消费了某资产版本 → 落一条血缘记录。orchestrator 在 video_generate 成功
    后自动调用(§SPEC-03 §6),不走显式 oskill 接口——这里只是它调用的底层函数。
    """
    await query(
        pool,
        sql=(
            "INSERT INTO vault_lineage (derived_sha256, run_id, shot_id, pack_id, version) "
            "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (derived_sha256, pack_id) DO NOTHING"
        ),
        params=[derived_sha256, run_id, shot_id, pack_id, version],
        limit=0,
    )


async def asset_promote(
    pool: PgPool,
    *,
    pack_id: str,
    version: str,
    stability_check: StabilityCheck,
) -> Manifest:
    """draft → validated(EXEC-01 M2 的 asset_promote 门):仅当 stability_check.passed
    才允许晋级。只更新 manifest 的 stability_check + lifecycle 字段,files/manifest_hash
    不变(内容没变,只是元数据状态转移,不是新版本)。
    """
    if not stability_check.passed:
        raise ValueError(
            f"cannot promote {pack_id}@{version}: stability_check not passed "
            f"(score={stability_check.score!r})"
        )
    rows = await query(
        pool,
        sql="SELECT manifest FROM vault_versions WHERE pack_id=$1 AND version=$2",
        params=[pack_id, version],
    )
    if not rows:
        raise KeyError(f"vault version not found: {pack_id!r} @ {version!r}")
    manifest = Manifest.model_validate_json(rows[0]["manifest"])
    manifest.stability_check = stability_check
    manifest.lifecycle = "validated"
    await query(
        pool,
        sql="UPDATE vault_versions SET manifest = $3::jsonb WHERE pack_id=$1 AND version=$2",
        params=[pack_id, version, manifest.model_dump_json()],
        limit=0,
    )
    return manifest
