"""P5-A External Video Runtime Contract 验收。

原则:HEVI 不安装 runtime;只认 runtime_ref + endpoint/process + checkpoint identity +
capability evidence + health state。没有实测证据的能力一律 False。
"""

import json
from pathlib import Path

import pytest

from hevi.generation.errors import GenerationError
from hevi.generation.evidence import AdmissionState
from hevi.generation.external_runtime import (
    OUTPUT_PROFILES,
    EndpointSpec,
    EnvironmentRequirements,
    ExternalRuntimeRef,
    HealthState,
    ProcessSpec,
    RuntimeCapabilities,
    RuntimeHealth,
    RuntimeKind,
    RuntimeSample,
    check_environment,
)
from hevi.generation.longcat_probe import runtime_ref_for_longcat
from hevi.generation.qualification import Phase, PhaseStatus, qualify

COG_LIKE = EnvironmentRequirements(vram_gb=48.0, disk_gb=25.0, cuda_required=True)


def _ref(**kw) -> ExternalRuntimeRef:
    base = dict(runtime_id="ext-video", kind=RuntimeKind.ENDPOINT,
                version="1.0", checkpoint_identity="rev-abc",
                endpoint=EndpointSpec("http://127.0.0.1:8080"),
                provenance="https://example.invalid/wrapper")
    return ExternalRuntimeRef(**{**base, **kw})


class FakeSurface:
    """确定性 surface 实现(HEVI 之外那一侧的可测替身)。"""

    def __init__(self, ref, *, health=HealthState.REACHABLE, caps=None,
                 failing: tuple[str, ...] = ()) -> None:
        self.ref = ref
        self._health, self._caps, self._failing = health, caps or {}, failing
        self.calls: list[str] = []

    def health(self) -> RuntimeHealth:
        return RuntimeHealth(self._health, "probe")

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(generation=dict(self._caps))

    def generate(self, request, mode: str) -> RuntimeSample:
        self.calls.append(mode)
        if mode in self._failing:
            return RuntimeSample(False, detail=f"{mode} unavailable")
        return RuntimeSample(True, artifact_path=f"/tmp/{mode}.mp4",
                             detail=f"{mode} ok",
                             observed={"720p": True, "30fps": mode == "t2v"})

    def validate_media(self, sample: RuntimeSample) -> RuntimeSample:
        return sample


# ── runtime ref 契约 ──
def test_ref_requires_identity_and_matching_spec():
    with pytest.raises(GenerationError):
        _ref(runtime_id="").validate()
    with pytest.raises(GenerationError):
        _ref(checkpoint_identity="").validate()          # 未 pin checkpoint → 不准入
    with pytest.raises(GenerationError):
        _ref(endpoint=None).validate()                   # ENDPOINT 必须有 endpoint
    with pytest.raises(GenerationError):
        _ref(kind=RuntimeKind.PROCESS, endpoint=None,
             process=None).validate()                     # PROCESS 必须有 process
    _ref().validate()


def test_ref_fingerprint_changes_with_checkpoint_or_version():
    base = _ref().fingerprint()
    assert base == _ref().fingerprint()
    assert base != _ref(checkpoint_identity="rev-xyz").fingerprint()
    assert base != _ref(version="2.0").fingerprint()
    assert base != _ref(runtime_id="other").fingerprint()


def test_ref_dict_is_serializable_and_leaks_no_secrets():
    payload = _ref().to_dict()
    json.dumps(payload)
    assert payload["checkpoint_identity"] == "rev-abc"
    assert "auth" not in json.dumps(payload) or payload["endpoint"]["auth_ref"] == ""


def test_process_ref_carries_no_model_internals():
    ref = _ref(kind=RuntimeKind.PROCESS, endpoint=None,
               process=ProcessSpec(argv_template=("longcat-video", "--mode", "t2v")))
    ref.validate()
    text = json.dumps(ref.to_dict())
    for leaked in ("num_cond_frames", "use_kv_cache", "enable_bsa", "lora"):
        assert leaked not in text


# ── 环境先于 runtime ──
def test_env_blocked_before_ever_starting_runtime():
    ref = _ref(requirements=COG_LIKE)
    health = check_environment(ref, vram_gb=10.0, disk_gb=200.0, cuda=True)
    assert health.state is HealthState.UNSUPPORTED_ENV and "vram" in health.detail
    report = qualify(FakeSurface(ref), provider="ext-video", vram_gb=10.0,
                     disk_gb=200.0, cuda=True)
    assert report.first_blocker is Phase.ENVIRONMENT
    assert report.phases[1].status is PhaseStatus.BLOCKED      # HEALTH skipped
    assert report.admission is AdmissionState.PROVIDER_NOT_INSTALLED
    assert report.admitted_generation == {}                    # 未准入任何能力


def test_env_satisfied_proceeds_to_health():
    ref = _ref(requirements=COG_LIKE)
    assert check_environment(ref, vram_gb=80.0, disk_gb=100.0,
                             cuda=True).state is HealthState.UNKNOWN
    report = qualify(FakeSurface(ref), provider="ext-video", vram_gb=80.0,
                     disk_gb=100.0, cuda=True, probes=False)
    assert report.first_blocker is not Phase.ENVIRONMENT
    assert report.phases[1].status is PhaseStatus.PASS        # HEALTH passed


def test_unreachable_runtime_admits_nothing():
    ref = _ref()
    report = qualify(FakeSurface(ref, health=HealthState.UNREACHABLE), provider="ext-video")
    assert report.first_blocker is Phase.HEALTH
    assert report.admission is AdmissionState.PROVIDER_NOT_INSTALLED
    assert all(report.admitted_generation.get(k) is not True
               for k in ("t2v", "i2v", "continuation", "refinement"))


# ── 能力矩阵:没有证据就是 False ──
def test_only_probed_capabilities_are_admitted():
    ref = _ref()
    surface = FakeSurface(ref, caps={"t2v": True, "i2v": True, "continuation": False})
    report = qualify(surface, provider="ext-video")
    assert report.admitted_generation["t2v"] is True
    assert report.admitted_generation["i2v"] is True
    assert report.admitted_generation["continuation"] is False   # 未通过探针
    assert report.admitted_generation["refinement"] is False     # 未声明
    assert report.admitted_profiles["720p"] is True
    assert report.admitted_profiles["30fps"] is True
    assert report.admission is AdmissionState.CAPABILITY_ADMITTED
    assert set(report.admitted_profiles) == set(OUTPUT_PROFILES)


def test_failing_probe_does_not_admit():
    ref = _ref()
    surface = FakeSurface(ref, caps={"t2v": True}, failing=("t2v",))
    report = qualify(surface, provider="ext-video")
    assert report.admitted_generation["t2v"] is False
    assert report.first_blocker is Phase.T2V_PROBE
    assert report.admission is AdmissionState.NOT_EVALUABLE
    assert surface.calls == ["t2v"]      # 未通过就不继续探下一个


def test_runtime_exception_is_treated_as_failure_not_pass():
    class Exploding(FakeSurface):
        def generate(self, request, mode):
            raise RuntimeError("cuda oom")

    ref = _ref()
    report = qualify(Exploding(ref, caps={"t2v": True}), provider="ext-video")
    assert report.admitted_generation["t2v"] is False
    assert "RuntimeError" in next(p.detail for p in report.phases if p.phase is Phase.T2V_PROBE)


def test_no_capability_declared_means_no_admission():
    report = qualify(FakeSurface(_ref(), caps={}), provider="ext-video")
    assert report.first_blocker in (Phase.CAPABILITY, Phase.T2V_PROBE)
    assert report.admitted_generation == {}


def test_probes_disabled_never_admits():
    ref = _ref()
    report = qualify(FakeSurface(ref, caps={"t2v": True}), provider="ext-video", probes=False)
    assert report.admitted_generation.get("t2v") is not True
    assert report.admission is not AdmissionState.CAPABILITY_ADMITTED


# ── 通用性:这不是 LongCat 专用机制 ──
def test_mechanism_is_backend_agnostic():
    for name in ("wan-local-ish", "veo3-ish", "some-future-backend"):
        report = qualify(FakeSurface(_ref(runtime_id=name), caps={"t2v": True}),
                         provider=name)
        assert report.admitted_generation["t2v"] is True
        assert report.provider == name


def test_report_is_serializable_for_receipts():
    json.dumps(qualify(FakeSurface(_ref(), caps={"t2v": True}), provider="ext").to_dict())


# ── LongCat 的 runtime_ref 反映 48GB/25GB 前置 ──
def test_longcat_ref_declares_cog_like_requirements():
    ref = runtime_ref_for_longcat()
    ref.validate()
    assert ref.requirements.vram_gb == 48.0 and ref.requirements.disk_gb == 25.0
    assert ref.kind is RuntimeKind.PROCESS and ref.process is not None
    # 本机 3080 10GB → 直接 ENV_BLOCKED,不去启动
    report = qualify(FakeSurface(ref), provider="longcat-video", vram_gb=10.0,
                     disk_gb=500.0, cuda=True)
    assert report.first_blocker is Phase.ENVIRONMENT
    assert report.admission is AdmissionState.PROVIDER_NOT_INSTALLED


def test_longcat_ref_endpoint_form():
    ref = runtime_ref_for_longcat(endpoint_url="http://127.0.0.1:9000")
    ref.validate()
    assert ref.kind is RuntimeKind.ENDPOINT and ref.endpoint is not None


def test_runtime_state_must_be_explicit_env_or_unavailable():
    for state in (HealthState.UNKNOWN, HealthState.UNSUPPORTED_ENV):
        report = qualify(FakeSurface(_ref(), health=state), provider="ext")
        assert report.admission is AdmissionState.PROVIDER_NOT_INSTALLED


def test_checkpoint_absent_blocks_admission(tmp_path):
    """checkpoint identity 未解析时不能算已就绪。"""
    with pytest.raises(GenerationError):
        ExternalRuntimeRef(runtime_id="x", kind=RuntimeKind.PROCESS,
                           process=ProcessSpec(argv_template=("x",)),
                           checkpoint_identity="").validate()
    assert Path("/nonexistent-checkpoint").exists() is False
