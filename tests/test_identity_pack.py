"""hevi.vault.identity_pack —— HEVI-EXEC-01 M2 身份包构建测试。

lint/grid 是纯函数,真测;build_identity_pack 打真实 hevi-vault DB(同 test_vault.py
惯例,不 mock PgPool/MinIO),但 mock 掉所有外部生成 provider(image_gen/vlm/tts_fn/
video_gen)——这些是 SDXL/Vidu/CosyVoice 的真实调用,会花钱或需要真实模型权重,
不适合在单测里打真的(同 L5/L6 character_bible/scene_render 测试的既有惯例)。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hevi.core.config import settings
from hevi.cost.circuit_breaker import CostLimit, CostLimitExceeded
from hevi.vault import (
    asset_resolve,
    build_identity_pack,
    get_minio_client,
    get_vault_pg_pool,
    init_vault_schema,
    lint_shot_prompt,
)
from hevi.vault.identity_pack import _compose_grid, _stability_precheck


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


def _mock_image_gen() -> AsyncMock:
    from PIL import Image

    async def _gen(*, prompt, output_path, extra, seed=None):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), (180, 60, 40)).save(output_path)
        return {"output_path": str(output_path), "seed": seed}

    return AsyncMock(side_effect=_gen)


def _mock_vlm(passes: bool = True) -> AsyncMock:
    return AsyncMock(return_value={"content": f'{{"passes": {str(passes).lower()}}}'})


def _mock_tts_fn() -> AsyncMock:
    async def _tts(*, script, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-wav-bytes")
        return output_path

    return AsyncMock(side_effect=_tts)


def _mock_video_gen() -> AsyncMock:
    async def _gen(*, prompt, reference_images, output_path, duration):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-mp4-bytes")
        return output_path

    return AsyncMock(side_effect=_gen)


# ── lint_shot_prompt(§11.1 规则1)────────────────────────────────────────


class TestLintShotPrompt:
    def test_flags_identity_word_in_prompt(self):
        violations = lint_shot_prompt("智伯站在殿前,玄色深衣飘动", "玄色深衣,束发玉冠")
        assert "玄色深衣" in violations

    def test_clean_prompt_returns_empty(self):
        violations = lint_shot_prompt("智伯站在殿前,举杯", "玄色深衣,束发玉冠")
        assert violations == []

    def test_ignores_short_fragments(self):
        # 切词后碎片 <2 字的不参与比对,减少误报
        violations = lint_shot_prompt("智伯站在殿前", "深衣,冠")
        assert violations == []


# ── _compose_grid(纯 PIL 拼图)────────────────────────────────────────────


class TestComposeGrid:
    def test_composes_expected_grid_size(self, tmp_path):
        from PIL import Image

        paths = []
        for i in range(4):
            p = tmp_path / f"v{i}.png"
            Image.new("RGB", (32, 32), (i * 50, 0, 0)).save(p)
            paths.append(p)

        out = _compose_grid(paths, tmp_path / "grid.png", cols=2)

        assert out.exists()
        img = Image.open(out)
        assert img.size == (64, 64)  # 2x2 格,每格 32x32


# ── _stability_precheck ───────────────────────────────────────────────────


class TestStabilityPrecheck:
    @pytest.mark.asyncio
    async def test_all_pass_gives_full_score(self, tmp_path):
        stability, canonical = await _stability_precheck(
            appearance="魁伟美髯",
            era_lock="战国早期服制",
            art_direction="水墨",
            character_id="C001",
            output_dir=tmp_path,
            image_gen=_mock_image_gen(),
            vlm=_mock_vlm(passes=True),
        )
        assert stability.passed is True
        assert stability.score == "3/3"
        assert canonical.exists()

    @pytest.mark.asyncio
    async def test_all_fail_vlm_audit_gives_failing_score(self, tmp_path):
        stability, canonical = await _stability_precheck(
            appearance="魁伟美髯",
            era_lock="战国早期服制",
            art_direction="水墨",
            character_id="C002",
            output_dir=tmp_path,
            image_gen=_mock_image_gen(),
            vlm=_mock_vlm(passes=False),
        )
        assert stability.passed is False
        assert stability.score == "0/3"

    @pytest.mark.asyncio
    async def test_image_gen_failure_counts_as_not_passed(self, tmp_path):
        image_gen = AsyncMock(side_effect=RuntimeError("GPU OOM"))
        stability, canonical = await _stability_precheck(
            appearance="x",
            era_lock="y",
            art_direction="z",
            character_id="C003",
            output_dir=tmp_path,
            image_gen=image_gen,
            vlm=_mock_vlm(passes=True),
        )
        assert stability.passed is False
        assert stability.score == "0/3"


# ── build_identity_pack(真实 vault DB + mock 生成 provider)────────────────


@pytest.mark.asyncio
async def test_build_identity_pack_skips_video_and_promotes(vault_pool, tmp_path):
    minio = get_minio_client()
    pack_id = "identity/TEST-C001"
    await _cleanup(vault_pool, pack_id)

    manifest = await build_identity_pack(
        pool=vault_pool,
        minio_client=minio,
        character_id="TEST-C001",
        name="智伯",
        appearance="魁伟美髯,玄色深衣",
        era_lock="战国早期服制",
        art_direction="水墨",
        output_dir=tmp_path,
        image_gen=_mock_image_gen(),
        vlm=_mock_vlm(passes=True),
        tts_fn=_mock_tts_fn(),
        build_turnaround_video=False,
    )

    assert manifest.lifecycle == "validated"
    assert manifest.stability_check.passed is True
    assert "refs/front.png" in manifest.files
    assert "refs/grid9.png" in manifest.files
    assert "refs/action_pose.png" in manifest.files
    assert "refs/voice_8s.wav" in manifest.files
    assert "refs/turn_5s.mp4" not in manifest.files  # 跳过了视频
    assert manifest.voice["tts_voice_id"] == "cosyvoice:test-c001_cloned"
    assert manifest.embeddings["face"]["dim"] == 512

    resolved = await asset_resolve(vault_pool, pack_id=pack_id)
    assert resolved["manifest"].lifecycle == "validated"

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_build_identity_pack_with_turnaround_video(vault_pool, tmp_path):
    minio = get_minio_client()
    pack_id = "identity/TEST-C002"
    await _cleanup(vault_pool, pack_id)

    manifest = await build_identity_pack(
        pool=vault_pool,
        minio_client=minio,
        character_id="TEST-C002",
        name="段规",
        appearance="中年谋士",
        era_lock="战国早期服制",
        art_direction="水墨",
        output_dir=tmp_path,
        image_gen=_mock_image_gen(),
        vlm=_mock_vlm(passes=True),
        tts_fn=_mock_tts_fn(),
        video_gen=_mock_video_gen(),
        build_turnaround_video=True,
    )

    assert "refs/turn_5s.mp4" in manifest.files

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_build_identity_pack_stays_draft_when_stability_fails(vault_pool, tmp_path):
    minio = get_minio_client()
    pack_id = "identity/TEST-C003"
    await _cleanup(vault_pool, pack_id)

    manifest = await build_identity_pack(
        pool=vault_pool,
        minio_client=minio,
        character_id="TEST-C003",
        name="韩康子",
        appearance="老臣",
        era_lock="战国早期服制",
        art_direction="水墨",
        output_dir=tmp_path,
        image_gen=_mock_image_gen(),
        vlm=_mock_vlm(passes=False),
        tts_fn=_mock_tts_fn(),
        build_turnaround_video=False,
    )

    assert manifest.lifecycle == "draft"
    assert manifest.stability_check.passed is False

    await _cleanup(vault_pool, pack_id)


@pytest.mark.asyncio
async def test_build_identity_pack_respects_cost_limit(vault_pool, tmp_path):
    minio = get_minio_client()
    pack_id = "identity/TEST-C004"
    await _cleanup(vault_pool, pack_id)

    with pytest.raises(CostLimitExceeded):
        await build_identity_pack(
            pool=vault_pool,
            minio_client=minio,
            character_id="TEST-C004",
            name="x",
            appearance="x",
            era_lock="x",
            art_direction="x",
            output_dir=tmp_path,
            image_gen=_mock_image_gen(),
            vlm=_mock_vlm(passes=True),
            tts_fn=_mock_tts_fn(),
            video_gen=_mock_video_gen(),
            build_turnaround_video=True,
            cost_limit=CostLimit(max_per_task_usd=0.01),
        )

    await _cleanup(vault_pool, pack_id)
