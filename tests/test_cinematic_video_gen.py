"""C6 视频生成 + CG6 门 + 降级链测试。打真实 hevi-vault DB(同 test_identity_pack.py
的既有惯例),mock video_gen/vlm(那些是 Vidu/本地 VLM 的真实调用,会花钱或需要真实
模型权重)。ffmpeg 抽帧/抽音轨/静帧兜底是真实调用(这台机器装了 ffmpeg,同
test_tongjian_assemble.py 的既有惯例)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from hevi.cinematic.schemas import BeatDialogue, CineShot, CineShotCamera
from hevi.cinematic.video_gen import _seed_for, generate_shot
from hevi.core.config import settings
from hevi.cost.circuit_breaker import CostLimit, CostTracker
from hevi.subjects.subject_embed import subject_embed
from hevi.vault import (
    asset_create,
    get_minio_client,
    get_vault_pg_pool,
    init_vault_schema,
    store_embedding,
)


def test_seed_for_stays_within_signed_32bit_range():
    """阿里云百炼 happyhorse-1.1-r2v 实测:seed 必须在 [0, 2147483647]——早先 8 位 hex
    没做位数收窄,能到 4294967295,超出这个范围导致 InvalidParameter 直接生成失败。"""
    for shot_id in ["SH01", "SH02", "B_zhibo1", ""]:
        for attempt in range(10):
            seed = _seed_for(shot_id, attempt)
            assert 0 <= seed <= 2147483647


def test_seed_for_is_deterministic():
    assert _seed_for("SH01", 0) == _seed_for("SH01", 0)
    assert _seed_for("SH01", 0) != _seed_for("SH01", 1)


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


@pytest.fixture
async def test_pack(vault_pool, tmp_path):
    """一个最小可用的测试身份包:真实 PNG + 真实 CLIP embedding 落进 vault,
    模拟 M2 identity pack 的产出。"""
    pack_id = "identity/test-cine-char"
    await _cleanup(vault_pool, pack_id)
    minio = get_minio_client()

    # 用一张有真实内容结构的图(不是纯色块)当参考像——纯色合成图的 CLIP embedding
    # 缺乏区分度,会让"跟纯黑测试视频对比"这个反例场景意外通过,不是真实场景会遇到
    # 的情况(见 M2 identity pack 的真实肖像 vs 纯黑视频,实测距离 0.489,稳定不通过)。
    real_portrait = Path("output/vault/identity/zhibo/portrait_v0.png")
    portrait_path = tmp_path / "front.png"
    if real_portrait.exists():
        portrait_path.write_bytes(real_portrait.read_bytes())
    else:
        Image.new("RGB", (256, 256), (120, 60, 40)).save(portrait_path)
    action_path = tmp_path / "action_pose.png"
    Image.new("RGB", (64, 64), (80, 100, 60)).save(action_path)

    embedding = subject_embed(image_path=portrait_path, kind="face")
    manifest = await asset_create(
        vault_pool,
        minio,
        pack_id=pack_id,
        pack_type="identity",
        name="测试角色",
        version="0.1.0",
        files={
            "refs/front.png": portrait_path.read_bytes(),
            "refs/action_pose.png": action_path.read_bytes(),
        },
        file_roles={"refs/front.png": "canonical_portrait", "refs/action_pose.png": "action_pose"},
    )
    await store_embedding(
        vault_pool, pack_id=pack_id, version="0.1.0", kind="identity", embedding=embedding
    )

    yield pack_id
    await _cleanup(vault_pool, pack_id)


def _make_shot(character_id: str, *, with_dialogue: bool = False) -> CineShot:
    dialogue = BeatDialogue(speaker=character_id, text="测试台词。") if with_dialogue else None
    return CineShot(
        shot_id="SH_TEST",
        scene_id="SC_TEST",
        beat_ids=["B1"],
        pack_ids=[character_id],
        shot_size="medium_close",
        camera=CineShotCamera(shot_size="medium_close"),
        on_screen=[character_id],
        dialogue_inline=dialogue,
        est_duration_s=3.0,
        prompt="test prompt",
    )


async def _mock_video_gen_black(*, prompt, reference_images, output_path, duration, seed=None):
    """产出一段跟身份包毫不相关的纯黑视频——CG6 的身份检查应该正确拒绝它,
    这是测试 reroll/降级链的关键前提,不是缺陷。"""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=320x240:d={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )


async def _mock_vlm_always_pass(*, messages, image_paths, max_tokens=300):
    return {"content": '{"passes": true, "violations": []}'}


@pytest.mark.asyncio
async def test_generate_shot_degrades_to_static_frame_when_identity_never_matches(
    vault_pool, test_pack
):
    """身份始终不匹配(mock 视频是纯黑,跟身份包毫无关系)→ reroll 3 次 → 降级为
    旁白转述 → 仍不过 → 最终静帧+推拉兜底,任何情况下都要有产出(不允许开天窗)。"""
    character_id = test_pack.split("/")[-1]
    shot = _make_shot(character_id, with_dialogue=True)
    tracker = CostTracker()

    result = await generate_shot(
        shot,
        vault_pool,
        get_minio_client(),
        video_gen=_mock_video_gen_black,
        vlm=_mock_vlm_always_pass,
        cost_limit=CostLimit(max_per_task_usd=20.0),
        cost_tracker=tracker,
    )

    assert result.output_path  # 任何情况下都要有产出
    assert result.degraded is True
    assert Path(result.output_path).exists()
    assert result.cg6.identity_passed is False
    assert tracker.spent_usd > 0


@pytest.mark.asyncio
async def test_generate_shot_records_lineage_on_success(vault_pool, test_pack):
    character_id = test_pack.split("/")[-1]
    shot = _make_shot(character_id, with_dialogue=False)

    result = await generate_shot(
        shot,
        vault_pool,
        get_minio_client(),
        run_id="a5f3b1c0-1234-4a4a-9abc-1234567890ab",
        video_gen=_mock_video_gen_black,
        vlm=_mock_vlm_always_pass,
        cost_limit=CostLimit(max_per_task_usd=20.0),
    )

    assert result.output_path
    async with vault_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM vault_lineage WHERE shot_id=$1 AND pack_id=$2",
            "SH_TEST",
            f"identity/{character_id}",
        )
    assert len(rows) == 1
    assert str(rows[0]["run_id"]) == "a5f3b1c0-1234-4a4a-9abc-1234567890ab"

    async with vault_pool.acquire() as conn:
        await conn.execute("DELETE FROM vault_lineage WHERE shot_id=$1", "SH_TEST")


@pytest.mark.asyncio
async def test_generate_shot_no_on_screen_character_skips_identity_check(vault_pool):
    """establishing 这类没有绑定具体角色 pack 的镜头(on_screen 为空)不应该尝试
    做身份检查,应该直接接受生成结果。"""
    shot = CineShot(
        shot_id="SH_EMPTY",
        scene_id="SC_TEST",
        shot_size="wide",
        camera=CineShotCamera(shot_size="wide"),
        on_screen=[],
        est_duration_s=6.0,
        prompt="establishing shot",
    )
    result = await generate_shot(
        shot,
        vault_pool,
        get_minio_client(),
        video_gen=_mock_video_gen_black,
        vlm=_mock_vlm_always_pass,
        cost_limit=CostLimit(max_per_task_usd=20.0),
    )
    assert result.cg6.passed is True
    assert result.degraded is False
