"""montage oprim:无状态原子，不得引用 oskill/omodul。

OpenMontage 核心原语：Pipeline/Tool/Cost/Reference/Playbook 处理。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

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
            line.actual_cost_usd = actual_cost_usd
            budget.spent_usd = budget.spent_usd - (line.actual_cost_usd - actual_cost_usd)
            line.actual_cost_usd = actual_cost_usd
            break
    return budget


# ─── Reference Video Analysis ──────────────────────


def analyze_reference_video(
    video_path: str | Path,
    analysis_tools: list[str] | None = None,
) -> VideoAnalysisBrief:
    """参考视频分析 (占位：实际调用 video_analyzer 工具)。"""
    # 实际实现由 oskill.reference 分析工具完成
    # 这里返回结构化占位
    return VideoAnalysisBrief(
        source_url=str(video_path),
        content="分析待完成",
        pacing="中等",
        structure="标准三幕",
        style="待识别",
        what_makes_it_work=["待提取"],
        duration_s=0.0,
    )


def extract_transcript(video_path: str | Path) -> str:
    """提取视频字幕/转录 (占位)。"""
    return ""


def detect_scenes(video_path: str | Path) -> list[dict[str, Any]]:
    """场景检测 (占位)。"""
    return []


def sample_frames(video_path: str | Path, count: int = 9) -> list[str]:
    """抽帧 (占位)。"""
    return []


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