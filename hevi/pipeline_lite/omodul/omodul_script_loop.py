"""omodul:omodul_script_loop —— 选题 → LLM 文案 → veya-loop 审稿闭环。

「veya-loop」= 可审计的文案可靠性循环(generate → critique → rewrite):
  1. 确定性硬门(字数/段数/空行/重复/结构)零 LLM 成本;
  2. LLM 软门(钩子、节奏、术语平衡、收束)可注入,失败不阻断硬门结论;
  3. 不过则带 issue 重写,最多 max_rounds 轮;仍不过 → 标 DEGRADED 交人审。

只产出 ScriptDraft / VeyaLoopResult,不渲染视频 —— 渲染走 omodul_lite_assembler。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import Any

from hevi.pipeline_lite.schemas import (
    LiteCue,
    ScriptDraft,
    ScriptIssue,
    ScriptVerdict,
    VeyaLoopResult,
)

logger = logging.getLogger(__name__)

# ── 默认质检阈值 ────────────────────────────────────────────────────────
_MIN_CUES = 3
_MAX_CUES = 10
_MIN_NARRATION = 12
_MAX_NARRATION = 120
_MIN_SCORE = 0.72
_DEFAULT_TARGET_CUES = 5
_DEFAULT_MAX_ROUNDS = 3

_DRAFT_PROMPT = """你是短视频解说编剧。根据选题写竖屏解说旁白分镜。

选题: {topic}
目标镜头数: {target_cues}(允许 {min_cues}-{max_cues})
语言: 中文口语,一句一镜,适合 TTS 朗读。

硬约束:
1. 第 1 镜必须是钩子(好奇/反差/数字),禁止「大家好」「今天我们来讲」;
2. 中间镜讲清一个核心点 + 一个例子/类比;
3. 最后一镜收束(结论或行动号召),不要突然结束;
4. 每镜旁白 18-80 字,口语,避免书面长句;
5. 每镜给 title(短标题,≤12 字)与 visual_query(英文 B-roll 检索词,2-5 词)。

只输出 JSON 对象:
{{
  "title": "成片标题",
  "hook": "一句话钩子摘要",
  "cues": [
    {{"narration":"旁白","title":"标题","visual_query":"keyword phrase"}}
  ]
}}
"""

_CRITIC_PROMPT = """你是短视频文案质检员。给下面解说分镜打分并找问题。

选题: {topic}
标题: {title}
分镜 JSON:
{cues_json}

检查维度(0-1 分):
- hook: 开场是否 3 秒内抓住人
- clarity: 核心概念是否讲清楚
- pacing: 信息密度与节奏是否合适
- structure: 是否有起承转合/收束
- spoken: 是否适合口播(不拗口、不过长)

只输出 JSON:
{{
  "score": 0.0,
  "passed": false,
  "summary": "一句话总评",
  "issues": [
    {{"code":"weak_hook","message":"...","severity":"hard|soft","cue_index":0,"fix_hint":"..."}}
  ]
}}
passed 规则: score>={min_score} 且无 hard severity 问题。
"""

_REWRITE_PROMPT = """你是短视频解说编剧。按质检意见改写分镜,保留选题,修掉全部问题。

选题: {topic}
上一版 JSON:
{draft_json}

质检意见:
{verdict_json}

硬约束同原稿:钩子开头、中段讲点+例子、结尾收束;每镜 18-80 字口语。
只输出同结构 JSON: {{"title","hook","cues":[{{"narration","title","visual_query"}}]}}
"""


def _resolve_llm(llm: Any) -> Any:
    if llm is not None:
        return llm
    try:
        from hevi.providers.llm_pick import resolve_text_llm

        return resolve_text_llm()
    except Exception:
        return None


async def _call_llm_json(llm: Any, prompt: str, *, max_tokens: int = 2048) -> dict[str, Any]:
    """兼容 sync/async LLM 适配器,抽取 JSON object。"""
    if llm is None:
        return {}

    def _invoke() -> Any:
        return llm(messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens)

    try:
        is_async = inspect.iscoroutinefunction(llm) or inspect.iscoroutinefunction(
            type(llm).__call__
        )
        if is_async or inspect.isfunction(llm):
            obj = llm(messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens)
        else:
            obj = await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=60.0)
        resp = await asyncio.wait_for(obj, timeout=60.0) if inspect.isawaitable(obj) else obj
    except Exception as exc:
        logger.warning("script_loop LLM 调用失败: %s", exc)
        return {}

    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    if not content:
        return {}
    text = str(content).strip()
    if text.startswith("```"):
        m = re.search(r"```(?:json)?\n?(.*?)\n?```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _fallback_draft(topic: str, target_cues: int) -> ScriptDraft:
    """LLM 不可用时的确定性兜底文案(保证管线可测、可跑)。"""
    n = max(_MIN_CUES, min(_MAX_CUES, target_cues))
    bodies = [
        f"关于「{topic}」，先记住一个反常识：它比你想的更底层。",
        f"核心就一句话：{topic}解决的是「为什么」而不是「是什么」。",
        "举个生活例子：把它想象成日常里反复发生、却被忽略的那一步。",
        "容易踩坑的地方：把表象当机制，结果越学越乱。",
        f"收束一下：抓住机制，{topic}就从概念变成可解释的工具。",
    ]
    cues: list[LiteCue] = []
    for i in range(n):
        narration = bodies[i] if i < len(bodies) else f"继续理解{topic}的第{i + 1}个要点。"
        cues.append(
            LiteCue(
                index=i,
                narration=narration,
                props={
                    "title": f"要点 {i + 1}",
                    "eyebrow": "HEVI · LITE",
                    "visual_query": "abstract education motion",
                },
            )
        )
    return ScriptDraft(
        topic=topic,
        title=topic[:40],
        hook=cues[0].narration if cues else topic,
        cues=cues,
        target_cues=n,
    )


def _normalize_cues(raw_cues: list[Any], topic: str) -> list[LiteCue]:
    cues: list[LiteCue] = []
    for i, item in enumerate(raw_cues or []):
        if isinstance(item, LiteCue):
            cues.append(
                item.model_copy(
                    update={
                        "index": i,
                        "narration": item.narration.strip(),
                    }
                )
            )
            continue
        if not isinstance(item, dict):
            continue
        narration = str(item.get("narration") or item.get("text") or "").strip()
        if not narration:
            continue
        title = str(item.get("title") or f"{topic} · {i + 1}").strip()[:24]
        visual = str(item.get("visual_query") or item.get("broll") or topic).strip()[:80]
        props = dict(item.get("props") or {})
        props.setdefault("title", title)
        props.setdefault("eyebrow", "HEVI · LITE")
        props.setdefault("visual_query", visual)
        cues.append(LiteCue(index=i, narration=narration[:2000], props=props))
    # reindex
    for i, c in enumerate(cues):
        c.index = i
    return cues


def draft_from_dict(data: dict[str, Any], topic: str, target_cues: int) -> ScriptDraft:
    cues = _normalize_cues(data.get("cues") or [], topic)
    if not cues:
        return _fallback_draft(topic, target_cues)
    title = str(data.get("title") or topic).strip()[:80] or topic
    hook = str(data.get("hook") or (cues[0].narration if cues else topic)).strip()[:200]
    return ScriptDraft(
        topic=topic,
        title=title,
        hook=hook,
        cues=cues,
        target_cues=target_cues,
    )


def deterministic_verdict(draft: ScriptDraft, *, round_idx: int = 0) -> ScriptVerdict:
    """零 LLM 硬门 + 软提示。"""
    issues: list[ScriptIssue] = []
    cues = draft.cues
    n = len(cues)

    if n < _MIN_CUES:
        issues.append(
            ScriptIssue(
                code="too_few_cues",
                message=f"镜头过少({n}<{_MIN_CUES})",
                severity="hard",
                fix_hint=f"扩到至少 {_MIN_CUES} 镜",
            )
        )
    if n > _MAX_CUES:
        issues.append(
            ScriptIssue(
                code="too_many_cues",
                message=f"镜头过多({n}>{_MAX_CUES})",
                severity="hard",
                fix_hint=f"压缩到 {_MAX_CUES} 镜以内",
            )
        )

    weak_openers = ("大家好", "今天我们来", "本期视频", "哈喽", "hello")
    if cues:
        first = cues[0].narration.lstrip()
        if any(first.lower().startswith(w) or first.startswith(w) for w in weak_openers):
            issues.append(
                ScriptIssue(
                    code="weak_hook",
                    message="开场像客套寒暄,钩子不足",
                    severity="hard",
                    cue_index=0,
                    fix_hint="用反差/数字/问题句开场",
                )
            )
        if len(first) < _MIN_NARRATION:
            issues.append(
                ScriptIssue(
                    code="hook_too_short",
                    message="开场过短",
                    severity="hard",
                    cue_index=0,
                    fix_hint="开场至少 12 字",
                )
            )

    seen: set[str] = set()
    for c in cues:
        text = c.narration.strip()
        if len(text) < _MIN_NARRATION:
            issues.append(
                ScriptIssue(
                    code="narration_too_short",
                    message=f"第{c.index + 1}镜过短",
                    severity="hard",
                    cue_index=c.index,
                    fix_hint=f"补到 ≥{_MIN_NARRATION} 字",
                )
            )
        if len(text) > _MAX_NARRATION:
            issues.append(
                ScriptIssue(
                    code="narration_too_long",
                    message=f"第{c.index + 1}镜过长({len(text)}字)",
                    severity="soft",
                    cue_index=c.index,
                    fix_hint=f"压到 ≤{_MAX_NARRATION} 字",
                )
            )
        key = re.sub(r"\s+", "", text)
        if key in seen:
            issues.append(
                ScriptIssue(
                    code="duplicate_cue",
                    message=f"第{c.index + 1}镜与前文重复",
                    severity="hard",
                    cue_index=c.index,
                    fix_hint="改写差异化信息点",
                )
            )
        seen.add(key)

    if cues and not any(
        k in cues[-1].narration for k in ("所以", "总之", "记住", "一句话", "下次", "行动")
    ):
        issues.append(
            ScriptIssue(
                code="weak_close",
                message="结尾缺少收束信号",
                severity="soft",
                cue_index=cues[-1].index,
                fix_hint="最后一镜给结论或行动号召",
            )
        )

    hard = [i for i in issues if i.severity == "hard"]
    soft = [i for i in issues if i.severity == "soft"]
    # 粗分: 无 hard 起步 0.85, 每个 soft -0.05, 有 hard 上限 0.55
    score = 0.85 - 0.05 * len(soft)
    if hard:
        score = min(score, 0.55) - 0.08 * (len(hard) - 1)
    score = max(0.0, min(1.0, score))
    passed = not hard and score >= _MIN_SCORE
    summary = "确定性门通过" if passed else f"未过: {len(hard)} hard / {len(soft)} soft"
    return ScriptVerdict(
        passed=passed,
        score=score,
        issues=issues,
        summary=summary,
        round=round_idx,
        source="deterministic",
    )


def merge_verdicts(
    det: ScriptVerdict, llm: ScriptVerdict | None, *, round_idx: int
) -> ScriptVerdict:
    if llm is None:
        return det
    issues = list(det.issues) + list(llm.issues)
    hard = any(i.severity == "hard" for i in issues)
    score = min(det.score, llm.score) if llm.score > 0 else det.score
    passed = (not hard) and score >= _MIN_SCORE and det.passed and llm.passed
    return ScriptVerdict(
        passed=passed,
        score=score,
        issues=issues,
        summary=llm.summary or det.summary,
        round=round_idx,
        source="hybrid",
    )


async def draft_script(
    topic: str,
    *,
    target_cues: int = _DEFAULT_TARGET_CUES,
    llm: Any = None,
) -> ScriptDraft:
    """选题 → 文案草稿。LLM 失败走确定性兜底。"""
    topic = topic.strip()
    if not topic:
        raise ValueError("topic 不能为空")
    target = max(_MIN_CUES, min(_MAX_CUES, int(target_cues)))
    resolved = _resolve_llm(llm)
    if resolved is None:
        return _fallback_draft(topic, target)
    prompt = _DRAFT_PROMPT.format(
        topic=topic,
        target_cues=target,
        min_cues=_MIN_CUES,
        max_cues=_MAX_CUES,
    )
    data = await _call_llm_json(resolved, prompt)
    if not data:
        logger.warning("script draft 空响应,走 fallback")
        return _fallback_draft(topic, target)
    return draft_from_dict(data, topic, target)


async def llm_verdict(
    draft: ScriptDraft, *, llm: Any = None, round_idx: int = 0
) -> ScriptVerdict | None:
    resolved = _resolve_llm(llm)
    if resolved is None:
        return None
    cues_json = json.dumps(
        [
            {
                "index": c.index,
                "narration": c.narration,
                "title": (c.props or {}).get("title"),
            }
            for c in draft.cues
        ],
        ensure_ascii=False,
        indent=2,
    )
    prompt = _CRITIC_PROMPT.format(
        topic=draft.topic,
        title=draft.title,
        cues_json=cues_json,
        min_score=_MIN_SCORE,
    )
    data = await _call_llm_json(resolved, prompt, max_tokens=1024)
    if not data:
        return None
    issues: list[ScriptIssue] = []
    for raw in data.get("issues") or []:
        if not isinstance(raw, dict):
            continue
        sev = str(raw.get("severity") or "soft")
        if sev not in ("hard", "soft"):
            sev = "soft"
        idx = raw.get("cue_index")
        issues.append(
            ScriptIssue(
                code=str(raw.get("code") or "llm_issue"),
                message=str(raw.get("message") or "")[:300],
                severity=sev,  # type: ignore[arg-type]
                cue_index=int(idx) if idx is not None else None,
                fix_hint=str(raw.get("fix_hint") or "")[:200],
            )
        )
    try:
        score = float(data.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    passed = bool(data.get("passed")) and score >= _MIN_SCORE and not any(
        i.severity == "hard" for i in issues
    )
    return ScriptVerdict(
        passed=passed,
        score=score,
        issues=issues,
        summary=str(data.get("summary") or "")[:300],
        round=round_idx,
        source="llm",
    )


async def rewrite_draft(
    draft: ScriptDraft,
    verdict: ScriptVerdict,
    *,
    llm: Any = None,
) -> ScriptDraft:
    resolved = _resolve_llm(llm)
    if resolved is None:
        # 无 LLM: 做最小确定性修补
        return _deterministic_repair(draft, verdict)
    draft_json = draft.model_dump(mode="json")
    prompt = _REWRITE_PROMPT.format(
        topic=draft.topic,
        draft_json=json.dumps(draft_json, ensure_ascii=False, indent=2),
        verdict_json=verdict.model_dump_json(indent=2),
    )
    data = await _call_llm_json(resolved, prompt)
    if not data:
        return _deterministic_repair(draft, verdict)
    return draft_from_dict(data, draft.topic, draft.target_cues or _DEFAULT_TARGET_CUES)


def _deterministic_repair(draft: ScriptDraft, verdict: ScriptVerdict) -> ScriptDraft:
    """无 LLM 时的最小修补:去重、补长度、弱开场替换。"""
    cues = list(draft.cues)
    codes = {i.code for i in verdict.issues}
    if "weak_hook" in codes and cues:
        cues[0] = cues[0].model_copy(
            update={
                "narration": f"先别急着背定义——关于「{draft.topic}」，真正关键的是机制。"
            }
        )
    if "weak_close" in codes and cues:
        last = cues[-1]
        if "所以" not in last.narration and "记住" not in last.narration:
            cues[-1] = last.model_copy(
                update={
                    "narration": f"所以记住：{draft.topic}不是名词堆砌，而是一套可解释的机制。"
                }
            )
    # 去重
    seen: set[str] = set()
    cleaned: list[LiteCue] = []
    for c in cues:
        key = re.sub(r"\s+", "", c.narration)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(c)
    while len(cleaned) < _MIN_CUES:
        cleaned.append(
            LiteCue(
                index=len(cleaned),
                narration=f"补充理解{draft.topic}：抓住输入、过程与输出三条线。",
                props={"title": f"补充 {len(cleaned) + 1}", "eyebrow": "HEVI · LITE"},
            )
        )
    for i, c in enumerate(cleaned):
        c.index = i
        if len(c.narration) < _MIN_NARRATION:
            cleaned[i] = c.model_copy(
                update={"narration": c.narration + f" —— 这与{draft.topic}直接相关。"}
            )
    hook = cleaned[0].narration if cleaned else draft.hook
    return draft.model_copy(update={"cues": cleaned, "hook": hook})


async def run_veya_loop(
    topic: str,
    *,
    target_cues: int = _DEFAULT_TARGET_CUES,
    max_rounds: int = _DEFAULT_MAX_ROUNDS,
    llm: Any = None,
    initial_draft: ScriptDraft | None = None,
) -> VeyaLoopResult:
    """完整 veya-loop: 出稿 → 审 → 改, 直到通过或轮次耗尽。"""
    trail: list[dict[str, Any]] = []
    draft = initial_draft or await draft_script(topic, target_cues=target_cues, llm=llm)
    trail.append(
        {
            "stage": "draft",
            "outcome": "ok",
            "cues": len(draft.cues),
            "source": "seed" if initial_draft else "llm_or_fallback",
        }
    )
    verdicts: list[ScriptVerdict] = []
    rounds = 0
    passed = False

    for r in range(max(1, max_rounds)):
        rounds = r + 1
        det = deterministic_verdict(draft, round_idx=r)
        llm_v = await llm_verdict(draft, llm=llm, round_idx=r)
        verdict = merge_verdicts(det, llm_v, round_idx=r)
        verdicts.append(verdict)
        trail.append(
            {
                "stage": "veya_review",
                "round": r,
                "passed": verdict.passed,
                "score": verdict.score,
                "issues": len(verdict.issues),
                "source": verdict.source,
            }
        )
        if verdict.passed:
            passed = True
            break
        draft = await rewrite_draft(draft, verdict, llm=llm)
        trail.append({"stage": "veya_rewrite", "round": r, "cues": len(draft.cues)})

    # 终检一轮确定性(改写后可能仍有硬伤)
    if not passed:
        final_det = deterministic_verdict(draft, round_idx=rounds)
        verdicts.append(final_det)
        passed = final_det.passed
        trail.append(
            {
                "stage": "veya_final",
                "passed": passed,
                "score": final_det.score,
                "degraded": not passed,
            }
        )

    return VeyaLoopResult(
        draft=draft,
        passed=passed,
        rounds=rounds,
        verdicts=verdicts,
        decision_trail=trail,
    )


def cues_from_script_text(topic: str, script: str) -> list[LiteCue]:
    """用户手写多行文案 → cues(兼容旧 Lite 入口)。"""
    lines = [ln.strip() for ln in script.splitlines() if ln.strip()]
    return [
        LiteCue(
            index=i,
            narration=line,
            props={"title": f"{topic} · {i + 1}", "eyebrow": "HEVI · LITE"},
        )
        for i, line in enumerate(lines)
    ]


__all__ = [
    "cues_from_script_text",
    "deterministic_verdict",
    "draft_script",
    "run_veya_loop",
]
