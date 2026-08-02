from pathlib import Path

import pytest

from hevi.tongjian.production import PresenterProductionError, render_presenter_video


@pytest.mark.asyncio
async def test_tongjian_l3_l8_runs_through_standard_presenter_transaction(tmp_path: Path) -> None:
    async def renderer(presentation: dict, output_dir: Path, _config: dict) -> dict:
        assert presentation == {"kind": "tongjian-history"}
        video = output_dir / "L8" / "final.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        return {"video_path": video, "report": {"completed_layers": ["L3", "L8"]}}

    result = await render_presenter_video(output_dir=tmp_path, renderer=renderer)

    assert result.video_path == tmp_path / "L8" / "final.mp4"
    assert result.engine_result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_tongjian_l3_l8_reports_missing_output_as_structured_failure(tmp_path: Path) -> None:
    async def renderer(_presentation: dict, output_dir: Path, _config: dict) -> dict:
        return {"video_path": output_dir / "L8" / "missing.mp4"}

    with pytest.raises(PresenterProductionError, match="ARTIFACT_MISSING"):
        await render_presenter_video(output_dir=tmp_path, renderer=renderer)
