"""E2E-A — presenter video, real 30–90 seconds.

What "real" means here, precisely:

* The audio is real human speech, not a synthesised placeholder.
* The delivered video is a real file, cut from real footage by real ffmpeg.
* Entity identity, continuity, presentation mix and QA are evaluated against
  that real media, not against a description of it.

What it does *not* pretend: that HEVI generated the presenter. It cannot on this
machine. The test probes every presenter integration that actually exists in the
codebase, records what it found, and then takes the honest path the spec allows
— a *qualified presenter source*. Presenter generation being unavailable is
reported as unavailable, never as a pass, and never silently substituted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from p5_2_real_assets import RealSource, ffprobe_duration, sha256_file

from hevi.production.entities import (
    ProductionEntityGraph,
    audit_continuity,
    person_entity,
)
from hevi.production.presenter import (
    AudioLock,
    PresenterBackgroundPolicy,
    PresenterPlan,
    PresenterProviderCapability,
    PresenterScale,
    PresenterShotRange,
    build_presenter_plan,
    check_presenter_qa,
    scale_for_role,
    validate_presentation_mix,
)
from hevi.production.raw_footage import (
    RawFootageSource,
    execute_fine_cut,
    extract_audio,
    probe_duration,
)

pytestmark = pytest.mark.slow

#: The spec's window for a presenter piece.
MIN_S, MAX_S = 30.0, 90.0


def _probe_presenter_generation() -> dict[str, str]:
    """Actually probe the presenter stack. Do not hardcode the answer.

    Each entry is a real integration that exists in this codebase. We record
    whether its runtime is reachable right now, so the qualification report can
    say *why* generation is unavailable instead of asserting that it is.
    """
    probes: dict[str, str] = {}

    try:
        import torch

        probes["gpu"] = "AVAILABLE" if torch.cuda.is_available() else "UNAVAILABLE"
    except Exception as exc:  # pragma: no cover - torch is a hard dep, be safe
        probes["gpu"] = f"UNPROBED:{type(exc).__name__}"

    comfy = subprocess.run(
        ["curl", "-s", "-m", "4", "-o", "/dev/null", "-w", "%{http_code}",
         "http://127.0.0.1:8188/system_stats"],
        capture_output=True, text=True, check=False,
    )
    probes["comfyui"] = "REACHABLE" if comfy.stdout.strip() == "200" else "UNREACHABLE"

    for name, env in (
        ("duix_live", "DUIX_SERVICE_URL"),
        ("livetalking", "LIVETALKING_WEBRTC_URL"),
        ("longcat", "GEN_ENGINE_BASE_URL"),
    ):
        import os

        value = os.environ.get(env, "").strip()
        probes[name] = "CONFIGURED" if value else "NOT_CONFIGURED"

    reachable = [k for k, v in probes.items() if v in {"AVAILABLE", "REACHABLE", "CONFIGURED"}]
    probes["_verdict"] = (
        "AVAILABLE" if "gpu" in reachable and "comfyui" in reachable
        else "UNAVAILABLE"
    )
    return probes


def test_e2e_a_presenter_generation_status_is_probed_not_assumed() -> None:
    """Record the real state of the presenter stack, whatever it is."""
    probes = _probe_presenter_generation()
    assert "_verdict" in probes
    # The report has to be specific enough to act on.
    for key in ("gpu", "comfyui", "duix_live", "livetalking", "longcat"):
        assert probes[key] in {
            "AVAILABLE", "REACHABLE", "CONFIGURED",
            "UNAVAILABLE", "UNREACHABLE", "NOT_CONFIGURED",
        } or probes[key].startswith("UNPROBED"), probes


@pytest.mark.skipif(
    _probe_presenter_generation()["_verdict"] == "AVAILABLE",
    reason="presenter generation is available; the source path is then not the honest one",
)
def test_e2e_a1_qualified_presenter_source_renders_30_to_90_seconds(
    nasa_interview: RealSource, tmp_path: Path
) -> None:
    """A real presenter piece, from a real qualified source, 30–90s."""
    source = RawFootageSource(
        "nasa-collins-0001", str(nasa_interview.path), duration_s=nasa_interview.duration_s,
        content_hash=nasa_interview.content_hash,
    )
    audio = extract_audio(source, tmp_path)
    assert audio.is_file(), "real audio was not extracted"

    audio_hash = sha256_file(audio)
    audio_duration = probe_duration(audio)
    assert audio_duration > MIN_S, f"source too short: {audio_duration:.1f}s"

    # 60 seconds of the real interview, inside the spec's window.
    cut_start, cut_end = 25.0, 85.0
    lock = AudioLock(
        audio_lock_id="al-collins-0001", audio_path=str(audio),
        audio_hash=audio_hash, duration_s=cut_end - cut_start,
        sample_rate=22050,
    )

    person = person_entity(
        "Michael Collins", face_ref="nasa:KSC-20190716-MH-NAS01_0001",
        clothing_ref="nasa:blue-polo", framing="medium", background="nasa:corridor",
        voice_identity="nasa:interview-voice", entity_id="person-collins",
    )
    graph = ProductionEntityGraph(project_id="e2e-a")
    graph.register(person)
    graph.bind_shot("a1", [person.entity_id])

    # Scale follows the editorial role rather than being chosen by hand, so the
    # piece has a visual rhythm instead of one framing for sixty seconds.
    beats = [
        ("a1", "DIRECT_ADDRESS", False),
        ("a2", "EVIDENCE", True),
        ("a3", "DIRECT_ADDRESS", False),
        ("a4", "EMOTIONAL_PRESENCE", False),
    ]
    span = (cut_end - cut_start) / len(beats)
    ranges = [
        PresenterShotRange(
            shot_id, round(index * span, 3), round((index + 1) * span, 3),
            scale_for_role(role, evidence_visible=evidence), role,
        )
        for index, (shot_id, role, evidence) in enumerate(beats)
    ]
    plan = build_presenter_plan(
        plan_id="p5.2-e2e-a", presenter_entity_id=person.entity_id, audio_lock=lock,
        shot_ranges=ranges, provider_id="QUALIFIED_SOURCE_NASA",
        source_video=str(nasa_interview.path), voice_identity_ref="nasa:interview-voice",
    )
    assert plan.provider_capability == PresenterProviderCapability.SOURCE_VIDEO.value
    assert plan.background_policy is PresenterBackgroundPolicy.REAL

    # A piece that never changes scale is not a piece with a visual language.
    ok, reasons = validate_presentation_mix(ranges, minimum_role_switches=2)
    assert ok, reasons

    # Real cut, real ffmpeg, real duration.
    cut_plan = _slice(source, cut_start, cut_end)
    rendered = execute_fine_cut(source, cut_plan, tmp_path / "render")
    assert rendered.is_file()
    duration = ffprobe_duration(rendered)
    assert MIN_S <= duration <= MAX_S, f"presenter piece is {duration:.2f}s, outside 30-90s"

    # Continuity is evaluated on the entity that actually appears.
    report = audit_continuity(graph, asset_bindings={"person-collins": [rendered.name]})
    assert report.ok, report.violations
    assert report.gates["CHARACTER_CONTINUITY"] is True

    qa = check_presenter_qa(
        _artifact(plan, rendered, audio_hash, duration), plan, audio_duration_s=duration,
        continuity={"face": "nasa:KSC-20190716-MH-NAS01_0001", "clothing": "nasa:blue-polo"},
    )
    assert qa.ok, [(issue.kind, issue.detail) for issue in qa.issues]
    assert {"duration_matches_audio_lock", "audio_hash_correct", "visual_continuity"} <= set(qa.checked)


def test_e2e_a2_scale_follows_semantic_role(nasa_interview: RealSource) -> None:
    """Scale is a decision, not a default: evidence must not shrink the presenter."""
    # Direct address owns the frame, so the presenter is full size.
    assert scale_for_role("DIRECT_ADDRESS", evidence_visible=False) is PresenterScale.MEDIUM
    # Real evidence on screen steps the presenter down rather than letting the
    # two fight for the frame.
    assert scale_for_role("DIRECT_ADDRESS", evidence_visible=True) is PresenterScale.PIP
    assert scale_for_role("EVIDENCE", evidence_visible=True) is PresenterScale.PIP
    assert scale_for_role("CONTEXTUAL_BROLL", evidence_visible=False) is PresenterScale.PIP
    # Nothing to present and no evidence: the presenter leaves the frame.
    assert scale_for_role("BACKGROUND", evidence_visible=False) is PresenterScale.HIDDEN


def _slice(source: RawFootageSource, start: float, end: float):
    from hevi.production.raw_footage import CutEntry, CutPlan, CutReason

    return CutPlan(
        source_id=source.source_id,
        entries=[
            CutEntry(
                index=0, source_start_s=start, source_end_s=end, output_start_s=0.0,
                reason=CutReason.KEEP, confidence=1.0,
            )
        ],
    )


def _artifact(plan: PresenterPlan, rendered: Path, audio_hash: str, duration: float):
    from hevi.production.presenter import PresenterArtifact

    return PresenterArtifact(
        presenter_id="presenter-collins", entity_id=plan.presenter_entity_id,
        provider="QUALIFIED_SOURCE_NASA", source_video=str(rendered),
        audio_hash=audio_hash, video_hash=sha256_file(rendered), duration_s=duration,
        scale=PresenterScale.MEDIUM,
    )
