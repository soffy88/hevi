from pathlib import Path

import pytest

import hevi.explainer.production as production
from hevi.explainer.render import RenderResult
from hevi.explainer.schemas import Storyboard


def _storyboard() -> Storyboard:
    return Storyboard.model_validate(
        {
            "topic": "private topic",
            "segments": [
                {
                    "id": "hook",
                    "sceneType": "hook",
                    "narration": "private narration",
                    "props": {},
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_e2_uses_standard_narrated_transaction_through_oservi(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_render(storyboard: Storyboard, output_dir: Path, **_kwargs: str) -> RenderResult:
        assert storyboard.topic == "private topic"
        portrait = output_dir / "portrait.mp4"
        landscape = output_dir / "landscape.mp4"
        output_dir.mkdir(parents=True, exist_ok=True)
        portrait.write_bytes(b"portrait")
        landscape.write_bytes(b"landscape")
        return RenderResult(manifest=[], portrait_path=portrait, landscape_path=landscape)

    monkeypatch.setattr(production, "render_storyboard", fake_render)

    result = await production.render_narrated_storyboard(_storyboard(), tmp_path)

    assert result.portrait_path == tmp_path / "portrait.mp4"
    assert result.landscape_path == tmp_path / "landscape.mp4"
    assert result.engine_result["status"] == "succeeded"
    assert result.engine_result["artifacts"][0]["primary"] is True


@pytest.mark.asyncio
async def test_e2_surfaces_the_structured_artifact_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_render(
        _storyboard: Storyboard, output_dir: Path, **_kwargs: str
    ) -> RenderResult:
        return RenderResult(
            manifest=[],
            portrait_path=output_dir / "missing-portrait.mp4",
            landscape_path=output_dir / "missing-landscape.mp4",
        )

    monkeypatch.setattr(production, "render_storyboard", fake_render)

    with pytest.raises(production.NarratedProductionError, match="ARTIFACT_MISSING"):
        await production.render_narrated_storyboard(_storyboard(), tmp_path)
