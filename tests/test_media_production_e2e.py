"""P4 media production E2E (E2E-1..E2E-5).

Composes the canonical 3O media transactions (omodul) through HEVI Layer4
authorities, using real runtimes (FFmpeg / faster-whisper / Remotion) where the
environment provides them and explicit contract assertions where it does not.

No internal function is mocked. Provider/port fakes exist only where production
has a port (V2V provider registry entry).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from obase.ffmpeg import run as ffmpeg_run
from obase.provider_registry import ProviderRegistry
from omodul._base_config import BaseConfig
from omodul.media_timeline_assemble import media_timeline_assemble
from omodul.previz_generate import previz_generate
from omodul.previz_guided_v2v_render import previz_guided_v2v_render
from omodul.remotion_template_render import remotion_template_render
from oprim import ffmpeg_probe_duration

REPO_ROOT = Path(__file__).parents[1]
REMOTION_ROOT = REPO_ROOT / "hevi-remotion"
_WHISPER_MODEL = Path.home() / "models/faster-whisper-large-v3-turbo"

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
_HAS_BLENDER = shutil.which("blender") is not None
_HAS_REMOTION = (REMOTION_ROOT / "node_modules" / ".bin" / "remotion").is_file()
try:
    import faster_whisper  # noqa: F401

    _HAS_FW = True
except ImportError:
    _HAS_FW = False


async def _color_clip(path: Path, *, color: str, seconds: float, fps: int = 24) -> Path:
    await ffmpeg_run(
        args=[
            "-f", "lavfi", "-i", f"color=c={color}:s=320x240:r={fps}:d={seconds}",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        expected_output=path,
    )
    return path


def _assert_transaction_contract(result: dict[str, Any], *, expected_status: str) -> None:
    assert result["status"] == expected_status
    assert "error" in result
    assert isinstance(result["_enabled_pillars"], list)
    assert len(result["_enabled_pillars"]) >= 1
    assert set(result["_enabled_pillars"]) <= {"fingerprint", "decision_trail", "report", "cost"}
    assert "result" in result
    assert "findings" not in result
    assert "cost_usd" not in result
    assert "report_path" not in result


# ── E2E-1: shot_spec → bpy script → Blender previz → artifact ────────────────


def test_e2e1_bpy_script_compilation_is_deterministic() -> None:
    """E2E-1 (pure half): shot_spec compiles to a stable, self-contained script."""
    from oskill.previz_compiler import build_previz_bpy_script

    spec = {"shot_id": "007", "scene_type": "character_block", "duration_s": 2.0}
    first = build_previz_bpy_script(spec, camera_motion="dolly_in", actor_action="walk_and_stop")
    second = build_previz_bpy_script(spec, camera_motion="dolly_in", actor_action="walk_and_stop")
    assert first == second
    assert "import bpy" in first
    assert "shot_007" in first
    assert "bpy.ops.render.render" in first


@pytest.mark.asyncio
async def test_e2e1_previz_generate_contract(tmp_path: Path) -> None:
    """E2E-1: previz_generate produces an artifact, or a structured failure."""
    result = await previz_generate(
        BaseConfig(),
        {
            "shot_spec": {"shot_id": "001", "scene_type": "geometry_block", "duration_s": 1.0},
            "fps": 12,
            "resolution": (128, 128),
        },
        tmp_path / "previz",
    )
    _assert_transaction_contract(result, expected_status=result["status"])
    if _HAS_BLENDER:
        assert result["status"] == "completed"
        assert Path(result["result"]["video_path"]).is_file()
        assert len(result["fingerprint"]) == 64
    else:
        assert result["status"] == "failed"
        assert result["error"]["code"] == "PREVIZ_GENERATE_FAILED"
        assert "blender" in result["error"]["message"].lower()
    # Script materialization must not leak a scratch file into the output dir.
    leftover = list((tmp_path / "previz").glob("*_render.py"))
    assert leftover == []


# ── E2E-2: previz → V2V → drift validation → artifact ────────────────────────


def _register_fake_v2v(
    name: str, *, out_vectors: list[list[float]], ref_vectors: list[list[float]]
) -> None:
    async def _fake(**kwargs: Any) -> dict[str, Any]:
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await _color_clip(output_path, color="teal", seconds=1.0, fps=12)
        return {
            "ref_motion_vectors": ref_vectors,
            "out_motion_vectors": out_vectors,
            "cost_usd": 0.25,
        }

    _fake.__module__ = "hevi.video.fake"
    ProviderRegistry.register("v2v", name, _fake, replace=True)


@pytest.mark.asyncio
async def test_e2e2_previz_to_v2v_within_drift_budget(tmp_path: Path) -> None:
    if not _HAS_FFMPEG:
        pytest.skip("ffmpeg required")
    previz = await _color_clip(tmp_path / "previz_001.mp4", color="gray", seconds=1.0, fps=12)
    vectors = [[1.0, 0.2], [1.1, 0.25], [0.9, 0.15]]
    _register_fake_v2v("fake_aligned", out_vectors=vectors, ref_vectors=vectors)

    result = await previz_guided_v2v_render(
        BaseConfig(),
        {
            "previz_video_path": str(previz),
            "prompt": "stylize as cinematic",
            "provider": "fake_aligned",
            "shot_id": "001",
        },
        tmp_path / "v2v",
    )
    _assert_transaction_contract(result, expected_status="completed")
    assert Path(result["result"]["clip_path"]).is_file()
    assert result["result"]["drift_score"] <= 0.15
    assert result["cost"] == 0.25
    assert len(result["fingerprint"]) == 64


@pytest.mark.asyncio
async def test_e2e2_v2v_drift_gate_rejects_divergence(tmp_path: Path) -> None:
    if not _HAS_FFMPEG:
        pytest.skip("ffmpeg required")
    previz = await _color_clip(tmp_path / "previz_001.mp4", color="gray", seconds=1.0, fps=12)
    _register_fake_v2v(
        "fake_divergent",
        ref_vectors=[[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]],
        out_vectors=[[-1.0, 0.0], [-1.0, 0.0], [-1.0, 0.0]],
    )

    result = await previz_guided_v2v_render(
        BaseConfig(),
        {
            "previz_video_path": str(previz),
            "prompt": "stylize",
            "provider": "fake_divergent",
            "shot_id": "001",
        },
        tmp_path / "v2v",
    )
    assert result["status"] == "failed"
    assert result["error"]["code"] == "CAMERA_DRIFT_EXCEEDED"
    # The transaction reports the drift; the accept/reject policy stays Layer4.
    assert result["decision_trail"]["drift_score"] > 0.15


# ── E2E-3: ASR → frame alignment → ASS → timeline assembly → final render ─────


@pytest.mark.asyncio
async def test_e2e3_asr_alignment_to_final_render(tmp_path: Path) -> None:
    if not (_HAS_FFMPEG and _HAS_FW and _WHISPER_MODEL.is_dir()):
        pytest.skip("ffmpeg + faster-whisper + local model required")
    from oprim import transcribe_audio

    # Build a speech track without any cloud dependency.
    audio = tmp_path / "narration.wav"
    if shutil.which("espeak") is None:
        pytest.skip("espeak required to synthesize deterministic speech")
    import subprocess

    subprocess.run(
        ["espeak", "-v", "zh", "这是一个视频旁白测试", "-w", str(audio)],
        check=True, capture_output=True,
    )
    transcript = await transcribe_audio(
        audio_path=audio,
        backend="local",
        model_size="base",
        language="zh",
        model_path=str(_WHISPER_MODEL),
    )
    assert transcript.segments, "ASR must return at least one segment"

    asr_segments = [
        {
            "start": s["start"],
            "end": s["end"],
            "text": s["text"],
            "words": [{"start": s["start"], "end": s["end"], "text": w}
                      for w in (s["text"].split() or [s["text"]])],
        }
        for s in transcript.segments
    ]

    shots = []
    for i, color in enumerate(("maroon", "olive")):
        clip = await _color_clip(tmp_path / f"shot_{i}.mp4", color=color, seconds=2.5)
        shots.append({"video_path": str(clip)})

    result = await media_timeline_assemble(
        BaseConfig(),
        {
            "shots": shots,
            "fps": 24,
            "resolution": (320, 240),
            "transition": "fade",
            "audio_path": str(audio),
            "asr_segments": asr_segments,
            "total_audio_ms": round(transcript.duration * 1000),
        },
        tmp_path / "timeline",
    )
    _assert_transaction_contract(result, expected_status="completed")
    final = Path(result["result"]["video_path"])
    assert final.is_file() and final.stat().st_size > 0
    assert result["decision_trail"]["has_subtitles"] is True
    assert result["decision_trail"]["aligned_transcript"]
    assert await ffmpeg_probe_duration(final) > 0


# ── E2E-4: Remotion branch → render → timeline assembly ──────────────────────


@pytest.mark.asyncio
async def test_e2e4_remotion_render_to_timeline(tmp_path: Path) -> None:
    if not _HAS_REMOTION:
        pytest.skip("remotion CLI required")
    result = await remotion_template_render(
        BaseConfig(),
        {
            "composition_id": "Zhibo",
            "props": {},
            "duration_frames": 150,
            "fps": 30,
            "remotion_root": str(REMOTION_ROOT),
        },
        tmp_path / "remotion",
    )
    _assert_transaction_contract(result, expected_status="completed")
    clip = Path(result["result"]["video_path"])
    assert clip.is_file() and clip.stat().st_size > 0
    assert len(result["fingerprint"]) == 64
    # The shared run_manifest.json must be untouched by a no-props render.
    manifest = (REMOTION_ROOT / "src" / "data" / "run_manifest.json").read_text(encoding="utf-8")
    assert manifest.strip().startswith("[")


# ── E2E-5: failure → existing RepairIncident → repair → verification ─────────


@pytest.mark.asyncio
async def test_e2e5_failure_enters_existing_repair_authority(tmp_path: Path) -> None:
    """oservi reports the failure; HEVI's RepairIncident authority owns the repair."""
    from oservi import PipelineComposerEngine, StepSpec

    from hevi.creative.layer4.repair_incident import (
        IncidentStatus,
        SelfHealingCoordinator,
    )
    from hevi.production.artifacts import ArtifactManifest, verify_local_manifest

    async def failing_step(config, input_data, output_dir, *, on_step=None):
        return {
            "status": "failed",
            "error": {"code": "PROVIDER_FAILURE", "message": "render transient", "retryable": True},
            "_enabled_pillars": ["decision_trail"],
            "result": None,
        }

    failing_step.__module__ = "omodul.fake"

    engine = PipelineComposerEngine(
        steps=[StepSpec("previz_generate", failing_step)],
        trigger={"on_demand": True},
        config=None,
        name="e2e5",
    )
    envelope = await engine.run(input_data={}, output_dir=tmp_path)
    assert envelope["status"] == "failed"
    # oservi must not invent repair semantics.
    assert "repair_incident" not in envelope

    # Layer4 consumes the generic failure envelope and opens the canonical incident.
    step = envelope["steps"]["previz_generate"]
    coordinator = SelfHealingCoordinator()
    incident = coordinator.open_incident(
        production_run_id="run-e2e5",
        node_key="previz.generate",
        failure=step["error"]["code"],
        evidence={"signature": "provider temporarily unavailable", "transient": True},
    )
    assert incident.candidate_actions
    action = incident.candidate_actions[0]
    approved, reason = coordinator.authorize(incident.incident_id, action)
    assert approved, reason
    coordinator.record_execution(incident.incident_id)

    # Repair produced a real artifact; Layer4 verifies and materializes it.
    repaired = await _color_clip(tmp_path / "repaired.mp4", color="black", seconds=1.0, fps=12)
    manifest = verify_local_manifest(ArtifactManifest.for_video(repaired))
    resolved = coordinator.verify(
        incident.incident_id,
        {"task_ok": True, "artifact_ok": True, "currency_ok": True, "presentation_ok": True},
    )
    assert resolved.status is IncidentStatus.RESOLVED
    assert manifest.primary_path() == repaired

    from hevi.creative.layer4.presentation import (
        AudioMode,
        CandidateMedia,
        PresentationSelector,
        for_download,
    )

    snapshot = PresentationSelector().select(
        project_id="p-e2e5",
        production_run_id="run-e2e5",
        revision_id="rev-1",
        scope_id="s1",
        video_candidates=(
            CandidateMedia(
                artifact_id="repaired",
                version=1,
                path=str(repaired),
                kind="video",
                dependency_revision="rev-1",
            ),
        ),
        actual_durations_ms={"repaired": round(await ffmpeg_probe_duration(repaired) * 1000)},
        audio_mode=AudioMode.SILENT,
        dependency_revisions={"revision": "rev-1"},
    )
    assert for_download(snapshot)["video_artifact_id"] == "repaired"
