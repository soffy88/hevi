"""B1 参考视频 → 差异化概念链路 —— 节奏分析/概念生成/成本估算/兜底测试。

覆盖 hevi/ingest/reference_concepts.py:
  - analyze_reference_pacing: 语速/句密度/句均长(纯函数, 空转写/零时长降级)
  - derive_reference_concepts: LLM 注入生成(JSON 数组解析/档位校验/成本估算)
  - 兜底: LLM 为 None / 非法返回 / 抛异常 → 确定性概念(不 raise)
  - 成本估算失败 → cost_estimate_usd=None(不阻断)
"""

from __future__ import annotations

import json

import pytest

from hevi.ingest.reference_concepts import (
    analyze_reference_pacing,
    derive_reference_concepts,
)
from hevi.ingest.video_transcript import TranscriptSegment
from hevi.ingest.video_watch import WatchResult


def _watch(transcript: str | None = None, duration_s: float = 60.0) -> WatchResult:
    segs = (
        [
            TranscriptSegment(
                start=0.0, end=duration_s, text=transcript
            )
        ]
        if transcript
        else []
    )
    return WatchResult(
        source="https://example.com/ref.mp4",
        frames=[],
        transcript=segs,
        duration_s=duration_s,
    )


class TestPacing:
    def test_pacing_derived(self) -> None:
        text = "这是第一句。这是第二句!这是第三句?"
        w = _watch(text, duration_s=60.0)
        p = analyze_reference_pacing(w)
        # 转写含时间戳前缀([000.00-000.00]), 断言相对关系而非绝对值
        assert p["sentence_count"] == 3
        assert p["chars"] > 0
        assert p["avg_len"] > 0
        assert p["wpm"] > 0

    def test_pacing_empty_transcript(self) -> None:
        p = analyze_reference_pacing(_watch(None, 60.0))
        assert p == {"wpm": 0.0, "sentence_count": 0, "avg_len": 0.0, "chars": 0}

    def test_pacing_zero_duration(self) -> None:
        p = analyze_reference_pacing(_watch("内容", 0.0))
        assert p["wpm"] == 0.0


class FakeLLM:
    """可控 LLM: 按预设返回 JSON 数组 / 非法文本 / 抛异常。"""

    def __init__(self, *, payload: str | Exception) -> None:
        self._payload = payload
        self.last_messages: list[dict[str, object]] = []

    def __call__(self, messages: list[dict[str, object]], **kwargs: object) -> dict[str, object]:
        self.last_messages = messages
        if isinstance(self._payload, Exception):
            raise self._payload
        return {"content": self._payload}


def _llm_json(n: int = 2) -> str:
    items = [
        {
            "title": f"概念{i}",
            "angle": f"角度{i}",
            "target_audience": "年轻观众",
            "duration_archetype": "short",
            "confidence": "high",
            "notes": "要点",
        }
        for i in range(1, n + 1)
    ]
    return json.dumps(items)


class TestConceptsWithLLM:
    async def test_llm_concepts_with_cost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        async def fake_estimate_cost(**kwargs: object) -> object:
            calls.append(str(kwargs.get("duration_archetype")))
            from hevi.cost.estimator import CostEstimate

            return CostEstimate(
                video_cost_usd=0.6,
                audio_cost_usd=0.634,
                total_usd=1.234,
                breakdown={},
                estimated_credits=123,
            )

        monkeypatch.setattr("hevi.cost.estimator.estimate_cost", fake_estimate_cost)
        w = _watch("这是参考视频的转写内容。", 60.0)
        llm = FakeLLM(payload=_llm_json(2))
        out = await derive_reference_concepts(w, llm=llm, top_n=3, video_provider="h3_local")
        assert len(out) == 2
        assert out[0]["title"] == "概念1"
        assert out[0]["duration_archetype"] == "short"
        assert out[0]["cost_estimate_usd"] == 1.234
        assert calls == ["short", "short"]
        # LLM 收到节奏分析上下文
        assert "字/分" in str(llm.last_messages[0]["content"])

    async def test_invalid_archetype_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "hevi.cost.estimator.estimate_cost",
            lambda **kw: type("E", (), {"total_usd": 0.5})(),
        )
        bad = json.dumps(
            [{"title": "t", "angle": "a", "duration_archetype": "weird", "confidence": "m"}]
        )
        out = await derive_reference_concepts(_watch("x"), llm=FakeLLM(payload=bad))
        assert out[0]["duration_archetype"] == "short"

    async def test_cost_estimate_failure_degrades(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(**kw: object) -> object:
            raise RuntimeError("no pricing")

        monkeypatch.setattr("hevi.cost.estimator.estimate_cost", boom)
        out = await derive_reference_concepts(
            _watch("x"), llm=FakeLLM(payload=_llm_json(1))
        )
        assert out[0]["cost_estimate_usd"] is None


class TestFallback:
    async def test_no_llm_returns_deterministic_concepts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(**kw: object) -> object:
            raise RuntimeError("no pricing")

        monkeypatch.setattr("hevi.cost.estimator.estimate_cost", boom)
        out = await derive_reference_concepts(_watch("参考转写", 60.0), llm=None, top_n=2)
        assert len(out) == 2
        assert out[0]["confidence"] == "low"
        assert "兜底" in out[0]["notes"]
        assert out[0]["cost_estimate_usd"] is None

    async def test_llm_garbage_falls_back(self) -> None:
        out = await derive_reference_concepts(
            _watch("x"), llm=FakeLLM(payload="not json at all"), top_n=2
        )
        assert len(out) == 2
        assert out[0]["confidence"] == "low"

    async def test_llm_exception_falls_back(self) -> None:
        out = await derive_reference_concepts(
            _watch("x"), llm=FakeLLM(payload=RuntimeError("boom")), top_n=1
        )
        assert len(out) == 1

    async def test_top_n_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "hevi.cost.estimator.estimate_cost",
            lambda **kw: type("E", (), {"total_usd": 0.5})(),
        )
        out = await derive_reference_concepts(_watch("x"), llm=None, top_n=99)
        assert len(out) <= 5
