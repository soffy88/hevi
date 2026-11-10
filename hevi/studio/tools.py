"""制片厂工具注册表 —— 已有模块的可调用积木,不是空声明。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.production.delivery_gate import PREVIEW_MAX_SECONDS, PREVIEW_MIN_SECONDS

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    kind: str
    summary: str
    input_keys: tuple[str, ...]
    output_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.tool_id,
            "kind": self.kind,
            "summary": self.summary,
            "input_keys": list(self.input_keys),
            "output_keys": list(self.output_keys),
        }


@dataclass(frozen=True)
class ToolResult:
    status: str
    tool_id: str
    payload: dict[str, Any]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "tool_id": self.tool_id,
            "payload": self.payload,
            "reason": self.reason,
        }


_SPECS: dict[str, ToolSpec] = {}
_HANDLERS: dict[str, Handler] = {}

# 产线默认视频候选(7 维,供 score.provider 在无外部候选时用)
DEFAULT_VIDEO_CANDIDATES: list[dict[str, Any]] = [
    {
        "provider": "h3_local",
        "task_fit": 0.85,
        "output_quality": 0.70,
        "control": 0.80,
        "reliability": 0.70,
        "cost_efficiency": 0.95,
        "latency": 0.40,
        "continuity": 0.70,
    },
    {
        "provider": "happyhorse_1_1_maas_lock",
        "task_fit": 0.90,
        "output_quality": 0.85,
        "control": 0.60,
        "reliability": 0.75,
        "cost_efficiency": 0.40,
        "latency": 0.60,
        "continuity": 0.65,
    },
    {
        "provider": "wan_local",
        "task_fit": 0.60,
        "output_quality": 0.50,
        "control": 0.50,
        "reliability": 0.60,
        "cost_efficiency": 1.00,
        "latency": 0.50,
        "continuity": 0.40,
    },
]


def register_tool(spec: ToolSpec, handler: Handler) -> None:
    _SPECS[spec.tool_id] = spec
    _HANDLERS[spec.tool_id] = handler


def list_tools() -> list[ToolSpec]:
    return [spec for _, spec in sorted(_SPECS.items())]


def get_tool(tool_id: str) -> ToolSpec | None:
    return _SPECS.get(tool_id)


async def invoke_tool(tool_id: str, payload: dict[str, Any] | None = None) -> ToolResult:
    spec = _SPECS.get(tool_id)
    handler = _HANDLERS.get(tool_id)
    if spec is None or handler is None:
        return ToolResult("failed", tool_id, {}, reason=f"unknown tool: {tool_id}")
    try:
        body = await handler(dict(payload or {}))
    except Exception as exc:
        logger.exception("studio tool %s failed", tool_id)
        return ToolResult("failed", tool_id, {}, reason=str(exc))
    status = str(body.pop("status", "ok"))
    reason = str(body.pop("reason", ""))
    return ToolResult(status, tool_id, body, reason=reason)


# ---------------------------------------------------------------------------
# handlers —— 直接调已落地模块
# ---------------------------------------------------------------------------


async def _research_plan(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.research.brief import plan_research_questions

    topic = str(payload.get("topic") or "").strip()
    if not topic:
        return {"status": "failed", "reason": "topic required"}
    angles = payload.get("angles") or ["fact", "worldview"]
    questions = plan_research_questions(topic, list(angles))
    return {"status": "ok", "questions": questions, "topic": topic}


async def _research_brief(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.research.brief import ResearchBrief, plan_research_questions, report_to_context

    topic = str(payload.get("topic") or "").strip()
    if not topic:
        return {"status": "failed", "reason": "topic required"}
    angles = list(payload.get("angles") or ["fact", "worldview"])
    caller = payload.get("caller")
    if caller is None:
        from hevi.providers.llm_pick import resolve_text_llm

        llm_fn = resolve_text_llm()
        if llm_fn is not None:

            class Adapter:
                async def call(self, system: str, prompt: str, temperature: float = 0.2) -> str:
                    res = await llm_fn(
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=temperature,
                    )
                    return res["content"]

            caller = Adapter()

    if caller is None:
        questions = plan_research_questions(topic, angles)
        return {
            "status": "ok",
            "topic": topic,
            "questions": questions,
            "findings": [],
            "context": "# 研究结果\n(未注入 LLM,仅排出研究问题)",
            "reason": "no caller; planned questions only",
        }
    from hevi.research.brief import run_research

    brief = ResearchBrief(topic=topic, angles=angles)
    report = await run_research(brief, caller)
    return {
        "status": "ok",
        "topic": topic,
        "questions": report.questions,
        "findings": report.findings,
        "sources": report.sources,
        "context": report_to_context(report),
    }


async def _watch_concepts(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.ingest.reference_concepts import derive_reference_concepts
    from hevi.ingest.video_watch import WatchResult

    watch = payload.get("watch")
    if isinstance(watch, WatchResult):
        result = watch
    else:
        text = str(payload.get("transcript") or payload.get("topic") or "")
        duration = float(payload.get("duration_s") or 0.0)
        result = WatchResult(source=str(payload.get("source") or "studio"), duration_s=duration)
        if text:
            from hevi.ingest.video_transcript import TranscriptSegment

            result.transcript.append(TranscriptSegment(start=0.0, end=duration, text=text))
    concepts = await derive_reference_concepts(result, llm=payload.get("llm"))
    return {"status": "ok", "concepts": concepts}


async def _video_evidence_index(payload: dict[str, Any]) -> dict[str, Any]:
    """VideoAgent 证据索引工具；事务本身负责 report/fingerprint/trail。"""

    from hevi.layer4_legacy.montage.omodul_impl.video_agent import video_evidence_index

    return await video_evidence_index(
        payload,
        payload,
        payload.get("output_dir") or "data/workspace/video-agent",
    )


async def _video_evidence_search(payload: dict[str, Any]) -> dict[str, Any]:
    """VideoAgent 证据检索工具；只返回时间戳 EvidenceRef。"""

    from hevi.layer4_legacy.montage.omodul_impl.video_agent import video_evidence_search

    return await video_evidence_search(
        payload,
        payload,
        payload.get("output_dir") or "data/workspace/video-agent",
    )


async def _video_script_from_transcript(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.layer4_legacy.montage.omodul_impl.video_agent import video_script_from_transcript

    return await video_script_from_transcript(
        payload, payload, payload.get("output_dir") or "output"
    )


async def _video_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """无 LLM 时提供可追溯的抽取式概览；高级摘要由 caller 注入。"""

    from hevi.layer4_legacy.montage.omodul_impl.video_agent import _read_refs

    index_path = Path(str(payload.get("index_path") or ""))
    if not index_path.is_file():
        return {"status": "blocked", "reason": "summary requires a local evidence index"}
    refs = _read_refs(index_path)
    text = " ".join(
        (ref.transcript or ref.caption).strip()
        for ref in refs
        if (ref.transcript or ref.caption).strip()
    )
    if not text:
        return {"status": "blocked", "reason": "evidence index has no transcript or caption"}
    summary = text[:1200]
    return {
        "status": "ok",
        "result": summary,
        "evidence_refs": [ref.model_dump(mode="json") for ref in refs[:8]],
        "summary_mode": "extractive",
    }


async def _video_qa(payload: dict[str, Any]) -> dict[str, Any]:
    """证据约束 QA：没有注入问答模型时返回证据，不编造答案。"""

    question = str(payload.get("question") or payload.get("query") or "").strip()
    if not question:
        return {"status": "failed", "reason": "question required"}
    index_path = str(payload.get("index_path") or "")
    if not index_path:
        return {"status": "blocked", "reason": "qa requires a local evidence index"}
    from hevi.layer4_legacy.montage.omodul_impl.video_agent import video_evidence_search

    result = await video_evidence_search(
        payload,
        {**payload, "index_path": index_path, "queries": [question]},
        payload.get("output_dir") or "data/workspace/video-agent",
    )
    if result.get("status") != "completed":
        return result
    refs = result.get("evidence_refs") or []
    caller = payload.get("caller")
    if caller is None:
        return {
            "status": "blocked",
            "reason": "evidence retrieved; inject a QA caller to produce a grounded answer",
            "evidence_refs": refs,
        }
    answer = caller(question=question, evidence=refs)
    if hasattr(answer, "__await__"):
        answer = await answer
    return {"status": "ok", "result": str(answer), "evidence_refs": refs}


async def _video_agent_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """VideoAgent 控制平面：只规划与反思，不执行生产副作用。"""

    from hevi.layer4_legacy.montage.omodul_impl.video_agent import _mapping
    from hevi.layer4_legacy.montage.oskill_impl.video_agent import (
        build_video_agent_plan,
        reflect_video_agent_plan,
    )

    data = _mapping(payload)
    available = {item.tool_id for item in list_tools()}
    plan = await build_video_agent_plan(
        str(data.get("requirement") or data.get("prompt") or data.get("topic") or ""),
        input_data=data,
        source_path=str(data.get("source_path") or data.get("media_path") or ""),
        available_tools=available,
        caller=data.get("caller"),
    )
    return {
        "status": "ok",
        "plan": plan.model_dump(mode="json"),
        "reflection": reflect_video_agent_plan(plan, available_tools=available),
    }


async def _video_agent_run(payload: dict[str, Any]) -> dict[str, Any]:
    """VideoAgent 事务入口；execute=false 时仅返回可审查计划。"""

    from hevi.layer4_legacy.montage.omodul_impl.video_agent import video_agent_transaction

    output_dir = payload.get("output_dir") or "output/montage/video-agent"
    return await video_agent_transaction(payload, payload, output_dir)


async def _warmgold_reference(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.explainer.warmgold import reference

    if not payload.get("rights_declared"):
        return {"status": "blocked", "reason": "需要声明对参考素材拥有权利"}
    work = Path("data/warmgold_reference") / (str(payload.get("run_id") or "canvas"))
    report = reference.decompose(payload, work)
    json_path, html_path = reference.write_report(report, work)
    return {
        "status": "ok",
        "report": report,
        "json_path": str(json_path),
        "html_path": str(html_path),
        "warnings": report.get("warnings") or [],
    }


async def _warmgold_beat_check(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.explainer.warmgold import beats, scriptcheck

    script = payload.get("script") or payload.get("content")
    if isinstance(script, str):
        import json as _json

        script = _json.loads(script)
    if not isinstance(script, dict) or not script.get("shots"):
        return {"status": "blocked", "reason": "需要逐拍脚本（shots）"}
    beat_data = beats.build_beats(script, music_path=payload.get("music_path") or None)
    result = scriptcheck.check_script(
        script, beat_data, music_present=bool(payload.get("music_path"))
    )
    return {"status": "ok" if result["pass"] else "blocked", **result}


async def _warmgold_render(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.explainer.warmgold import render

    script = payload.get("script") or payload.get("content")
    if isinstance(script, str):
        import json as _json

        script = _json.loads(script)
    if not isinstance(script, dict) or not script.get("shots"):
        return {"status": "blocked", "reason": "需要逐拍脚本（shots）"}
    run_id = str(payload.get("run_id") or "canvas")
    out = Path("output/warmgold") / f"{run_id}.mp4"
    report = render.render(
        script,
        out,
        workdir=Path("output/warmgold") / f"work_{run_id}",
        music_path=payload.get("music_path") or None,
        voice=bool(payload.get("voice", True)),
    )
    return {"status": "ok" if report.ok else "blocked", **report.to_dict()}


async def _style_search(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.style_library import catalog

    section = str(payload.get("section") or "styles")
    try:
        return catalog.search(
            section,
            query=str(payload.get("query") or payload.get("q") or ""),
            category=str(payload.get("category") or ""),
            use_case=str(payload.get("use_case") or ""),
            limit=int(payload.get("limit") or 60),
            offset=int(payload.get("offset") or 0),
        )
    except catalog.StyleLibraryError as exc:
        return {"status": "blocked", "reason": str(exc)}


async def _style_recommend(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.style_library import catalog

    return catalog.recommend(
        str(payload.get("topic") or ""),
        mood=str(payload.get("mood") or ""),
        platform=str(payload.get("platform") or ""),
        style_hint=str(payload.get("style_hint") or ""),
    )


async def _cover_build(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.style_library import cover

    plan = cover.plan_cover(
        payload.get("source") or payload,
        style_id=str(payload.get("style_id") or "FA-039"),
        theme_color_id=str(payload.get("theme_color_id") or "C-27"),
        layout_id=str(payload.get("layout_id") or "SC-016"),
        title=str(payload.get("title") or ""),
    )
    run_id = str(payload.get("run_id") or "canvas")
    out = Path("output/style_library/covers") / run_id
    manifest = cover.render_covers(plan, out, sizes=payload.get("sizes") or ["9:16", "3:4", "16:9"])
    return {"status": "ok" if manifest["ok"] else "blocked", **manifest}


async def _article_illustrate(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.style_library import article

    markdown = str(payload.get("markdown") or payload.get("content") or "")
    if not markdown.strip():
        return {"status": "blocked", "reason": "需要 article markdown"}
    run_id = str(payload.get("run_id") or "canvas")
    out = Path("output/style_library/articles") / run_id
    manifest = article.export_article(
        markdown,
        out,
        style_id=str(payload.get("style_id") or "FA-001"),
        theme_color_id=str(payload.get("theme_color_id") or "C-05"),
        points=int(payload.get("points") or 3),
        title=str(payload.get("title") or ""),
    )
    return {"status": "ok", **manifest}


async def _script_quick(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.quick.service import QuickVideoConfig, plan_quick

    topic = str(payload.get("topic") or "").strip()
    if not topic:
        return {"status": "failed", "reason": "topic required"}
    cfg = QuickVideoConfig(
        target_duration_s=float(payload.get("target_duration_s") or 40.0),
        max_lines=int(payload.get("max_lines") or 6),
    )
    plan = await plan_quick(topic, cfg)
    return {"status": "ok", **plan.to_dict()}


async def _material_rank(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.video.material_corpus import MaterialInfo, rank_by_keywords

    query = str(payload.get("query") or payload.get("topic") or "").strip()
    raw_items = payload.get("items") or []
    items = [
        MaterialInfo(
            source=str(it.get("source") or "local"),
            id=str(it.get("id") or ""),
            url=str(it.get("url") or ""),
            title=str(it.get("title") or ""),
            keywords=tuple(it.get("keywords") or ()),
            width=int(it.get("width") or 0),
            height=int(it.get("height") or 0),
            duration_s=float(it.get("duration_s") or 0.0),
        )
        for it in raw_items
        if isinstance(it, dict) and it.get("id")
    ]
    ranked = rank_by_keywords(items, query, target_aspect=str(payload.get("aspect") or ""))
    return {"status": "ok", "query": query, "items": [m.to_dict() for m in ranked]}


async def _score_provider(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.providers.scoring import choose_provider

    tool_name = str(payload.get("tool_name") or "video/shot")
    candidates = payload.get("candidates") or DEFAULT_VIDEO_CANDIDATES
    log_path = payload.get("decision_log")
    winner = choose_provider(
        tool_name,
        candidates,
        decision_log=Path(log_path) if log_path else None,
        reason=str(payload.get("reason") or "studio.score.provider"),
    )
    if winner is None:
        return {"status": "failed", "reason": "no candidates"}
    return {"status": "ok", "winner": winner.to_dict(), "explain": winner.explain()}


async def _memory_remember(payload: dict[str, Any]) -> dict[str, Any]:
    store = _memory_store(payload)
    key = str(payload.get("key") or "").strip()
    if not key:
        return {"status": "failed", "reason": "key required"}
    rec = store.remember(
        str(payload.get("kind") or "short_term"),
        key,
        payload.get("payload") or {},
    )
    return {"status": "ok", "id": rec}


async def _memory_recall(payload: dict[str, Any]) -> dict[str, Any]:
    store = _memory_store(payload)
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"status": "failed", "reason": "query required"}
    hits = store.recall(query, k=int(payload.get("k") or 3))
    return {
        "status": "ok",
        "hits": [
            {
                "id": h.id,
                "kind": h.kind,
                "key": h.key,
                "payload": h.payload,
                "score": h.score,
            }
            for h in hits
        ],
    }


async def _nle_edit_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """ChatCut 式:编辑对象是时间线,不是再跑一条管线。"""
    lines = payload.get("script_lines") or []
    materials = payload.get("materials") or []
    cuts: list[dict[str, Any]] = []
    cursor = 0.0
    for i, line in enumerate(lines):
        text = str(line.get("text") or line) if isinstance(line, dict) else str(line)
        dur = max(2.5, min(8.0, len(text) / 8.0))
        mat = materials[i] if i < len(materials) else None
        source = ""
        source_in_s = 0.0
        material_duration = 0.0
        if isinstance(mat, dict):
            # EvidenceRef is the only material shape accepted by this path:
            # preserve its local source and source time window.
            source = str(mat.get("source_path") or mat.get("path") or mat.get("url") or "")
            source_in_s = float(mat.get("start_s") or mat.get("source_in_s") or 0.0)
            material_duration = max(0.0, float(mat.get("end_s") or 0.0) - source_in_s)
        duration = min(dur, material_duration) if material_duration > 0 else dur
        cuts.append(
            {
                "index": i,
                "start_s": round(cursor, 2),
                "duration_s": round(max(0.4, duration), 2),
                "text": text,
                "visual": source or None,
                "source_in_s": round(source_in_s, 3),
                "action": "keep",
            }
        )
        cursor += max(0.4, duration)
    return {
        "status": "ok",
        "edit_plan": {
            "kind": "nle_edit_plan",
            "total_s": round(cursor, 2),
            "cuts": cuts,
        },
    }


async def _delivery_preview(payload: dict[str, Any]) -> dict[str, Any]:
    estimate = float(payload.get("estimate_s") or 0.0)
    in_band = PREVIEW_MIN_SECONDS <= estimate <= PREVIEW_MAX_SECONDS if estimate else True
    return {
        "status": "ok",
        "preview_min_s": PREVIEW_MIN_SECONDS,
        "preview_max_s": PREVIEW_MAX_SECONDS,
        "estimate_s": estimate,
        "in_band": in_band,
    }


async def _asset_bind(payload: dict[str, Any]) -> dict[str, Any]:
    from hevi.studio.assets import bind_asset

    kind = str(payload.get("kind") or "")
    label = str(payload.get("label") or kind)
    line_id = str(payload.get("line_id") or "studio")
    try:
        ref = bind_asset(
            kind,
            line_id=line_id,
            label=label,
            payload=payload.get("asset") or {},
            asset_id=payload.get("asset_id"),
        )
    except ValueError as exc:
        return {"status": "failed", "reason": str(exc)}
    return {"status": "ok", "asset": ref.to_dict()}


def _memory_store(payload: dict[str, Any]) -> Any:
    from hevi.memory.store import MemoryStore

    if payload.get("store") is not None:
        return payload["store"]
    path = payload.get("db_path") or "data/memory/studio.db"
    return MemoryStore(Path(path))


def _register_kit_tools() -> None:
    from hevi.studio.kit import KIT_HANDLERS, KIT_SPECS

    async def _wrap(fn: Any, payload: dict[str, Any]) -> dict[str, Any]:
        result = fn(payload)
        if hasattr(result, "__await__"):
            return dict(await result)
        return dict(result)

    for tool_id, kind, summary, inputs, outputs in KIT_SPECS:
        handler = KIT_HANDLERS[tool_id]

        async def _run(payload: dict[str, Any], _fn: Any = handler) -> dict[str, Any]:
            return await _wrap(_fn, payload)

        register_tool(ToolSpec(tool_id, kind, summary, inputs, outputs), _run)


def _register_defaults() -> None:
    register_tool(
        ToolSpec(
            "research.plan",
            "research",
            "按角度排出可引用研究问题",
            ("topic",),
            ("questions",),
        ),
        _research_plan,
    )
    register_tool(
        ToolSpec(
            "research.brief",
            "research",
            "跑研究并产出带引用的 brief",
            ("topic",),
            ("findings", "context"),
        ),
        _research_brief,
    )
    register_tool(
        ToolSpec(
            "watch.concepts",
            "watch",
            "参考片节奏 → 差异化概念",
            ("transcript",),
            ("concepts",),
        ),
        _watch_concepts,
    )
    register_tool(
        ToolSpec(
            "video.evidence.index",
            "watch",
            "本地视频→带 hash/时间戳的证据索引",
            ("source_path",),
            ("index_path", "manifest_path"),
        ),
        _video_evidence_index,
    )
    register_tool(
        ToolSpec(
            "video.evidence.search",
            "material",
            "细粒度视觉查询→EvidenceRef",
            ("index_path", "queries"),
            ("evidence_refs", "per_query"),
        ),
        _video_evidence_search,
    )
    register_tool(
        ToolSpec(
            "video.script.from_transcript",
            "script",
            "带时间戳转写→脚本分段",
            ("transcript",),
            ("script_lines",),
        ),
        _video_script_from_transcript,
    )
    register_tool(
        ToolSpec(
            "video.summary",
            "watch",
            "证据约束的视频抽取式概览",
            ("index_path",),
            ("result", "evidence_refs"),
        ),
        _video_summary,
    )
    register_tool(
        ToolSpec(
            "video.qa",
            "watch",
            "证据约束 Video QA",
            ("index_path", "question"),
            ("result", "evidence_refs"),
        ),
        _video_qa,
    )
    register_tool(
        ToolSpec(
            "video.agent.plan",
            "director",
            "自然语言→类型化 VideoAgent DAG",
            ("requirement",),
            ("plan", "reflection"),
        ),
        _video_agent_plan,
    )
    register_tool(
        ToolSpec(
            "video.agent.run",
            "director",
            "VideoAgent 规划/检索/执行事务",
            ("requirement",),
            ("findings", "artifact_manifest"),
        ),
        _video_agent_run,
    )
    register_tool(
        ToolSpec("script.quick", "script", "主题 → 可装配脚本行", ("topic",), ("script_lines",)),
        _script_quick,
    )
    register_tool(
        ToolSpec(
            "material.rank",
            "material",
            "素材按关键词/画幅排序",
            ("query", "items"),
            ("items",),
        ),
        _material_rank,
    )
    register_tool(
        ToolSpec(
            "score.provider",
            "score",
            "7 维可解释选 provider",
            ("tool_name",),
            ("winner", "explain"),
        ),
        _score_provider,
    )
    register_tool(
        ToolSpec("memory.remember", "memory", "写入跨会话记忆", ("key", "payload"), ("id",)),
        _memory_remember,
    )
    register_tool(
        ToolSpec("memory.recall", "memory", "语义召回制片记忆", ("query",), ("hits",)),
        _memory_recall,
    )
    register_tool(
        ToolSpec(
            "nle.edit_plan",
            "nle",
            "脚本+素材 → 可改时间线",
            ("script_lines",),
            ("edit_plan",),
        ),
        _nle_edit_plan,
    )
    register_tool(
        ToolSpec(
            "delivery.preview",
            "delivery",
            "试播 60–90s 预算闸",
            ("estimate_s",),
            ("in_band",),
        ),
        _delivery_preview,
    )
    register_tool(
        ToolSpec("asset.bind", "asset", "登记跨产线资产引用", ("kind", "label"), ("asset",)),
        _asset_bind,
    )
    register_tool(
        ToolSpec(
            "explainer.reference_breakdown",
            "watch",
            "参考片 → 互动比例/爆点卡/信息差/心理链/原句禁用清单（需声明权利）",
            ("video_path", "interactions", "transcript", "rights_declared"),
            ("report", "json_path", "html_path"),
        ),
        _warmgold_reference,
    )
    register_tool(
        ToolSpec(
            "explainer.beat_check",
            "script",
            "暖黑金逐拍脚本自检（17 条规则）",
            ("script", "music_path"),
            ("pass", "issues", "metrics"),
        ),
        _warmgold_beat_check,
    )
    register_tool(
        ToolSpec(
            "explainer.warmgold_render",
            "render",
            "暖黑金图解逐帧渲染（HTML/SVG + ffmpeg，不用 Remotion）",
            ("script", "music_path", "voice"),
            ("video_path", "report"),
        ),
        _warmgold_render,
    )
    register_tool(
        ToolSpec(
            "style.search",
            "style",
            "风格库检索（370 风格 / 170 排版 / 36 主题色）",
            ("query", "section", "category", "use_case"),
            ("styles", "layouts", "colors"),
        ),
        _style_search,
    )
    register_tool(
        ToolSpec(
            "style.recommend",
            "style",
            "按主题情绪自动推荐风格+主题色+版式，并给一句理由",
            ("topic", "mood", "platform"),
            ("style", "theme_color", "layout", "reason"),
        ),
        _style_recommend,
    )
    register_tool(
        ToolSpec(
            "cover.build",
            "render",
            "封面节点：摘要/受众/视觉隐喻 → 9:16 / 3:4 / 16:9 文字层封面",
            ("source", "style_id", "theme_color_id", "layout_id", "title"),
            ("covers", "checks", "plan"),
        ),
        _cover_build,
    )
    register_tool(
        ToolSpec(
            "article.illustrate",
            "render",
            "长文配图规划：2–5 个点位、单风格单色、Markdown/公众号 HTML",
            ("markdown", "style_id", "theme_color_id", "points"),
            ("markdown", "wechat_html", "images", "plan"),
        ),
        _article_illustrate,
    )
    _register_kit_tools()
    _register_ai_drama_tools()
    _register_anidoodle_tools()
    from hevi.studio.catalog import register_catalog

    register_catalog()


def _register_anidoodle_tools() -> None:
    """S29: code-drawn styles, drawing-process clips, code music and gates.

    Each is its own node, so a failed still does not throw away a clip and a
    failed music check does not block a picture. The handlers are thin wrappers
    over ``hevi.anidoodle`` and fail closed with the engine's message.
    """

    async def _styles(payload: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from hevi.anidoodle import (
            families,
            list_styles,
            recommend_style,
            validation_for,
        )

        topic = str(payload.get("topic") or "")
        intent = str(payload.get("intent") or "")
        return {
            "styles": [{**style.to_dict(), **validation_for(style.id)} for style in list_styles()],
            "families": families(),
            "recommendation": (
                await asyncio.to_thread(recommend_style, topic, intent=intent)
                if topic or intent
                else None
            ),
        }

    async def _still(payload: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from hevi.anidoodle import render_still

        return await asyncio.to_thread(
            render_still,
            str(payload.get("style_id") or ""),
            frame=payload.get("frame"),
            scale=float(payload.get("scale") or 1.0),
        )

    async def _draw(payload: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from hevi.anidoodle import render_draw_clip

        return await asyncio.to_thread(
            render_draw_clip,
            str(payload.get("style_id") or ""),
            poster_frame=payload.get("poster_frame"),
            scale=float(payload.get("scale") or 1.0),
        )

    async def _music(payload: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from hevi.anidoodle import compose_bgm

        return await asyncio.to_thread(
            compose_bgm,
            style=str(payload.get("style") or "lofiElectronic"),
            mood=str(payload.get("mood") or ""),
            key=str(payload.get("key") or ""),
            bpm=int(payload.get("bpm") or 0),
            bars=int(payload.get("bars") or 12),
            seed=int(payload.get("seed") or 29),
            fmt=str(payload.get("format") or "mp3"),
        )

    async def _gate(payload: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from hevi.anidoodle import run_gate, run_verify_export

        mp4 = str(payload.get("mp4") or "")
        gate = await asyncio.to_thread(
            run_gate, str(payload.get("film") or ""), mp4, bool(payload.get("drawing", True))
        )
        verify = await asyncio.to_thread(run_verify_export, mp4)
        return {"gate": gate, "verify_export": verify}

    register_tool(
        ToolSpec(
            "anidoodle.styles",
            "style",
            "anidoodle 32 种代码手绘风格；按主题/用途推荐并给理由",
            ("topic", "intent"),
            ("styles", "families", "recommendation"),
        ),
        _styles,
    )
    register_tool(
        ToolSpec(
            "anidoodle.still",
            "render",
            "anidoodle 成图节点：一种风格的一张完成稿（PNG，可复现）",
            ("style_id", "frame", "scale"),
            ("path", "md5", "reproducible"),
        ),
        _still,
    )
    register_tool(
        ToolSpec(
            "anidoodle.draw_clip",
            "render",
            "anidoodle 绘制过程片节点：线稿→铺色→细节，末帧=成图；独立 gate/verify",
            ("style_id", "poster_frame", "scale"),
            ("path", "determinism", "gate", "verify_export"),
        ),
        _draw,
    )
    register_tool(
        ToolSpec(
            "anidoodle.music",
            "audio",
            "anidoodle 代码作曲节点：无录音、无音色包；自检调式/响度/掩蔽/分轨/novelty",
            ("style", "mood", "bars", "seed"),
            ("path", "check"),
        ),
        _music,
    )
    register_tool(
        ToolSpec(
            "anidoodle.gate",
            "qa",
            "anidoodle 成片自检：确定性、死空镜、音画/峰值/文字裁切",
            ("film", "mp4", "drawing"),
            ("gate", "verify_export"),
        ),
        _gate,
    )


def _register_ai_drama_tools() -> None:
    """Expose the ai_drama stage/series nodes as Studio tools.

    Canvas dispatch for these ids goes through
    ``hevi.ai_drama.canvas_nodes.run_canvas_tool`` so upstream documents are
    threaded; this registration makes them listable and callable from the tool
    palette too.
    """
    from hevi.ai_drama.canvas_nodes import ALL_TOOLS

    summaries = {
        "drama.series_create": ("asset", "建立系列固定 cast 与角色卡"),
        "drama.series_topics": ("script", "3 个 15–20s 点子 + 前 2 秒钩子 + 推荐"),
        "drama.series_beats": ("script", "约 5 拍节拍脚本（可只改一拍、支持 POV）"),
        "drama.series_episode": ("video", "系列单集：选题→节拍→闸门→成片"),
        "drama.series_review": ("script", "各集播放量 → 最好类型 → 下一集 3 个点子"),
        "drama.stage_script": ("script", "drama 节点：剧本"),
        "drama.stage_storyboard": ("script", "drama 节点：分镜"),
        "drama.stage_assets": ("asset", "drama 节点：资产身份板/场景/道具"),
        "drama.stage_voice": ("audio", "drama 节点：固定音色与参考"),
        "drama.stage_segments": ("video", "drama 节点：视频段（成本闸门）"),
        "drama.stage_edit": ("script", "drama 节点：剪辑单/多语字幕/BGM/音效"),
        "drama.stage_publish": ("video", "drama 节点：9:16 成片"),
    }

    def _make(tool_id: str) -> Handler:
        async def _run(payload: dict[str, Any]) -> dict[str, Any]:
            from hevi.ai_drama.canvas_nodes import run_canvas_tool

            return await run_canvas_tool(tool_id, payload, {})

        return _run

    for tool_id in ALL_TOOLS:
        kind, summary = summaries.get(tool_id, ("script", "drama 节点"))
        register_tool(
            ToolSpec(
                tool_id,
                kind,
                summary,
                ("topic", "series_dir", "out_dir"),
                ("output", "ai_drama_state"),
            ),
            _make(tool_id),
        )


_register_defaults()
