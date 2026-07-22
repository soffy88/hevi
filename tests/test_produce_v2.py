"""hevi.director.produce_v2 测试 — 真实 ffmpeg/CLIP/装配链路 + lavfi 合成片,
provider/TTS/ASR/VLM 全部显式依赖注入(同 `generate_multirole_segment`/`segment_qc` 的
`gen_fn`/`tts_fn` 既定约定,不碰真实网络/GPU/花钱调用)。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hevi.director.pipeline_schemas import (
    CharacterVolumeEntry,
    DesignCharacter,
    DesignList,
    DesignScene,
    SceneScript,
    SceneScriptDialogueLine,
    SceneScriptSegment,
    SceneScriptSet,
    Screenplay,
    ScreenplayScene,
    VisualVolume,
    WorldBible,
)
from hevi.director.produce_v2 import ProduceV2Error, run_v2_produce

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


def _make_av_clip(path: Path, seconds: float, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{color}:size=64x64:duration={seconds}:rate=8",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=16000:cl=mono:d={seconds}",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _make_canon(path: Path, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{color}:size=64x64",
            "-vframes",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _gen_fn_factory(
    *, color: str = "808080", seconds: float = 2.0, fail_for: set[str] | None = None
):
    """假 provider:按 output_path 文件名写一个真实的小 lavfi 合成 clip(带静音音轨,让下游
    probe_duration/CLIP/ASR 这些真实操作有真文件可处理)。`fail_for` 是要让哪些 segment_id
    的所有尝试都失败(测试优雅降级用)。"""

    async def _gen_fn(*, prompt, reference_images, output_path, duration, resolution, ratio, seed):
        output_path = Path(output_path)
        if fail_for and any(sid in output_path.name for sid in fail_for):
            raise RuntimeError("模拟 provider 失败")
        _make_av_clip(output_path, seconds, color)
        return output_path

    return _gen_fn


async def _fake_tts_fn(*, script, output_path, voice=None, emotion=None, **kw) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1.0", str(output_path)],
        check=True,
        capture_output=True,
    )
    return Path(output_path)


def _fake_transcribe_fn(path, *, language=None) -> list:
    """始终测不到人声开口——确定性地把每个有台词的段推进 fallback TTS 分支,不依赖真实
    faster-whisper 推理(快、确定性),同 `tests/test_native_dialogue.py` 的注入约定。"""
    return []


def _fake_vlm(*, messages, image_paths, max_tokens):
    return {
        "content": (
            '{"spatial_jump": false, "camera_looks_repeated": false, '
            '"identity_consistent": true, "color_mismatch": false, "reason": "ok"}'
        )
    }


def _fake_llm(*, messages, max_tokens=4096):
    """喂给 `extract_scene_stage_from_script`(结构抽取)/`positive_rephrase_negatives`
    (负面约束改写)的假文本 LLM——同步可调用即可(`_call_llm_json` 会自己判断要不要
    await),空 JSON 让两处都退回各自的确定性兜底路径,不用猜测真实抽取内容的形状。"""
    return {"content": "{}"}


def _build_inputs(*, n_segments_with_dialogue: int = 1) -> dict:
    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(scene_no=1, location="测试场景", characters_present=["角色A"]),
        ]
    )
    design_list = DesignList(
        characters=[DesignCharacter(name="角色A")],
        scenes=[DesignScene(name="测试场景")],
    )
    world_bible = WorldBible(
        characters=[CharacterVolumeEntry(name="角色A", identity_lock_sentence="角色A身份始终一致")],
        visual=VisualVolume(style_manifesto="", negative_list=[]),
    )
    segments = [
        SceneScriptSegment(
            segment_id="sg001",
            order=1,
            t_start_s=0.0,
            t_end_s=2.0,
            narrative_text="角色A静立河边。",
            camera_movement="静态对话",
            dialogue=[],
        ),
        SceneScriptSegment(
            segment_id="sg002",
            order=2,
            t_start_s=2.0,
            t_end_s=4.0,
            narrative_text="角色A开口。",
            camera_movement="静态对话",
            dialogue=[SceneScriptDialogueLine(character_name="角色A", text="你好")],
        ),
    ]
    scene_script = SceneScript(
        scene_ref=1, characters_present=["角色A"], segments=segments, no_cut_to=[]
    )
    scene_script_set = SceneScriptSet(scripts=[scene_script])
    return {
        "screenplay": screenplay,
        "design_list": design_list,
        "world_bible": world_bible,
        "scene_script_set": scene_script_set,
    }


async def _strict_create_shot_state(data: dict) -> dict:
    """镜像真实 `TaskRepository.create_shot_state(self, data: dict)` 的签名——它只收
    一个位置字典参数。用 kwargs 调(produce_v2 曾经的写法)会 TypeError,让签名不匹配
    在测试里就暴露,而不是等真机产集跑到收尾那一步才崩(2026-07-21 批C 真机撞见:
    成片已装配完成却因这步 TypeError 被标 failed)。"""
    return dict(data)


def _make_task_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.update_task = AsyncMock()
    repo.delete_shots = AsyncMock()
    repo.create_shot_state = AsyncMock(side_effect=_strict_create_shot_state)
    return repo


@ffmpeg_only
async def test_run_v2_produce_happy_path_completes_and_reports_real_cost(tmp_path: Path) -> None:
    canon = tmp_path / "canon_a.png"
    _make_canon(canon, "808080")
    task_repo = _make_task_repo()
    progress_calls: list[tuple] = []

    async def progress_cb(stage, pct, completed, total):
        progress_calls.append((stage, pct, completed, total))

    await run_v2_produce(
        task_repo=task_repo,
        task_id="task-1",
        run_dir=tmp_path / "run",
        subject_ref_paths={"角色A": str(canon)},
        scene_ref_paths={},
        voice_by_speaker={"角色A": "zh-CN-XiaoxiaoNeural"},
        progress_cb=progress_cb,
        gen_fn=_gen_fn_factory(color="808080", seconds=2.0),
        tts_fn=_fake_tts_fn,
        transcribe_fn=_fake_transcribe_fn,
        vlm=_fake_vlm,
        llm=_fake_llm,
        **_build_inputs(),
    )

    task_repo.update_task.assert_awaited()
    final_call = task_repo.update_task.await_args_list[-1]
    _, payload = final_call.args
    assert payload["status"] == "completed"
    assert payload["progress_pct"] == 100.0
    assert payload["total_shots"] == 2
    assert payload["completed_shots"] == 2
    assert payload["config_json"]["actual_usd"] > 0
    assert payload["config_json"]["failed_segments"] == []
    assert Path(payload["result_video_path"]).exists()

    task_repo.delete_shots.assert_awaited_once_with("task-1")
    assert task_repo.create_shot_state.await_count == 2

    stages = [c[0] for c in progress_calls]
    assert "提取场事实" in stages
    assert any("渲染片段" in s for s in stages)
    assert "装配" in stages
    assert "终审" in stages


@ffmpeg_only
async def test_run_v2_produce_degrades_gracefully_on_persistent_segment_failure(
    tmp_path: Path,
) -> None:
    canon = tmp_path / "canon_a.png"
    _make_canon(canon, "808080")
    task_repo = _make_task_repo()

    await run_v2_produce(
        task_repo=task_repo,
        task_id="task-2",
        run_dir=tmp_path / "run",
        subject_ref_paths={"角色A": str(canon)},
        scene_ref_paths={},
        voice_by_speaker={},
        gen_fn=_gen_fn_factory(color="808080", seconds=2.0, fail_for={"sg002"}),
        tts_fn=_fake_tts_fn,
        transcribe_fn=_fake_transcribe_fn,
        vlm=_fake_vlm,
        llm=_fake_llm,
        **_build_inputs(),
    )

    final_call = task_repo.update_task.await_args_list[-1]
    _, payload = final_call.args
    # 一段持续失败不中断整任务——仍然 completed,如实报"少了一段"。
    assert payload["status"] == "completed"
    assert payload["total_shots"] == 2
    assert payload["completed_shots"] == 1
    assert "s1_sg002" in payload["config_json"]["failed_segments"]


@ffmpeg_only
async def test_run_v2_produce_raises_when_no_segments(tmp_path: Path) -> None:
    inputs = _build_inputs()
    inputs["scene_script_set"] = SceneScriptSet(scripts=[])
    task_repo = _make_task_repo()

    with pytest.raises(ProduceV2Error):
        await run_v2_produce(
            task_repo=task_repo,
            task_id="task-3",
            run_dir=tmp_path / "run",
            subject_ref_paths={},
            scene_ref_paths={},
            voice_by_speaker={},
            gen_fn=_gen_fn_factory(),
            tts_fn=_fake_tts_fn,
            transcribe_fn=_fake_transcribe_fn,
            vlm=_fake_vlm,
            llm=_fake_llm,
            **inputs,
        )
