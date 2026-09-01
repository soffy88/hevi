"""VideoAgent 原语与类型合同。

这些类型把 VideoAgent 的 agent graph 从“LLM 输出的 JSON”变成 HEVI 可以
校验、版本化和恢复的生产计划。模块不做文件/数据库 IO，也不选择 provider。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanPort(BaseModel):
    """节点的有类型输入/输出端口。"""

    name: str
    type: str = "json"
    description: str = ""
    required: bool = True


class PlanNode(BaseModel):
    """可执行计划节点；tool_id 必须来自 HEVI 工具注册表。"""

    model_config = ConfigDict(extra="allow")

    node_id: str
    capability: str
    tool_id: str
    inputs: list[PlanPort] = Field(default_factory=list)
    outputs: list[PlanPort] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    requirements: dict[str, Any] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)


class PlanEdge(BaseModel):
    """节点端口之间的数据连接。"""

    source_node: str
    source_port: str
    target_node: str
    target_port: str
    transform: str = "identity"


class EvidenceQuery(BaseModel):
    """Storyboard/用户意图生成的一个视觉证据查询。"""

    query_id: str
    text: str
    scene_id: str = ""
    start_s: float | None = Field(default=None, ge=0.0)
    end_s: float | None = Field(default=None, ge=0.0)
    target_duration_s: float | None = Field(default=None, gt=0.0)
    modalities: list[str] = Field(default_factory=lambda: ["visual", "transcript"])
    top_k: int = Field(default=5, ge=1, le=100)


class EvidenceRef(BaseModel):
    """可追溯的本地视频片段证据。"""

    evidence_id: str
    source_path: str
    source_sha256: str
    segment_id: str
    start_s: float = Field(ge=0.0)
    end_s: float = Field(gt=0.0)
    transcript: str = ""
    caption: str = ""
    keyframe_paths: list[str] = Field(default_factory=list)
    score: float = 0.0
    provenance: dict[str, Any] = Field(default_factory=dict)
    license: str = "unknown"
    embedding: list[float] = Field(default_factory=list, exclude=True)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


class VideoIntent(BaseModel):
    """规范化后的用户意图，不含 provider 细节。"""

    requirement: str
    intents: list[str] = Field(default_factory=list)
    output_type: Literal["video", "answer", "summary"] = "video"
    explicit_requirements: list[str] = Field(default_factory=list)
    implicit_requirements: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)


class VideoAgentPlan(BaseModel):
    """HEVI 版 VideoAgent 计划。

    feasibility 使用三态：Feasible、NeedsInput、Infeasible。NeedsInput
    是可恢复的业务状态，不等价于失败。
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    plan_id: str
    revision: int = 1
    intent: VideoIntent
    nodes: list[PlanNode] = Field(default_factory=list)
    edges: list[PlanEdge] = Field(default_factory=list)
    evidence_queries: list[EvidenceQuery] = Field(default_factory=list)
    feasibility: Literal["Feasible", "NeedsInput", "Infeasible"] = "NeedsInput"
    missing_tools: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_video_agent_plan(
    plan: VideoAgentPlan,
    *,
    available_tools: set[str] | None = None,
) -> list[str]:
    """校验节点、端口、依赖和环；返回可展示的错误列表。"""

    errors: list[str] = []
    node_map: dict[str, PlanNode] = {}
    for node in plan.nodes:
        if node.node_id in node_map:
            errors.append(f"duplicate node id: {node.node_id}")
        node_map[node.node_id] = node
        if available_tools is not None and node.tool_id not in available_tools:
            errors.append(f"tool unavailable: {node.tool_id}")

    errors.extend(
        f"{node.node_id} depends on unknown node: {dependency}"
        for node in plan.nodes
        for dependency in node.depends_on
        if dependency not in node_map
    )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            errors.append(f"plan contains dependency cycle at: {node_id}")
            return
        if node_id in visited or node_id not in node_map:
            return
        visiting.add(node_id)
        for dependency in node_map[node_id].depends_on:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node in plan.nodes:
        visit(node.node_id)

    ports: dict[str, dict[str, dict[str, PlanPort]]] = {}
    for node in plan.nodes:
        ports[node.node_id] = {
            "inputs": {port.name: port for port in node.inputs},
            "outputs": {port.name: port for port in node.outputs},
        }
        if len(ports[node.node_id]["inputs"]) != len(node.inputs):
            errors.append(f"duplicate input port on node: {node.node_id}")
        if len(ports[node.node_id]["outputs"]) != len(node.outputs):
            errors.append(f"duplicate output port on node: {node.node_id}")

    seen_edges: set[tuple[str, str, str, str]] = set()
    incoming: dict[tuple[str, str], int] = defaultdict(int)
    for edge in plan.edges:
        edge_key = (edge.source_node, edge.source_port, edge.target_node, edge.target_port)
        if edge_key in seen_edges:
            errors.append(f"duplicate edge: {'/'.join(edge_key)}")
        seen_edges.add(edge_key)
        source = ports.get(edge.source_node)
        target = ports.get(edge.target_node)
        if source is None or target is None:
            errors.append(f"edge references unknown node: {edge.source_node}->{edge.target_node}")
            continue
        source_port = source["outputs"].get(edge.source_port)
        target_port = target["inputs"].get(edge.target_port)
        if source_port is None:
            errors.append(f"unknown output port: {edge.source_node}.{edge.source_port}")
            continue
        if target_port is None:
            errors.append(f"unknown input port: {edge.target_node}.{edge.target_port}")
            continue
        if not _types_compatible(source_port.type, target_port.type):
            errors.append(
                f"incompatible ports: {edge.source_node}.{edge.source_port} ({source_port.type}) "
                f"-> {edge.target_node}.{edge.target_port} ({target_port.type})"
            )
        incoming[(edge.target_node, edge.target_port)] += 1

    for node in plan.nodes:
        for port in node.inputs:
            if port.required and incoming[(node.node_id, port.name)] == 0:
                if port.name in node.requirements:
                    continue
                if port.name not in {
                    "source",
                    "source_path",
                    "requirement",
                    "output_path",
                    "script_lines",
                    "index_path",
                }:
                    errors.append(f"required input is unconnected: {node.node_id}.{port.name}")

    return sorted(set(errors))


def _types_compatible(source: str, target: str) -> bool:
    if source == target or source == "any" or target == "any":
        return True
    if source == "path" and target in {"file_path", "str"}:
        return True
    return source == "file_path" and target in {"path", "str"}


def compute_video_plan_fingerprint(plan: VideoAgentPlan) -> str:
    """为同一意图/图形生成稳定指纹；不包含用户 PII。"""

    payload = plan.model_dump(mode="json", exclude={"plan_id", "revision"})
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]


def build_storyboard_queries(
    scenes: list[dict[str, Any]] | list[str],
    *,
    default_duration_s: float | None = None,
) -> list[EvidenceQuery]:
    """把脚本/分镜转换为细粒度视觉查询，不执行检索。"""

    queries: list[EvidenceQuery] = []
    for index, raw in enumerate(scenes):
        if isinstance(raw, str):
            text = raw.strip()
            scene_id = f"scene-{index + 1}"
            start_s = end_s = None
            duration = default_duration_s
            modalities = ["visual", "transcript"]
        elif isinstance(raw, dict):
            text = str(
                raw.get("visual_query")
                or raw.get("description")
                or raw.get("narration")
                or raw.get("text")
                or ""
            ).strip()
            scene_id = str(raw.get("scene_id") or raw.get("id") or f"scene-{index + 1}")
            start_s = _optional_float(raw.get("start_s"))
            end_s = _optional_float(raw.get("end_s"))
            duration = _optional_float(raw.get("target_duration_s") or raw.get("duration_s"))
            modalities = [str(item) for item in raw.get("modalities", ["visual", "transcript"])]
        else:
            continue
        if not text:
            continue
        queries.append(
            EvidenceQuery(
                query_id=f"query-{index + 1}",
                scene_id=scene_id,
                text=text,
                start_s=start_s,
                end_s=end_s,
                target_duration_s=duration,
                modalities=modalities,
            )
        )
    return queries


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "EvidenceQuery",
    "EvidenceRef",
    "PlanEdge",
    "PlanNode",
    "PlanPort",
    "VideoAgentPlan",
    "VideoIntent",
    "build_storyboard_queries",
    "compute_video_plan_fingerprint",
    "validate_video_agent_plan",
]
