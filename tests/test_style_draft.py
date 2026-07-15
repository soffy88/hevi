"""StylePack 创建入口(参考图/视频 → VLM 拆解草稿)测试(HEVI 路线图 Phase3 #38)。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hevi.style.draft_from_reference import StyleDraftError, draft_style_from_reference


def _vlm(content: str) -> AsyncMock:
    return AsyncMock(return_value={"content": content})


async def test_draft_from_image_parses_all_four_fields(tmp_path):
    img = tmp_path / "ref.png"
    img.write_bytes(b"\x89PNG\r\n")
    vlm = _vlm(
        '{"style": "cinematic, moody", "lighting": "low-key", '
        '"camera": "slow dolly", "color_grade": "teal orange"}'
    )
    draft = await draft_style_from_reference(img, vlm=vlm)
    assert draft == {
        "style": "cinematic, moody",
        "lighting": "low-key",
        "camera": "slow dolly",
        "color_grade": "teal orange",
    }


async def test_draft_missing_file_raises():
    with pytest.raises(StyleDraftError):
        await draft_style_from_reference("/nonexistent/ref.png", vlm=_vlm("{}"))


async def test_draft_malformed_response_raises(tmp_path):
    img = tmp_path / "ref.png"
    img.write_bytes(b"\x89PNG\r\n")
    with pytest.raises(StyleDraftError):
        await draft_style_from_reference(img, vlm=_vlm("not json"))


async def test_draft_vlm_exception_raises(tmp_path):
    img = tmp_path / "ref.png"
    img.write_bytes(b"\x89PNG\r\n")
    vlm = AsyncMock(side_effect=RuntimeError("vl model down"))
    with pytest.raises(StyleDraftError):
        await draft_style_from_reference(img, vlm=vlm)


async def test_draft_missing_fields_default_to_empty_string(tmp_path):
    img = tmp_path / "ref.png"
    img.write_bytes(b"\x89PNG\r\n")
    vlm = _vlm('{"style": "minimalist"}')
    draft = await draft_style_from_reference(img, vlm=vlm)
    assert draft["style"] == "minimalist"
    assert draft["lighting"] == ""


async def test_draft_from_video_extracts_frame_first(tmp_path, monkeypatch):
    video = tmp_path / "ref.mp4"
    video.write_bytes(b"fake video bytes")
    extracted = tmp_path / "extracted_frame.png"
    extracted.write_bytes(b"\x89PNG\r\n")

    calls = {}

    def _fake_extract(source, out_path):
        calls["source"] = source
        return extracted

    monkeypatch.setattr("hevi.verdict.frame_extract.extract_representative_frame", _fake_extract)
    vlm = _vlm('{"style": "handheld vlog", "lighting": "", "camera": "", "color_grade": ""}')
    draft = await draft_style_from_reference(video, vlm=vlm)
    assert draft["style"] == "handheld vlog"
    assert calls["source"] == video
