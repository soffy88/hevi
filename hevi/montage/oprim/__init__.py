"""montage oprim:无状态原子，不得引用 oskill/omodul。

OpenMontage 核心原语：Pipeline/Tool/Cost/Reference/Playbook 处理。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.montage.oprim.video_agent import (
    EvidenceQuery,
    EvidenceRef,
    PlanEdge,
    PlanNode,
    PlanPort,
    VideoAgentPlan,
    VideoIntent,
    build_storyboard_queries,
    compute_video_plan_fingerprint,
    validate_video_agent_plan,
)
from hevi.montage.schemas import (
    Artifact,
    ArtifactType,
    CheckpointState,
    CostBudget,
    CostLineItem,
    CostPhase,
    PipelineManifest,
    PlaybookSchema,
    StageDef,
    ToolContract,
    ToolEnvelope,
    VideoAnalysisBrief,
    make_default_checkpoint,
    make_default_cost_budget,
    make_default_pipeline_manifest,
    make_default_tool_contract,
)

# ─── Pipeline Manifest Loading ─────────────────────


def load_pipeline_manifest(path: str | Path) -> PipelineManifest:
    """加载 pipeline manifest (YAML/JSON)。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Pipeline manifest not found: {path}")

    if path.suffix in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    elif path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported manifest format: {path.suffix}")

    if not isinstance(data, dict):
        raise ValueError("pipeline manifest must be an object")
    # OpenMontage manifests use a slightly broader vocabulary than HEVI's
    # public enum and allow stage skills to be implicit.  Normalize that
    # syntax once at the boundary instead of weakening the runtime schema.
    category_aliases = {
        "custom": "test",
        "documentary": "footage_based",
        "footage": "footage_based",
        "generated_video": "generated",
        "talking_head": "footage_based",
    }
    category = str(data.get("category") or "generated")
    data["category"] = category_aliases.get(category, category)
    stages = data.get("stages") or []
    if isinstance(stages, list):
        data["stages"] = [
            {
                **stage,
                "skill": stage.get("skill") or f"pipelines/{data.get('name', 'pipeline')}/{stage.get('name', 'stage')}",
            }
            for stage in stages
            if isinstance(stage, dict)
        ]

    return PipelineManifest(**data)


def validate_pipeline_manifest(manifest: PipelineManifest) -> list[str]:
    """验证 pipeline manifest 完整性。"""
    errors: list[str] = []

    if not manifest.name:
        errors.append("pipeline name is required")

    if not manifest.stages:
        errors.append("at least one stage is required")

    for i, stage in enumerate(manifest.stages):
        if not stage.name:
            errors.append(f"stage {i}: name is required")
        if not stage.skill:
            errors.append(f"stage {i} ({stage.name}): skill is required")

    return errors


# ─── Tool Registry ─────────────────────────────────


def register_tool(contract: ToolContract, registry: dict[str, ToolContract]) -> None:
    """注册工具到注册表。"""
    registry[contract.name] = contract


def discover_tools(tools_dir: str | Path) -> dict[str, ToolContract]:
    """从目录发现工具契约 (JSON schema)。"""
    registry: dict[str, ToolContract] = {}
    path = Path(tools_dir)

    for json_file in path.rglob("*.schema.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            contract = ToolContract(**data)
            registry[contract.name] = contract
        except Exception:
            continue

    return registry


def build_tool_envelope(registry: dict[str, ToolContract]) -> ToolEnvelope:
    """构建能力信封：capability -> [tools], provider -> [tools]。"""
    capabilities: dict[str, list[str]] = {}
    providers: dict[str, list[str]] = {}

    for tool_name, contract in registry.items():
        cap = contract.capability.value
        if cap not in capabilities:
            capabilities[cap] = []
        capabilities[cap].append(tool_name)

        if contract.provider:
            prov = contract.provider
            if prov not in providers:
                providers[prov] = []
            providers[prov].append(tool_name)

    return ToolEnvelope(
        capabilities=capabilities,
        providers=providers,
        total_tools=len(registry),
    )


def provider_menu(envelope: ToolEnvelope) -> dict[str, list[str]]:
    """生成 provider menu：capability -> [providers]。"""
    return envelope.providers


def support_envelope(envelope: ToolEnvelope) -> dict[str, Any]:
    """生成 support envelope：完整能力概览。"""
    return {
        "capabilities": envelope.capabilities,
        "providers": envelope.providers,
        "total_tools": envelope.total_tools,
    }


# ─── Cost Tracking ──────────────────────────────────


def estimate_cost(
    budget: CostBudget,
    tool_name: str,
    provider: str,
    capability: str,
    estimated_units: float,
    cost_per_unit_usd: float,
) -> CostBudget:
    """估算成本并添加到预算。"""
    line = CostLineItem(
        tool_name=tool_name,
        provider=provider,
        capability=capability,
        estimated_units=estimated_units,
        cost_per_unit_usd=cost_per_unit_usd,
        estimated_cost_usd=estimated_units * cost_per_unit_usd,
        phase=CostPhase.ESTIMATE,
    )
    budget.line_items.append(line)
    budget.reserved_usd += line.estimated_cost_usd
    return budget


def reserve_cost(budget: CostBudget, tool_name: str, actual_units: float) -> CostBudget:
    """预留成本：estimate -> reserve。"""
    for line in budget.line_items:
        if line.tool_name == tool_name and line.phase == CostPhase.ESTIMATE:
            line.phase = CostPhase.RESERVE
            line.actual_units = actual_units
            line.actual_cost_usd = actual_units * line.cost_per_unit_usd
            budget.reserved_usd -= line.estimated_cost_usd
            budget.spent_usd += line.actual_cost_usd
            break
    return budget


def reconcile_cost(budget: CostBudget, tool_name: str, actual_cost_usd: float) -> CostBudget:
    """结算成本：reserve -> reconcile。"""
    for line in budget.line_items:
        if line.tool_name == tool_name and line.phase == CostPhase.RESERVE:
            line.phase = CostPhase.RECONCILE
            reserved_cost = line.actual_cost_usd
            line.actual_cost_usd = actual_cost_usd
            budget.spent_usd = budget.spent_usd - (reserved_cost - actual_cost_usd)
            break
    return budget


# ─── Reference Video Analysis ──────────────────────


def analyze_reference_video(
    video_path: str | Path,
    analysis_tools: list[str] | None = None,
) -> VideoAnalysisBrief:
    """分析本地参考视频；缺少本地输入时返回未执行状态。

    This primitive deliberately does not invent a transcript or scene
    description.  Local media gets real ffprobe/frame/sidecar-subtitle data;
    URL acquisition and neural transcription belong to the service boundary.
    """
    del analysis_tools
    source = Path(video_path)
    if not source.is_file():
        return VideoAnalysisBrief(source_url=str(video_path), content="分析待完成")
    transcript = extract_transcript(source)
    scenes = detect_scenes(source)
    duration = 0.0
    try:
        from hevi.production.delivery_gate import probe_video

        duration = probe_video(source).duration_s
    except Exception:
        pass
    sentence_count = len([line for line in transcript.splitlines() if line.strip()])
    pacing = f"{sentence_count} 个字幕段 / {len(scenes)} 个场景候选"
    return VideoAnalysisBrief(
        source_url=str(source),
        content=transcript[:1000] or "未检测到本地字幕；仅完成媒体结构分析",
        pacing=pacing,
        structure="; ".join(
            f"scene-{index + 1} {item['start_s']:.2f}-{item['end_s']:.2f}s"
            for index, item in enumerate(scenes[:12])
        )
        or "未检测到场景边界",
        style="frame-sample-based" if scenes else "未执行视觉样本分析",
        what_makes_it_work=[
            "字幕存在，可进入节奏/脚本分析" if transcript else "没有本地字幕，需注入 ASR 才能做文本分析",
            f"识别到 {len(scenes)} 个场景候选" if scenes else "没有可用的场景候选",
        ],
        duration_s=duration,
        scene_count=len(scenes),
    )


def extract_transcript(video_path: str | Path) -> str:
    """读取本地同名 SRT/VTT/ASS 字幕，不在 oprim 内启动 ASR。"""
    source = Path(video_path)
    if not source.is_file():
        return ""
    from hevi.ingest.video_transcript import parse_subtitle

    candidates = [
        source.with_suffix(".srt"),
        source.with_suffix(".vtt"),
        source.with_suffix(".ass"),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            if candidate.suffix.lower() == ".ass":
                lines = [
                    line.split(",", 9)[-1].replace("\\N", " ").strip()
                    for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines()
                    if line.startswith("Dialogue:") and "," in line
                ]
                if lines:
                    return "\n".join(lines)
            else:
                parsed = parse_subtitle(candidate.read_text(encoding="utf-8", errors="replace"))
                if parsed:
                    return "\n".join(item.text for item in parsed)
        except OSError:
            continue
    return ""


def detect_scenes(video_path: str | Path) -> list[dict[str, Any]]:
    """Use HEVI's local frame detector and return timestamp-only scene rows."""
    source = Path(video_path)
    if not source.is_file():
        return []
    import tempfile

    from hevi.ingest.video_frames import extract_watch_frames

    try:
        with tempfile.TemporaryDirectory(prefix="hevi-montage-scenes-") as work:
            frames = extract_watch_frames(source, Path(work), detail="balanced", budget=32)
    except Exception:
        return []
    if not frames:
        return []
    try:
        from hevi.production.delivery_gate import probe_video

        duration = probe_video(source).duration_s
    except Exception:
        duration = frames[-1].timestamp_s
    rows: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        end = frames[index + 1].timestamp_s if index + 1 < len(frames) else duration
        rows.append(
            {
                "scene_index": index,
                "start_s": round(frame.timestamp_s, 3),
                "end_s": round(max(end, frame.timestamp_s), 3),
            }
        )
    return rows


def sample_frames(video_path: str | Path, count: int = 9) -> list[str]:
    """Persist a bounded set of local reference frames for human/agent review."""
    source = Path(video_path)
    if not source.is_file():
        return []
    from hevi.ingest.video_frames import extract_watch_frames

    out_dir = Path("output/montage/reference") / source.stem
    try:
        frames = extract_watch_frames(source, out_dir, detail="balanced", budget=max(1, min(count, 64)))
    except Exception:
        return []
    return [str(frame.path) for frame in frames]


# ─── Playbook ───────────────────────────────────────


def load_playbook(path: str | Path) -> PlaybookSchema:
    """加载风格手册。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Playbook not found: {path}")

    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PlaybookSchema(**data)


def apply_playbook_to_compose(
    playbook: PlaybookSchema,
    edit_decisions: dict[str, Any],
) -> dict[str, Any]:
    """将 playbook 设计 token 应用到 compose 决策。"""
    # 实际实现：将 color_rules/typography/motion 注入到 compose 工具
    return {
        **edit_decisions,
        "playbook": {
            "color_rules": playbook.color_rules,
            "typography": playbook.typography,
            "motion": playbook.motion,
            "audio": playbook.audio,
        },
    }


# ─── Checkpoint ─────────────────────────────────────


def write_checkpoint(
    path: str | Path,
    checkpoint: CheckpointState,
) -> None:
    """写入检查点。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(checkpoint.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")


def read_checkpoint(path: str | Path) -> CheckpointState:
    """读取检查点。"""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return CheckpointState(**data)


def update_checkpoint_approval(
    checkpoint: CheckpointState,
    approval: str,
    notes: str = "",
) -> CheckpointState:
    """更新检查点审批状态。"""
    checkpoint.human_approval = approval
    checkpoint.review_notes = notes
    checkpoint.updated_at = datetime.utcnow()
    return checkpoint


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
    "load_pipeline_manifest",
    "validate_pipeline_manifest",
    "register_tool",
    "discover_tools",
    "build_tool_envelope",
    "provider_menu",
    "support_envelope",
    "estimate_cost",
    "reserve_cost",
    "reconcile_cost",
    "analyze_reference_video",
    "extract_transcript",
    "detect_scenes",
    "sample_frames",
    "load_playbook",
    "apply_playbook_to_compose",
    "write_checkpoint",
    "read_checkpoint",
    "update_checkpoint_approval",
]
