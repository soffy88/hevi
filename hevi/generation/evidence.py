"""Provider Evidence Bridge —— 上游声明的能力事实 ≠ HEVI 拥有的能力。

P4 收口原则(修正自初版审计):
    P4 不阻塞 canonical generation contract;
    P4 阻塞的是 **runtime admission**。

本模块只做两件事:
1. 把上游官方能力登记为 **external evidence**(带出处、带核实状态);
2. 在证据链走完之前 **拒绝把能力写进 HEVI registry**。

知道 ≠ 拥有。declared_upstream 的能力永远不会自动变成 supports(...)==True。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from hevi.generation.errors import CapabilityUnsupported

CAPABILITY_KEYS = (
    "t2v", "i2v", "continuation", "long_video", "refinement",
    "temporal_refinement", "spatial_refinement", "audio_conditioning",
    "interactive_generation",
)


class EvidenceStatus(StrEnum):
    DECLARED_UPSTREAM = "DECLARED_UPSTREAM"  # 上游官方声称,本地未核实
    LOCALLY_VERIFIED = "LOCALLY_VERIFIED"    # 本地 probe 通过
    REFUTED = "REFUTED"                      # 本地 probe 失败


class AdmissionState(StrEnum):
    NOT_EVALUABLE = "NOT_EVALUABLE"
    PROVIDER_NOT_INSTALLED = "PROVIDER_NOT_INSTALLED"
    CAPABILITY_ADMITTED = "CAPABILITY_ADMITTED"


@dataclass(frozen=True)
class ExternalEvidence:
    """一条上游能力事实。source 必填:无出处的"事实"不予登记。"""
    capability: str
    claim: str
    source: str
    status: EvidenceStatus = EvidenceStatus.DECLARED_UPSTREAM

    def validate(self) -> None:
        if self.capability not in CAPABILITY_KEYS:
            raise ValueError(f"unknown capability key: {self.capability}")
        if not self.source:
            raise ValueError("external evidence requires a source")


@dataclass
class ProviderEvidenceBridge:
    """证据登记 + 准入闸。能力准入要求每条 evidence 都是 LOCALLY_VERIFIED。"""
    provider: str
    evidence: list[ExternalEvidence] = field(default_factory=list)
    admission: AdmissionState = AdmissionState.NOT_EVALUABLE
    admission_notes: list[str] = field(default_factory=list)

    def declare(self, item: ExternalEvidence) -> ExternalEvidence:
        item.validate()
        self.evidence = [e for e in self.evidence if e.capability != item.capability]
        self.evidence.append(item)
        return item

    def mark(self, capability: str, status: EvidenceStatus) -> ExternalEvidence:
        for item in self.evidence:
            if item.capability == capability:
                object.__setattr__(item, "status", status)
                return item
        raise CapabilityUnsupported(f"no evidence registered for {capability}")

    def declared_only(self) -> tuple[str, ...]:
        return tuple(e.capability for e in self.evidence
                     if e.status is EvidenceStatus.DECLARED_UPSTREAM)

    def verified(self) -> tuple[str, ...]:
        return tuple(e.capability for e in self.evidence
                     if e.status is EvidenceStatus.LOCALLY_VERIFIED)

    def try_admit(self, *, runtime_ready: bool) -> AdmissionState:
        """准入以**已核实**的 capability 为准,而不是要求所有声明都被核实。

        未被 probe 覆盖的上游声明(temporal/spatial refinement 等)保持 declared 态,
        不准入 —— 门因此可以在只覆盖部分能力时通过,前提是至少有一项被实证。
        runtime 未就绪则一律不准入。
        """
        if not runtime_ready:
            self.admission = AdmissionState.PROVIDER_NOT_INSTALLED
            self.admission_notes.append("runtime not initialized; no capability admitted")
            return self.admission
        if not self.verified():
            self.admission = AdmissionState.NOT_EVALUABLE
            self.admission_notes.append("no locally verified capability")
            return self.admission
        self.admission = AdmissionState.CAPABILITY_ADMITTED
        self.admission_notes.append(
            f"admitted {sorted(self.verified())}; still declared-only {sorted(self.declared_only())}")
        return self.admission

    def admitted_capabilities(self) -> dict[str, bool]:
        """HEVI 实际能力。默认全 False —— 声明不自动升级。"""
        if self.admission is not AdmissionState.CAPABILITY_ADMITTED:
            return dict.fromkeys(CAPABILITY_KEYS, False)
        return {key: key in self.verified() for key in CAPABILITY_KEYS}


# ── LongCat-Video:上游官方能力(声明态,非 HEVI 能力)──

LONGCAT_UPSTREAM_SOURCE = "https://github.com/meituan-longcat/LongCat-Video"

LONGCAT_VIDEO_UPSTREAM_EVIDENCE: tuple[ExternalEvidence, ...] = (
    ExternalEvidence("t2v", "generate_t2v entrypoint", LONGCAT_UPSTREAM_SOURCE),
    ExternalEvidence("i2v", "generate_i2v entrypoint", LONGCAT_UPSTREAM_SOURCE),
    ExternalEvidence("continuation", "generate_vc entrypoint with conditioning frames",
                     LONGCAT_UPSTREAM_SOURCE),
    ExternalEvidence("refinement", "generate_refine stage of the inference path",
                     LONGCAT_UPSTREAM_SOURCE),
    ExternalEvidence("long_video", "run_demo_long_video continuation loop",
                     LONGCAT_UPSTREAM_SOURCE),
    ExternalEvidence("temporal_refinement", "KV cache reuse during continuation",
                     LONGCAT_UPSTREAM_SOURCE),
    ExternalEvidence("spatial_refinement", "refinement LoRA + BSA, coarse-to-fine 480p->720p",
                     LONGCAT_UPSTREAM_SOURCE),
    ExternalEvidence("interactive_generation", "unified 13.6B T2V/I2V/VC stack",
                     LONGCAT_UPSTREAM_SOURCE),
)
# 官方未声称 audio conditioning;显式登记为"上游无此能力声明",避免下游误期待。
LONGCAT_NO_AUDIO_CLAIM = ExternalEvidence(
    "audio_conditioning", "no upstream claim; audio path belongs to a separate Avatar stack",
    LONGCAT_UPSTREAM_SOURCE)


def longcat_bridge() -> ProviderEvidenceBridge:
    """每次返回**全新** evidence 实例。

    刻意不复用模块级常量:ExternalEvidence 是可变(frozen 只挡属性赋值,拦不住
    object.__setattr__),共享实例会让一次 probe 的 LOCALLY_VERIFIED 泄漏到后续
    所有 bridge —— 那等于"跑过一次就永远认为已核实"。宁可每次重建。
    """
    bridge = ProviderEvidenceBridge("longcat-video")
    for item in LONGCAT_VIDEO_UPSTREAM_EVIDENCE:
        bridge.declare(ExternalEvidence(item.capability, item.claim, item.source, item.status))
    return bridge