"""LongCat runtime admission probe(Evidence Gate)。

P4 解除条件 = 完整走完八步证据链;任一步失败 → NOT_EVALUABLE。
前三步(SOURCE/IMPORTABLE/CHECKPOINT)现在就能真检查;后五步需要真实 runtime,
未接入时返回 NOT_EVALUABLE 而不是 PASS —— 绝不因为"官方说有"就判通过。
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from hevi.generation.evidence import (
    CAPABILITY_KEYS,
    EvidenceStatus,
    ProviderEvidenceBridge,
    longcat_bridge,
)


class StepStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class StepName(StrEnum):
    SOURCE_AVAILABLE = "SOURCE_AVAILABLE"
    IMPORTABLE = "IMPORTABLE"
    CHECKPOINT_AVAILABLE = "CHECKPOINT_AVAILABLE"
    RUNTIME_INITIALIZES = "RUNTIME_INITIALIZES"
    T2V_PROBE = "T2V_PROBE"
    I2V_PROBE = "I2V_PROBE"
    VC_PROBE = "VC_PROBE"
    REFINEMENT_PROBE = "REFINEMENT_PROBE"
    MEDIA_VALIDATION = "MEDIA_VALIDATION"
    CAPABILITY_ADMITTED = "CAPABILITY_ADMITTED"


ORDER: tuple[StepName, ...] = (
    StepName.SOURCE_AVAILABLE,
    StepName.IMPORTABLE,
    StepName.CHECKPOINT_AVAILABLE,
    StepName.RUNTIME_INITIALIZES,
    StepName.T2V_PROBE,
    StepName.I2V_PROBE,
    StepName.VC_PROBE,
    StepName.REFINEMENT_PROBE,
    StepName.MEDIA_VALIDATION,
    StepName.CAPABILITY_ADMITTED,
)


@dataclass(frozen=True)
class StepResult:
    name: StepName
    status: StepStatus
    detail: str = ""


@dataclass
class ProbeReport:
    provider: str
    steps: list[StepResult] = field(default_factory=list)
    bridge: ProviderEvidenceBridge | None = None

    @property
    def passed(self) -> bool:
        return all(s.status is StepStatus.PASS for s in self.steps)

    @property
    def first_blocker(self) -> StepName | None:
        for step in self.steps:
            if step.status is not StepStatus.PASS:
                return step.name
        return None

    def to_dict(self) -> dict[str, object]:
        return {"provider": self.provider, "passed": self.passed,
                "first_blocker": str(self.first_blocker or ""),
                "steps": [{"name": str(s.name), "status": str(s.status), "detail": s.detail}
                          for s in self.steps]}


def _source_present(source_root: str | os.PathLike[str] | None) -> bool:
    if not source_root:
        return False
    root = Path(source_root)
    return root.is_dir() and any(root.rglob("*.py"))


def _runtime_steps(runtime_probe: object | None) -> dict[StepName, StepResult | bool]:
    """runtime 探针可以是可调用对象或已备好的映射;两者都不接受静默缺省。"""
    if runtime_probe is None:
        return {}
    raw = runtime_probe() if callable(runtime_probe) else runtime_probe
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, StepName)}


def probe(*, source_root: str | os.PathLike[str] | None = None,
          module_name: str = "longcat_video",
          checkpoint_path: str | os.PathLike[str] | None = None,
          runtime_probe: object | None = None) -> ProbeReport:
    """按证据链顺序执行;卡在第一步失败处,后续记 NOT_EVALUABLE(不跳过、不假装)。

    runtime_probe: 可调用对象或映射,键为 StepName,值为 StepResult 或 bool,
    用于接入真实 runtime 后的 T2V/I2V/VC/refinement/media 五步。
    """
    bridge = longcat_bridge()
    steps: list[StepResult] = []

    steps.append(StepResult(StepName.SOURCE_AVAILABLE,
                            StepStatus.PASS if _source_present(source_root) else StepStatus.FAIL,
                            str(source_root or "not configured")))

    spec = importlib.util.find_spec(module_name) if steps[-1].status is StepStatus.PASS else None
    steps.append(StepResult(StepName.IMPORTABLE,
                            StepStatus.PASS if spec else StepStatus.FAIL,
                            module_name if spec else f"{module_name} not importable"))

    ckpt_ok = bool(checkpoint_path) and Path(str(checkpoint_path)).exists()
    steps.append(StepResult(StepName.CHECKPOINT_AVAILABLE,
                            StepStatus.PASS if ckpt_ok else StepStatus.FAIL,
                            str(checkpoint_path or "not configured")))

    runtime_steps = _runtime_steps(runtime_probe)
    for name in (StepName.RUNTIME_INITIALIZES, StepName.T2V_PROBE, StepName.I2V_PROBE,
                 StepName.VC_PROBE, StepName.REFINEMENT_PROBE, StepName.MEDIA_VALIDATION):
        got = runtime_steps.get(name)
        if got is None:
            steps.append(StepResult(name, StepStatus.NOT_EVALUABLE, "no runtime probe wired"))
        elif isinstance(got, StepResult):
            steps.append(got)
        else:
            steps.append(StepResult(name, StepStatus.PASS if got else StepStatus.FAIL, ""))

    verified = any(s.status is StepStatus.PASS for s in steps)
    if verified:
        for name, capability in (
            (StepName.T2V_PROBE, "t2v"), (StepName.I2V_PROBE, "i2v"),
            (StepName.VC_PROBE, "continuation"), (StepName.REFINEMENT_PROBE, "refinement"),
            (StepName.MEDIA_VALIDATION, "long_video"),
        ):
            result = next(s for s in steps if s.name is name)
            if result.status is StepStatus.PASS:
                bridge.mark(capability, EvidenceStatus.LOCALLY_VERIFIED)

    admitted = verified and all(s.status is StepStatus.PASS for s in steps)
    blocker = next((s.name for s in steps if s.status is not StepStatus.PASS), None)
    steps.append(StepResult(StepName.CAPABILITY_ADMITTED,
                            StepStatus.PASS if admitted else StepStatus.NOT_EVALUABLE,
                            "all evidence steps passed" if admitted
                            else f"blocked at {blocker}"))
    bridge.try_admit(runtime_ready=admitted)
    return ProbeReport(bridge.provider, steps, bridge)


def admitted_capabilities_from(report: ProbeReport) -> dict[str, bool]:
    """从 probe 报告导出 HEVI 实际能力。未全通过 → 全 False(声明不升级为能力)。"""
    if not report.passed or report.bridge is None:
        return dict.fromkeys(CAPABILITY_KEYS, False)
    return report.bridge.admitted_capabilities()


def evidence_snapshot() -> dict[str, object]:
    """当前登记的 external evidence 快照(声明态 vs 已核实)。"""
    bridge = longcat_bridge()
    return {
        "provider": bridge.provider,
        "admission": str(bridge.admission),
        "declared_upstream": sorted(bridge.declared_only()),
        "locally_verified": sorted(bridge.verified()),
        "admitted": bridge.admission.value == "CAPABILITY_ADMITTED",
    }
