"""source_media_review 测试 —— 完整源片审查工件(OpenMontage 内化)。

覆盖: 扩展名归类 / 图片探测(纯元数据, 无 ffprobe 依赖) / 空批 / 规划影响。
ffprobe 路径用 mock 验证, 不依赖本机二进制行为。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hevi.verdict.source_media_review import (
    detect_media_type,
    has_user_media,
    review_source_media,
)


def test_detect_media_type() -> None:
    assert detect_media_type(Path("a.mp4")) == "video"
    assert detect_media_type(Path("a.MOV")) == "video"
    assert detect_media_type(Path("b.mp3")) == "audio"
    assert detect_media_type(Path("c.png")) == "image"
    assert detect_media_type(Path("d.txt")) is None


def test_has_user_media(tmp_path: Path) -> None:
    assert has_user_media(tmp_path) is False
    (tmp_path / "clip.mp4").write_bytes(b"x")
    assert has_user_media(tmp_path) is True


def test_review_empty_files() -> None:
    review = review_source_media([])
    assert review["files"] == []
    assert any("No source media" in i for i in review["planning_implications"])


def test_review_image(tmp_path: Path) -> None:
    img = tmp_path / "hero.png"
    img.write_bytes(b"fake-png")
    review = review_source_media([img])
    assert len(review["files"]) == 1
    entry = review["files"][0]
    assert entry["media_type"] == "image"
    assert entry["reviewed"] is True
    assert entry["usable_for"] == ["visual asset", "reference image"]
    assert any("Source video" not in i for i in review["planning_implications"])


def test_review_missing_and_unknown_files(tmp_path: Path) -> None:
    missing = tmp_path / "nope.mp4"
    unknown = tmp_path / "data.bin"
    unknown.write_bytes(b"x")
    review = review_source_media([missing, unknown])
    assert review["files"] == []  # 两者都被跳过


def test_review_video_uses_ffprobe(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")
    fake_probe = {
        "format": {"duration": "12.5", "size": "1024", "bit_rate": "65536"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264",
             "width": 1920, "height": 1080, "r_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac",
             "sample_rate": "48000", "channels": "2"},
        ],
    }
    with patch("hevi.verdict.source_media_review._ffprobe_json", return_value=fake_probe):
        review = review_source_media([video])
    entry = review["files"][0]
    probe = entry["technical_probe"]
    assert probe["duration_seconds"] == 12.5
    assert probe["resolution"] == "1920x1080"
    assert probe["fps"] == 30.0
    assert entry["content_summary"].startswith("Video file: 12.5s")
    assert "hero footage" in entry["usable_for"]
    assert "b-roll" in entry["usable_for"]
    assert "source audio" in entry["usable_for"]
    assert any("Source video available" in i for i in review["planning_implications"])


def test_review_video_probe_failure_degrades(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")
    with patch("hevi.verdict.source_media_review._ffprobe_json", return_value=None):
        review = review_source_media([video])
    entry = review["files"][0]
    assert any("ffprobe 不可用" in r for r in entry["quality_risks"])
    assert entry["reviewed"] is True  # 仍标记 reviewed, 但风险已记录


def test_review_transcribe_optional(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")
    fake_probe = {
        "format": {"duration": "20.0", "size": "1024", "bit_rate": "0"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264",
             "width": 1280, "height": 720, "r_frame_rate": "30000/1001"},
        ],
    }

    def _fake_transcribe(_p: Path) -> str:
        return "hello world this is a narration"

    with patch("hevi.verdict.source_media_review._ffprobe_json", return_value=fake_probe):
        review = review_source_media([video], transcribe=_fake_transcribe)
    entry = review["files"][0]
    assert entry["transcript_summary"] == "hello world this is a narration"
    assert "source dialogue" in entry["usable_for"]
