"""hevi-vault(HEVI-SPEC-03 V-P0)集成测试:真实打到本地 hevi-vault docker-compose 栈
(独立 Postgres+pgvector / MinIO,见 docker-compose.yml),不 mock PgPool/Minio——这类
DB/blob 交互的 SQL 正确性,mock 测不出来,与 tests/test_assets.py 的既有约定一致。

跑之前需要 `docker compose up -d`(仓库根目录的 docker-compose.yml,project 名 hevi-vault)。
"""

from __future__ import annotations

import hashlib

import pytest

from hevi.core.config import settings
from hevi.vault import (
    asset_create,
    asset_promote,
    asset_resolve,
    asset_verify,
    get_minio_client,
    get_vault_pg_pool,
    init_vault_schema,
    record_lineage,
    store_embedding,
)
from hevi.vault.schemas import Manifest, StabilityCheck


async def _cleanup(pool, pack_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM vault_lineage WHERE pack_id = $1", pack_id)
        await conn.execute("DELETE FROM vault_embeddings WHERE pack_id = $1", pack_id)
        await conn.execute("DELETE FROM vault_platform_bindings WHERE pack_id = $1", pack_id)
        await conn.execute("DELETE FROM vault_versions WHERE pack_id = $1", pack_id)
        await conn.execute("DELETE FROM vault_packs WHERE pack_id = $1", pack_id)


@pytest.fixture
async def vault_pool():
    await init_vault_schema(settings.vault_database_url)
    pool = await get_vault_pg_pool()
    yield pool


@pytest.mark.asyncio
async def test_asset_create_writes_content_addressed_blob(vault_pool):
    minio = get_minio_client()
    pack_id = "identity/TEST-C001"
    await _cleanup(vault_pool, pack_id)

    data = b"fake portrait bytes for content-addressing test"
    manifest = await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="测试角色",
        version="0.1.0",
        files={"refs/front.png": data},
        file_roles={"refs/front.png": "canonical_portrait"},
    )

    expected_sha = hashlib.sha256(data).hexdigest()
    assert manifest.files["refs/front.png"].sha256 == expected_sha
    assert manifest.files["refs/front.png"].role == "canonical_portrait"

    stat = minio.stat_object("vault-identity", expected_sha)
    assert stat.size == len(data)

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_asset_create_dedupes_identical_content(vault_pool):
    minio = get_minio_client()
    pack_id = "identity/TEST-DEDUPE"
    await _cleanup(vault_pool, pack_id)
    sha = hashlib.sha256(b"same bytes twice").hexdigest()
    async with vault_pool.acquire() as conn:
        # vault_files 按内容哈希全局去重,不按 pack_id 隔离,清一下这条测试内容自己的行,
        # 避免重复跑这个测试时 ref_count 从非零基线开始。
        await conn.execute("DELETE FROM vault_files WHERE sha256 = $1", sha)

    data = b"same bytes twice"
    await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="a",
        version="0.1.0",
        files={"refs/a.png": data},
    )
    manifest2 = await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="a",
        version="0.2.0",
        files={"refs/b.png": data},
    )
    assert manifest2.files["refs/b.png"].sha256 == sha

    async with vault_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT ref_count FROM vault_files WHERE sha256 = $1", sha)
        assert row["ref_count"] == 2  # 两个版本各引用一次,同内容只存一份 blob
        await conn.execute("DELETE FROM vault_files WHERE sha256 = $1", sha)

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_asset_resolve_returns_canonical_manifest(vault_pool):
    minio = get_minio_client()
    pack_id = "identity/TEST-RESOLVE"
    await _cleanup(vault_pool, pack_id)

    await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="智伯",
        version="1.0.0",
        files={"refs/front.png": b"v1"},
        immutable_traits="四十余岁,魁伟美髯",
    )
    resolved = await asset_resolve(vault_pool, pack_id=pack_id)

    assert resolved["version"] == "1.0.0"
    assert isinstance(resolved["manifest"], Manifest)
    assert resolved["manifest"].immutable_traits == "四十余岁,魁伟美髯"
    assert resolved["remote_ref_id"] is None  # 无 platform 绑定(V-P1 才实现懒同步)

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_asset_resolve_unknown_pack_raises(vault_pool):
    with pytest.raises(KeyError):
        await asset_resolve(vault_pool, pack_id="identity/DOES-NOT-EXIST")


@pytest.mark.asyncio
async def test_asset_verify_identity_embedding_distance(vault_pool):
    minio = get_minio_client()
    pack_id = "identity/TEST-VERIFY"
    await _cleanup(vault_pool, pack_id)

    await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="x",
        version="1.0.0",
        files={"refs/front.png": b"v1"},
    )
    ref_embedding = [1.0] + [0.0] * 511
    await store_embedding(
        vault_pool, pack_id=pack_id, version="1.0.0", kind="identity", embedding=ref_embedding
    )

    same = await asset_verify(
        vault_pool, pack_id=pack_id, version="1.0.0", frame_embedding=ref_embedding
    )
    assert same["passed"] is True
    assert same["distance"] == pytest.approx(0.0, abs=1e-5)

    orthogonal = await asset_verify(
        vault_pool, pack_id=pack_id, version="1.0.0", frame_embedding=[0.0] * 511 + [1.0]
    )
    assert orthogonal["passed"] is False
    assert orthogonal["distance"] == pytest.approx(1.0, abs=1e-5)

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_asset_verify_missing_embedding_fails_closed(vault_pool):
    minio = get_minio_client()
    pack_id = "identity/TEST-NO-EMBEDDING"
    await _cleanup(vault_pool, pack_id)

    await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="x",
        version="1.0.0",
        files={"refs/front.png": b"v1"},
    )
    result = await asset_verify(
        vault_pool, pack_id=pack_id, version="1.0.0", frame_embedding=[0.0] * 512
    )
    assert result["passed"] is False
    assert result["distance"] is None

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_record_lineage_and_query(vault_pool):
    minio = get_minio_client()
    pack_id = "identity/TEST-LINEAGE"
    await _cleanup(vault_pool, pack_id)

    await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="x",
        version="1.0.0",
        files={"refs/front.png": b"v1"},
    )
    await record_lineage(
        vault_pool,
        derived_sha256="deadbeef" * 4,
        run_id=None,
        shot_id="SH01",
        pack_id=pack_id,
        version="1.0.0",
    )

    async with vault_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM vault_lineage WHERE derived_sha256 = $1", "deadbeef" * 4
        )
        assert row is not None
        assert row["pack_id"] == pack_id
        assert row["shot_id"] == "SH01"

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_manifest_rejects_invalid_pack_type():
    with pytest.raises(ValueError):
        Manifest(pack_id="x/1", pack_type="not-a-real-type", version="1.0.0", name="x")


# ── asset_promote(EXEC-01 M2)──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_asset_promote_passing_stability_check_sets_validated(vault_pool):
    minio = get_minio_client()
    pack_id = "identity/TEST-PROMOTE-OK"
    await _cleanup(vault_pool, pack_id)

    await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="x",
        version="1.0.0",
        files={"refs/front.png": b"v1"},
    )
    manifest = await asset_promote(
        vault_pool,
        pack_id=pack_id,
        version="1.0.0",
        stability_check=StabilityCheck(passed=True, score="3/3"),
    )

    assert manifest.lifecycle == "validated"
    assert manifest.stability_check.passed is True
    assert manifest.stability_check.score == "3/3"

    resolved = await asset_resolve(vault_pool, pack_id=pack_id)
    assert resolved["manifest"].lifecycle == "validated"

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_asset_promote_rejects_failing_stability_check(vault_pool):
    minio = get_minio_client()
    pack_id = "identity/TEST-PROMOTE-FAIL"
    await _cleanup(vault_pool, pack_id)

    await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="x",
        version="1.0.0",
        files={"refs/front.png": b"v1"},
    )
    with pytest.raises(ValueError, match="not passed"):
        await asset_promote(
            vault_pool,
            pack_id=pack_id,
            version="1.0.0",
            stability_check=StabilityCheck(passed=False, score="1/3"),
        )

    resolved = await asset_resolve(vault_pool, pack_id=pack_id)
    assert resolved["manifest"].lifecycle == "draft"  # 未通过则不改状态

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_asset_promote_unknown_version_raises(vault_pool):
    with pytest.raises(KeyError):
        await asset_promote(
            vault_pool,
            pack_id="identity/DOES-NOT-EXIST",
            version="9.9.9",
            stability_check=StabilityCheck(passed=True, score="3/3"),
        )
