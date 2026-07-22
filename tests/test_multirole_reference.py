"""hevi.director.multirole_reference 测试 — 纯函数 + gen_fn 注入 AsyncMock,不碰真实
网络/GPU(多角色同框能力上一轮已用 $0.72 真机验证过,这里只测代码迁移本身)。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from hevi.director.multirole_reference import (
    build_reference_images,
    compile_multirole_prompt,
    generate_multirole_segment,
    positive_rephrase_negatives,
    requires_multirole_reference,
)
from hevi.director.pipeline_schemas import (
    CharacterVolumeEntry,
    InitialPosition,
    SceneBlocking,
    SceneScriptDialogueLine,
    SceneScriptSegment,
    SceneStage,
    VisualVolume,
    WorldBible,
)


def test_requires_multirole_reference_boundary() -> None:
    assert requires_multirole_reference([]) is False
    assert requires_multirole_reference(["王生"]) is False
    assert requires_multirole_reference(["王生", "老道士"]) is True
    assert requires_multirole_reference(["王生", "老道士", "店家"]) is True


def _stage(*positions: InitialPosition) -> SceneStage:
    return SceneStage(scene_ref=2, blocking=SceneBlocking(initial_positions=list(positions)))


def test_compile_multirole_prompt_with_scene_plate_numbers_from_image_2() -> None:
    stage = _stage(
        InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"),
        InitialPosition(char_id="老道士", posture="直立", facing="正面垂视"),
    )
    prompt = compile_multirole_prompt(
        action_text="王生跪求收留",
        scene_stage=stage,
        character_names=["王生", "老道士"],
        scene_plate_path=Path("/tmp/plate.png"),
    )
    assert "[Image 1] 是这场戏的空景参考图" in prompt
    assert "[Image 2] 是王生的身份参考图" in prompt
    assert "姿态:跪伏,朝向:俯身叩首" in prompt
    assert "[Image 3] 是老道士的身份参考图" in prompt
    assert "王生跪求收留" in prompt
    assert "不要融合成同一张脸" in prompt


def test_compile_multirole_prompt_without_scene_plate_numbers_from_image_1() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    prompt = compile_multirole_prompt(
        action_text="王生独自行走",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=None,
    )
    assert "空景参考图" not in prompt
    assert "[Image 1] 是王生的身份参考图" in prompt


def test_compile_multirole_prompt_missing_blocking_data_does_not_crash() -> None:
    stage = _stage()  # 没有任何 blocking 数据
    prompt = compile_multirole_prompt(
        action_text="两人对话",
        scene_stage=stage,
        character_names=["王生", "老道士"],
        scene_plate_path=None,
    )
    assert "[Image 1] 是王生的身份参考图" in prompt
    assert "[Image 2] 是老道士的身份参考图" in prompt
    # 没有 blocking 数据时不应该出现空的"姿态:,朝向:"这种半成品文本
    assert "姿态:" not in prompt


def test_compile_multirole_prompt_continuity_reference_numbered_after_scene_plate() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    prompt = compile_multirole_prompt(
        action_text="王生起身",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=Path("/tmp/plate.png"),
        continuity_reference_path=Path("/tmp/prev_frame.png"),
    )
    assert "[Image 1] 是这场戏的空景参考图" in prompt
    assert "[Image 2] 是上一段结尾的真实画面" in prompt
    assert "紧接这张图里的人物位置" in prompt
    assert "[Image 3] 是王生的身份参考图" in prompt


def test_compile_multirole_prompt_continuity_reference_without_scene_plate_starts_at_1() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    prompt = compile_multirole_prompt(
        action_text="王生起身",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=None,
        continuity_reference_path=Path("/tmp/prev_frame.png"),
    )
    assert "[Image 1] 是上一段结尾的真实画面" in prompt
    assert "[Image 2] 是王生的身份参考图" in prompt


def test_compile_multirole_prompt_injects_style_manifesto_before_action_text() -> None:
    # style-lock 摸查①落地(2026-07-20):有 world_bible.visual.style_manifesto 时,
    # 每段统一插一次,且必须排在 action_text 之前(风格先声明,动作再描述)。
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    wb = WorldBible(visual=VisualVolume(style_manifesto="水墨渗染质感，留白式构图"))
    prompt = compile_multirole_prompt(
        action_text="王生起身",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=None,
        world_bible=wb,
    )
    assert "【整体美术风格,这一帧必须遵守】水墨渗染质感，留白式构图" in prompt
    assert prompt.index("整体美术风格") < prompt.index("王生起身")


def test_compile_multirole_prompt_without_world_bible_unchanged() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    prompt = compile_multirole_prompt(
        action_text="王生起身", scene_stage=stage, character_names=["王生"], scene_plate_path=None
    )
    assert "整体美术风格" not in prompt


def test_compile_multirole_prompt_empty_style_manifesto_not_injected() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    wb = WorldBible(visual=VisualVolume(style_manifesto=""))
    prompt = compile_multirole_prompt(
        action_text="王生起身",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=None,
        world_bible=wb,
    )
    assert "整体美术风格" not in prompt


def test_compile_multirole_prompt_injects_identity_lock_sentence() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    wb = WorldBible(
        characters=[
            CharacterVolumeEntry(name="王生", identity_lock_sentence="王生的身份始终一致。")
        ]
    )
    prompt = compile_multirole_prompt(
        action_text="王生起身",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=None,
        world_bible=wb,
    )
    assert "[Image 1] 是王生的身份参考图" in prompt
    assert "王生的身份始终一致。" in prompt
    # 身份锁定句必须跟在同一张参考图的声明行里,不是独立另起一行。
    assert prompt.split("\n")[0].endswith("王生的身份始终一致。")


def test_compile_multirole_prompt_identity_lock_sentence_missing_character_no_crash() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    wb = WorldBible(characters=[CharacterVolumeEntry(name="老道士", identity_lock_sentence="X")])
    prompt = compile_multirole_prompt(
        action_text="王生起身",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=None,
        world_bible=wb,
    )
    assert "[Image 1] 是王生的身份参考图" in prompt
    assert "X" not in prompt


def test_compile_multirole_prompt_injects_negative_constraints_text() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    prompt = compile_multirole_prompt(
        action_text="王生起身",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=None,
        negative_constraints_text="画面呈现柔和自然的胶片质感。",
    )
    assert "【画面必须呈现的效果" in prompt
    assert "画面呈现柔和自然的胶片质感。" in prompt
    assert prompt.index("画面必须呈现的效果") < prompt.index("王生起身")


def test_compile_multirole_prompt_empty_negative_constraints_not_injected() -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    prompt = compile_multirole_prompt(
        action_text="王生起身",
        scene_stage=stage,
        character_names=["王生"],
        scene_plate_path=None,
        negative_constraints_text="",
    )
    assert "画面必须呈现的效果" not in prompt


async def test_positive_rephrase_negatives_empty_list_skips_llm() -> None:
    llm = AsyncMock()
    result = await positive_rephrase_negatives([], llm=llm)
    assert result == ""
    llm.assert_not_called()


async def test_positive_rephrase_negatives_uses_llm_output() -> None:
    llm = AsyncMock(return_value={"content": "画面呈现柔和自然的胶片质感。"})
    result = await positive_rephrase_negatives(["绝不出现手持晃动"], llm=llm)
    assert result == "画面呈现柔和自然的胶片质感。"
    llm.assert_awaited_once()


async def test_positive_rephrase_negatives_falls_back_when_llm_fails() -> None:
    llm = AsyncMock(side_effect=RuntimeError("boom"))
    result = await positive_rephrase_negatives(["绝不出现手持晃动", "绝不出现现代锐度"], llm=llm)
    assert "务必避免以下内容" in result
    assert "绝不出现手持晃动" in result
    assert "绝不出现现代锐度" in result


async def test_positive_rephrase_negatives_falls_back_when_llm_returns_empty() -> None:
    llm = AsyncMock(return_value={"content": "   "})
    result = await positive_rephrase_negatives(["绝不出现手持晃动"], llm=llm)
    assert "务必避免以下内容" in result


def test_build_reference_images_order_matches_prompt_numbering(tmp_path: Path) -> None:
    plate = tmp_path / "plate.png"
    canon_a = tmp_path / "canon_a.png"
    canon_b = tmp_path / "canon_b.png"
    for p in (plate, canon_a, canon_b):
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    refs = build_reference_images(
        scene_plate_path=plate,
        canon_paths={"王生": canon_a, "老道士": canon_b},
        character_names=["王生", "老道士"],
    )
    assert len(refs) == 3
    assert all(r.startswith("data:image/png;base64,") for r in refs)


def test_build_reference_images_without_scene_plate(tmp_path: Path) -> None:
    canon_a = tmp_path / "canon_a.png"
    canon_a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    refs = build_reference_images(
        scene_plate_path=None, canon_paths={"王生": canon_a}, character_names=["王生"]
    )
    assert len(refs) == 1


def test_build_reference_images_skips_character_with_no_canon(tmp_path: Path) -> None:
    canon_a = tmp_path / "canon_a.png"
    canon_a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    refs = build_reference_images(
        scene_plate_path=None,
        canon_paths={"王生": canon_a},  # 老道士没有 canon
        character_names=["王生", "老道士"],
    )
    assert len(refs) == 1


def _segment(*, duration_s: float, with_dialogue: bool = True) -> SceneScriptSegment:
    dialogue = (
        [SceneScriptDialogueLine(character_name="王生", text="弟子慕道已久", target_name="老道士")]
        if with_dialogue
        else []
    )
    return SceneScriptSegment(
        t_start_s=0.0,
        t_end_s=duration_s,
        narrative_text="王生跪地叩首",
        dialogue=dialogue,
    )


async def test_generate_multirole_segment_calls_gen_fn_with_compiled_prompt(tmp_path: Path) -> None:
    stage = _stage(
        InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"),
        InitialPosition(char_id="老道士", posture="直立", facing="正面垂视"),
    )
    canon_a = tmp_path / "canon_a.png"
    canon_b = tmp_path / "canon_b.png"
    for p in (canon_a, canon_b):
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    gen_fn = AsyncMock(return_value=tmp_path / "out.mp4")

    result = await generate_multirole_segment(
        scene_stage=stage,
        segment=_segment(duration_s=5.0),
        character_names=["王生", "老道士"],
        canon_paths={"王生": canon_a, "老道士": canon_b},
        scene_plate_path=None,
        output_path=tmp_path / "out.mp4",
        gen_fn=gen_fn,
    )

    assert result == tmp_path / "out.mp4"
    gen_fn.assert_awaited_once()
    kwargs = gen_fn.await_args.kwargs
    assert "[Image 1] 是王生的身份参考图" in kwargs["prompt"]
    assert "[Image 2] 是老道士的身份参考图" in kwargs["prompt"]
    assert "弟子慕道已久" in kwargs["prompt"]
    assert len(kwargs["reference_images"]) == 2
    assert kwargs["duration"] == 5


async def test_generate_multirole_segment_threads_world_bible_style_manifesto(
    tmp_path: Path,
) -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    canon_a = tmp_path / "canon_a.png"
    canon_a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    gen_fn = AsyncMock(return_value=tmp_path / "out.mp4")
    wb = WorldBible(visual=VisualVolume(style_manifesto="水墨渗染质感"))

    await generate_multirole_segment(
        scene_stage=stage,
        segment=_segment(duration_s=5.0, with_dialogue=False),
        character_names=["王生"],
        canon_paths={"王生": canon_a},
        scene_plate_path=None,
        world_bible=wb,
        output_path=tmp_path / "out.mp4",
        gen_fn=gen_fn,
    )
    assert "【整体美术风格,这一帧必须遵守】水墨渗染质感" in gen_fn.await_args.kwargs["prompt"]


async def test_generate_multirole_segment_threads_identity_lock_sentence(tmp_path: Path) -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    canon_a = tmp_path / "canon_a.png"
    canon_a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    gen_fn = AsyncMock(return_value=tmp_path / "out.mp4")
    wb = WorldBible(
        characters=[CharacterVolumeEntry(name="王生", identity_lock_sentence="王生始终一致。")]
    )

    await generate_multirole_segment(
        scene_stage=stage,
        segment=_segment(duration_s=5.0, with_dialogue=False),
        character_names=["王生"],
        canon_paths={"王生": canon_a},
        scene_plate_path=None,
        world_bible=wb,
        output_path=tmp_path / "out.mp4",
        gen_fn=gen_fn,
    )
    assert "王生始终一致。" in gen_fn.await_args.kwargs["prompt"]


async def test_generate_multirole_segment_rephrases_and_injects_negative_constraints(
    tmp_path: Path,
) -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    canon_a = tmp_path / "canon_a.png"
    canon_a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    gen_fn = AsyncMock(return_value=tmp_path / "out.mp4")
    rephrase_llm = AsyncMock(return_value={"content": "画面保持柔和自然的质感。"})
    wb = WorldBible(visual=VisualVolume(negative_list=["绝不出现手持晃动"]))

    await generate_multirole_segment(
        scene_stage=stage,
        segment=_segment(duration_s=5.0, with_dialogue=False),
        character_names=["王生"],
        canon_paths={"王生": canon_a},
        scene_plate_path=None,
        world_bible=wb,
        no_cut_to=["不切至水面倒影特写"],
        output_path=tmp_path / "out.mp4",
        gen_fn=gen_fn,
        rephrase_llm=rephrase_llm,
    )

    rephrase_llm.assert_awaited_once()
    rephrased_prompt = rephrase_llm.await_args.kwargs["messages"][0]["content"]
    assert "绝不出现手持晃动" in rephrased_prompt
    assert "不切至水面倒影特写" in rephrased_prompt
    assert "画面保持柔和自然的质感。" in gen_fn.await_args.kwargs["prompt"]


async def test_generate_multirole_segment_skips_rephrase_when_nothing_to_rephrase(
    tmp_path: Path,
) -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    canon_a = tmp_path / "canon_a.png"
    canon_a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    gen_fn = AsyncMock(return_value=tmp_path / "out.mp4")
    rephrase_llm = AsyncMock()

    await generate_multirole_segment(
        scene_stage=stage,
        segment=_segment(duration_s=5.0, with_dialogue=False),
        character_names=["王生"],
        canon_paths={"王生": canon_a},
        scene_plate_path=None,
        output_path=tmp_path / "out.mp4",
        gen_fn=gen_fn,
        rephrase_llm=rephrase_llm,
    )
    rephrase_llm.assert_not_called()


async def test_generate_multirole_segment_clamps_duration_to_provider_range(tmp_path: Path) -> None:
    stage = _stage()
    gen_fn = AsyncMock(return_value=tmp_path / "out.mp4")

    await generate_multirole_segment(
        scene_stage=stage,
        segment=_segment(duration_s=30.0, with_dialogue=False),
        character_names=["王生", "老道士"],
        canon_paths={},
        scene_plate_path=None,
        output_path=tmp_path / "out.mp4",
        gen_fn=gen_fn,
    )
    assert gen_fn.await_args.kwargs["duration"] == 15

    gen_fn.reset_mock()
    await generate_multirole_segment(
        scene_stage=stage,
        segment=_segment(duration_s=1.0, with_dialogue=False),
        character_names=["王生", "老道士"],
        canon_paths={},
        scene_plate_path=None,
        output_path=tmp_path / "out.mp4",
        gen_fn=gen_fn,
    )
    assert gen_fn.await_args.kwargs["duration"] == 3


def test_build_reference_images_includes_continuity_reference(tmp_path: Path) -> None:
    plate = tmp_path / "plate.png"
    prev_frame = tmp_path / "prev_frame.png"
    canon_a = tmp_path / "canon_a.png"
    for p in (plate, prev_frame, canon_a):
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    refs = build_reference_images(
        scene_plate_path=plate,
        canon_paths={"王生": canon_a},
        character_names=["王生"],
        continuity_reference_path=prev_frame,
    )
    assert len(refs) == 3  # 空景板 + 连续性参考 + 1 角色


async def test_generate_multirole_segment_with_continuity_reference(tmp_path: Path) -> None:
    stage = _stage(InitialPosition(char_id="王生", posture="跪伏", facing="俯身叩首"))
    canon_a = tmp_path / "canon_a.png"
    prev_frame = tmp_path / "prev_frame.png"
    for p in (canon_a, prev_frame):
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    gen_fn = AsyncMock(return_value=tmp_path / "out.mp4")

    await generate_multirole_segment(
        scene_stage=stage,
        segment=_segment(duration_s=5.0, with_dialogue=False),
        character_names=["王生"],
        canon_paths={"王生": canon_a},
        scene_plate_path=None,
        continuity_reference_path=prev_frame,
        output_path=tmp_path / "out.mp4",
        gen_fn=gen_fn,
    )
    kwargs = gen_fn.await_args.kwargs
    assert "[Image 1] 是上一段结尾的真实画面" in kwargs["prompt"]
    assert "[Image 2] 是王生的身份参考图" in kwargs["prompt"]
    assert len(kwargs["reference_images"]) == 2
