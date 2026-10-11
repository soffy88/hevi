"""Integration test for omlines free-tier production."""

import pytest
from hevi.studio.veya import produce
from scripts.qualify_autonomous_production import _slots


@pytest.mark.asyncio
async def test_omlines_documentary_montage(tmp_path):
    job = await produce(
        line_id="documentary_montage",
        slots=_slots("documentary_montage"),
        output_dir=str(tmp_path / "documentary_montage"),
        execute=True,
        publish=False,
    )
    assert job.status in {"ready", "completed"}
    assert job.artifact is not None


@pytest.mark.asyncio
async def test_omlines_localization_dub(tmp_path):
    job = await produce(
        line_id="localization_dub",
        slots=_slots("localization_dub"),
        output_dir=str(tmp_path / "localization_dub"),
        execute=True,
        publish=False,
    )
    assert job.status in {"ready", "completed"}
    assert job.artifact is not None


@pytest.mark.asyncio
async def test_omlines_talking_head(tmp_path):
    job = await produce(
        line_id="talking_head",
        slots=_slots("talking_head"),
        output_dir=str(tmp_path / "talking_head"),
        execute=True,
        publish=False,
    )
    assert job.status in {"ready", "completed"}
    assert job.artifact is not None
