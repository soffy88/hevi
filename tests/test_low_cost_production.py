from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hevi.production.low_cost import LOW_COST_POLICY, execute_low_cost, policy_for
from hevi.studio.veya import produce, reset_veya


def _make_test_inputs(tmp_path: Path) -> tuple[Path, Path]:
    from PIL import Image

    image = tmp_path / "approved-image.png"
    Image.new("RGB", (640, 360), (30, 70, 120)).save(image)
    audio = tmp_path / "source-audio.mp3"
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.2", str(audio)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0 and audio.is_file()
    return image, audio


def test_low_cost_policy_is_explicit_and_cpu_only() -> None:
    assert policy_for("low_cost") == LOW_COST_POLICY
    assert LOW_COST_POLICY.local_gpu_required is False
    assert LOW_COST_POLICY.zero_human_after_start is True
    with pytest.raises(ValueError):
        policy_for("not-a-real-mode")


@pytest.mark.asyncio
async def test_low_cost_entrypoint_does_not_fallback_to_standard_renderer(tmp_path: Path) -> None:
    reset_veya()
    job = await produce(
        line_id="cinematic",
        production_mode="low_cost",
        execute=True,
        output_dir=tmp_path,
    )
    assert job.status == "blocked"
    assert job.artifact == ""
    assert job.reason == "LOW_COST_RECIPE_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_low_cost_cpu_render_has_real_media_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image, audio = _make_test_inputs(tmp_path)

    async def tts(**kwargs: object) -> None:
        output_path = Path(str(kwargs["output_path"]))
        output_path.write_bytes(audio.read_bytes())

    monkeypatch.setattr("hevi.audio.edge_tts_custom.edge_tts_synthesize_smart", tts)
    result = await execute_low_cost(
        line_id="emotional_reading",
        slots={
            "full_script": "第一句。第二句。",
            "asset_paths": [str(image)],
            "voice_provider": "edge_tts",
        },
        output_dir=tmp_path / "run",
    )
    assert result["status"] == "completed"
    final = Path(str(result["result_video_path"]))
    assert final.is_file()
    assert result["artifact_manifest"]["artifacts"][0]["sha256"]
    assert result["quality_report"]["passed"] is True
    assert result["cost_ledger"]["local_gpu_used"] is False
    assert result["cost_ledger"]["video_generation_api_calls"] == 0
