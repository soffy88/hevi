"""Tests for hevi.creative.layer4.v2v_workflow + v2v adapter wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hevi.creative.layer4.v2v_workflow import (
    V2VContractError,
    assess_v2v_quality,
    build_v2v_request,
    v2v_render_workflow,
    validate_v2v_output,
)


def _spec(**overrides):
    base = {
        "prompt": "gentle camera push-in, ink wash style preserved",
        "provider": "dashscope-i2v",
        "model": "wan2.2-i2v-flash",
        "resolution": "720P",
    }
    base.update(overrides)
    return base


class TestBuildV2VRequest:
    def test_valid_request(self):
        req = build_v2v_request(v2v_spec=_spec(), source_path="/tmp/previz.png")
        assert req["provider"] == "dashscope-i2v"
        assert req["model"] == "wan2.2-i2v-flash"
        assert req["model_allowlisted"] is True

    def test_missing_prompt_refused(self):
        with pytest.raises(V2VContractError, match="V2V_PROMPT_REQUIRED"):
            build_v2v_request(v2v_spec=_spec(prompt="  "), source_path="/tmp/x.png")

    def test_missing_reference_refused(self):
        with pytest.raises(V2VContractError, match="V2V_REFERENCE_REQUIRED"):
            build_v2v_request(v2v_spec=_spec(), source_path="")

    def test_unknown_provider_fail_closed(self):
        with pytest.raises(V2VContractError, match="V2V_UNKNOWN_PROVIDER"):
            build_v2v_request(
                v2v_spec=_spec(provider="kling"), source_path="/tmp/x.png"
            )

    def test_non_allowlisted_model_passes_through_for_genuine_rejection(self):
        req = build_v2v_request(
            v2v_spec=_spec(model="probe-nonexistent-model-xyz"),
            source_path="/tmp/x.png",
        )
        assert req["model_allowlisted"] is False
        assert req["model"] == "probe-nonexistent-model-xyz"


class TestAssessQuality:
    def test_pass(self):
        assert (
            assess_v2v_quality(
                requested_duration=5.0,
                actual_duration=5.1,
                has_video=True,
                lineage_ok=True,
            )
            == "PASS"
        )

    def test_block_without_video_or_lineage(self):
        assert (
            assess_v2v_quality(
                requested_duration=None,
                actual_duration=None,
                has_video=False,
                lineage_ok=True,
            )
            == "BLOCK"
        )
        assert (
            assess_v2v_quality(
                requested_duration=None,
                actual_duration=5.0,
                has_video=True,
                lineage_ok=False,
            )
            == "BLOCK"
        )

    def test_warn_then_block_on_drift(self):
        assert (
            assess_v2v_quality(
                requested_duration=5.0,
                actual_duration=6.5,
                has_video=True,
                lineage_ok=True,
            )
            == "WARN"
        )
        assert (
            assess_v2v_quality(
                requested_duration=5.0,
                actual_duration=9.0,
                has_video=True,
                lineage_ok=True,
            )
            == "BLOCK"
        )


class TestValidateOutput:
    def test_missing_file_blocked(self, tmp_path):
        result = validate_v2v_output(
            path=str(tmp_path / "nope.mp4"),
            provider="dashscope-i2v",
            model="wan2.2-i2v-flash",
        )
        assert result.success is False
        assert result.failure_code == "V2V_OUTPUT_MISSING"

    def test_empty_file_blocked(self, tmp_path):
        empty = tmp_path / "empty.mp4"
        empty.write_bytes(b"")
        result = validate_v2v_output(
            path=str(empty), provider="dashscope-i2v", model="wan2.2-i2v-flash"
        )
        assert result.success is False
        assert result.failure_code == "V2V_OUTPUT_EMPTY"


@pytest.mark.asyncio
async def test_workflow_failure_carries_failure_code(tmp_path):
    async def boom(**kwargs):
        raise RuntimeError("DURABLE_SUBMIT_REJECTED:HTTP 404: Model not exist.")

    result = await v2v_render_workflow(
        v2v_spec=_spec(model="probe-nonexistent-model-xyz"),
        source_path=str(tmp_path / "previz.png"),
        output_path=str(tmp_path / "out.mp4"),
        runner=boom,
    )
    assert result.success is False
    assert result.failure_code == "V2V_PROVIDER_REJECTED"
    assert result.repair_action == "RETRY_TARGET"
    assert result.quality_signal == "BLOCK"


@pytest.mark.asyncio
async def test_workflow_success_with_fake_runner(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("imageio")
    if __import__("shutil").which("ffprobe") is None:
        pytest.skip("ffprobe not installed")

    async def fake_runner(**kwargs):
        out = Path(str(kwargs["output_path"]))
        import imageio.v2 as imageio
        import numpy as np

        writer = imageio.get_writer(
            str(out), fps=24, codec="libx264", macro_block_size=None
        )
        frame = (np.zeros((64, 64, 3), dtype=np.uint8) + 128).tobytes()
        for _ in range(24):
            writer.append_data(np.frombuffer(frame, dtype=np.uint8).reshape(64, 64, 3))
        writer.close()
        return out

    result = await v2v_render_workflow(
        v2v_spec=_spec(),
        source_path=str(tmp_path / "previz.png"),
        output_path=str(tmp_path / "out.mp4"),
        runner=fake_runner,
    )
    assert result.success is True
    assert result.output_sha256
    assert result.duration_s and result.duration_s > 0


@pytest.mark.asyncio
async def test_v2v_adapter_registered_and_dispatched():
    from hevi.production.adapters import default_production_adapters

    assert "v2v" in default_production_adapters().sources()

    from hevi.production.adapters import ProductionAdapterRegistry

    repo = MagicMock()
    repo.pool = MagicMock()
    repo.update_task = AsyncMock()
    adapters = ProductionAdapterRegistry()

    async def fake_v2v(task, pool):
        return {**task, "status": "completed"}

    adapters.register("v2v", fake_v2v)
    from unittest.mock import patch

    from hevi.tasks.task_service import TaskService

    service = TaskService(repo, production_adapters=adapters)
    with patch(
        "hevi.tasks.task_service.TaskService._apply_provider_policy",
        new_callable=AsyncMock,
    ) as policy:
        await service._run_adapter_task(
            {"id": uuid4(), "config_json": {"production_source": "v2v"}}
        )
    policy.assert_not_called()
