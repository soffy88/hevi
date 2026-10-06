"""Canonical generation contract 验收(P1-P3)。

架构红线测试:provider 专属 flag 不得出现在 canonical 结构中。
"""

import dataclasses

import pytest

from hevi.generation import (
    CAPABILITY_KEYS,
    FORBIDDEN_CANONICAL_FIELDS,
    BudgetLevel,
    CapabilityUnsupported,
    Conditioning,
    ConditioningWindow,
    ConditioningWindowInvalid,
    ContinuationState,
    ContinuationStateMissing,
    GeneratedClip,
    GenerationBudget,
    GenerationJournal,
    GenerationMode,
    GenerationStage,
    Intent,
    MediaIntegrityError,
    OutputSpec,
    SilentFallbackDetected,
    StageRecord,
    ValidationSpec,
    VideoGenerationCapabilities,
    VideoGenerationRequest,
    new_continuation_state,
    run_generation,
    validate_capability,
)


# ── 测试用 backend(确定性,不 mock 契约)──
class FakeBackend:
    def __init__(self, caps: dict[str, bool], *, name: str = "fake", version: str = "1",
                 bind_state: bool = True, fps: int = 24) -> None:
        self.name, self.version = name, version
        self._caps = VideoGenerationCapabilities(declared=dict(caps))
        self._bind_state = bind_state
        self._fps = fps
        self.calls: list[VideoGenerationRequest] = []

    def capabilities(self) -> VideoGenerationCapabilities:
        return self._caps

    def generate(self, request: VideoGenerationRequest) -> GeneratedClip:
        self.calls.append(request)
        return GeneratedClip(
            artifact_path="", artifact_hash="h", generation_id=request.generation_id,
            source_shot_id=request.shot_id,
            continuation_state_id=(request.conditioning.continuation_state_id
                                   if self._bind_state else ""),
            generation_stage=request.stage, backend=self.name, backend_version=self.version,
            fps=self._fps, frame_count=24, duration_ms=1000)


FULL_CAPS = dict.fromkeys(CAPABILITY_KEYS, True)


def _request(**kw) -> VideoGenerationRequest:
    base = dict(project_id="p", scene_id="s1", shot_id="S1", generation_id="g1",
                intent=Intent(prompt="a black hole"), output=OutputSpec(fps=24, duration_ms=1000))
    return VideoGenerationRequest(**{**base, **kw})


def _window(frames: int = 13, fps: int = 24) -> ConditioningWindow:
    span = round((frames - 1) * 1000 / fps)
    return ConditioningWindow("media://accel", 0, frames - 1, 0, span, fps)


def _state(window: ConditioningWindow | None = None) -> ContinuationState:
    window = window or _window()
    return ContinuationState("cs:g0:0", "g0", "S0", window, backend="fake", backend_version="1")


# ── P1 canonical contract ──
def test_p1_request_is_provider_agnostic():
    request = _request()
    names = {f.name for f in dataclasses.fields(request)}
    for banned in FORBIDDEN_CANONICAL_FIELDS:
        assert banned not in names
    # 嵌套结构同样不得含 provider flag
    nested = {f.name for f in dataclasses.fields(request.intent)} | {
        f.name for f in dataclasses.fields(request.conditioning)} | {
        f.name for f in dataclasses.fields(request.output)} | {
        f.name for f in dataclasses.fields(request.quality)} | {
        f.name for f in dataclasses.fields(request.validation)}
    assert not (nested & set(FORBIDDEN_CANONICAL_FIELDS))


def test_p1_request_hash_stable_and_input_sensitive():
    assert _request().request_hash() == _request().request_hash()
    assert _request().request_hash() != _request(generation_id="g2").request_hash()
    assert _request(mode=GenerationMode.I2V).required_capabilities() == ("i2v",)
    assert _request(mode=GenerationMode.DIRECTED_CONTINUATION).required_capabilities() == (
        "continuation",)


def test_p1_budget_and_stage_enums():
    budget = GenerationBudget(spatial_budget=BudgetLevel.HIGH,
                              motion_budget=BudgetLevel.LOW)
    assert budget.spatial_budget is BudgetLevel.HIGH
    assert [str(s) for s in GenerationStage] == ["DRAFT", "CONTINUATION", "REFINEMENT", "FINAL"]


def test_p1_capability_model_missing_keys_default_false():
    caps = VideoGenerationCapabilities({"t2v": True})
    assert caps.supports("t2v") and not caps.supports("continuation")
    assert caps.missing(("t2v", "refinement")) == ("refinement",)


# ── P2 conditioning window ──
def test_p2_window_invariants():
    window = _window(13)
    window.validate()
    assert window.frame_count == 13
    # frame_count 不符
    with pytest.raises(ConditioningWindowInvalid):
        ConditioningWindow("m", 5, 4, 0, 1000, 24).validate()
    # timestamp 与 fps 不符
    with pytest.raises(ConditioningWindowInvalid):
        ConditioningWindow("m", 0, 12, 0, 999, 24).validate()
    # media_ref 必填(禁止 last_frame 式空引用)
    with pytest.raises(ConditioningWindowInvalid):
        ConditioningWindow("", 0, 12, 0, 500, 24).validate()


def test_p2_state_is_not_a_last_frame_file(tmp_path):
    state = _state()
    state.validate()
    assert state.conditioning_window.frame_count == 13
    # state 带时间语义与视觉锚点,不是裸文件路径
    assert state.conditioning_window.timestamp_end_ms > 0
    assert state.visual_anchor is not None


def test_p2_new_state_from_previous_clip(tmp_path):
    media = tmp_path / "shot0.mp4"
    media.write_bytes(b"clip")
    clip = GeneratedClip(str(media), "h", "g0", "S0", fps=24, frame_count=24, duration_ms=1000)
    state = new_continuation_state(source=clip, media_path=media, window=_window(),
                                   backend="fake", backend_version="1", seed=7)
    state.validate()
    assert state.source_generation_id == "g0" and state.generation_seed == 7
    with pytest.raises(MediaIntegrityError):
        new_continuation_state(source=clip, media_path=tmp_path / "gone.mp4",
                               window=_window(), backend="fake", backend_version="1")


# ── P3 backend + fail-closed ──
def test_p3_capability_gate():
    backend = FakeBackend({"t2v": True})
    validate_capability(backend, _request())
    with pytest.raises(CapabilityUnsupported):
        validate_capability(backend, _request(mode=GenerationMode.DIRECTED_CONTINUATION))
    with pytest.raises(CapabilityUnsupported):
        validate_capability(backend, _request(mode=GenerationMode.I2V))


def test_p3_continuation_fail_closed_on_missing_state(tmp_path):
    backend = FakeBackend(FULL_CAPS)
    request = _request(mode=GenerationMode.DIRECTED_CONTINUATION,
                       conditioning=Conditioning("continuation", "", "cs:g0:0"),
                       validation=ValidationSpec(continuity_required=True))
    with pytest.raises(ContinuationStateMissing):
        run_generation(backend, request, state=None, artifact=tmp_path / "x.mp4")
    # 即便给了 state,但 backend 静默不绑定 → 视同退回 T2V
    silent = FakeBackend(FULL_CAPS, bind_state=False)
    with pytest.raises(SilentFallbackDetected):
        run_generation(silent, request, state=_state(), artifact=tmp_path / "x.mp4")


def test_p3_continuation_requires_continuity_required_flag(tmp_path):
    backend = FakeBackend(FULL_CAPS)
    request = _request(mode=GenerationMode.DIRECTED_CONTINUATION,
                       conditioning=Conditioning("continuation", "", "cs:g0:0"))
    with pytest.raises(ContinuationStateMissing):
        run_generation(backend, request, state=_state(), artifact=tmp_path / "x.mp4")


def test_p3_success_carries_provenance(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"data")
    backend = FakeBackend(FULL_CAPS)
    request = _request(mode=GenerationMode.DIRECTED_CONTINUATION, stage=GenerationStage.CONTINUATION,
                       conditioning=Conditioning("continuation", "", "cs:g0:0"),
                       validation=ValidationSpec(continuity_required=True))
    result = run_generation(backend, request, state=_state(), artifact=media)
    prov = result.provenance()
    for key in ("generation_id", "source_shot_id", "continuation_state_id",
                "generation_stage", "backend", "backend_version", "request_hash"):
        assert prov[key]
    assert result.gates["continuity_gate"] == "PASS"
    assert result.gates["media_integrity_gate"] == "PASS"


def test_p3_media_gate_fails_on_missing_artifact(tmp_path):
    backend = FakeBackend(FULL_CAPS)
    with pytest.raises(MediaIntegrityError):
        run_generation(backend, _request(), artifact=tmp_path / "nope.mp4")
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(MediaIntegrityError):
        run_generation(backend, _request(), artifact=empty)


def test_p3_fps_mismatch_fails_closed(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"data")
    backend = FakeBackend(FULL_CAPS, fps=30)
    with pytest.raises(MediaIntegrityError):
        run_generation(backend, _request(), artifact=media)  # request fps=24


# ── resume(spec §13) ──
def test_p3_refinement_failure_reuses_validated_stage1(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"data")
    clip = GeneratedClip(str(media), "h", "g1", "S1", fps=24, frame_count=24, duration_ms=1000,
                         generation_stage=GenerationStage.CONTINUATION)
    journal = GenerationJournal("g1")
    journal.record(StageRecord(GenerationStage.DRAFT, clip, gates={"media_integrity_gate": "PASS"}))
    journal.record(StageRecord(GenerationStage.CONTINUATION, clip,
                               gates={"continuity_gate": "PASS", "media_integrity_gate": "PASS"}))
    assert journal.resumable_stage(GenerationStage.REFINEMENT) is GenerationStage.CONTINUATION
    assert journal.validated_output(GenerationStage.CONTINUATION) is clip
    # DRAFT 未验证则不可续
    journal2 = GenerationJournal("g2")
    journal2.record(StageRecord(GenerationStage.DRAFT, clip, gates={"media_integrity_gate": "FAIL"}))
    assert journal2.validated_output(GenerationStage.DRAFT) is None
    assert journal2.resumable_stage(GenerationStage.CONTINUATION) is None


def test_p3_retry_keeps_same_generation_contract():
    a, b = _request(), _request()
    assert a.request_hash() == b.request_hash()  # 重试同一契约,不重新生成 scene
