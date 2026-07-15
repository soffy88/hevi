"""平台绑定懒同步测试——打真实 hevi-vault DB(同 test_identity_pack.py 的既有惯例,
不 mock PgPool)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.cinematic.platform_binding import ensure_platform_binding
from hevi.core.config import settings
from hevi.vault import get_vault_pg_pool, init_vault_schema
from hevi.vault.service import get_platform_binding


async def _cleanup(pool, pack_id: str, version: str, platform: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM vault_platform_bindings WHERE pack_id=$1 AND version=$2 AND platform=$3",
            pack_id,
            version,
            platform,
        )


@pytest.fixture
async def vault_pool():
    await init_vault_schema(settings.vault_database_url)
    pool = await get_vault_pg_pool()
    yield pool


@pytest.mark.asyncio
async def test_ensure_platform_binding_writes_and_returns_data_uris(vault_pool, tmp_path):
    pack_id, version, platform = "identity/TEST-PB001", "0.1.0", "vidu"
    await _cleanup(vault_pool, pack_id, version, platform)

    img_path = tmp_path / "front.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")

    uris = await ensure_platform_binding(
        vault_pool, pack_id=pack_id, version=version, platform=platform, image_paths=[img_path]
    )

    assert len(uris) == 1
    assert uris[0].startswith("data:image/png;base64,")

    binding = await get_platform_binding(
        vault_pool, pack_id=pack_id, version=version, platform=platform
    )
    assert binding is not None
    assert binding["status"] == "active"
    assert binding["remote_kind"] == "reference_image"

    await _cleanup(vault_pool, pack_id, version, platform)


@pytest.mark.asyncio
async def test_ensure_platform_binding_reuses_existing_record_on_second_call(vault_pool, tmp_path):
    pack_id, version, platform = "identity/TEST-PB002", "0.1.0", "vidu"
    await _cleanup(vault_pool, pack_id, version, platform)

    img_path = tmp_path / "front.png"
    img_path.write_bytes(b"same-bytes")

    await ensure_platform_binding(
        vault_pool, pack_id=pack_id, version=version, platform=platform, image_paths=[img_path]
    )
    first = await get_platform_binding(
        vault_pool, pack_id=pack_id, version=version, platform=platform
    )

    # 第二次调用(同一张图):remote_ref_id(本地 sha256)应该保持一致,因为内容没变。
    await ensure_platform_binding(
        vault_pool, pack_id=pack_id, version=version, platform=platform, image_paths=[img_path]
    )
    second = await get_platform_binding(
        vault_pool, pack_id=pack_id, version=version, platform=platform
    )

    assert first["remote_ref_id"] == second["remote_ref_id"]

    await _cleanup(vault_pool, pack_id, version, platform)


@pytest.mark.asyncio
async def test_get_platform_binding_returns_none_when_absent(vault_pool):
    result = await get_platform_binding(
        vault_pool, pack_id="identity/NONEXISTENT", version="0.1.0", platform="vidu"
    )
    assert result is None
