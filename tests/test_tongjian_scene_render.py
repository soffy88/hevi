"""L6 场景与画面生成 + G6 校验门测试。

CLIP/VLM 打分本身(真的能不能分辨"像不像"/"文不对题")由 test_subject_embed.py
的真实 CLIP 测试覆盖;这里 mock _score_frame 只测试 render_shot/build_frame_manifest
的 reroll/降级链/门控编排逻辑本身。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from hevi.tongjian.schemas import (
    CharacterBible,
    CharacterBibleEntry,
    Constitution,
    SceneAsset,
    Shot,
    ShotList,
    VisualStyle,
)
from hevi.tongjian.scene_render import (
    build_frame_manifest,
    gate_frame_manifest,
    generate_scene_assets,
    render_shot,
)

CONSTITUTION = Constitution(
    visual_style=VisualStyle(art_direction="水墨质感历史插画", palette=["#2b2b2b"])
)


def _make_bible() -> CharacterBible:
    return CharacterBible(
        characters=[
            CharacterBibleEntry(
                character_id="C001",
                name="智伯",
                appearance="魁伟美髯",
                ref_image="refs/c001.png",
                gen_lock={"seed": 1, "ip_adapter_weight": 0.6},
            ),
        ]
    )


def _mock_image_gen() -> AsyncMock:
    async def _gen(*, prompt, output_path, seed, extra):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-png")
        return {"output_path": str(output_path), "seed": seed}

    return AsyncMock(side_effect=_gen)


def _score(clip_score: float, consistency: float | None, passed_audit: bool) -> tuple:
    return (clip_score, consistency, passed_audit)


# ── generate_scene_assets ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scene_assets_dedup_by_scene_id(tmp_path):
    shotlist = ShotList(
        shots=[
            Shot(shot_id="SH001", scene_id="E001", visual_prompt="宫殿夜宴"),
            Shot(shot_id="SH002", scene_id="E001", visual_prompt="宫殿夜宴,近景"),
            Shot(shot_id="SH003", scene_id="E002", visual_prompt="城墙"),
        ]
    )
    image_gen = _mock_image_gen()

    scenes = await generate_scene_assets(
        shotlist, CONSTITUTION, output_dir=tmp_path, image_gen=image_gen
    )

    assert set(scenes.keys()) == {"E001", "E002"}
    assert image_gen.await_count == 2  # 同 scene_id 只生成一次,不是每个 shot 都生成


@pytest.mark.asyncio
async def test_scene_asset_generation_failure_excluded(tmp_path):
    shotlist = ShotList(shots=[Shot(shot_id="SH001", scene_id="E001", visual_prompt="x")])
    image_gen = AsyncMock(side_effect=RuntimeError("GPU OOM"))

    scenes = await generate_scene_assets(
        shotlist, CONSTITUTION, output_dir=tmp_path, image_gen=image_gen
    )

    assert scenes == {}


# ── render_shot(reroll + 降级链)──────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_shot_passes_first_attempt(tmp_path):
    shot = Shot(shot_id="SH001", scene_id="E001", visual_prompt="智伯举杯", characters=["C001"])
    scene = SceneAsset(scene_id="E001", image_path=str(tmp_path / "scene.png"), prompt="p")
    image_gen = _mock_image_gen()

    with patch(
        "hevi.tongjian.scene_render._score_frame", AsyncMock(return_value=_score(0.3, 0.7, True))
    ):
        frame = await render_shot(
            shot,
            scene,
            _make_bible(),
            None,
            output_dir=tmp_path,
            image_gen=image_gen,
            vlm=AsyncMock(),
        )

    assert not frame.degraded
    assert frame.characters == ["C001"]
    assert frame.frame_path == str(tmp_path / "sh001_v0.png")
    image_gen.assert_awaited_once()


@pytest.mark.asyncio
async def test_render_shot_rerolls_then_passes(tmp_path):
    shot = Shot(shot_id="SH001", scene_id="E001", visual_prompt="智伯举杯", characters=["C001"])
    scene = SceneAsset(scene_id="E001", image_path=str(tmp_path / "scene.png"), prompt="p")
    image_gen = _mock_image_gen()
    scores = AsyncMock(side_effect=[_score(0.05, 0.7, True), _score(0.3, 0.7, True)])

    with patch("hevi.tongjian.scene_render._score_frame", scores):
        frame = await render_shot(
            shot,
            scene,
            _make_bible(),
            None,
            output_dir=tmp_path,
            image_gen=image_gen,
            vlm=AsyncMock(),
        )

    assert not frame.degraded
    assert frame.frame_path == str(tmp_path / "sh001_v1.png")
    assert image_gen.await_count == 2


@pytest.mark.asyncio
async def test_render_shot_degrades_to_scene_only_after_max_rerolls(tmp_path):
    shot = Shot(shot_id="SH001", scene_id="E001", visual_prompt="智伯举杯", characters=["C001"])
    scene = SceneAsset(scene_id="E001", image_path=str(tmp_path / "scene.png"), prompt="p")
    image_gen = _mock_image_gen()
    # 3 次 reroll 都不达标(consistency 太低),第4次(丢角色的场景空镜)达标
    scores = AsyncMock(
        side_effect=[
            _score(0.3, 0.1, True),
            _score(0.3, 0.1, True),
            _score(0.3, 0.1, True),
            _score(0.3, None, True),
        ]
    )

    with patch("hevi.tongjian.scene_render._score_frame", scores):
        frame = await render_shot(
            shot,
            scene,
            _make_bible(),
            None,
            output_dir=tmp_path,
            image_gen=image_gen,
            vlm=AsyncMock(),
            max_rerolls=3,
        )

    assert frame.degraded
    assert "场景空镜" in frame.degrade_reason
    assert frame.characters == []
    assert image_gen.await_count == 4  # 3 reroll + 1 scene-only


@pytest.mark.asyncio
async def test_render_shot_falls_back_to_adjacent_scene_when_all_generation_fails(tmp_path):
    shot = Shot(shot_id="SH001", scene_id="E001", visual_prompt="智伯举杯", characters=["C001"])
    scene = SceneAsset(scene_id="E001", image_path=str(tmp_path / "scene.png"), prompt="p")
    fallback = SceneAsset(scene_id="E000", image_path=str(tmp_path / "adjacent.png"), prompt="q")
    image_gen = AsyncMock(side_effect=RuntimeError("GPU OOM"))

    frame = await render_shot(
        shot,
        scene,
        _make_bible(),
        fallback,
        output_dir=tmp_path,
        image_gen=image_gen,
        vlm=AsyncMock(),
        max_rerolls=2,
    )

    assert frame.degraded
    assert frame.frame_path == fallback.image_path
    assert "相邻场景" in frame.degrade_reason


@pytest.mark.asyncio
async def test_render_shot_without_characters_skips_consistency_check(tmp_path):
    shot = Shot(shot_id="SH001", scene_id="E001", visual_prompt="城墙远景", characters=[])
    scene = SceneAsset(scene_id="E001", image_path=str(tmp_path / "scene.png"), prompt="p")
    image_gen = _mock_image_gen()

    with patch(
        "hevi.tongjian.scene_render._score_frame", AsyncMock(return_value=_score(0.3, None, True))
    ):
        frame = await render_shot(
            shot,
            scene,
            _make_bible(),
            None,
            output_dir=tmp_path,
            image_gen=image_gen,
            vlm=AsyncMock(),
        )

    assert not frame.degraded
    image_gen.assert_awaited_once()


# ── build_frame_manifest + gate_frame_manifest ───────────────────────────


@pytest.mark.asyncio
async def test_build_frame_manifest_end_to_end(tmp_path):
    shotlist = ShotList(
        shots=[
            Shot(shot_id="SH001", scene_id="E001", visual_prompt="智伯举杯", characters=["C001"]),
            Shot(shot_id="SH002", scene_id="E001", visual_prompt="旁白", characters=[]),
        ]
    )
    image_gen = _mock_image_gen()

    with patch(
        "hevi.tongjian.scene_render._score_frame", AsyncMock(return_value=_score(0.3, 0.7, True))
    ):
        manifest, result = await build_frame_manifest(
            shotlist,
            _make_bible(),
            CONSTITUTION,
            output_dir=tmp_path,
            image_gen=image_gen,
            vlm=AsyncMock(),
        )

    assert result.passed
    assert len(manifest.frames) == 2
    assert len(manifest.scenes) == 1  # 两个 shot 共用一个场景


def test_gate_reports_open_sky_as_error():
    from hevi.tongjian.schemas import FrameManifest, ShotFrame

    shotlist = ShotList(shots=[Shot(shot_id="SH001", scene_id="E001")])
    manifest = FrameManifest(frames=[ShotFrame(shot_id="SH001", scene_id="E001", frame_path="")])

    result = gate_frame_manifest(manifest, shotlist)

    assert not result.passed
    assert any("开天窗" in e for e in result.errors)


def test_gate_reports_degraded_as_warning_not_error():
    from hevi.tongjian.schemas import FrameManifest, ShotFrame

    shotlist = ShotList(shots=[Shot(shot_id="SH001", scene_id="E001")])
    manifest = FrameManifest(
        frames=[
            ShotFrame(
                shot_id="SH001",
                scene_id="E001",
                frame_path="x.png",
                degraded=True,
                degrade_reason="复用相邻场景底图",
            ),
        ]
    )

    result = gate_frame_manifest(manifest, shotlist)

    assert result.passed
    assert any("降级链" in w for w in result.warnings)
