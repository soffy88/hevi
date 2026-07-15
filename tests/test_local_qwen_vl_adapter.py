"""hevi/providers/local_qwen_vl_adapter.py 测试——2026-07-12 真实撞见的 bug:视频直出
provider(happyhorse 等)给的候选是 .mp4,之前 `_b64_data_uri` 直接把原始视频字节
base64、贴假 mime "data:image/mp4",ollama 正确判定非法图片数据秒拒(400)。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hevi.providers.local_qwen_vl_adapter import _b64_data_uri


def test_b64_data_uri_image_path_unchanged(tmp_path):
    img = tmp_path / "frame.png"
    img.write_bytes(b"fake-png-bytes")
    uri = _b64_data_uri(img)
    assert uri is not None
    assert uri.startswith("data:image/png;base64,")


def test_b64_data_uri_video_path_extracts_frame_first(tmp_path):
    clip = tmp_path / "shot_0000_v0.mp4"
    clip.write_bytes(b"fake-mp4-bytes")  # 内容不重要,ffmpeg 调用本身被 mock 掉
    extracted_png = tmp_path / "extracted_frame.png"
    extracted_png.write_bytes(b"real-frame-bytes")

    with patch(
        "hevi.providers.local_qwen_vl_adapter._video_frame_to_temp_png",
        return_value=extracted_png,
    ):
        uri = _b64_data_uri(clip)

    assert uri is not None
    # mime 应该是抽出来的帧(png),不是视频本身、更不是假的 "image/mp4"
    assert uri.startswith("data:image/png;base64,")
    assert "mp4" not in uri.split(",", 1)[0]


def test_b64_data_uri_video_frame_extraction_failure_degrades_to_none(tmp_path):
    clip = tmp_path / "shot_0000_v0.mp4"
    clip.write_bytes(b"fake-mp4-bytes")

    with patch(
        "hevi.providers.local_qwen_vl_adapter._video_frame_to_temp_png",
        return_value=None,
    ):
        uri = _b64_data_uri(clip)

    assert uri is None


def test_video_frame_to_temp_png_cleans_up_after_read(tmp_path):
    """抽出来的临时帧文件用完就该删,不留垃圾。"""
    clip = tmp_path / "shot.mp4"
    clip.write_bytes(b"fake-mp4-bytes")
    extracted_png = tmp_path / "extracted_frame.png"
    extracted_png.write_bytes(b"real-frame-bytes")

    with patch(
        "hevi.providers.local_qwen_vl_adapter._video_frame_to_temp_png",
        return_value=extracted_png,
    ):
        _b64_data_uri(clip)

    assert not extracted_png.exists()
