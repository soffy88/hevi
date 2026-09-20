"""P3: HEVI Layer4 media pipeline integration tests.

Verifies HEVI Layer4 assembles P2 omodul transactions via generic oservi
composition — without introducing a second authority or Monkey Patch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from hevi.services.media_pipeline import build_media_pipeline_steps, run_media_pipeline


def test_pipeline_topology_declares_fan_out_and_fan_in() -> None:
    steps = build_media_pipeline_steps()
    by_id = {s.step_id: s for s in steps}

    assert "remotion_template_render" in by_id
    assert by_id["remotion_template_render"].mode == "fan_out"

    assert by_id["previz_generate"].mode == "fan_out"
    assert by_id["previz_guided_v2v_render"].depends_on == ("previz_generate",)

    assert by_id["media_timeline_assemble"].mode == "fan_in"
    assert set(by_id["media_timeline_assemble"].depends_on) == {
        "remotion_template_render",
        "previz_guided_v2v_render",
    }


def test_pipeline_topology_has_no_business_authority_names() -> None:
    steps = build_media_pipeline_steps()
    names = " ".join(s.step_id for s in steps)
    for forbidden in ("MediaStreamDirector", "VideoPipelineEngine", "HeviPipelineComposer"):
        assert forbidden not in names


@pytest.mark.asyncio
async def test_previz_sequence_through_oservi(tmp_path: Path) -> None:
    """previz_generate → previz_guided_v2v_render via oservi sequential deps."""
    previz_calls: list[dict] = []
    v2v_calls: list[dict] = []

    async def fake_previz(config, input_data, output_dir, *, on_step=None):
        previz_calls.append(input_data)
        out = tmp_path / "previz_001.mp4"
        out.write_bytes(b"previz")
        return {
            "status": "completed",
            "error": None,
            "_enabled_pillars": ["fingerprint"],
            "result": {"video_path": str(out), "shot_id": "001"},
            "fingerprint": "p",
            "decision_trail": {},
            "cost": 0.0,
            "report": None,
        }

    async def fake_v2v(config, input_data, output_dir, *, on_step=None):
        v2v_calls.append(input_data)
        out = tmp_path / "clip_001.mp4"
        out.write_bytes(b"clip")
        return {
            "status": "completed",
            "error": None,
            "_enabled_pillars": ["fingerprint"],
            "result": {"clip_path": str(out), "drift_score": 0.01, "provider": "fake"},
            "fingerprint": "v",
            "decision_trail": {},
            "cost": 0.5,
            "report": None,
        }

    with (
        patch("hevi.services.media_pipeline.previz_generate", new=fake_previz),
        patch("hevi.services.media_pipeline.previz_guided_v2v_render", new=fake_v2v),
    ):
        out = await run_media_pipeline(
            payload={
                "shot_spec": {"shot_id": "001", "duration_s": 2.0},
                "prompt": "stylize",
                "v2v_provider": "fake",
            },
            output_dir=tmp_path,
            enable_remotion_branch=False,
        )

    assert out["steps"]["previz_generate"]["status"] == "completed"
    assert out["steps"]["previz_guided_v2v_render"]["status"] == "completed"
    # v2v received previz output path via Layer4 input resolver
    assert v2v_calls[0]["previz_video_path"].endswith("previz_001.mp4")


@pytest.mark.asyncio
async def test_remotion_branch_through_oservi(tmp_path: Path) -> None:
    async def fake_remotion(config, input_data, output_dir, *, on_step=None):
        out = tmp_path / "remotion_Explainer.mp4"
        out.write_bytes(b"remotion")
        return {
            "status": "completed",
            "error": None,
            "_enabled_pillars": ["fingerprint"],
            "result": {"video_path": str(out), "composition_id": "Explainer"},
            "fingerprint": "r",
            "decision_trail": {},
            "cost": 0.0,
            "report": None,
        }

    with patch("hevi.services.media_pipeline.remotion_template_render", new=fake_remotion):
        out = await run_media_pipeline(
            payload={"composition_id": "Explainer", "props": {}, "duration_frames": 24},
            output_dir=tmp_path,
            enable_previz_branch=False,
        )

    assert out["steps"]["remotion_template_render"]["status"] == "completed"
    # timeline fan-in runs (remotion optional but completed)
    assert "media_timeline_assemble" in out["steps"]


@pytest.mark.asyncio
async def test_fan_out_fan_in_timeline_collects_clips(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    async def fake_remotion(config, input_data, output_dir, *, on_step=None):
        out = tmp_path / "r.mp4"
        out.write_bytes(b"r")
        return {
            "status": "completed", "error": None, "_enabled_pillars": ["fingerprint"],
            "result": {"video_path": str(out)}, "fingerprint": "r",
            "decision_trail": {}, "cost": 0.0, "report": None,
        }

    async def fake_previz(config, input_data, output_dir, *, on_step=None):
        out = tmp_path / "p.mp4"
        out.write_bytes(b"p")
        return {
            "status": "completed", "error": None, "_enabled_pillars": ["fingerprint"],
            "result": {"video_path": str(out)}, "fingerprint": "p",
            "decision_trail": {}, "cost": 0.0, "report": None,
        }

    async def fake_v2v(config, input_data, output_dir, *, on_step=None):
        out = tmp_path / "v.mp4"
        out.write_bytes(b"v")
        return {
            "status": "completed", "error": None, "_enabled_pillars": ["fingerprint"],
            "result": {"clip_path": str(out)}, "fingerprint": "v",
            "decision_trail": {}, "cost": 0.0, "report": None,
        }

    async def fake_timeline(config, input_data, output_dir, *, on_step=None):
        captured.update(input_data)
        out = tmp_path / "final.mp4"
        out.write_bytes(b"final")
        return {
            "status": "completed", "error": None, "_enabled_pillars": ["fingerprint"],
            "result": {"video_path": str(out), "duration_s": 4.0}, "fingerprint": "f",
            "decision_trail": {}, "cost": 0.0, "report": None,
        }

    with (
        patch("hevi.services.media_pipeline.remotion_template_render", new=fake_remotion),
        patch("hevi.services.media_pipeline.previz_generate", new=fake_previz),
        patch("hevi.services.media_pipeline.previz_guided_v2v_render", new=fake_v2v),
        patch("hevi.services.media_pipeline.media_timeline_assemble", new=fake_timeline),
    ):
        out = await run_media_pipeline(
            payload={"shot_spec": {"shot_id": "001"}, "composition_id": "X", "props": {}},
            output_dir=tmp_path,
        )

    assert out["status"] == "completed"
    assert out["steps"]["media_timeline_assemble"]["status"] == "completed"
    # fan-in collected both remotion + v2v clip paths
    shot_paths = {s["video_path"] for s in captured.get("shots", [])}
    assert any(p.endswith("r.mp4") for p in shot_paths)
    assert any(p.endswith("v.mp4") for p in shot_paths)


@pytest.mark.asyncio
async def test_omodul_failure_returns_to_layer4_for_repair(tmp_path: Path) -> None:
    """oservi reports failure; Layer4 (caller) owns RepairIncident routing."""

    async def fake_previz(config, input_data, output_dir, *, on_step=None):
        return {
            "status": "failed",
            "error": {"code": "BLENDER_RENDER_ERR", "message": "boom", "retryable": True},
            "result": None,
            "_enabled_pillars": ["decision_trail"],
            "fingerprint": None,
            "decision_trail": {},
            "cost": 0.0,
            "report": None,
        }

    from oservi import PipelineComposerEngine, StepSpec

    import hevi.services.media_pipeline as mp

    # Build a minimal engine directly to isolate failure propagation.
    engine = PipelineComposerEngine(
        steps=[
            StepSpec("previz_generate", fake_previz),
            StepSpec("previz_guided_v2v_render", AsyncMock(), depends_on=("previz_generate",)),
        ],
        trigger={"on_demand": True},
        config=None,
        name="failure-test",
    )
    out = await engine.run(input_data={}, output_dir=tmp_path)

    assert out["status"] == "failed"
    assert out["steps"]["previz_generate"]["status"] == "failed"
    assert out["steps"]["previz_guided_v2v_render"]["status"] == "skipped"
    # oservi does not invent repair semantics
    assert "repair_incident" not in out
    assert "repair" not in out["steps"]["previz_generate"]
    _ = mp  # module import is part of Layer4 wiring path


@pytest.mark.asyncio
async def test_layer4_decision_fn_reuse_skips_side_effects(tmp_path: Path) -> None:
    """Layer4 can pre-empt duplicate external side effects via reuse decisions."""
    ran: list[str] = []

    async def fake_previz(config, input_data, output_dir, *, on_step=None):
        ran.append("previz")
        out = tmp_path / "p.mp4"
        out.write_bytes(b"p")
        return {
            "status": "completed", "error": None, "_enabled_pillars": ["fingerprint"],
            "result": {"video_path": str(out)}, "fingerprint": "p",
            "decision_trail": {}, "cost": 0.0, "report": None,
        }

    def decision_fn(*, step_id, dependency_results, config):
        if step_id == "previz_generate":
            return {"decision": "reuse_existing", "result": {"video_path": "/cached/p.mp4"}}
        return "run"

    with patch("hevi.services.media_pipeline.previz_generate", new=fake_previz):
        out = await run_media_pipeline(
            payload={"shot_spec": {"shot_id": "001"}},
            output_dir=tmp_path,
            decision_fn=decision_fn,
            enable_remotion_branch=False,
        )

    assert out["steps"]["previz_generate"]["status"] == "reused"
    assert ran == []  # side effect avoided


def test_no_monkey_patch_in_layer4_assembly() -> None:
    """Layer4 assembly must not rebind production symbols at runtime."""
    source = (
        Path(__file__).parents[1] / "hevi" / "services" / "media_pipeline.py"
    ).read_text(encoding="utf-8")
    for token in ("setattr(", "monkeypatch", "monkey_patch", "types.MethodType"):
        assert token not in source
