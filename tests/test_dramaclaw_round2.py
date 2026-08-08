"""情感感知配音 + storyboard 图像池 + Task 断点续跑 测试(对标 DramaClaw 三项)。

纯逻辑:情感→TTS 参数映射、关键词分类、synth 装配(mock caller)、
图像池启发式选择、checkpoint 续跑决策。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

# ── 情感感知配音 ────────────────────────────────────────────────
from hevi.assembly.subtitle_align import Cue
from hevi.dub.emotion import (
    apply_emotion_to_edge_tts,
    detect_emotion,
    emotion_tts_params,
)


def test_emotion_detect_keywords():
    assert detect_emotion("哈哈,太高兴了") == "happy"
    assert detect_emotion("你别太过分,混蛋") == "angry"
    assert detect_emotion("我很难过,眼泪止不住") == "sad"
    assert detect_emotion("普通陈述句") == "neutral"


def test_emotion_tts_params():
    prof = emotion_tts_params("sad")
    assert prof["rate"].startswith("-")  # 悲伤放慢
    assert prof["pitch"].startswith("-")  # 悲伤低沉
    assert emotion_tts_params("unknown_emotion") == emotion_tts_params("neutral")


def test_apply_emotion_merges():
    merged = apply_emotion_to_edge_tts({"rate": "+0%", "pitch": "+0%", "volume": "+0%"}, "angry")
    assert merged["volume"] == "+15%"
    assert merged["pitch"] == "-10%"


@pytest.mark.asyncio
async def test_synth_injects_emotion_params():
    """synth_cues_edge_tts: 未标注 cue 自动情感分类 + 参数注入 caller。"""
    from hevi.dub import _synth

    calls: dict = {}

    async def fake_edge_tts(**kwargs):
        calls.update(kwargs)

    orig = None
    import obase.provider_registry as pr

    # monkeypatch ProviderRegistry.get().generic
    orig_get = pr.ProviderRegistry.get
    fake_registry = AsyncMock()
    fake_registry.generic = AsyncMock(return_value=fake_edge_tts)
    # ProviderRegistry.get().generic(...) 返回 caller(可调用), 不是协程对象
    pr.ProviderRegistry.get = lambda: SimpleNamespace(generic=lambda *a, **k: fake_edge_tts)
    try:
        cues = [
            Cue(start=0, end=1, text="哈哈,太高兴了"),       # → happy
            Cue(start=1, end=2, text="普通句子", emotion="neutral"),
            Cue(start=2, end=3, text="愤怒的话", emotion="angry"),
        ]
        await _synth.synth_cues_edge_tts(
            cues=cues, language="zh-CN", output_path=Path("/tmp/x.wav"))
        script = calls["script"]
        assert script[0].rate == "+10%"   # happy
        assert script[2].rate == "+5%"    # angry
        assert script[2].volume == "+15%"
        assert script[1].rate == "+0%"    # neutral
    finally:
        pr.ProviderRegistry.get = orig_get


# ── storyboard 图像池 ───────────────────────────────────────────
from hevi.director.storyboard import _pool_score, select_best_from_pool


def test_pool_select_best():
    pool = ["雨夜,主角在巷口", "晴天公园", "雨夜,主角在巷口,镜头平视"]
    best = select_best_from_pool(pool, "雨夜主角")
    assert "雨夜" in best  # 主题相关优先


def test_pool_dedup():
    pool = ["雨夜主角在巷口", "雨夜主角在巷口(重复)", "晴天"]
    best = select_best_from_pool(pool, "雨夜")
    assert best == "雨夜主角在巷口"  # 去重后只剩主题相关


def test_pool_score_density():
    # 主题命中权重 > 长度
    assert _pool_score("雨夜,主角", "雨夜") > _pool_score("很长很长……" * 20, "雨夜")


@pytest.mark.asyncio
async def test_plan_shots_with_pool():
    """plan_shots(image_pool_size>1) 走池选择,产出 num_shots 条。"""
    from hevi.director.storyboard import plan_shots

    async def fake_llm(**kwargs):
        return {"content": '["雨夜主角在巷口", "晴天", "雨夜主角在巷口特写", "雪景", "雨夜奔跑", "白天"]'}

    shots = await plan_shots(
        topic="雨夜追逐", num_shots=3, llm=fake_llm, image_pool_size=2)
    assert len(shots) == 3
    assert any("雨夜" in s for s in shots)  # 池选择倾向主题相关


# ── Task 断点续跑 ───────────────────────────────────────────────
from hevi.tasks.checkpoint import (
    Checkpoint,
    CheckpointStore,
    build_checkpoint_from_task,
    resume_decision,
)


def test_checkpoint_store_roundtrip():
    store = CheckpointStore()
    tid = uuid4()
    store.save(Checkpoint(task_id=tid, stage="分镜", completed_shots=3, total_shots=10))
    cp = store.get(tid)
    assert cp is not None and cp.completed_shots == 3 and cp.stage == "分镜"
    store.clear(tid)
    assert store.get(tid) is None


def test_build_checkpoint_from_task():
    tid = uuid4()
    task = {
        "task_id": tid, "status": "failed", "completed_shots": 4,
        "total_shots": 8, "progress_pct": 50.0,
        "config_json": {"stage": "镜头生成"},
    }
    cp = build_checkpoint_from_task(task)
    assert cp is not None and cp.stage == "镜头生成" and cp.completed_shots == 4


def test_resume_decision_matrix():
    tid = uuid4()
    failed = {"task_id": tid, "status": "failed", "completed_shots": 4,
              "total_shots": 8, "progress_pct": 50.0}
    cp = build_checkpoint_from_task(failed)

    # 可续跑: failed + 有 checkpoint + 未到终局
    d = resume_decision(failed, cp)
    assert d["resumable"] is True and d["skip_shots"] == 4
    assert d["resumed_count"] == 1

    # 不可续跑: running 状态
    d2 = resume_decision({**failed, "status": "running"}, cp)
    assert d2["resumable"] is False

    # 不可续跑: 无 checkpoint
    d3 = resume_decision({**failed, "status": "failed"}, None)
    assert d3["resumable"] is False and "无 checkpoint" in d3["reason"]

    # 不可续跑: 已到终局
    d4 = resume_decision(failed, Checkpoint(task_id=tid, stage="装配成片", completed_shots=8, total_shots=8))
    assert d4["resumable"] is False


def test_store_memory_resume_flow():
    """端到端: 失败 → checkpoint 保存 → resume 决策 → 更新 resumed_count。"""
    store = CheckpointStore()
    tid = uuid4()
    task = {"task_id": tid, "status": "cancelled", "completed_shots": 2,
            "total_shots": 10, "progress_pct": 20.0}
    cp = build_checkpoint_from_task(task)
    store.save(cp)
    d = resume_decision(task, store.get(tid))
    assert d["resumable"] is True
    cp2 = store.get(tid)
    cp2.resumed_count += 1
    store.save(cp2)
    assert store.get(tid).resumed_count == 1
