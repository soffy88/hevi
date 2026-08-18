"""reference_concepts —— 参考视频 → 差异化概念 + 成本估算(3O oskill 组合, 差距 B1 链路)。

对标 OpenMontage 的 reference_input(粘贴 YouTube/TikTok → 转录/节奏/场景/关键帧分析
→ 2-3 差异化概念 + 成本估算 + 样片), 补 hevi 链路: hevi/ingest 已能「看视频」
(hevi-watch: fetch → 帧 → 转写), 本模块把 watch 结果推进到**可立项的概念**。

组合(≥2 oprim/oskill):
    ingest.video_watch(fetch+抽帧+转写) + 节奏分析(纯函数) + LLM 概念生成
    + cost.estimate_cost(成本估算) → 差异化概念清单

契约:
    derive_reference_concepts(watch, llm=None, top_n=3, video_provider=...) -> list[dict]
    失败不 raise: LLM 不可用/解析失败 → 确定性兜底(转写主题词 + 档位默认值)。
    每个概念: {title, angle, target_audience, duration_archetype,
               cost_estimate_usd, confidence, notes}
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from hevi.ingest.video_watch import WatchResult

logger = logging.getLogger(__name__)

# 档位默认(与 hevi/cost/duration_mapper 对齐)
_ARCHETYPES = ("short", "1-5min", "5-15min", "15-45min", "45min+")

_PROMPT = """你是短视频制片企划。基于参考视频分析,给出 {top_n} 个**差异化**概念——
每个都必须与原视频形成明显区分(不同切入角度/受众/风格),不能是原视频复述。

参考视频分析:
- 时长: {duration_s:.0f}s
- 节奏: 语速 {wpm:.0f} 字/分, 转写 {sentence_count} 句, 句均 {avg_len:.0f} 字
- 转写摘要(前 {char_limit} 字): {transcript_excerpt}

只输出 JSON 数组, 每项: {{"title": "概念名", "angle": "差异化角度(一句话)",
"target_audience": "目标观众", "duration_archetype": "short|1-5min|5-15min|15-45min|45min+",
"confidence": "high|medium|low", "notes": "制作要点"}}"""


class ConceptLLM(Protocol):
    """概念生成 LLM 注入点(与 oskill.LLMCaller 同构, 测试用 FakeCaller)。"""

    def __call__(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any: ...


def analyze_reference_pacing(watch: WatchResult) -> dict[str, Any]:
    """参考视频节奏分析(纯函数): 语速/句密度/句均长。转写为空时全部 0。"""
    text = watch.transcript_text.strip()
    if not text or watch.duration_s <= 0:
        return {"wpm": 0.0, "sentence_count": 0, "avg_len": 0.0, "chars": 0}
    chars = len(re.sub(r"\s", "", text))
    sentences = [s for s in re.split(r"[。！？!?；;\n]", text) if s.strip()]
    wpm = chars / (watch.duration_s / 60.0)
    return {
        "wpm": round(wpm, 1),
        "sentence_count": len(sentences),
        "avg_len": round(chars / len(sentences), 1) if sentences else 0.0,
        "chars": chars,
    }


def _fallback_concepts(pacing: dict[str, Any], top_n: int) -> list[dict[str, Any]]:
    """确定性兜底: 无 LLM/解析失败时给出可立项的默认概念(不阻断)。"""
    arch = "short" if pacing["wpm"] > 0 else "1-5min"
    base = {
        "title": "参考视频主题解读",
        "angle": "以参考视频为风格锚点, 换一个切入角度重新立意",
        "target_audience": "原视频受众的相邻人群",
        "duration_archetype": arch,
        "confidence": "low",
        "notes": "兜底概念(LLM 不可用): 建议接入 LLM 后重新生成差异化概念",
    }
    variants = [
        {**base, "title": "知识点拆解版", "angle": "把原视频内容拆成可检索的知识点短篇"},
        {**base, "title": "反转型解读", "angle": "从对立视角重述同一主题, 制造认知冲突"},
    ]
    return variants[:top_n]


async def _cost_for(
    archetype: str, video_provider: str, audio_provider: str = "vibevoice"
) -> float | None:
    try:
        from hevi.cost.estimator import estimate_cost

        est = await estimate_cost(
            duration_archetype=archetype,
            video_provider=video_provider,
            audio_provider=audio_provider,
        )
        return round(float(est.total_usd), 3)
    except Exception as exc:
        logger.warning("cost estimate failed for %s: %s", archetype, exc)
        return None


async def derive_reference_concepts(
    watch: WatchResult,
    *,
    llm: ConceptLLM | None = None,
    top_n: int = 3,
    video_provider: str = "h3_local",
    char_limit: int = 600,
) -> list[dict[str, Any]]:
    """WatchResult → 差异化概念清单 + 成本估算。

    - llm 为 None/失败 → 确定性兜底(不 raise)。
    - 成本估算失败 → cost_estimate_usd=None(不阻断)。
    """
    top_n = max(1, min(top_n, 5))
    pacing = analyze_reference_pacing(watch)
    excerpt = watch.transcript_text[:char_limit]

    concepts: list[dict[str, Any]] = []
    if llm is not None:
        try:
            prompt = _PROMPT.format(
                top_n=top_n,
                duration_s=watch.duration_s,
                wpm=pacing["wpm"],
                sentence_count=pacing["sentence_count"],
                avg_len=pacing["avg_len"],
                char_limit=char_limit,
                transcript_excerpt=excerpt or "(无转写)",
            )
            resp = llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
            content = resp.get("content") if hasattr(resp, "get") else str(resp)
            m = re.search(r"\[.*\]", content, re.DOTALL)
            if not m:
                raise ValueError("LLM 未返回 JSON 数组")
            data = json.loads(m.group(0))
            for item in data[:top_n]:
                if not isinstance(item, dict):
                    continue
                arch = item.get("duration_archetype", "short")
                if arch not in _ARCHETYPES:
                    arch = "short"
                concepts.append(
                    {
                        "title": str(item.get("title", "")).strip() or "未命名概念",
                        "angle": str(item.get("angle", "")).strip(),
                        "target_audience": str(item.get("target_audience", "")).strip(),
                        "duration_archetype": arch,
                        "confidence": str(item.get("confidence", "medium")),
                        "notes": str(item.get("notes", "")).strip(),
                        "cost_estimate_usd": await _cost_for(arch, video_provider),
                    }
                )
        except Exception as exc:
            logger.warning("concept LLM failed, falling back: %s", exc)
    if not concepts:
        concepts = [
            {
                **c,
                "cost_estimate_usd": await _cost_for(c["duration_archetype"], video_provider),
            }
            for c in _fallback_concepts(pacing, top_n)
        ]
    return concepts


__all__ = [
    "ConceptLLM",
    "analyze_reference_pacing",
    "derive_reference_concepts",
]
