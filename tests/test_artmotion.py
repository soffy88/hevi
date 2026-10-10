import pytest
from hevi.explainer.schemas import Storyboard, StoryboardSegment
from hevi.explainer.production import render_narrated_storyboard
from pathlib import Path
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_artmotion_adapter_basic(tmp_path: Path):
    sb = Storyboard(
        topic="test",
        segments=[
            StoryboardSegment(
                id="1",
                scene_type="explainer",
                narration="测试口播。",
                keywords=[],
                props={}
            )
        ]
    )
    # mock the executor inside production.py
    with patch("hevi.explainer.production.execute_standard_operation") as mock_exec, \
         patch("hevi.explainer.production.SequentialComposerEngine") as mock_engine, \
         patch("hevi.explainer.production.cover_extract_and_render") as mock_cover:
        
        mock_engine.return_value.run.return_value = {
            "results": [{
                "status": "succeeded",
                "artifacts": [
                    {"kind": "video", "primary": True, "path": str(tmp_path / "portrait.mp4")},
                    {"kind": "video", "primary": False, "path": str(tmp_path / "landscape.mp4")},
                ]
            }]
        }
        mock_cover.return_value = {"status": "succeeded", "path": str(tmp_path / "cover.jpg"), "media_type": "image/jpeg"}
        
        # Test renderer="artmotion"
        (tmp_path / "portrait.mp4").write_text("dummy")
        (tmp_path / "landscape.mp4").write_text("dummy")
        
        res = await render_narrated_storyboard(sb, tmp_path, renderer="artmotion")
        assert res.portrait_path == tmp_path / "portrait.mp4"

