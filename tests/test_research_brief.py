"""research brief 测试 —— 一等研究阶段(差距 B10)。

FakeCaller 注入(零网络), 覆盖: 问题规划/逐问研究/失败降级/引用去重/上下文块。
"""

from __future__ import annotations

import pytest

from hevi.research.brief import (
    ResearchBrief,
    plan_research_questions,
    report_to_context,
    run_research,
)


class FakeCaller:
    """模拟 oskill.LLMCaller: 按问题内容返回稳定摘要。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(self, system: str, prompt: str, temperature: float = 0.2) -> str:
        self.calls.append(prompt)
        return "综合要点: 主题有可靠史料支撑。"


def test_plan_research_questions_default_angles():
    qs = plan_research_questions("唐长安")
    assert len(qs) >= 2
    assert all("唐长安" in q for q in qs)
    assert any("事实核验" in q for q in qs)


def test_plan_research_questions_custom_angles():
    qs = plan_research_questions("克隆技术", angles=["technique"])
    assert len(qs) == 1
    assert "技术" in qs[0]


@pytest.mark.asyncio
async def test_run_research_end_to_end(monkeypatch):
    """用 FakeCaller 跑 oskill.web_research —— monkeypatch 其网络部分为假。"""
    from oskill import ResearchResult, web_research as _wr

    async def fake_web_research(query, *, caller, max_sources=5):
        assert caller is not None
        return ResearchResult(
            query=query,
            sources=["https://src.example/1", "https://src.example/1"],  # 故意重复
            summary="综合要点: 主题有可靠史料支撑。",
            confidence=0.8,
        )

    monkeypatch.setattr("hevi.research.brief.web_research", fake_web_research)
    brief = ResearchBrief(topic="唐长安", angles=["fact", "worldview"])
    report = await run_research(brief, FakeCaller(), max_sources=3)
    assert len(report.findings) == 2
    assert all(f["confidence"] == 0.8 for f in report.findings)
    # 引用去重
    assert len(report.sources) == 1
    assert report.sources[0] == "https://src.example/1"


@pytest.mark.asyncio
async def test_run_research_question_failure_degrades(monkeypatch):
    async def failing(query, *, caller, max_sources=5):
        if "世界观" in query:
            raise RuntimeError("network down")
        from oskill import ResearchResult

        return ResearchResult(query=query, sources=["https://a"], summary="ok", confidence=0.5)

    monkeypatch.setattr("hevi.research.brief.web_research", failing)
    brief = ResearchBrief(topic="X", angles=["fact", "worldview"])
    report = await run_research(brief, FakeCaller())
    assert len(report.findings) == 2
    failed = [f for f in report.findings if f.get("error")]
    assert len(failed) == 1
    assert "network down" in failed[0]["error"]


def test_report_to_context_includes_citations():
    from hevi.research.brief import ResearchReport

    report = ResearchReport(
        topic="唐长安",
        questions=["q1"],
        findings=[
            {
                "question": "q1",
                "summary": "长安城面积 84 平方公里",
                "confidence": 0.9,
                "sources": ["https://hist.example/a"],
            }
        ],
        sources=["https://hist.example/a"],
    )
    ctx = report_to_context(report)
    assert "84 平方公里" in ctx
    assert "https://hist.example/a" in ctx
    assert "研究结果" in ctx


def test_report_to_context_empty():
    from hevi.research.brief import ResearchReport

    assert "无研究结果" in report_to_context(ResearchReport(topic="x"))


@pytest.mark.asyncio
async def test_run_research_respects_max_questions(monkeypatch):
    async def fake_web_research(query, *, caller, max_sources=5):
        from oskill import ResearchResult

        return ResearchResult(query=query, sources=[], summary="s", confidence=0.3)

    monkeypatch.setattr("hevi.research.brief.web_research", fake_web_research)
    brief = ResearchBrief(topic="T", angles=["fact", "worldview", "character"], max_questions=2)
    report = await run_research(brief, FakeCaller())
    assert len(report.findings) == 2
