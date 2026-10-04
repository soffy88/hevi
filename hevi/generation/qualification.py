"""P5-A 统一准入机制 —— 对**任何**外部视频 runtime 通用,LongCat 只是第一个 consumer。

链条:ENV → HEALTH → CAPABILITY → T2V → I2V → VC → REFINEMENT → MEDIA → ADMITTED

纪律(承自 P4):
- 环境不满足 → ENV_BLOCKED,不去启动;
- runtime 不可达 → UNREACHABLE;
- 没有实测证据的能力一律 False;
- 换 checkpoint / 换版本 → 证据不继承(re-verify)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from hevi.generation.evidence import (
    CAPABILITY_KEYS,
    AdmissionState,
    EvidenceStatus,
    ExternalEvidence,
    ProviderEvidenceBridge,
)
from hevi.generation.external_runtime import (
    OUTPUT_PROFILES,
    HealthState,
    RuntimeSample,
    VideoRuntimeSurface,
    check_environment,
)

GENERATION_PROBES: tuple[str, ...] = ("t2v", "i2v", "continuation", "refinement")


class Phase(StrEnum):
    ENVIRONMENT = "ENVIRONMENT"
    HEALTH = "HEALTH"
    CAPABILITY = "CAPABILITY"
    T2V_PROBE = "T2V_PROBE"
    I2V_PROBE = "I2V_PROBE"
    VC_PROBE = "VC_PROBE"
    REFINEMENT_PROBE = "REFINEMENT_PROBE"
    MEDIA_VALIDATION = "MEDIA_VALIDATION"
    ADMITTED = "ADMITTED"


class PhaseStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_EVALUABLE = "NOT_EVALUABLE"


@dataclass(frozen=True)
class PhaseResult:
    phase: Phase
    status: PhaseStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is PhaseStatus.PASS


@dataclass
class QualificationReport:
    provider: str
    runtime_fingerprint: str
    phases: list[PhaseResult] = field(default_factory=list)
    admitted_generation: dict[str, bool] = field(default_factory=dict)
    admitted_profiles: dict[str, bool] = field(default_factory=dict)
    admission: AdmissionState = AdmissionState.NOT_EVALUABLE
    evidence: list[ExternalEvidence] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(p.ok for p in self.phases)

    @property
    def first_blocker(self) -> Phase | None:
        for phase in self.phases:
            if not phase.ok:
                return phase.phase
        return None

    def to_dict(self) -> dict[str, object]:
        return {"provider": self.provider, "runtime_fingerprint": self.runtime_fingerprint,
                "passed": self.passed, "first_blocker": str(self.first_blocker or ""),
                "admission": str(self.admission),
                "admitted_generation": self.admitted_generation,
                "admitted_profiles": self.admitted_profiles,
                "phases": [{"phase": str(p.phase), "status": str(p.status), "detail": p.detail}
                           for p in self.phases]}


def qualify(surface: VideoRuntimeSurface, *, provider: str,
            evidence_source: str = "",
            vram_gb: float = 0.0, disk_gb: float = 0.0, cuda: bool = False,
            probes: bool = True) -> QualificationReport:
    """跑完整准入链。probes=False 时只做 ENV/HEALTH/CAPABILITY(不启动生成)。"""
    ref = surface.ref
    ref.validate()
    report = QualificationReport(provider, ref.fingerprint())

    env = check_environment(ref, vram_gb=vram_gb, disk_gb=disk_gb, cuda=cuda)
    report.phases.append(PhaseResult(
        Phase.ENVIRONMENT,
        PhaseStatus.PASS if env.state is not HealthState.UNSUPPORTED_ENV else PhaseStatus.BLOCKED,
        env.detail))
    if env.state is HealthState.UNSUPPORTED_ENV:
        report.phases.append(PhaseResult(Phase.HEALTH, PhaseStatus.BLOCKED, "skipped: env"))
        report.phases.append(PhaseResult(Phase.ADMITTED, PhaseStatus.BLOCKED,
                                         f"{env.state}: {env.detail}"))
        report.admission = AdmissionState.PROVIDER_NOT_INSTALLED
        return report

    health = surface.health()
    report.phases.append(PhaseResult(
        Phase.HEALTH, PhaseStatus.PASS if health.usable else PhaseStatus.FAIL,
        f"{health.state}: {health.detail}".strip()))
    if not health.usable:
        for phase in (Phase.CAPABILITY, Phase.T2V_PROBE, Phase.I2V_PROBE, Phase.VC_PROBE,
                      Phase.REFINEMENT_PROBE, Phase.MEDIA_VALIDATION):
            report.phases.append(PhaseResult(phase, PhaseStatus.NOT_EVALUABLE,
                                             "skipped: runtime not reachable"))
        report.phases.append(PhaseResult(Phase.ADMITTED, PhaseStatus.FAIL,
                                         f"health={health.state}"))
        report.admission = AdmissionState.PROVIDER_NOT_INSTALLED
        return report

    caps = surface.capabilities()
    declared = [key for key in GENERATION_PROBES if caps.supports(key)]
    report.phases.append(PhaseResult(
        Phase.CAPABILITY, PhaseStatus.PASS, f"declared by runtime: {declared}"))
    if not declared:
        for phase in (Phase.T2V_PROBE, Phase.I2V_PROBE, Phase.VC_PROBE,
                      Phase.REFINEMENT_PROBE, Phase.MEDIA_VALIDATION):
            report.phases.append(PhaseResult(phase, PhaseStatus.NOT_EVALUABLE,
                                             "skipped: runtime declares no capability"))
        report.phases.append(PhaseResult(Phase.ADMITTED, PhaseStatus.FAIL,
                                         "no capability declared by runtime"))
        report.admission = AdmissionState.NOT_EVALUABLE
        return report

    verified: dict[str, bool] = dict.fromkeys(CAPABILITY_KEYS, False)
    profiles: dict[str, bool] = dict.fromkeys(OUTPUT_PROFILES, False)
    for key, phase in zip(GENERATION_PROBES,
                          (Phase.T2V_PROBE, Phase.I2V_PROBE, Phase.VC_PROBE,
                           Phase.REFINEMENT_PROBE), strict=True):
        if key not in declared:
            report.phases.append(PhaseResult(phase, PhaseStatus.NOT_EVALUABLE,
                                             "not declared by runtime"))
            continue
        if not probes:
            report.phases.append(PhaseResult(phase, PhaseStatus.NOT_EVALUABLE,
                                             "probes disabled"))
            continue
        try:
            sample = surface.generate(None, key)
        except Exception as exc:  # runtime 侧异常 = 该能力未通过,不外泄实现细节
            report.phases.append(PhaseResult(phase, PhaseStatus.FAIL, type(exc).__name__))
            continue
        if not sample.ok:
            report.phases.append(PhaseResult(phase, PhaseStatus.FAIL, sample.detail))
            continue
        report.phases.append(PhaseResult(phase, PhaseStatus.PASS, sample.detail or key))
        verified[key] = True
        for profile in OUTPUT_PROFILES:
            if sample.observed.get(profile):
                profiles[profile] = True

    media_ok = any(verified.values())
    report.phases.append(PhaseResult(
        Phase.MEDIA_VALIDATION,
        PhaseStatus.PASS if media_ok else PhaseStatus.FAIL,
        "media validated" if media_ok else "no verified generation to validate"))

    report.admitted_generation = verified
    report.admitted_profiles = {k: bool(v and media_ok) for k, v in profiles.items()}
    report.admission = (AdmissionState.CAPABILITY_ADMITTED if media_ok
                        else AdmissionState.NOT_EVALUABLE)

    bridge = ProviderEvidenceBridge(provider)
    for key, is_verified in verified.items():
        if is_verified:
            bridge.declare(ExternalEvidence(key, f"probe:{key}",
                                           evidence_source or ref.provenance,
                                           EvidenceStatus.LOCALLY_VERIFIED))
    bridge.try_admit(runtime_ready=media_ok)
    report.evidence = list(bridge.evidence)
    report.phases.append(PhaseResult(Phase.ADMITTED,
                                     PhaseStatus.PASS if media_ok else PhaseStatus.FAIL,
                                     str(report.admission)))
    return report


__all__ = [
    "GENERATION_PROBES",
    "OUTPUT_PROFILES",
    "Phase",
    "PhaseResult",
    "PhaseStatus",
    "QualificationReport",
    "RuntimeSample",
    "qualify",
]
