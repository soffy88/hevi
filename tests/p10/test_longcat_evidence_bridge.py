"""P4 Provider Evidence Bridge 验收:声明 ≠ 准入。

红线:HEVI capability registry 不得因"官方声称"而出现 longcat-video 能力。
"""

import json

import pytest

from hevi.generation.evidence import (
    CAPABILITY_KEYS,
    AdmissionState,
    EvidenceStatus,
    ExternalEvidence,
    ProviderEvidenceBridge,
    longcat_bridge,
)
from hevi.generation.longcat_adapter import (
    LongCatVideoAdapterSkeleton,
    ProviderNotInstalled,
)
from hevi.generation.longcat_probe import (
    ORDER,
    StepName,
    StepResult,
    StepStatus,
    admitted_capabilities_from,
    evidence_snapshot,
    probe,
)
from hevi.generation.models import Intent, VideoGenerationRequest


# ── evidence 登记 ──
def test_upstream_claims_are_registered_with_source():
    bridge = longcat_bridge()
    assert set(bridge.declared_only()) >= {"t2v", "i2v", "continuation", "refinement",
                                           "long_video", "temporal_refinement"}
    assert bridge.verified() == ()
    for item in bridge.evidence:
        assert item.source.startswith("https://")  # 无出处不予登记


def test_evidence_requires_source():
    with pytest.raises(ValueError):
        ExternalEvidence("t2v", "claim", "").validate()
    with pytest.raises(ValueError):
        ExternalEvidence("not_a_capability", "claim", "https://x").validate()


# ── 声明永不自动升级为能力 ──
def test_declared_upstream_never_becomes_capability():
    bridge = longcat_bridge()
    assert bridge.admitted_capabilities() == dict.fromkeys(CAPABILITY_KEYS, False)
    assert bridge.admission is AdmissionState.NOT_EVALUABLE
    # 即使 runtime_ready,只要还有未核实声明就不准入
    assert bridge.try_admit(runtime_ready=True) is AdmissionState.NOT_EVALUABLE
    assert bridge.admitted_capabilities() == dict.fromkeys(CAPABILITY_KEYS, False)


def test_full_verification_admits():
    bridge = ProviderEvidenceBridge("demo")
    for key in ("t2v", "i2v"):
        bridge.declare(ExternalEvidence(key, "claim", "https://x"))
        bridge.mark(key, EvidenceStatus.LOCALLY_VERIFIED)
    assert bridge.try_admit(runtime_ready=True) is AdmissionState.CAPABILITY_ADMITTED
    assert bridge.admitted_capabilities()["t2v"] is True
    assert bridge.admitted_capabilities()["refinement"] is False  # 未声明即 False


def test_runtime_not_ready_reports_not_installed():
    bridge = longcat_bridge()
    assert bridge.try_admit(runtime_ready=False) is AdmissionState.PROVIDER_NOT_INSTALLED
    assert bridge.admitted_capabilities() == dict.fromkeys(CAPABILITY_KEYS, False)


# ── Evidence Gate ──
def test_gate_blocks_at_first_step_and_covers_full_chain():
    report = probe()
    assert not report.passed
    assert report.first_blocker is StepName.SOURCE_AVAILABLE
    assert [s.name for s in report.steps] == list(ORDER)  # 全链都记录,不静默跳过
    assert report.steps[-1].status is StepStatus.NOT_EVALUABLE


def test_gate_passes_only_with_source_importable_checkpoint_and_runtime():
    def runtime_probe():
        return dict.fromkeys((StepName.RUNTIME_INITIALIZES, StepName.T2V_PROBE, StepName.I2V_PROBE, StepName.VC_PROBE, StepName.REFINEMENT_PROBE, StepName.MEDIA_VALIDATION), True)

    # 真实存在且可导入的 python 包目录 + 真实 checkpoint 文件
    import pathlib

    src = pathlib.Path(__file__).parent
    ckpt = src / "fixtures" / "fake.ckpt"
    ckpt.parent.mkdir(exist_ok=True)
    ckpt.write_text("x")
    report = probe(source_root=str(src), module_name="json",
                   checkpoint_path=str(ckpt), runtime_probe=runtime_probe)
    assert report.passed, report.to_dict()
    admitted = admitted_capabilities_from(report)
    assert admitted["t2v"] and admitted["i2v"] and admitted["continuation"]
    assert admitted["refinement"] and admitted["long_video"]
    assert admitted["audio_conditioning"] is False  # 上游无声明,不猜


def test_gate_partial_runtime_stays_not_evaluable(tmp_path):
    import pathlib

    src = pathlib.Path(__file__).parent
    ckpt = tmp_path / "c.ckpt"
    ckpt.write_text("x")
    report = probe(source_root=str(src), module_name="json", checkpoint_path=str(ckpt),
                   runtime_probe={StepName.RUNTIME_INITIALIZES: True, StepName.T2V_PROBE: True})
    assert not report.passed
    assert report.first_blocker is StepName.I2V_PROBE  # 停在第一个未验证的探针
    assert admitted_capabilities_from(report) == dict.fromkeys(CAPABILITY_KEYS, False)


# ── adapter skeleton:形状齐备,能力为空 ──
def test_skeleton_claims_no_capability():
    adapter = LongCatVideoAdapterSkeleton()
    caps = adapter.capabilities()
    assert caps.declared == dict.fromkeys(CAPABILITY_KEYS, False)
    assert adapter.supports_anything() is False
    assert longcat_evidence_snapshot_admission() != "CAPABILITY_ADMITTED"


def longcat_evidence_snapshot_admission() -> str:
    return str(evidence_snapshot()["admission"])


def test_skeleton_refuses_to_generate_media():
    adapter = LongCatVideoAdapterSkeleton()
    request = VideoGenerationRequest("p", "s", "S1", "g1", intent=Intent(prompt="x"))
    with pytest.raises(ProviderNotInstalled) as exc:
        adapter.generate(request)
    assert exc.value.code == "PROVIDER_NOT_INSTALLED"


def test_skeleton_not_registered_in_provider_registry():
    """HEVI capability registry 保持现实能力:不得出现 longcat-video。"""
    from hevi.providers.facts import PROVIDER_CATALOGUE, get_profile
    from hevi.providers.facts import ProviderKind as Kind

    assert get_profile("longcat-video") is None
    longcat = get_profile("longcat")
    assert longcat is not None and longcat.kind is Kind.LLM  # 现状:LLM endpoint,非视频
    assert PROVIDER_CATALOGUE is not None


def test_evidence_snapshot_is_serializable():
    payload = evidence_snapshot()
    json.dumps(payload)  # 可进 receipt
    assert payload["admitted"] is False
    assert payload["locally_verified"] == []
    assert "continuation" in payload["declared_upstream"]


def test_probe_report_is_serializable():
    json.dumps(probe().to_dict())


def test_evidence_instances_are_not_shared_between_bridges():
    """回归:模块级 frozen 常量若被复用,一次 mark 会泄漏到所有后续 bridge ——
    等于"跑过一次就永远认为已核实"。"""
    first = longcat_bridge()
    first.mark("t2v", EvidenceStatus.LOCALLY_VERIFIED)
    assert "t2v" in first.verified()
    second = longcat_bridge()
    assert "t2v" not in second.verified(), "verified state leaked into a fresh bridge"
    assert "t2v" in second.declared_only()


def test_capability_partial_probe_admits_only_probed_ones():
    bridge = ProviderEvidenceBridge("demo")
    for key in ("t2v", "refinement"):
        bridge.declare(ExternalEvidence(key, "claim", "https://x"))
    bridge.mark("t2v", EvidenceStatus.LOCALLY_VERIFIED)  # refinement 未 probe
    assert bridge.try_admit(runtime_ready=True) is AdmissionState.CAPABILITY_ADMITTED
    caps = bridge.admitted_capabilities()
    assert caps["t2v"] is True and caps["refinement"] is False


def test_step_result_honest_passthrough():
    assert StepResult(StepName.VC_PROBE, StepStatus.FAIL, "no VC").status is StepStatus.FAIL
