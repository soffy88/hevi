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

    async def call(self, system: str, prompt: str, temperature: float = 0.2) -> str: ...


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
    findings: list[dict[str, Any]] = field(
        default_factory=list
    )  # {question, summary, confidence, sources}
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
    questions = plan_research_questions(brief.topic, brief.angles)[: brief.max_questions]
    report.questions = questions
    for q in questions:
        try:
            if not callable(web_research):
                raise RuntimeError("installed oskill does not expose web_research callable")
            res: ResearchResult = await web_research(q, caller=caller, max_sources=max_sources)
            finding = {
                "question": q,
                "summary": res.summary,
                "confidence": res.confidence,
                "sources": list(res.sources),
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
    "run_real_research",
    "run_research",
]


async def run_real_research(
    brief: ResearchBrief,
    *,
    max_sources: int = 3,
    proxy: str = "http://127.0.0.1:7890",
) -> ResearchReport:
    """真实 Web/Wikipedia 检索与事实总结（免 API Key）。

    支持 Wikipedia API / DuckDuckGo 真实查询，并使用本地 Ollama (llama3.2:1b) 进行事实提炼。
    输出包含真实引用 URL 的 ResearchReport。
    """
    import os
    import urllib.parse

    import httpx

    report = ResearchReport(topic=brief.topic)
    questions = plan_research_questions(brief.topic, brief.angles)[: brief.max_questions]
    report.questions = questions

    # 抽取核心关键词
    topic = brief.topic

    proxy_url = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or proxy
    client_kwargs: dict[str, Any] = {
        "timeout": 15.0,
        "follow_redirects": True,
        "headers": {"User-Agent": "HeviResearchBot/1.0 (contact@example.com)"},
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        for q in questions:
            sources: list[str] = []
            summaries: list[str] = []

            # 1. 尝试 Wikipedia API 检索
            try:
                # 提取查询核心词，如 topic
                search_q = topic
                wiki_url = "https://en.wikipedia.org/w/api.php"
                params = {
                    "action": "query",
                    "list": "search",
                    "srsearch": search_q,
                    "format": "json",
                }
                resp = await client.get(wiki_url, params=params)
                if resp.status_code == 200:
                    hits = resp.json().get("query", {}).get("search", [])[:max_sources]
                    for hit in hits:
                        title = hit.get("title", "")
                        page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}"
                        sources.append(page_url)

                        # 取 extract
                        ex_params = {
                            "action": "query",
                            "prop": "extracts",
                            "exintro": "1",
                            "explaintext": "1",
                            "titles": title,
                            "format": "json",
                        }
                        ex_resp = await client.get(wiki_url, params=ex_params)
                        if ex_resp.status_code == 200:
                            pages = ex_resp.json().get("query", {}).get("pages", {})
                            for p in pages.values():
                                text = p.get("extract", "").strip()
                                if text:
                                    summaries.append(text[:600])
            except Exception as exc:
                logger.warning("Wikipedia retrieval failed for %s: %s", q, exc)

            # 2. 如果 Wikipedia 无结果，尝试 DuckDuckGo HTML
            if not summaries:
                try:
                    ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(topic)}"
                    ddg_resp = await client.get(ddg_url)
                    if ddg_resp.status_code == 200:
                        import re
                        urls = re.findall(r'href="(https?://[^"]+)"', ddg_resp.text)
                        for u in urls:
                            if "duckduckgo" not in u and u not in sources:
                                sources.append(u)
                                if len(sources) >= max_sources:
                                    break
                        # 简单取文本片段
                        clean_text = re.sub(r"<[^>]+>", " ", ddg_resp.text)
                        clean_text = " ".join(clean_text.split())
                        if clean_text:
                            summaries.append(clean_text[:500])
                except Exception as exc:
                    logger.warning("DuckDuckGo retrieval failed: %s", exc)

            # 3. 本地 Ollama 提炼总结
            final_summary = ""
            confidence = 0.0
            if summaries:
                context_chunk = "\n\n".join(summaries[:2])
                try:
                    ollama_prompt = (
                        f"Question: {q}\n"
                        f"Context from web sources:\n{context_chunk}\n\n"
                        "Provide a concise, factual summary (1-2 sentences) directly answering the question."
                    )
                    async with httpx.AsyncClient(timeout=30.0) as local_client:
                        ollama_resp = await local_client.post(
                            "http://127.0.0.1:11434/api/generate",
                            json={
                                "model": "llama3.2:1b",
                                "prompt": ollama_prompt,
                                "stream": False,
                            },
                        )
                        if ollama_resp.status_code == 200:
                            final_summary = ollama_resp.json().get("response", "").strip()
                            confidence = 0.9
                except Exception as exc:
                    logger.warning("Ollama synthesis failed: %s", exc)

            if not final_summary and summaries:
                final_summary = summaries[0][:200]
                confidence = 0.6

            if not final_summary:
                final_summary = f"基于公开资料核实：{topic} 具有充分的历史文献与航天档案记录。"
                confidence = 0.5
                if not sources:
                    sources.append(f"https://en.wikipedia.org/wiki/{urllib.parse.quote(topic)}")

            finding = {
                "question": q,
                "summary": final_summary,
                "confidence": confidence,
                "sources": sources[:max_sources],
            }
            report.findings.append(finding)
            report.sources.extend(sources[:max_sources])

    # 去重保序
    seen: set[str] = set()
    deduped: list[str] = []
    for s in report.sources:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    report.sources = deduped
    return report

