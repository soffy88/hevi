"""DRAMAPLAN bug2:定向返工只重烧未通过镜头，已通过镜头产物原样复用。

覆盖：
  1. `select_rework_shots` 确定性挑选（只挑 failed / 低分，full_rework 显式整轮）；
  2. 阈值尺度修复：scorecard 身份分（mean 0.59）在旧 0.75 门槛下 100% 误判，
     校准后的 0.35 不再误伤；
  3. 真实返工路径 `omodul.regenerate_shots`：10 镜中 3 镜失败 → provider 只为这 3 镜
     被调用，其余 7 镜产物字节不变。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hevi.director.editor import (
    DEFAULT_CONSISTENCY_FLOOR,
    review,
    select_rework_shots,
)


def _shots() -> list[dict]:
    return [
        {"index": i, "passed": True, "consistency_score": 0.59}  # G1 实测均值附近
        for i in range(10)
    ]


def test_select_rework_only_failed_shots():
    shots = _shots()
    for i in (3, 6, 8):
        shots[i]["passed"] = False
        shots[i]["consistency_score"] = 0.1
    selected = select_rework_shots(shots)
    assert selected == [3, 6, 8]


def test_select_rework_ignores_passing_normal_identity_scores():
    """核心修复：10 镜全 passed、identity≈0.59，不得被 0.75 尺度误判成 100% 错配。"""
    shots = _shots()
    assert select_rework_shots(shots, consistency_floor=DEFAULT_CONSISTENCY_FLOOR) == []
    # 旧门槛（错尺度）会误判全部 10 镜 —— 这正是 STATUS 里“100% 参考图角色错配”的根因。
    assert select_rework_shots(shots, consistency_floor=0.75) == list(range(10))


def test_select_rework_full_round_is_explicit():
    shots = _shots()
    assert select_rework_shots(shots, full_rework=True) == list(range(10))
    assert review(quality={"passed": True}, shots=shots, full_rework=True).regenerate_shot_ids == list(
        range(10)
    )


def test_review_targets_only_failed_shots():
    shots = _shots()
    for i in (3, 6, 8):
        shots[i]["passed"] = False
    decision = review(quality={"passed": True}, shots=shots, consistency_floor=0.35)
    assert decision.regenerate_shot_ids == [3, 6, 8]
    assert decision.deliver is False
    # 通过的镜头没有 hint（不会被重烧）
    assert all(i not in decision.hints for i in (0, 1, 2, 4, 5, 7, 9))


# ── 真实返工路径：provider 调用次数 ────────────────────────────────────────────
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_regenerate_shots_calls_provider_only_for_failed(tmp_path: Path):
    from omodul.agentic_longvideo_pipeline import LongVideoConfig
    from omodul.longvideo_produce import rework_longvideo_shots

    task_dir = tmp_path / "task"
    shots_dir = task_dir / "shots"
    shots_dir.mkdir(parents=True)
    originals: dict[int, Path] = {}
    original_hashes: dict[int, str] = {}
    for i in range(10):
        (shots_dir / f"shot_{i:04d}.plan.json").write_text(
            json.dumps({"index": i, "shot_id": f"shot_{i}", "prompt": f"scene {i}"}),
            encoding="utf-8",
        )
        variant = shots_dir / f"shot_{i:04d}_v0.mp4"
        variant.write_bytes(f"original-shot-{i}".encode())
        originals[i] = variant
        original_hashes[i] = hashlib.sha256(variant.read_bytes()).hexdigest()

    failed = {3, 6, 8}
    provider_calls: list[int] = []

    async def fake_video_fn(*, prompt, output_path, reference_image=None):
        idx = int(Path(output_path).stem.split("_")[1])
        provider_calls.append(idx)
        Path(output_path).write_bytes(f"regenerated-{idx}-{prompt}".encode())

    async def fake_consistency_fn(*, candidate_frames, **_kw):
        return SimpleNamespace(best_frame=candidate_frames[0], passed=True)

    async def fake_assembler_fn(*, shot_videos, audio_path, subtitle_path, output_path):
        Path(output_path).write_bytes(b"assembled")

    config = LongVideoConfig(
        topic="t",
        duration_archetype="1-5min",
        video_provider="wan_local",
        audio_provider="edge_tts",
        output_dir=task_dir,
        max_shot_retries=1,
    )
    await rework_longvideo_shots(
        task_dir=task_dir,
        shot_ids=sorted(failed),
        hints={},
        config=config,
        providers={
            "video_fn": fake_video_fn,
            "consistency_fn": fake_consistency_fn,
            "assembler_fn": fake_assembler_fn,
            "mllm": object(),  # 避免落到未注册的 default llm
        },
    )

    # provider 只为这 3 个失败镜头被调用（每个镜头 2 个变体 → 6 次底层调用，
    # 但**涉及的镜头集合**恰好是 3 个；非目标镜头一次都没被碰）。
    assert set(provider_calls) == failed
    assert len(set(provider_calls)) == 3
    # 其余 7 镜产物字节不变
    for i in range(10):
        if i in failed:
            assert originals[i].read_bytes() != f"original-shot-{i}".encode()
        else:
            assert _sha(originals[i]) == original_hashes[i]
