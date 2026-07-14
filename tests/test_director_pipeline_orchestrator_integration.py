"""SPEC-003:orchestrate_longvideo 消费 locked_shot_list/shot_character_refs 的集成测试。

跟 test_pipeline_degradation.py 同一手法——patch omodul 的 agentic_longvideo_pipeline
为"假 omodul",但这里假 omodul 还要按真实 omodul 的调用顺序触发
script_fn → storyboard_fn → shot_gen_fn(真实序列见 omodul/agentic_longvideo_pipeline.py:
132-150),才能验证锁定 ShotList 真的能通过这三个规划期钩子转成 oskill 认识的形状,
而不是只测"provider 被调用"这种表面结果。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from omodul.agentic_longvideo_pipeline import LongVideoResult

from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo
from hevi.providers.registry import ProviderRegistry, register_all_providers


@pytest.fixture(autouse=True)
def _providers():
    register_all_providers()
    yield


def _locked_shot_list() -> dict:
    return {
        "shots": [
            {
                "shot_id": "SH001_01",
                "scene_no": 1,
                "visual_prompt": "二人对峙",
                "dialogue_lines": [
                    {"character_name": "智伯", "text": "把地给我。"},
                    {"character_name": "韩康子", "text": "不给。"},
                ],
                "character_names": ["智伯", "韩康子"],
                "duration_s": 6.0,
            },
            {
                "shot_id": "SH002_01",
                "scene_no": 2,
                "visual_prompt": "史官旁白",
                "dialogue_lines": [{"character_name": "", "text": "三家终于罢兵。"}],
                "duration_s": 4.0,
            },
        ]
    }


@pytest.mark.asyncio
async def test_locked_shot_list_produces_multi_speaker_dialogues_and_shot_plans(tmp_path):
    """治"只有旁白没对白":真实走一遍 script_fn→storyboard_fn→shot_gen_fn,验证
    产出的 chapter.dialogues 每行都带正确 speaker_id,shot_gen_fn 产出的 plans 数量
    跟锁定的镜头数一致。"""
    captured: dict = {}

    async def fake_pipeline(*, config, _providers):
        chapter_script = await _providers["script_fn"]()
        captured["dialogues"] = chapter_script.chapters[0].dialogues
        all_plans = []
        for chapter in chapter_script.chapters:
            storyboard = await _providers["storyboard_fn"](script=chapter, llm=None)
            plans = await _providers["shot_gen_fn"](storyboard=storyboard, llm=None)
            all_plans.extend(plans)
        captured["plans"] = all_plans

        config.output_dir.mkdir(parents=True, exist_ok=True)
        vp = config.output_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=10.0,
            chapters=1,
            shots_generated=len(all_plans),
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="英雄对峙",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            locked_shot_list=_locked_shot_list(),
        )

    speakers = [(d.speaker_id, d.text) for d in captured["dialogues"]]
    assert speakers == [
        ("智伯", "把地给我。"),
        ("韩康子", "不给。"),
        ("", "三家终于罢兵。"),
    ]
    assert len(captured["plans"]) == 2
    assert captured["plans"][0].shot_id == "SH001_01"
    assert captured["plans"][0].duration_s == 6.0


@pytest.mark.asyncio
async def test_no_locked_shot_list_leaves_script_fn_unregistered(tmp_path):
    """零回归:不传 locked_shot_list → 不注入 script_fn(旧路径走 oskill 自己的
    script_writer,不受这次改动影响)。"""
    captured: dict = {}

    async def fake_pipeline(*, config, _providers):
        captured["has_script_fn"] = "script_fn" in _providers
        config.output_dir.mkdir(parents=True, exist_ok=True)
        vp = config.output_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
        )

    assert captured["has_script_fn"] is False


@pytest.mark.asyncio
async def test_shot_character_refs_overrides_per_shot_reference_image(tmp_path):
    """治"人物/场景乱跳":命中 shot_character_refs 的镜头用自己的角色参考图,不是
    全片统一的那张 character_reference。"""
    char_a = tmp_path / "char_a.jpg"
    char_a.write_bytes(b"\xff\xd8\xff\xe0a")
    global_ref = tmp_path / "global.jpg"
    global_ref.write_bytes(b"\xff\xd8\xff\xe0g")

    seen: list[dict] = []

    async def capturing_video(**kwargs):
        seen.append({"reference_image": kwargs.get("reference_image")})
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", capturing_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
        await vfn(prompt="p", output_path=shots / "shot_0000_v0.mp4", reference_image=None)
        vp = tmp_path / "task" / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            character_reference=str(global_ref),
            shot_character_refs={0: [str(char_a)]},
        )

    assert seen[0]["reference_image"] == char_a  # 不是 global_ref


@pytest.mark.asyncio
async def test_shot_character_refs_missing_falls_back_to_global_reference(tmp_path):
    """没在 shot_character_refs 里出现的镜头,继续用全片统一的 character_reference——
    零回归。"""
    global_ref = tmp_path / "global.jpg"
    global_ref.write_bytes(b"\xff\xd8\xff\xe0g")
    seen: list[dict] = []

    async def capturing_video(**kwargs):
        seen.append({"reference_image": kwargs.get("reference_image")})
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", capturing_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
        await vfn(prompt="p", output_path=shots / "shot_0000_v0.mp4", reference_image=None)
        vp = tmp_path / "task" / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            character_reference=str(global_ref),
            shot_character_refs={5: ["/nonexistent/other_shot.jpg"]},  # 不是 shot 0
        )

    assert seen[0]["reference_image"] == global_ref


@pytest.mark.asyncio
async def test_shot_character_refs_multi_char_composes_via_qwen_image_edit(tmp_path):
    """2+ 张走 SPEC-002 B2 同一个 qwen-image-edit 多图合成原语,不是简单拼接/只取第一张。"""
    char_a = tmp_path / "char_a.jpg"
    char_a.write_bytes(b"\xff\xd8\xff\xe0a")
    char_b = tmp_path / "char_b.jpg"
    char_b.write_bytes(b"\xff\xd8\xff\xe0b")
    seen: list[dict] = []

    async def capturing_video(**kwargs):
        seen.append({"reference_image": kwargs.get("reference_image")})
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", capturing_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_qwen_edit(*, image_path, instruction, output_path, **_kw):
        assert len(image_path) == 2
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x00" * 4096)
        return output_path

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
        await vfn(prompt="p", output_path=shots / "shot_0000_v0.mp4", reference_image=None)
        vp = tmp_path / "task" / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            side_effect=fake_pipeline,
        ),
        patch("hevi.image.qwen_image_service.qwen_image_edit", fake_qwen_edit),
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            shot_character_refs={0: [str(char_a), str(char_b)]},
        )

    assert seen[0]["reference_image"] == Path(tmp_path / "task" / "shot_0_character_roster.png")
