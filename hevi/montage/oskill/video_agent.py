"""VideoAgent 规划与检索技能。

LLM（如果注入）只提出意图/查询建议；节点图由本模块的确定性编译器生成，
因此模型输出不会直接变成可执行代码。所有技能均不写文件、不入库。
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Protocol
from uuid import uuid4

from hevi.montage.oprim.video_agent import (
    EvidenceQuery,
    PlanEdge,
    PlanNode,
    PlanPort,
    VideoAgentPlan,
    VideoIntent,
    build_storyboard_queries,
    validate_video_agent_plan,
)


def rank_evidence_candidates(
    candidates: Sequence[Any],
    query: EvidenceQuery,
    *,
    used_segment_ids: set[str] | None = None,
    embedder: Callable[[str], list[float]] | None = None,
) -> list[Any]:
    """按视觉/文本相似度、时长约束和多样性重排证据候选。

    候选由上层注入，技能本身不读索引、不写文件。
    """

    from hevi.memory.store import TfIdfEmbedder, cosine_similarity

    encode = embedder or TfIdfEmbedder().embed
    query_vector = encode(query.text)
    used = used_segment_ids or set()
    ranked: list[tuple[float, Any]] = []
    query_terms = {term for term in re.findall(r"[\w\u4e00-\u9fff]+", query.text.lower()) if term}
    for candidate in candidates:
        if getattr(candidate, "segment_id", "") in used:
            continue
        if query.start_s is not None and candidate.end_s <= query.start_s:
            continue
        if query.end_s is not None and candidate.start_s >= query.end_s:
            continue
        text = f"{candidate.transcript} {candidate.caption}".lower()
        lexical = sum(1 for term in query_terms if term in text) / max(1, len(query_terms))
        semantic = cosine_similarity(query_vector, candidate.embedding)
        duration_fit = 1.0
        if query.target_duration_s and candidate.duration_s > 0:
            duration_fit = min(candidate.duration_s, query.target_duration_s) / max(
                candidate.duration_s, query.target_duration_s
            )
        score = 0.55 * semantic + 0.35 * lexical + 0.10 * duration_fit
        ranked.append((score, candidate.model_copy(update={"score": round(score, 6)})))
    ranked.sort(key=lambda item: (-item[0], item[1].source_path, item[1].start_s))
    return [item[1] for item in ranked[: query.top_k]]


class VideoIntentCaller(Protocol):
    """可注入的 LLM 调用边界，不绑定具体厂商。"""

    def __call__(self, **kwargs: Any) -> Any: ...


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _call_intent_model(caller: VideoIntentCaller, requirement: str) -> dict[str, Any]:
    prompt = {
        "task": "video_intent_analysis",
        "requirement": requirement,
        "output": {
            "intents": ["understand", "edit", "remake", "qa", "summary", "beat_sync"],
            "implicit_requirements": ["..."],
            "constraints": {"aspect_ratio": "9:16", "duration_s": 60},
            "visual_queries": ["..."],
        },
        "rules": [
            "Return JSON only.",
            "Do not select tools or emit executable code.",
            "Do not invent missing media paths or facts.",
        ],
    }
    try:
        raw = await _await(
            caller(
                messages=[
                    {"role": "system", "content": "You analyze video intent safely."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                max_tokens=1200,
            )
        )
    except TypeError:
        raw = await _await(caller(prompt=prompt))
    if hasattr(raw, "choices") and raw.choices:
        raw = raw.choices[0].message.content
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("intent caller returned no JSON object")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("intent caller returned a non-object")
    return parsed


def infer_video_intent(
    requirement: str,
    *,
    source_path: str = "",
    input_data: Mapping[str, Any] | None = None,
    model_hint: Mapping[str, Any] | None = None,
) -> VideoIntent:
    """从自然语言生成可审计的显式/隐式意图；无模型时也可执行。"""

    text = str(requirement or "").strip()
    lowered = text.lower()
    data = dict(input_data or {})
    hint = dict(model_hint or {})
    terms = {
        "qa": ("问", "回答", "qa", "question", "what", "who", "when", "哪里"),
        "summary": ("总结", "摘要", "概览", "overview", "summar", "梳理"),
        "edit": ("剪", "编辑", "montage", "cut", "clip", "拼接", "混剪"),
        "remake": ("改编", "重制", "remix", "remake", "meme", "新的视频"),
        "beat_sync": ("节拍", "卡点", "rhythm", "beat", "音乐视频", "music video"),
        "localization": ("翻译", "字幕", "配音", "dub", "translate", "多语言"),
        "commentary": ("解说", "评论", "commentary", "新闻", "news"),
    }
    intents = [
        name
        for name, candidates in terms.items()
        if any(candidate in lowered or candidate in text for candidate in candidates)
    ]
    hinted = [str(item) for item in hint.get("intents", []) if str(item).strip()]
    for intent in hinted:
        if intent not in intents:
            intents.append(intent)
    if not intents:
        intents = ["edit"] if source_path or data.get("evidence_index_path") else ["understand"]

    constraints = dict(hint.get("constraints") or {})
    if data.get("aspect_ratio"):
        constraints["aspect_ratio"] = str(data["aspect_ratio"])
    if data.get("target_duration_s"):
        constraints["duration_s"] = float(data["target_duration_s"])
    aspect_match = re.search(r"(?:画幅|比例|aspect)[：:= ]*([0-9]+:[0-9]+)", text, re.I)
    if aspect_match:
        constraints["aspect_ratio"] = aspect_match.group(1)
    duration_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:秒|s|second)", text, re.I)
    if duration_match:
        constraints["duration_s"] = float(duration_match.group(1))

    explicit = [name for name in intents if name in terms]
    implicit: list[str] = [str(item) for item in hint.get("implicit_requirements", [])]
    if any(item in {"edit", "remake", "beat_sync", "commentary"} for item in intents):
        implicit.extend(["素材必须绑定到带时间戳的证据片段", "输出时间线必须可再次编辑"])
    if "localization" in intents:
        implicit.append("字幕/配音需要保留语言和时间轴对应关系")
    implicit = list(dict.fromkeys(implicit))

    output_type: Literal["video", "answer", "summary"] = "video"
    if "qa" in intents:
        output_type = "answer"
    elif "summary" in intents and not any(item in intents for item in ("edit", "remake", "beat_sync")):
        output_type = "summary"

    missing: list[str] = []
    if ("qa" in intents or "summary" in intents or any(item in intents for item in ("edit", "remake"))) and not (
        source_path or data.get("source_path") or data.get("media_path") or data.get("evidence_index_path")
    ):
        missing.append("source_path 或 evidence_index_path")
    if (
        output_type == "video"
        and any(item in intents for item in ("edit", "remake", "beat_sync"))
        and not data.get("script_lines")
        and not data.get("transcript")
        and not data.get("source_path")
    ):
        missing.append("script_lines 或 transcript")

    return VideoIntent(
        requirement=text,
        intents=intents,
        output_type=output_type,
        explicit_requirements=explicit,
        implicit_requirements=list(dict.fromkeys(implicit)),
        constraints=constraints,
        missing_inputs=list(dict.fromkeys(missing)),
    )


async def build_video_agent_plan(
    requirement: str,
    *,
    input_data: Mapping[str, Any] | None = None,
    source_path: str = "",
    available_tools: set[str] | None = None,
    caller: VideoIntentCaller | None = None,
) -> VideoAgentPlan:
    """生成受约束的 VideoAgent 计划。

    可选 LLM 只增强意图和视觉查询，节点和连线仍由确定性编译器产生。
    """

    data = dict(input_data or {})
    source = str(source_path or data.get("source_path") or data.get("media_path") or "").strip()
    warnings: list[str] = []
    model_hint: dict[str, Any] = {}
    if caller is not None:
        try:
            model_hint = await _call_intent_model(caller, requirement)
        except Exception as exc:
            warnings.append(f"intent model unavailable; deterministic fallback used: {exc}")
    intent = infer_video_intent(requirement, source_path=source, input_data=data, model_hint=model_hint)

    tools = set(available_tools or _DEFAULT_TOOLS)
    nodes: list[PlanNode] = []
    edges: list[PlanEdge] = []
    queries = build_storyboard_queries(
        data.get("scenes") or data.get("script_lines") or model_hint.get("visual_queries") or [requirement],
        default_duration_s=float(intent.constraints.get("duration_s") or 5.0),
    )

    needs_source = bool(source)
    needs_evidence = any(item in intent.intents for item in ("edit", "remake", "beat_sync", "commentary"))
    needs_index = needs_evidence or intent.output_type in {"answer", "summary"}
    watch_node: PlanNode | None = None
    index_node: PlanNode | None = None

    if needs_source:
        watch_node = PlanNode(
            node_id="watch",
            capability="video_analyze",
            tool_id="watch.video",
            inputs=[PlanPort(name="source", type="path", description="本地视频路径")],
            outputs=[
                PlanPort(name="watch", type="json", description="带时间戳的多模态观察结果"),
                PlanPort(name="transcript", type="text", description="视频转写"),
            ],
            requirements={"source_path": source},
        )
        nodes.append(watch_node)
    if needs_index:
        if source:
            index_node = PlanNode(
                node_id="evidence-index",
                capability="video_evidence_index",
                tool_id="video.evidence.index",
                inputs=[PlanPort(name="source", type="path", description="待索引视频")],
                outputs=[PlanPort(name="index_path", type="path", description="本地证据索引")],
                depends_on=["watch"] if watch_node else [],
                requirements={"segment_length_s": float(data.get("segment_length_s") or 10.0)},
            )
            nodes.append(index_node)
        if not index_node and not data.get("evidence_index_path"):
            intent.missing_inputs.append("evidence_index_path")
        if needs_evidence:
            search = PlanNode(
                node_id="evidence-search",
                capability="video_evidence_search",
                tool_id="video.evidence.search",
                inputs=[
                    PlanPort(name="index_path", type="path", description="证据索引路径"),
                    PlanPort(name="queries", type="json", description="细粒度视觉查询"),
                ],
                outputs=[PlanPort(name="evidence_refs", type="json", description="带时间戳证据引用")],
                depends_on=["evidence-index"] if index_node else [],
                requirements={
                    "queries": [query.model_dump(mode="json") for query in queries],
                    **({"index_path": str(data["evidence_index_path"])} if data.get("evidence_index_path") else {}),
                },
            )
            nodes.append(search)
            if index_node:
                    edges.append(
                        PlanEdge(
                            source_node="evidence-index",
                            source_port="index_path",
                            target_node="evidence-search",
                            target_port="index_path",
                        )
                    )

    if intent.output_type == "video":
        script_node: PlanNode | None = None
        if watch_node and not data.get("script_lines"):
            script_node = PlanNode(
                node_id="transcript-script",
                capability="script",
                tool_id="video.script.from_transcript",
                inputs=[PlanPort(name="transcript", type="text", description="视频转写")],
                outputs=[PlanPort(name="script_lines", type="json", description="带时长的脚本分段")],
                depends_on=["watch"],
            )
            nodes.append(script_node)
            edges.append(
                PlanEdge(
                    source_node="watch",
                    source_port="transcript",
                    target_node="transcript-script",
                    target_port="transcript",
                )
            )
        edit = PlanNode(
            node_id="edit-plan",
            capability="edit_plan",
            tool_id="nle.edit_plan",
            inputs=[
                PlanPort(name="script_lines", type="json", description="脚本/旁白分段"),
                PlanPort(name="materials", type="json", description="证据片段素材", required=needs_evidence),
            ],
            outputs=[PlanPort(name="edit_plan", type="json", description="可编辑时间线计划")],
            depends_on=(["evidence-search"] if needs_evidence else [])
            + (["transcript-script"] if script_node else []),
        )
        timeline = PlanNode(
            node_id="timeline",
            capability="video_compose",
            tool_id="timeline.create",
            inputs=[PlanPort(name="edit_plan", type="json", description="剪辑计划")],
            outputs=[PlanPort(name="timeline", type="json", description="可编辑时间线")],
            depends_on=["edit-plan"],
        )
        export = PlanNode(
            node_id="export",
            capability="video_compose",
            tool_id="timeline.export",
            inputs=[PlanPort(name="timeline", type="json", description="时间线")],
            outputs=[PlanPort(name="video_path", type="path", description="本地产物视频")],
            depends_on=["timeline"],
            side_effects=["write_local_artifact"],
        )
        nodes.extend([edit, timeline, export])
        if needs_evidence:
            edges.append(
                PlanEdge(
                    source_node="evidence-search",
                    source_port="evidence_refs",
                    target_node="edit-plan",
                    target_port="materials",
                )
            )
        if script_node:
            edges.append(
                PlanEdge(
                    source_node="transcript-script",
                    source_port="script_lines",
                    target_node="edit-plan",
                    target_port="script_lines",
                )
            )
        elif data.get("script_lines"):
            edit.requirements["script_lines"] = data["script_lines"]
        else:
            intent.missing_inputs.append("script_lines")
        edges.extend(
            [
                PlanEdge(
                    source_node="edit-plan",
                    source_port="edit_plan",
                    target_node="timeline",
                    target_port="edit_plan",
                ),
                PlanEdge(
                    source_node="timeline",
                    source_port="timeline",
                    target_node="export",
                    target_port="timeline",
                ),
            ]
        )
    elif intent.output_type in {"answer", "summary"}:
        tool_id = "video.qa" if intent.output_type == "answer" else "video.summary"
        inputs = [PlanPort(name="index_path", type="path", description="证据索引路径")]
        requirements: dict[str, Any] = {}
        if data.get("evidence_index_path") and not index_node:
            requirements["index_path"] = str(data["evidence_index_path"])
        if intent.output_type == "answer":
            inputs.append(PlanPort(name="question", type="text", description="用户问题"))
            requirements["question"] = str(data.get("question") or requirement)
        node = PlanNode(
            node_id="video-understanding",
            capability="video_qa" if intent.output_type == "answer" else "video_summary",
            tool_id=tool_id,
            inputs=inputs,
            outputs=[PlanPort(name="result", type="text", description="问答/摘要结果")],
            depends_on=["evidence-index"] if index_node else [],
            requirements=requirements,
        )
        nodes.append(node)
        if index_node:
            edges.append(
                PlanEdge(
                    source_node="evidence-index",
                    source_port="index_path",
                    target_node="video-understanding",
                    target_port="index_path",
                )
            )

    plan = VideoAgentPlan(
        plan_id=f"vap-{uuid4().hex[:12]}",
        intent=intent,
        nodes=nodes,
        edges=edges,
        evidence_queries=queries if needs_evidence else [],
        missing_tools=sorted({node.tool_id for node in nodes if node.tool_id not in tools}),
        reasoning=[
            "LLM 只增强意图/查询，节点图由 HEVI 编译器生成",
            "视频素材通过 EvidenceRef 绑定 source hash 与时间窗口",
            "渲染节点只输出本地文件，交付由 HEVI artifact/quality gate 复核",
        ],
        warnings=warnings,
    )
    errors = validate_video_agent_plan(plan, available_tools=tools)
    plan.warnings.extend(errors)
    if plan.missing_tools:
        plan.feasibility = "Infeasible"
    elif intent.missing_inputs:
        plan.feasibility = "NeedsInput"
    elif errors:
        plan.feasibility = "Infeasible"
    else:
        plan.feasibility = "Feasible"
    return plan


def reflect_video_agent_plan(
    plan: VideoAgentPlan,
    *,
    available_tools: set[str] | None = None,
) -> dict[str, Any]:
    """VideoAgent 两阶段自检的 HEVI 版本。"""

    errors = validate_video_agent_plan(plan, available_tools=available_tools)
    redundant: list[str] = []
    seen_capabilities: set[str] = set()
    for node in plan.nodes:
        if node.capability in seen_capabilities and node.capability in {"video_compose", "video_evidence_search"}:
            redundant.append(f"重复能力节点: {node.capability}")
        seen_capabilities.add(node.capability)
    # timeline.create + timeline.export are two deliberate stages of one
    # compose capability; a repeated capability is advisory, not a failed plan.
    findings = errors
    return {
        "passed": not findings,
        "findings": findings,
        "warnings": redundant,
        "missing_tools": sorted(
            {node.tool_id for node in plan.nodes if available_tools is not None and node.tool_id not in available_tools}
        ),
        "coverage": {
            "intent_count": len(plan.intent.intents),
            "query_count": len(plan.evidence_queries),
            "node_count": len(plan.nodes),
            "edge_count": len(plan.edges),
        },
    }


_DEFAULT_TOOLS = {
    "watch.video",
    "video.evidence.index",
    "video.evidence.search",
    "video.script.from_transcript",
    "nle.edit_plan",
    "timeline.create",
    "timeline.export",
    "video.qa",
    "video.summary",
}


__all__ = [
    "VideoIntentCaller",
    "build_video_agent_plan",
    "infer_video_intent",
    "rank_evidence_candidates",
    "reflect_video_agent_plan",
]
