"""HEVI P5.2 — Parts D/E/F/G/H/I: presenter, raw footage, product, renderers, editable, TTS.

Covers presenter planning and audio-lock discipline, take detection, silence
classification, cut planning and boundary QA, product surface manifests and
claim grounding, the fake-UI guard, renderer registry and capability selection,
the HTML sandbox, frame determinism, editable backends, CapCut security, draft
lint, backend differential validation, structural round trip, flattening truth
and Pocket TTS capability.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from hevi.editable import (
    BackendProjection,
    EditabilityLevel,
    EditableBackendId,
    EditableProjectManifest,
    ProjectOutcome,
    TrackElement,
    compare_projections,
    lint_manifest,
    project_manifest,
    register_all_backends,
    structural_round_trip,
)
from hevi.editable.capcut_cli import (
    EXPECTED_REVISION,
    EXPECTED_VERSION,
    LAYER_TO_TRACK,
    CapCutCliBackend,
    CapCutSecurityError,
    assert_contained,
    assert_safe_name,
    classify_editability,
    scrub_device_identifiers,
)
from hevi.ops.p5_1_types import EvidenceAsset, EvidenceSourceType
from hevi.production.presenter import (
    AudioLock,
    PresenterArtifact,
    PresenterScale,
    PresenterShotRange,
    build_presenter_plan,
    check_presenter_qa,
    resolve_presenter_provider,
    scale_for_role,
    validate_presentation_mix,
)
from hevi.production.product_video import (
    REAL_PRODUCT_TIERS,
    ProductDemoState,
    ProductEvidenceTier,
    ProductRepoMutationError,
    ProductSurface,
    ProductSurfaceManifest,
    assert_not_fake_product_ui,
    assert_repo_read_only,
    build_product_video_plan,
    ground_claim,
    is_capability_claim,
    product_gate_report,
)
from hevi.production.raw_footage import (
    BREATH_S,
    CutReason,
    RawFootageSource,
    SilenceClass,
    TakeQuality,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
    build_cut_plan,
    check_cut_boundaries,
    classify_silence,
    detect_silences,
    detect_takes,
    parse_whisper_json,
)
from hevi.providers.pocket_tts import (
    DECLARED_LANGUAGES,
    LanguageSupport,
    PocketTtsLanguageError,
    TtsRequest,
    probe,
    synthesise,
    tts_gate_report,
)
from hevi.renderers import (
    FfmpegRenderer,
    HtmlGsapRenderer,
    RemotionRenderer,
    RenderContractViolation,
    RendererCapability,
    RendererId,
    RenderOutcome,
    RenderPlan,
    RenderResult,
    SelectionRequirement,
    enforce_equivalence,
    plan_requires_semantic_motion,
    register_all_renderers,
    renderer_capability_matrix,
    select_renderer,
    verify_equivalence,
)
from hevi.renderers.html_gsap import (
    assert_no_unsafe_url,
    assert_sandbox_path,
    scrubbed_environment,
)

# ══ D. Presenter ═══════════════════════════════════════════════════════

def _lock(duration: float = 4.2) -> AudioLock:
    return AudioLock("al", "/tmp/a.wav", "sha256:abc", duration)


# ── test_presenter_plan ──────────────────────────────────────────────────


def test_presenter_plan_is_bound_to_an_audio_lock() -> None:
    lock = _lock()
    plan = build_presenter_plan(
        plan_id="pp", presenter_entity_id="e1", audio_lock=lock,
        shot_ranges=[PresenterShotRange("s1", 0.0, 2.0, PresenterScale.MEDIUM, "DIRECT_ADDRESS")],
    )
    assert plan.audio_lock.audio_lock_id == "al"
    assert plan.audio_lock.duration_s == 4.2
    assert plan.to_dict()["audio_lock"]["audio_hash"] == "sha256:abc"


def test_presenter_plan_refuses_an_empty_audio_lock() -> None:
    with pytest.raises(ValueError):
        build_presenter_plan(plan_id="pp", presenter_entity_id="e1", audio_lock=_lock(0.0))


def test_presenter_plan_declares_capabilities_not_products() -> None:
    plan = build_presenter_plan(plan_id="pp", presenter_entity_id="e1", audio_lock=_lock())
    assert plan.provider_capability == "AVATAR_GENERATION"
    assert plan.provider_id == ""


# ── test_presenter_audio_lock ────────────────────────────────────────────


def test_presenter_audio_lock_must_match(tmp_path: Path) -> None:
    """A8: a presenter built against the wrong audio is blocked."""
    import hashlib

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"voice-track")
    digest = hashlib.sha256(b"voice-track").hexdigest()
    lock = AudioLock("al", str(audio), f"sha256:{digest}", 1.0)
    plan = build_presenter_plan(plan_id="pp", presenter_entity_id="e", audio_lock=lock)
    from hevi.production.presenter import assert_audio_lock

    assert_audio_lock(plan, str(audio), f"sha256:{digest}", 1.0)
    with pytest.raises(ValueError, match="PRESENTER_AUDIO_HASH_MISMATCH"):
        assert_audio_lock(plan, str(audio), "sha256:wrong", 0.0)


def test_presenter_audio_drift_is_refused(tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    lock = AudioLock("al", str(audio), "", 4.2)
    plan = build_presenter_plan(plan_id="pp", presenter_entity_id="e", audio_lock=lock)
    from hevi.production.presenter import assert_audio_lock

    with pytest.raises(ValueError, match="PRESENTER_AUDIO_DRIFT"):
        assert_audio_lock(plan, str(audio), "", 2.0)


# ── test_presenter_consistency ───────────────────────────────────────────


def test_presenter_consistency_qa_passes_for_a_clean_artifact() -> None:
    plan = build_presenter_plan(plan_id="pp", presenter_entity_id="e", audio_lock=_lock())
    artifact = PresenterArtifact("pr", "e", "prov", audio_hash="sha256:abc", duration_s=4.2,
                                 lip_sync_metadata={"ok": True})
    report = check_presenter_qa(artifact, plan, audio_duration_s=4.2)
    assert report.ok is True
    assert "lip_sync_artifact_exists" in report.checked


def test_presenter_truncating_narration_fails_qa() -> None:
    """A9: a presenter that cuts the narration short must fail."""
    plan = build_presenter_plan(plan_id="pp", presenter_entity_id="e", audio_lock=_lock())
    artifact = PresenterArtifact("pr", "e", "prov", audio_hash="sha256:abc", duration_s=2.0,
                                 lip_sync_metadata={"ok": True})
    report = check_presenter_qa(artifact, plan, audio_duration_s=4.2)
    kinds = {i.kind for i in report.issues}
    assert "PRESENTER_TRUNCATES_NARRATION" in kinds
    assert report.ok is False


def test_presenter_missing_lip_sync_fails_when_required() -> None:
    plan = build_presenter_plan(plan_id="pp", presenter_entity_id="e", audio_lock=_lock())
    artifact = PresenterArtifact("pr", "e", "prov", audio_hash="sha256:abc", duration_s=4.2)
    kinds = {i.kind for i in check_presenter_qa(artifact, plan, audio_duration_s=4.2).issues}
    assert "LIP_SYNC_METADATA_MISSING" in kinds


def test_presenter_continuity_drift_is_caught() -> None:
    plan = build_presenter_plan(plan_id="pp", presenter_entity_id="e", audio_lock=_lock())
    artifact = PresenterArtifact("pr", "e", "prov", audio_hash="sha256:abc", duration_s=4.2,
                                 lip_sync_metadata={"ok": True},
                                 provenance={"continuity": {"clothing": "red"}})
    report = check_presenter_qa(artifact, plan, audio_duration_s=4.2,
                               continuity={"clothing": "navy"})
    assert any(i.kind == "PRESENTER_CONTINUITY_DRIFT" for i in report.issues)


def test_presenter_provider_resolution_requires_capability() -> None:
    class Provider:
        def __init__(self, name: str, caps: set[str]) -> None:
            self.provider_id = name
            self.capabilities = {type("C", (), {"value": c})() for c in caps}

    good = Provider("good", {"AVATAR_GENERATION", "LIP_SYNC"})
    no_lip = Provider("no_lip", {"AVATAR_GENERATION"})
    chosen, reason = resolve_presenter_provider([no_lip, good])
    assert chosen is good
    assert "CAPABILITY_MATCH" in reason
    none, reason = resolve_presenter_provider([no_lip])
    assert none is None
    assert "NO_CAPABLE_PROVIDER" in reason


def test_presenter_scale_follows_evidence_visibility() -> None:
    assert scale_for_role("DIRECT_ADDRESS", evidence_visible=True) is PresenterScale.PIP
    assert scale_for_role("DIRECT_ADDRESS", evidence_visible=False) is PresenterScale.MEDIUM
    assert scale_for_role("CONTEXTUAL_BROLL", evidence_visible=False) is PresenterScale.PIP


def test_all_full_screen_presenter_is_a_policy_failure() -> None:
    """A10: a presenter that owns every shot is a policy failure."""
    ranges = [PresenterShotRange(f"s{i}", 0, 1, scale=PresenterScale.FULL) for i in range(4)]
    ok, violations = validate_presentation_mix(ranges)
    assert ok is False
    assert "PRESENTER_FULL_SCREEN_EVERYWHERE" in violations


def test_presenter_mix_switches_pass() -> None:
    ranges = [
        PresenterShotRange("s1", 0, 1, scale=PresenterScale.MEDIUM),
        PresenterShotRange("s2", 1, 2, scale=PresenterScale.PIP),
        PresenterShotRange("s3", 2, 3, scale=PresenterScale.HIDDEN),
    ]
    assert validate_presentation_mix(ranges)[0] is True


# ══ E. Raw footage ══════════════════════════════════════════════════════

def _transcript() -> Transcript:
    return Transcript(
        segments=[
            TranscriptSegment(0, "所以我想说的是这个功能。", 0.0, 2.0),
            TranscriptSegment(1, "嗯让我再试一次。", 2.2, 4.0),
            TranscriptSegment(2, "这个功能真的很好用。", 4.2, 6.0),
            TranscriptSegment(3, "总之你先去试一下。", 9.0, 10.5),
        ]
    )


# ── test_take_detection ──────────────────────────────────────────────────


def test_take_detection_classifies_fillers_without_deleting_them() -> None:
    takes = detect_takes(_transcript())
    by_index = {t.index: t for t in takes}
    assert by_index[0].quality is TakeQuality.VALID
    assert by_index[1].quality is TakeQuality.FILLER
    assert "flagged, not deleted" in by_index[1].reason


def test_take_detection_flags_a_restart_after_a_long_pause() -> None:
    takes = detect_takes(_transcript())
    assert next(t for t in takes if t.index == 3).quality is TakeQuality.RESTART


def test_take_detection_flags_a_repeated_phrase() -> None:
    transcript = Transcript(segments=[
        TranscriptSegment(0, "我们今天来看这个设置怎么改。", 0.0, 2.0),
        TranscriptSegment(1, "我们今天来看这个设置怎么改。", 2.1, 4.0),
    ])
    takes = detect_takes(transcript)
    assert takes[1].quality is TakeQuality.DUPLICATE_PHRASE


def test_take_detection_flags_non_speech() -> None:
    transcript = Transcript(segments=[TranscriptSegment(0, "嗯", 0.0, 0.1)])
    assert detect_takes(transcript)[0].quality is TakeQuality.NON_SPEECH


def test_take_detection_does_not_flag_ordinary_deixis_as_filler() -> None:
    """这个/那个 carry meaning in Chinese and must not be mechanically flagged."""
    transcript = Transcript(segments=[
        TranscriptSegment(0, "这个功能我要讲一下。", 0.0, 2.0),
    ])
    assert detect_takes(transcript)[0].quality is TakeQuality.VALID


# ── test_silence_classification ──────────────────────────────────────────


def test_silence_classification_covers_every_class() -> None:
    assert classify_silence(0, 0.2).classification is SilenceClass.BREATH
    assert (
        classify_silence(0, 0.6, preceded_by_sentence_end=True).classification
        is SilenceClass.INTENTIONAL_PAUSE
    )
    assert classify_silence(0, 1.5).classification is SilenceClass.EDITABLE_GAP
    assert classify_silence(0, 3.0).classification is SilenceClass.DEAD_AIR


def test_short_pause_is_always_a_breath() -> None:
    assert classify_silence(0, BREATH_S - 0.01).classification is SilenceClass.BREATH


def test_emotional_pause_is_not_removed_as_silence() -> None:
    """A11: an intentional emotional pause must survive the cut."""
    transcript = Transcript(segments=[
        TranscriptSegment(0, "我一开始也觉得这很难。", 0.0, 2.0),
        TranscriptSegment(1, "后来才明白。", 2.9, 4.0),
    ])
    silences = detect_silences(transcript, total_duration_s=4.2)
    beat = next(s for s in silences if abs(s.start_s - 2.0) < 0.05)
    assert beat.classification is SilenceClass.INTENTIONAL_PAUSE
    plan = build_cut_plan(
        RawFootageSource("s", "/x"), transcript, detect_takes(transcript), silences
    )
    assert (2.0, 2.9) not in [tuple(r) for r in plan.removed_ranges]


def test_dead_air_is_recorded_as_a_removal() -> None:
    transcript = _transcript()
    silences = detect_silences(transcript, total_duration_s=10.8)
    dead = next(s for s in silences if s.classification is SilenceClass.DEAD_AIR)
    plan = build_cut_plan(
        RawFootageSource("s", "/x"), transcript, detect_takes(transcript), silences
    )
    assert any(
        abs(start - dead.start_s) < 0.01 for start, _end in plan.removed_ranges
    )


# ── test_cut_plan ───────────────────────────────────────────────────────


def test_cut_plan_keeps_valid_takes_and_records_a_reason_per_cut() -> None:
    transcript = _transcript()
    takes = detect_takes(transcript)
    silences = detect_silences(transcript, total_duration_s=10.8)
    plan = build_cut_plan(RawFootageSource("s", "/x"), transcript, takes, silences)
    assert plan.entries
    for entry in plan.entries:
        assert entry.reason is CutReason.KEEP
        assert entry.note
        assert entry.confidence > 0


def test_cut_plan_drops_a_restart_with_a_reason() -> None:
    transcript = _transcript()
    takes = detect_takes(transcript)
    silences = detect_silences(transcript, total_duration_s=10.8)
    plan = build_cut_plan(RawFootageSource("s", "/x"), transcript, takes, silences)
    assert CutReason.REMOVE_RESTART in plan.dropped_reasons
    assert any("DROPPED_RESTART" in w for w in plan.warnings)
    assert not any(e.take_index == 3 for e in plan.entries), "the restart must not survive"


def test_cut_plan_output_times_are_contiguous() -> None:
    transcript = _transcript()
    takes = detect_takes(transcript)
    silences = detect_silences(transcript, total_duration_s=10.8)
    plan = build_cut_plan(RawFootageSource("s", "/x"), transcript, takes, silences)
    cursor = 0.0
    for entry in plan.entries:
        assert abs(entry.output_start_s - cursor) < 0.01
        cursor += entry.duration_s


def test_whisper_json_is_parsed_to_word_timestamps() -> None:
    transcript = parse_whisper_json(
        {"text": "你好世界", "segments": [
            {"start": 0.0, "end": 1.0, "text": "你好世界",
             "words": [
                 {"word": "你", "start": 0.0, "end": 0.4, "probability": 0.99},
                 {"word": "好", "start": 0.4, "end": 0.7, "probability": 0.95},
             ]}
        ]},
        language="zh",
    )
    assert transcript.language == "zh"
    assert [w.text for w in transcript.words()] == ["你", "好"]


# ── test_cut_boundary ───────────────────────────────────────────────────


def test_cut_boundary_detects_word_truncation() -> None:
    """A12: a cut inside a word is blocked."""
    transcript = Transcript(segments=[
        TranscriptSegment(0, "测试", 0.0, 1.0,
                          words=[TranscriptWord("测试", 0.0, 0.5)])
    ])
    plan = build_cut_plan(
        RawFootageSource("s", "/x"), transcript,
        detect_takes(transcript), detect_silences(transcript, total_duration_s=1.0),
    )
    assert check_cut_boundaries(plan, transcript) == []
    plan.entries[0].source_start_s = 0.25
    kinds = {i.kind for i in check_cut_boundaries(plan, transcript)}
    assert "WORD_TRUNCATION" in kinds


def test_cut_boundary_detects_an_unexplained_removal() -> None:
    transcript = Transcript(segments=[
        TranscriptSegment(0, "第一句。", 0.0, 1.0),
        TranscriptSegment(1, "第二句。", 5.0, 6.0),
    ])
    plan = build_cut_plan(
        RawFootageSource("s", "/x"), transcript,
        detect_takes(transcript), [], remove_dead_air=False,
    )
    kinds = {i.kind for i in check_cut_boundaries(plan, transcript)}
    assert "UNEXPLAINED_REMOVAL" in kinds


def test_a_fully_explained_plan_has_no_boundary_issue() -> None:
    transcript = _transcript()
    takes = detect_takes(transcript)
    silences = detect_silences(transcript, total_duration_s=10.8)
    plan = build_cut_plan(RawFootageSource("s", "/x"), transcript, takes, silences)
    assert check_cut_boundaries(plan, transcript) == []


# ══ F. Product video ════════════════════════════════════════════════════

def _manifest() -> ProductSurfaceManifest:
    return ProductSurfaceManifest(
        product_id="acme",
        repository_revision="abc123",
        routes=[ProductSurface("/dashboard", renderable=True)],
        states=[ProductDemoState("dash", "dashboard loaded", "/dashboard",
                                 reachable=True, captured_asset_id="ev1")],
    )


def _evidence(source_type: EvidenceSourceType, asset_id: str, **kw) -> EvidenceAsset:
    base = {
        "asset_id": asset_id,
        "source_type": source_type,
        "claim_supported": "Acme Console",
        "entity": "acme",
        "captured_at": "2026-09-01T00:00:00Z",
        "source_uri": "https://acme.dev/dashboard",
    }
    base.update(kw)
    return EvidenceAsset(**base)


# ── test_product_surface_manifest ────────────────────────────────────────


def test_product_surface_manifest_records_discovery() -> None:
    payload = _manifest().to_dict()
    for field in (
        "product_id", "repository_revision", "routes", "components",
        "design_tokens", "verified_surfaces", "renderable_surfaces", "source_refs",
    ):
        assert field in payload, field
    assert payload["read_only"] is True
    assert len(payload["renderable_surfaces"]) == 1


def test_product_surface_manifest_separates_verified_from_renderable() -> None:
    manifest = _manifest()
    manifest.routes.append(ProductSurface("/draft", renderable=False))
    payload = manifest.to_dict()
    assert len(payload["verified_surfaces"]) == 1
    assert len(payload["routes"]) == 2


# ── test_claim_ui_grounding ──────────────────────────────────────────────


def test_claim_ui_grounding_accepts_a_real_capture() -> None:
    plan = build_product_video_plan(plan_id="p", manifest=_manifest(),
                                    claims=["这个产品支持批量导出。"])
    grounding = ground_claim(
        claim="这个产品支持批量导出。", plan=plan, state_id="dash",
        evidence=_evidence(EvidenceSourceType.REAL_INTERFACE, "ev1"), shot_id="s1",
    )
    assert grounding.grounded is True
    assert grounding.tier is ProductEvidenceTier.REAL_RUNNING_UI
    assert grounding.shot_id == "s1"


def test_capability_claim_cannot_ground_on_a_symbolic_visual() -> None:
    plan = build_product_video_plan(plan_id="p", manifest=_manifest(),
                                    claims=["这个产品支持批量导出。"])
    grounding = ground_claim(
        claim="这个产品支持批量导出。", plan=plan,
        evidence=_evidence(EvidenceSourceType.SYMBOLIC, "ev2",
                           provenance={"generated": True, "labelled_as_generated": True}),
        shot_id="s1",
    )
    assert grounding.grounded is False
    assert "CAPABILITY_CLAIM_NOT_BACKED_BY_REAL_UI" in grounding.reason


def test_unreachable_state_blocks_grounding() -> None:
    manifest = _manifest()
    manifest.states[0].reachable = False
    manifest.states[0].unreachable_reason = "requires an enterprise account"
    plan = build_product_video_plan(plan_id="p", manifest=manifest, claims=["x"])
    grounding = ground_claim(
        claim="x", plan=plan, state_id="dash",
        evidence=_evidence(EvidenceSourceType.REAL_INTERFACE, "ev1"),
    )
    assert grounding.grounded is False
    assert "STATE_UNREACHABLE" in grounding.reason


def test_capability_claim_detection() -> None:
    assert is_capability_claim("这个产品支持批量导出。") is True
    assert is_capability_claim("This product supports bulk export.") is True
    assert is_capability_claim("我们来看一眼界面。") is False


def test_product_gate_report_fails_ungrounded_capability_claims() -> None:
    plan = build_product_video_plan(plan_id="p", manifest=_manifest(),
                                    claims=["这个产品支持批量导出。"])
    report = product_gate_report(plan)
    assert report["PRODUCT_CLAIM_GROUNDING"] == "FAIL"
    assert report["FAKE_PRODUCT_UI_AS_REAL"] == 0


def test_product_gate_report_passes_when_grounded() -> None:
    plan = build_product_video_plan(plan_id="p", manifest=_manifest(),
                                    claims=["这个产品支持批量导出。"])
    plan.claims[0] = ground_claim(
        claim="这个产品支持批量导出。", plan=plan, state_id="dash",
        evidence=_evidence(EvidenceSourceType.REAL_INTERFACE, "ev1"),
    )
    assert product_gate_report(plan)["PRODUCT_CLAIM_GROUNDING"] == "PASS"


# ── test_fake_ui_guard ───────────────────────────────────────────────────


def test_fake_ui_guard_rejects_generated_material_as_real() -> None:
    """A14: a generated UI may never be presented as the real product."""
    ok, violations = assert_not_fake_product_ui(
        _evidence(EvidenceSourceType.REAL_INTERFACE, "ev",
                  provenance={"generated": True}),
        ProductEvidenceTier.REAL_RUNNING_UI,
    )
    assert ok is False
    assert any("FAKE_PRODUCT_UI_AS_REAL" in v for v in violations)


def test_fake_ui_guard_rejects_a_mock_uri() -> None:
    ok, violations = assert_not_fake_product_ui(
        _evidence(EvidenceSourceType.OFFICIAL_SCREENSHOT, "ev",
                  source_uri="https://acme.dev/mock-console"),
        ProductEvidenceTier.VERIFIED_SCREENSHOT,
    )
    assert ok is False
    assert any("MOCKED_UI_AS_REAL" in v for v in violations)


def test_fake_ui_guard_rejects_a_real_tier_without_a_capture() -> None:
    ok, _violations = assert_not_fake_product_ui(
        _evidence(EvidenceSourceType.OFFICIAL_SCREENSHOT, "ev", captured_at=""),
        ProductEvidenceTier.VERIFIED_SCREENSHOT,
    )
    assert ok is False


def test_fake_ui_guard_allows_a_labelled_symbolic_fallback() -> None:
    ok, violations = assert_not_fake_product_ui(
        _evidence(EvidenceSourceType.SYMBOLIC, "ev",
                  provenance={"generated": True, "labelled_as_generated": True}),
        ProductEvidenceTier.GENERATED_SYMBOLIC_VISUAL,
    )
    assert ok is True, violations


def test_every_real_tier_is_non_generated() -> None:
    assert ProductEvidenceTier.REAL_RUNNING_UI in REAL_PRODUCT_TIERS
    assert ProductEvidenceTier.GENERATED_SYMBOLIC_VISUAL not in REAL_PRODUCT_TIERS


def test_product_repo_mutation_is_blocked() -> None:
    """A16: a video is not a reason to edit someone's product."""
    manifest = _manifest()
    with pytest.raises(ProductRepoMutationError):
        assert_repo_read_only(manifest, before={"a.py"}, after={"a.py", "b.py"})
    assert_repo_read_only(manifest, before={"a.py"}, after={"a.py"})


def test_product_repo_mutation_requires_explicit_authorisation() -> None:
    manifest = _manifest()
    assert_repo_read_only(manifest, before={"a"}, after={"a", "b"}, authorised=True)


# ══ G. Renderers ════════════════════════════════════════════════════════

# ── test_renderer_registry ───────────────────────────────────────────────


def test_renderer_registry_registers_the_canonical_backends() -> None:
    ids = register_all_renderers(force=True)
    assert set(ids) == {"REMOTION", "HTML_GSAP", "FFMPEG"}


def test_renderer_registry_is_idempotent() -> None:
    first = register_all_renderers(force=True)
    second = register_all_renderers()
    assert sorted(first) == sorted(second)


def test_renderer_registry_is_not_the_provider_registry() -> None:
    """Renderers execute media; providers call models. Different authorities."""
    from hevi.renderers import base

    source = Path(base.__file__).read_text(encoding="utf-8")
    assert "register_provider" not in source
    assert "class ProviderRegistry" not in source


# ── test_renderer_capability ─────────────────────────────────────────────


def test_renderer_capability_covers_every_declared_capability() -> None:
    matrix = renderer_capability_matrix()
    assert set(matrix) == {"REMOTION", "HTML_GSAP", "FFMPEG"}
    declared = {c for caps in matrix.values() for c in caps}
    assert {
        "TEXT", "SVG", "HTML", "CSS", "3D", "VIDEO", "AUDIO", "CANVAS",
        "FRAME_EXACT", "TRANSPARENCY",
    } <= declared | {"TRANSPARENCY"}


def test_html_backend_declares_canvas_and_frame_exact() -> None:
    renderer = HtmlGsapRenderer()
    assert renderer.supports(RendererCapability.CANVAS)
    assert renderer.supports(RendererCapability.FRAME_EXACT)
    assert renderer.frame_deterministic is True


def test_remotion_backend_is_not_claimed_frame_exact() -> None:
    """Remotion renders on wall-clock time; claiming otherwise would be false."""
    assert RemotionRenderer.frame_deterministic is False


# ── test_renderer_capability selection ───────────────────────────────────


def test_renderer_selection_prefers_the_declared_capability() -> None:
    decision = select_renderer(
        [FfmpegRenderer(), HtmlGsapRenderer()],
        SelectionRequirement(required_capabilities=[RendererCapability.CANVAS]),
    )
    assert decision.renderer is RendererId.HTML_GSAP
    assert "CAPABILITY_MATCH" in decision.reason


def test_renderer_capability_outranks_profile_preference() -> None:
    """A profile preference cannot override a stated capability requirement."""
    decision = select_renderer(
        [FfmpegRenderer(), HtmlGsapRenderer()],
        SelectionRequirement(
            required_capabilities=[RendererCapability.CANVAS],
            preferred_renderers=[RendererId.FFMPEG],
        ),
    )
    assert decision.renderer is RendererId.HTML_GSAP
    assert "FFMPEG" in decision.rejected


def test_renderer_selection_honours_profile_preference_when_capable() -> None:
    decision = select_renderer(
        [HtmlGsapRenderer(), FfmpegRenderer()],
        SelectionRequirement(
            required_capabilities=[RendererCapability.VIDEO],
            preferred_renderers=[RendererId.FFMPEG],
        ),
    )
    assert decision.renderer is RendererId.FFMPEG
    assert decision.reason.startswith("PROFILE_PREFERRED")


def test_renderer_selection_is_deterministic_not_random() -> None:
    requirement = SelectionRequirement(
        required_capabilities=[RendererCapability.VIDEO, RendererCapability.AUDIO]
    )
    picks = {
        select_renderer([HtmlGsapRenderer(), FfmpegRenderer()], requirement).renderer
        for _ in range(8)
    }
    assert len(picks) == 1


def test_renderer_selection_rejects_an_incapable_backend() -> None:
    decision = select_renderer(
        [FfmpegRenderer()],
        SelectionRequirement(required_capabilities=[RendererCapability.THREE_D]),
    )
    assert decision.renderer is None
    assert "NO_CAPABLE_RENDERER" in decision.reason
    assert "FFMPEG" in decision.rejected


def test_ffmpeg_refuses_semantic_motion() -> None:
    plan = RenderPlan(shot_id="s", duration_s=2.0, motion_purposes=["REVEAL_STRUCTURE"])
    assert plan_requires_semantic_motion(plan) == ["REVEAL_STRUCTURE"]
    result = FfmpegRenderer().render(plan, Path("/tmp/opencode/p52ff"))
    assert result.outcome is RenderOutcome.REJECTED
    assert "FFMPEG_CANNOT_EXPRESS_SEMANTIC_MOTION" in result.reason


def test_renderer_equivalence_rejects_a_duration_change() -> None:
    """A19: a backend must not silently change the shot's length."""
    plan = RenderPlan(shot_id="s", duration_s=2.0, fps=30)
    ok, violations = verify_equivalence(
        plan, RenderResult(shot_id="s", renderer="X", duration_s=5.0)
    )
    assert ok is False
    assert any("DURATION_CHANGED" in v for v in violations)
    with pytest.raises(RenderContractViolation):
        enforce_equivalence(plan, RenderResult(shot_id="s", renderer="X", duration_s=5.0))


def test_renderer_equivalence_tolerates_container_padding() -> None:
    plan = RenderPlan(shot_id="s", duration_s=4.0, fps=30)
    ok, _ = verify_equivalence(plan, RenderResult(shot_id="s", renderer="X", duration_s=4.05))
    assert ok is True


def test_renderer_equivalence_rejects_dropped_evidence() -> None:
    plan = RenderPlan(shot_id="s", duration_s=2.0, required_evidence=["ev.png"],
                      extra={"evidence_present": False})
    ok, violations = verify_equivalence(plan, RenderResult(shot_id="s", renderer="X", duration_s=2.0))
    assert ok is False
    assert "REQUIRED_EVIDENCE_DROPPED" in violations


# ── test_html_sandbox ────────────────────────────────────────────────────


def test_html_sandbox_scrubs_the_environment() -> None:
    """A17: a host secret must not be readable from inside a render."""
    env = scrubbed_environment()
    assert set(env) <= {"PATH", "HOME", "LANG", "TZ", "TMPDIR", "DISPLAY"}
    os.environ["HEVI_TEST_FAKE_SECRET"] = "s3cret"
    try:
        assert "HEVI_TEST_FAKE_SECRET" not in scrubbed_environment()
    finally:
        del os.environ["HEVI_TEST_FAKE_SECRET"]


def test_html_sandbox_refuses_path_escape() -> None:
    """A18: a render may not read outside its sandbox."""
    with pytest.raises(PermissionError, match="PATH_ESCAPE"):
        assert_sandbox_path(Path("/etc/passwd"), Path("/tmp/sandbox"))
    with pytest.raises(PermissionError, match="PATH_ESCAPE"):
        assert_sandbox_path(Path("/tmp/sandbox/../secrets"), Path("/tmp/sandbox"))
    assert_sandbox_path(Path("/tmp/sandbox/ok.html"), Path("/tmp/sandbox"))


def test_html_sandbox_refuses_network_schemes() -> None:
    for url in ("https://evil.example/x", "http://a/b", "file:///etc/passwd"):
        with pytest.raises(PermissionError):
            assert_no_unsafe_url(url)
    for url in ("data:image/png;base64,AAA", "about:blank"):
        assert_no_unsafe_url(url)


@pytest.mark.slow
def test_html_sandbox_actually_blocks_a_real_attack(tmp_path: Path) -> None:
    """Drive a hostile page through the real capture path and confirm it is fenced."""
    if not HtmlGsapRenderer().detect():
        pytest.skip("HTML backend unavailable")
    from hevi.renderers.html_gsap import _resolve_playwright_module

    if not _resolve_playwright_module():
        pytest.skip("no node playwright driver")
    probe_dir = tmp_path / "sandbox"
    probe_dir.mkdir()
    page = probe_dir / "probe.html"
    page.write_text(
        "<!doctype html><html><body><script>"
        "const o={net:[],fs:[],cp:[]};"
        "try{const r=require('fs');o.fs.push('fs-ok:'+!!r);}catch(e){o.fs.push('fs-blocked');}"
        "try{const r=require('child_process');o.cp.push('cp-ok:'+!!r);}catch(e){o.cp.push('cp-blocked');}"
        "try{o.net.push('env:'+String(typeof process!=='undefined'?Object.keys(process.env||{}).length:'no-process'));}catch(e){}"
        "fetch('https://example.com/steal').then(()=>o.net.push('fetch-ok')).catch(()=>o.net.push('fetch-blocked'));"
        "document.title=JSON.stringify(o);"
        "</script></body></html>",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", "-e", f"""
const {{chromium}}=require('playwright-core');
(async()=>{{
  const blocked=[];
  const b=await chromium.launch({{args:['--no-sandbox']}});
  const c=await b.newContext({{offline:true,viewport:{{width:320,height:180}}}});
  await c.route('**/*',r=>{{const u=r.request().url();
    if(u.startsWith('file://')||u.startsWith('data:')||u.startsWith('about:')) return r.continue();
    blocked.push(u); return r.abort();}});
  const p=await c.newPage();
  await p.goto('{(probe_dir / 'probe.html').as_uri()}',{{waitUntil:'load'}});
  await p.waitForTimeout(1200);
  console.log(JSON.stringify({{title:await p.title(),blocked:blocked}}));
  await b.close();
}})();
"""],
        capture_output=True, text=True, timeout=180, check=False,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(probe_dir),
             "NODE_PATH": _resolve_playwright_module(),
             # The browser binary is a *tool* path, like NODE_PATH. Without it the
             # scrubbed HOME means playwright cannot find its own browser.
             "PLAYWRIGHT_BROWSERS_PATH": os.path.expanduser("~/.cache/ms-playwright")},
        cwd=str(probe_dir),
    )
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    assert lines, f"sandbox probe produced no output: {result.stderr[-300:]}"
    payload = json.loads(lines[-1])
    assert "fs-blocked" in payload["title"]
    assert "cp-blocked" in payload["title"]
    assert "no-process" in payload["title"]
    assert any("example.com" in url for url in payload["blocked"])


# ── test_frame_determinism ───────────────────────────────────────────────


@pytest.mark.slow
def test_frame_determinism_produces_identical_bytes(tmp_path: Path) -> None:
    if not HtmlGsapRenderer().detect():
        pytest.skip("HTML backend unavailable")
    from hevi.renderers.html_gsap import _resolve_playwright_module

    if not _resolve_playwright_module():
        pytest.skip("no node playwright driver")
    renderer = HtmlGsapRenderer()
    plan = RenderPlan(shot_id="det", duration_s=1.2, caption_text="确定性", extra={"title": "T"})
    first = renderer.render(plan, tmp_path / "a")
    second = renderer.render(plan, tmp_path / "b")
    assert first.outcome is RenderOutcome.OK
    assert first.content_hash == second.content_hash
    assert first.frame_deterministic is True
    assert first.sandbox_report["clean"] is True


@pytest.mark.slow
def test_frame_determinism_is_content_sensitive(tmp_path: Path) -> None:
    if not HtmlGsapRenderer().detect():
        pytest.skip("HTML backend unavailable")
    from hevi.renderers.html_gsap import _resolve_playwright_module

    if not _resolve_playwright_module():
        pytest.skip("no node playwright driver")
    renderer = HtmlGsapRenderer()
    a = renderer.render(
        RenderPlan(shot_id="a", duration_s=1.2, caption_text="第一段"), tmp_path / "a"
    )
    b = renderer.render(
        RenderPlan(shot_id="b", duration_s=1.2, caption_text="第二段"), tmp_path / "b"
    )
    assert a.content_hash != b.content_hash


@pytest.mark.slow
def test_html_backend_renders_a_real_video(tmp_path: Path) -> None:
    if not HtmlGsapRenderer().detect():
        pytest.skip("HTML backend unavailable")
    result = HtmlGsapRenderer().render(
        RenderPlan(shot_id="real", duration_s=1.5, caption_text="真实渲染",
                   semantic_intent="intro"),
        tmp_path,
    )
    assert result.outcome is RenderOutcome.OK
    assert Path(result.output_path).is_file()
    assert abs(result.duration_s - 1.5) < 0.1


# ══ H. Editable backends ════════════════════════════════════════════════

def _manifest_elements(tmp_path: Path) -> list[TrackElement]:
    video = tmp_path / "bg.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=teal:s=160x90:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, capture_output=True,
    )
    audio = tmp_path / "voice.m4a"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", str(audio)],
        check=True, capture_output=True,
    )
    srt = tmp_path / "captions.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    return [
        TrackElement("bg", "BACKGROUND", "CONTEXTUAL_BROLL", 0, 1000, str(video), editable_properties={}),
        TrackElement("ev", "EVIDENCE", "EVIDENCE_DOMINANT", 0, 1000, str(video), editable_properties={}),
        TrackElement("cap", "CAPTIONS", "CAPTION", 0, 1000, str(srt),
                     editable_properties={"text": "你好"}),
        TrackElement("voi", "VOICE", "NARRATION", 0, 1000, str(audio),
                     editable_properties={"volume": 1.0}),
    ]


def _project_manifest(tmp_path: Path) -> EditableProjectManifest:
    return EditableProjectManifest(
        project_id="p52 demo", duration_ms=1000, elements=_manifest_elements(tmp_path)
    )


# ── test_editable_backend ────────────────────────────────────────────────


def test_editable_backend_registers_both_projections() -> None:
    ids = register_all_backends(force=True)
    assert ids == ["CAPCUT_CLI", "INTERNAL_JIANYING"]


def test_every_canonical_layer_maps_to_a_capcut_track() -> None:
    assert set(LAYER_TO_TRACK) == {
        "BACKGROUND", "SPEAKER", "EVIDENCE", "OVERLAY",
        "CAPTIONS", "VOICE", "BGM", "SFX",
    }
    assert LAYER_TO_TRACK["CAPTIONS"] == "text"
    assert LAYER_TO_TRACK["VOICE"] == "audio"
    assert LAYER_TO_TRACK["BACKGROUND"] == "video"


def test_manifest_is_the_authority_not_the_backend() -> None:
    manifest = EditableProjectManifest(project_id="p", duration_ms=1000)
    payload = manifest.to_dict()
    assert payload["backend_hint"] == ""
    assert payload["element_count"] == 0


def test_unavailable_capcut_backend_reports_unavailable(tmp_path: Path) -> None:
    backend = CapCutCliBackend(binary="definitely-not-installed-xyz")
    if backend.detect():
        pytest.skip("binary unexpectedly present")
    projection = backend.project(_project_manifest(tmp_path), tmp_path / "out")
    assert projection.outcome is ProjectOutcome.UNAVAILABLE
    assert "not found" in projection.reason


def test_jianying_backend_projects_a_real_draft(tmp_path: Path) -> None:
    register_all_backends(force=True)
    manifest = _project_manifest(tmp_path)
    manifest.project_id = "jy demo"
    projection = project_manifest(
        manifest, tmp_path / "jy_a", EditableBackendId.INTERNAL_JIANYING
    )
    assert projection.outcome is ProjectOutcome.OK
    assert projection.track_count >= 3
    assert Path(projection.project_path).is_dir()


# ── test_capcut_security ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["a;rm -rf /", "../../etc/passwd", "x$(whoami)", "", "n" * 200, "a|b", "a`b`", "~/x"],
)
def test_capcut_rejects_malicious_filenames(name: str) -> None:
    """A20: a hostile filename is a filename, never a command."""
    with pytest.raises(CapCutSecurityError):
        assert_safe_name(name)


def test_capcut_accepts_a_legitimate_project_name() -> None:
    assert assert_safe_name("p52 demo") == "p52 demo"
    assert assert_safe_name("video-01_v2") == "video-01_v2"


def test_capcut_rejects_path_traversal() -> None:
    """A21: a path outside the project root is refused."""
    with pytest.raises(CapCutSecurityError, match="PATH_ESCAPE"):
        assert_contained(Path("/etc/passwd"), Path("/tmp/project"))
    with pytest.raises(CapCutSecurityError, match="PATH_ESCAPE"):
        assert_contained(Path("/tmp/project/../secrets"), Path("/tmp/project"))
    assert assert_contained(Path("/tmp/project/ok.json"), Path("/tmp/project"))


def test_capcut_strips_device_identifiers() -> None:
    payload = {
        "device_id": "abc", "hostname": "h", "username": "u", "uuid": "x",
        "install_id": "y", "project": "p",
        "nested": {"mac_address": "m", "keep": 1},
    }
    cleaned = scrub_device_identifiers(payload)
    assert cleaned == {"project": "p", "nested": {"keep": 1}}


def test_capcut_version_is_pinned_not_floating() -> None:
    assert EXPECTED_VERSION == "0.26.0"
    assert len(EXPECTED_REVISION) == 12
    backend = CapCutCliBackend()
    assert backend.version == EXPECTED_VERSION
    assert backend.revision == EXPECTED_REVISION
    assert "latest" not in backend.version.lower()


def test_capcut_never_uses_a_shell() -> None:
    source = Path(CapCutCliBackend.__module__.replace(".", "/") + ".py")
    source = Path(__import__(CapCutCliBackend.__module__, fromlist=["x"]).__file__ or "")
    text = source.read_text(encoding="utf-8")
    assert "shell=True" not in text
    assert "os.system" not in text


def test_capcut_never_writes_credentials(tmp_path: Path) -> None:
    text = Path(capcut_module_path()).read_text(encoding="utf-8")
    for secret_marker in ("FAL_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "JWT_SECRET"):
        assert secret_marker not in text


def capcut_module_path() -> str:
    import hevi.editable.capcut_cli as module

    return str(module.__file__)


# ── test_draft_lint ──────────────────────────────────────────────────────


def test_draft_lint_passes_a_well_formed_manifest(tmp_path: Path) -> None:
    assert lint_manifest(_project_manifest(tmp_path), project_root=tmp_path) == []


def test_draft_lint_catches_a_missing_material(tmp_path: Path) -> None:
    manifest = _project_manifest(tmp_path)
    manifest.elements[0].source_artifact = "/definitely/missing.mp4"
    errors = lint_manifest(manifest, project_root=tmp_path)
    assert any("MISSING_MATERIAL_FILE" in e for e in errors)


def test_draft_lint_catches_a_negative_duration(tmp_path: Path) -> None:
    manifest = _project_manifest(tmp_path)
    manifest.elements[0].end_ms = 0
    assert any(
        "NON_POSITIVE_DURATION" in e for e in lint_manifest(manifest, project_root=tmp_path)
    )


def test_draft_lint_catches_an_element_past_the_timeline(tmp_path: Path) -> None:
    manifest = _project_manifest(tmp_path)
    manifest.elements[0].end_ms = 5000
    assert any(
        "ELEMENT_BEYOND_TIMELINE" in e for e in lint_manifest(manifest, project_root=tmp_path)
    )


def test_draft_lint_catches_a_missing_semantic_role(tmp_path: Path) -> None:
    manifest = _project_manifest(tmp_path)
    manifest.elements[0].semantic_role = ""
    assert any(
        "MISSING_SEMANTIC_ROLE" in e for e in lint_manifest(manifest, project_root=tmp_path)
    )


def test_draft_lint_catches_an_invalid_source_range(tmp_path: Path) -> None:
    manifest = _project_manifest(tmp_path)
    manifest.elements[0].source_in_ms = 900
    manifest.elements[0].source_out_ms = 100
    assert any(
        "INVALID_SOURCE_RANGE" in e for e in lint_manifest(manifest, project_root=tmp_path)
    )


def test_draft_lint_catches_a_caption_role_mismatch(tmp_path: Path) -> None:
    manifest = _project_manifest(tmp_path)
    caption = next(e for e in manifest.elements if e.layer == "CAPTIONS")
    caption.semantic_role = "NARRATION"
    assert any(
        "CAPTION_LAYER_ROLE_MISMATCH" in e for e in lint_manifest(manifest, project_root=tmp_path)
    )


def test_backend_refuses_to_project_a_failing_lint(tmp_path: Path) -> None:
    register_all_backends(force=True)
    manifest = _project_manifest(tmp_path)
    manifest.project_id = "lint demo"
    manifest.duration_ms = 0
    projection = project_manifest(
        manifest, tmp_path / "jy_lint", EditableBackendId.INTERNAL_JIANYING
    )
    assert projection.outcome is ProjectOutcome.LINT_FAILED
    assert projection.lint_errors


# ── test_backend_differential ────────────────────────────────────────────


def test_backend_differential_needs_two_backends() -> None:
    report = compare_projections(
        EditableProjectManifest(project_id="p", duration_ms=1000), []
    )
    assert report.ok is False


def test_backend_differential_agrees_on_manifest_dimensions(tmp_path: Path) -> None:
    if not CapCutCliBackend().detect():
        pytest.skip("capcut-cli not installed")
    register_all_backends(force=True)
    manifest = _project_manifest(tmp_path)
    manifest.project_id = "diff demo"
    a = project_manifest(manifest, tmp_path / "jy_d", EditableBackendId.INTERNAL_JIANYING)
    b = project_manifest(manifest, tmp_path / "cc_d", EditableBackendId.CAPCUT_CLI)
    assert a.outcome is ProjectOutcome.OK, a.reason
    assert b.outcome is ProjectOutcome.OK, b.reason
    report = compare_projections(manifest, [a, b])
    assert report.shared["duration_ms"] == 1000
    assert report.shared["semantic_layers"] == 4
    assert report.ok is True, report.divergences
    # Physical track counts are reported, not required to match: the two tools
    # group clips differently.
    assert set(report.track_counts) == {"INTERNAL_JIANYING", "CAPCUT_CLI"}


def test_backend_differential_reports_a_material_shortfall(tmp_path: Path) -> None:
    manifest = _project_manifest(tmp_path)
    layers = sorted({e.layer for e in manifest.elements})
    thin = BackendProjection("THIN", track_count=3, material_count=0, duration_ms=1000,
                             layer_coverage=layers)
    other = BackendProjection("FAT", track_count=3, material_count=9, duration_ms=1000,
                              layer_coverage=layers)
    report = compare_projections(manifest, [thin, other])
    assert report.ok is False
    assert any("MATERIALS_BELOW_MANIFEST" in d for d in report.divergences)


# ── test_structural_roundtrip ────────────────────────────────────────────


def test_structural_round_trip_passes_for_jianying(tmp_path: Path) -> None:
    register_all_backends(force=True)
    manifest = _project_manifest(tmp_path)
    manifest.project_id = "rt demo"
    projection = project_manifest(
        manifest, tmp_path / "jy_rt", EditableBackendId.INTERNAL_JIANYING
    )
    ok, errors = structural_round_trip(manifest, projection)
    assert ok is True, errors


def test_structural_round_trip_fails_without_a_timeline() -> None:
    ok, errors = structural_round_trip(
        EditableProjectManifest(project_id="p", duration_ms=1000),
        BackendProjection("X", timeline_path=""),
    )
    assert ok is False
    assert errors == ["PROJECTION_WITHOUT_TIMELINE"]


def test_structural_round_trip_rejects_an_unreadable_timeline(tmp_path: Path) -> None:
    path = tmp_path / "draft_content.json"
    path.write_text("{not json", encoding="utf-8")
    ok, errors = structural_round_trip(
        EditableProjectManifest(project_id="p", duration_ms=1000),
        BackendProjection("X", timeline_path=str(path)),
    )
    assert ok is False
    assert any("TIMELINE_UNREADABLE" in e for e in errors)


def test_structural_round_trip_rejects_an_empty_projection(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"elements": []}), encoding="utf-8")
    ok, errors = structural_round_trip(
        EditableProjectManifest(project_id="p", duration_ms=1000),
        BackendProjection("X", timeline_path=str(path)),
    )
    assert ok is False
    assert any("PROJECTION_HAS_NO_ELEMENTS" in e for e in errors)


# ── test_flattening_truth ────────────────────────────────────────────────


def test_flattening_truth_marks_baked_captions_as_flattened() -> None:
    """A23: a caption baked into pixels is not natively editable."""
    element = TrackElement("cap", "CAPTIONS", "CAPTION", 0, 1000, "/a.mp4")
    assert classify_editability(element) is EditabilityLevel.FLATTENED_MEDIA


def test_flattening_truth_marks_evidence_as_natively_editable() -> None:
    element = TrackElement("ev", "EVIDENCE", "EVIDENCE_DOMINANT", 0, 1000, "/a.png")
    assert classify_editability(element) is EditabilityLevel.NATIVE_EDITABLE


def test_flattening_truth_is_reported_in_the_projection(tmp_path: Path) -> None:
    register_all_backends(force=True)
    manifest = _project_manifest(tmp_path)
    manifest.project_id = "flat demo"
    projection = project_manifest(
        manifest, tmp_path / "jy_flat", EditableBackendId.INTERNAL_JIANYING
    )
    assert "cap" in projection.flattened
    assert "bg" not in projection.flattened


def test_manifest_reports_editability_per_element(tmp_path: Path) -> None:
    manifest = _project_manifest(tmp_path)
    levels = {e.editability.value for e in manifest.elements}
    assert levels == {EditabilityLevel.NATIVE_EDITABLE.value}


# ══ I. Pocket TTS ═══════════════════════════════════════════════════════

# ── test_pocket_tts_capability ───────────────────────────────────────────


def test_pocket_tts_declares_its_capabilities() -> None:
    capability = probe()
    assert set(capability.capabilities) == {
        "LOCAL_TTS", "STREAMING_TTS", "VOICE_CLONING"
    }
    assert capability.cpu_only is True


def test_pocket_tts_declares_english_and_excludes_chinese() -> None:
    capability = probe()
    assert capability.language_status("en-US") is LanguageSupport.SUPPORTED
    assert capability.language_status("zh-CN") is LanguageSupport.UNSUPPORTED
    assert "zh" not in [l.split("-")[0] for l in capability.supported_languages]
    assert DECLARED_LANGUAGES


def test_pocket_tts_refuses_chinese_loudly() -> None:
    """A24: an unsupported language must fail, never fall through silently."""
    capability = probe()
    with pytest.raises(PocketTtsLanguageError, match="CHINESE_TTS=UNSUPPORTED"):
        synthesise(
            TtsRequest(text="你好", language="zh-CN", output_path="/tmp/x.wav"), capability
        )


def test_pocket_tts_reports_unknown_language_as_unknown() -> None:
    assert probe().language_status("") is LanguageSupport.UNKNOWN


def test_pocket_tts_gate_report_never_claims_silent_fallback() -> None:
    report = tts_gate_report()
    assert report["SILENT_LANGUAGE_FALLBACK"] == 0
    assert report["CHINESE_TTS"] == "UNSUPPORTED"
    assert report["POCKET_TTS_PROVIDER"] in ("PASS", "NOT_ADOPTED")


def test_pocket_tts_does_not_resolve_the_volcano_blocker() -> None:
    """§78: a local English TTS changes nothing about P5's Chinese blocker."""
    report = tts_gate_report()
    assert report["CHINESE_TTS"] == "UNSUPPORTED"
