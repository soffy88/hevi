import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from hevi.explainer.schemas import Storyboard, StoryboardSegment
from hevi.explainer.production import render_narrated_storyboard
from hevi.artmotion.adapter import (
    ArtmotionRenderError,
    render_artmotion,
    render_artmotion_direct,
    resolve_style_id,
)
import hevi.layer4_legacy.artmotion.omodul_impl.scripts.film_gate as film_gate


@pytest.mark.asyncio
async def test_artmotion_adapter_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "dummy")
    sb = Storyboard(
        topic="test",
        segments=[
            StoryboardSegment(
                id="1", scene_type="hook", narration="测试口播。", keywords=[], props={}
            )
        ],
    )
    with (
        patch("hevi.explainer.production.execute_standard_operation") as mock_exec,
        patch("hevi.explainer.production.SequentialComposerEngine") as mock_engine,
        patch("hevi.explainer.cover.cover_extract_and_render") as mock_cover,
    ):
        mock_engine.return_value.run = AsyncMock(
            return_value={
                "results": [
                    {
                        "status": "succeeded",
                        "artifacts": [
                            {
                                "kind": "video",
                                "primary": True,
                                "path": str(tmp_path / "portrait.mp4"),
                            },
                            {
                                "kind": "video",
                                "primary": False,
                                "path": str(tmp_path / "landscape.mp4"),
                            },
                        ],
                    }
                ]
            }
        )
        mock_cover.return_value = {
            "status": "succeeded",
            "path": str(tmp_path / "cover.jpg"),
            "media_type": "image/jpeg",
        }

        (tmp_path / "portrait.mp4").write_text("dummy")
        (tmp_path / "landscape.mp4").write_text("dummy")

        res = await render_narrated_storyboard(sb, tmp_path, renderer="artmotion")
        assert res.portrait_path == tmp_path / "portrait.mp4"


def test_style_id_resolution():
    assert resolve_style_id("17_ink") == "17_ink"
    assert resolve_style_id("ink") == "17_ink"
    assert resolve_style_id("17") == "17_ink"
    assert resolve_style_id("water_ink") == "17_ink"
    assert resolve_style_id("scenes/17_ink.js") == "17_ink"

    assert resolve_style_id("25_ghibli") == "25_ghibli"
    assert resolve_style_id("ghibli") == "25_ghibli"
    assert resolve_style_id("25") == "25_ghibli"

    assert resolve_style_id("14_8bit") == "14_8bit"
    assert resolve_style_id("8bit") == "14_8bit"
    assert resolve_style_id("14") == "14_8bit"
    assert resolve_style_id("pixel") == "14_8bit"

    assert resolve_style_id("12_bauhaus") == "12_bauhaus"
    assert resolve_style_id("bauhaus") == "12_bauhaus"


def test_artmotion_adapter_contract(tmp_path: Path):
    dummy_video = tmp_path / "artmotion_landscape.mp4"
    dummy_video.write_text("dummy")

    mock_record = {
        "video_path": str(dummy_video),
        "width": 1920,
        "height": 1080,
        "duration_s": 25.5,
        "render_seconds": 12.0,
        "style_id": "17_ink",
        "grammar_id": "t1_3b1b",
        "gate_light": "green",
        "fast_ratio": 0.082,
        "still_ratio": 0.52,
        "blank_run_s": 0.0,
        "blue_purple_share": 0.0,
        "gates": [
            {"name": "gate_light", "passed": True, "value": "green"},
            {"name": "fast_ratio", "passed": True, "value": 0.082},
        ],
        "sha256": "fakehash",
    }

    with patch("hevi.artmotion.adapter.produce_artmotion") as mock_produce:
        mock_produce.return_value = {
            "status": "succeeded",
            "records": [mock_record],
        }

        # Test string script input
        res = render_artmotion(
            script="第一段测试解说。第二段测试解说。",
            output_dir=tmp_path,
            style_id="17_ink",
            grammar_id="t1_3b1b",
            aspect_ratio="16:9",
        )
        assert res["video_path"] == str(dummy_video)
        assert res["record_path"] == str(tmp_path / "record.json")
        assert res["style_id"] == "17_ink"
        assert res["grammar_id"] == "t1_3b1b"
        assert res["gate_light"] == "green"
        assert res["fast_ratio"] == 0.082
        assert mock_produce.call_count == 1

        args, kwargs = mock_produce.call_args
        assert kwargs["style_id"] == "17_ink"
        assert kwargs["grammar_id"] == "t1_3b1b"
        assert kwargs["aspect_ratio"] == "16:9"
        assert len(kwargs["segments"]) == 1
        assert len(kwargs["segments"][0].sentences) == 2

        # Test pre-existing audio input
        dummy_wav = tmp_path / "audio.wav"
        dummy_wav.write_text("wav")
        res_audio = render_artmotion_direct(
            audio_path=dummy_wav,
            output_dir=tmp_path,
            style_id="25_ghibli",
            grammar_id="y5_kinetic_type",
            aspect_ratio="9:16",
        )
        assert res_audio["video_path"] == str(dummy_video)
        assert mock_produce.call_args[1]["audio_path"] == dummy_wav

        # Test failure behavior
        mock_produce.return_value = {
            "status": "failed",
            "records": [
                {
                    "video_path": str(dummy_video),
                    "gates": [
                        {
                            "name": "fast_ratio",
                            "passed": False,
                            "value": 0.02,
                            "message": "too slow",
                        }
                    ],
                }
            ],
        }
        with pytest.raises(ArtmotionRenderError, match="artmotion gates failed"):
            render_artmotion(script="失败测试", output_dir=tmp_path)


def test_film_gate_missing_cv2():
    with patch.dict(sys.modules, {"cv2": None}):
        with pytest.raises(RuntimeError, match="cv2 缺失"):
            film_gate.measure("dummy.mp4")


def test_sanitize_latex_no_source_on_screen():
    """上屏文本含 \\ ^ _ { } 即 FAIL：sanitize_latex 必须把它们全消掉（r5 B4）。"""
    from hevi.layer4_legacy.artmotion.omodul_impl.produce import (
        sanitize_latex,
        find_latex_source,
    )

    # 审核方点名的两个用例（token 级与整串级）
    for raw in ("QK^T/\\sqrt{d_k}", "\\text{Softmax}(QK^T)V"):
        clean = sanitize_latex(raw)
        assert find_latex_source(clean) == "", f"{raw!r} -> {clean!r} 仍残留 LaTeX 源码"
        for ch in "\\^_{}":
            assert ch not in clean

    # ^ / _ 必须变成 Unicode 上下标，不是被删掉
    assert sanitize_latex("QK^T/\\sqrt{d_k}") == "QKᵀ/√dₖ"
    assert sanitize_latex("\\text{Softmax}(QK^T)V") == "Softmax(QKᵀ)V"
    # 带花括号的写法同样处理
    assert sanitize_latex("QK^{T}/\\sqrt{d_{k}}") == "QKᵀ/√dₖ"
    # 分 token（E2E 里的真实写法：K^T 与 /\sqrt{d_k} 是两条 cue token）
    assert sanitize_latex("K^T") == "Kᵀ"
    assert sanitize_latex("/\\sqrt{d_k}") == "/√dₖ"
    # 纯文本原样
    assert sanitize_latex("attention 机制") == "attention 机制"
    assert find_latex_source("attention 机制") == ""
