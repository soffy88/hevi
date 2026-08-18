"""hevi.research —— 一等研究阶段(3O oskill 组合, 差距 B10)。

对标 OpenMontage 的 research 阶段(15-25 次 web 搜索 + 引用 + 成本估算), 补 hevi
差距: screenplay 无系统化事实研究/引用, 世界观依赖 prompt 硬塞。

落点: 直接复用 `oskill.web_research`(http_fetch + html_to_markdown +
extract_main_content + LLM 综合) —— 3O 已有能力, hevi 补的是**制片语境**:

  - `ResearchBrief`: 制片研究任务(问题清单/角度/引用纪律/预算)
  - `plan_research_questions(topic, angles)`: 由主题与角度生成研究问题(确定性模板 +
    LLM 增强注入点)
  - `run_research(brief, caller, max_sources)`: 逐问题调用 oskill.web_research,
    汇总为 ResearchReport(sources/引用/要点)
  - `report_to_context(report)`: 转成 screenplay 阶段的注入上下文块(带引用)

LLM 注入: caller 遵循 oskill.LLMCaller Protocol(见 oskill.llm_client);
测试用 FakeCaller 注入, 零网络。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from oskill import ResearchResult, web_research

logger = logging.getLogger(__name__)


class LLMCaller(Protocol):
    """oskill.LLMCaller 的最小面(注入点)。"""

    async def call(
        self, system: str, prompt: str, temperature: float = 0.2
    ) -> str: ...


@dataclass
class ResearchBrief:
    """制片研究任务定义。angles 为研究角度(世界观/人物/史实/技术…)。"""

    topic: str
    angles: list[str] = field(default_factory=lambda: ["fact", "worldview"])
    max_questions: int = 5
    require_citations: bool = True  # 引用纪律: 事实性陈述必须带来源


_DEFAULT_ANGLES: dict[str, str] = {
    "fact": "事实核验: 主题相关的可查证事实、数据、时间线",
    "worldview": "世界观: 已有设定与真实世界的兼容点/冲突点",
    "character": "人物: 与主题相关的人物原型、关系、动机素材",
    "technique": "技术/工艺: 主题涉及的技术、流程、术语",
    "controversy": "争议: 主题的争议点、敏感性(规避红线)",
    "audience": "受众: 目标受众的既有认知与兴趣点",
}


def plan_research_questions(topic: str, angles: list[str] | None = None) -> list[str]:
    """由主题与角度生成研究问题(确定性模板; LLM 增强留注入点)。

    每个角度产 1 问, 最多 max 问; 问题保持制片语境(可查证、可引用)。
    """
    angles = angles or list(_DEFAULT_ANGLES)
    questions: list[str] = []
    for angle in angles:
        desc = _DEFAULT_ANGLES.get(angle, f"研究角度: {angle}")
        questions.append(f"针对「{topic}」的{desc}, 给出可查证的事实与可靠来源。")
    return questions


@dataclass
class ResearchReport:
    topic: str
    questions: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)  # {question, summary, confidence, sources}
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "questions": self.questions,
            "findings": self.findings,
            "sources": self.sources,
        }


async def run_research(
    brief: ResearchBrief,
    caller: LLMCaller,
    *,
    max_sources: int = 4,
) -> ResearchReport:
    """逐问题跑 oskill.web_research, 汇总为 ResearchReport。

    单问题失败降级(记 note), 不阻断整个研究阶段。
    """
    report = ResearchReport(topic=brief.topic)
    questions = plan_research_questions(brief.topic, brief.angles)[
        : brief.max_questions
    ]
    report.questions = questions
    for q in questions:
        try:
            res: ResearchResult = await web_research(
                q, caller=caller, max_sources=max_sources
            )
            finding = {
                "question": q,
                "summary": res.summary,
                "confidence": res.confidence,
                "sources": [s for s in res.sources],
            }
            report.findings.append(finding)
            report.sources.extend(res.sources)
        except Exception as exc:
            logger.warning("research question failed (%s): %s", q, exc)
            report.findings.append(
                {"question": q, "summary": "", "confidence": 0.0, "error": str(exc)}
            )
    # 去重保序
    seen: set[str] = set()
    deduped: list[str] = []
    for s in report.sources:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    report.sources = deduped
    return report


def report_to_context(report: ResearchReport) -> str:
    """研究结果 → screenplay 阶段注入上下文块(Markdown, 带引用)。"""
    if not report.findings:
        return "# 研究结果\n(无研究结果)"
    lines = ["# 研究结果(制片事实基线)", f"## 主题: {report.topic}"]
    for f in report.findings:
        if f.get("error"):
            lines.append(f"- ❌ {f['question']}: {f['error']}")
            continue
        srcs = f.get("sources", [])
        src_txt = "; ".join(srcs[:3]) if srcs else "(无引用)"
        lines.append(
            f"- **{f['question']}**\n  - 要点: {f['summary']}\n"
            f"  - 置信度: {f.get('confidence', 0)}\n  - 来源: {src_txt}"
        )
    if report.sources:
        lines.append("## 全部来源")
        lines.extend(f"- {s}" for s in report.sources)
    return "\n".join(lines)


__all__ = [
    "LLMCaller",
    "ResearchBrief",
    "ResearchReport",
    "plan_research_questions",
    "report_to_context",
    "run_research",
]
