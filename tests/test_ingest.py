"""Phase A 内化测试: 帧预算 / 去重 / 字幕解析 / 联络表 / 抽帧。

纯算法部分全部确定性可测;yt-dlp / whisper 外部路径不 mock 网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from hevi.ingest.contact_sheet import ContactSheetError, build_contact_sheet
from hevi.ingest.frame_budget import (
    FRAME_BUDGET_TABLE,
    focused_budget,
    frame_budget_for_duration,
)
from hevi.ingest.frame_dedup import dedupe_frames, frame_delta
from hevi.ingest.video_frames import FramesError, WatchDetail, extract_watch_frames
from hevi.ingest.video_transcript import TranscriptError, parse_subtitle, read_subtitle_file

# ---- frame budget ----

def test_budget_table_matches_source_contract():
    assert FRAME_BUDGET_TABLE[0] == (30.0, 30)
    assert FRAME_BUDGET_TABLE[-1][1] == 100
    assert frame_budget_for_duration(10) == 30
    assert frame_budget_for_duration(45) == 40
    assert frame_budget_for_duration(120) == 60
    assert frame_budget_for_duration(400) == 80
    assert frame_budget_for_duration(3600) == 100
    assert frame_budget_for_duration(-1) == 100  # unknown duration -> max tier
    assert frame_budget_for_duration(3600, cap=50) == 50
    assert frame_budget_for_duration(0, cap=1) == 1


def test_focused_budget():
    assert focused_budget(None, None) == 0
    assert focused_budget(0, 30) == 60  # 30s * 2fps
    assert focused_budget(100, 105) == 10
    assert focused_budget(0, 0) >= 1


# ---- frame dedup ----

def test_frame_delta_basic():
    a = bytes([10]) * 256
    b = bytes([11]) * 256
    assert frame_delta(a, b) == pytest.approx(1.0)
    assert frame_delta(a, bytes([255]) * 256) == pytest.approx(245.0)
    # 长度不匹配 -> 最大差异
    assert frame_delta(a, b"short") == 255.0


def test_dedupe_frames_keeps_distinct():
    thumbs = [bytes([i]) * 256 for i in (0, 1, 2)]  # 相邻差 1.0 < 2.0
    survivors, dropped = dedupe_frames(thumbs)
    assert survivors == [0]
    assert dropped == 2


def test_dedupe_keeps_big_changes():
    thumbs = [bytes([i]) * 256 for i in (0, 50, 100, 150)]
    survivors, dropped = dedupe_frames(thumbs)
    assert survivors == [0, 1, 2, 3]
    assert dropped == 0


def test_dedupe_compares_against_last_kept():
    # 慢渐变:0 -> 1 -> 2 -> 100。每帧 vs 上一保留帧差 <=2,只有最后一帧保留
    thumbs = [bytes([i]) * 256 for i in (0, 1, 2, 100)]
    survivors, _ = dedupe_frames(thumbs)
    assert survivors == [0, 3]


# ---- subtitle parsing ----

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.500
第一句台词

00:00:04.000 --> 00:00:06.000
第二句台词

00:00:07.000 --> 00:00:09.250
跨行
台词
"""

SRT = """1
00:00:01,000 --> 00:00:03,500
first line

2
00:00:04,000 --> 00:00:06,000
second
line
"""


def test_parse_vtt():
    segs = parse_subtitle(VTT)
    assert len(segs) == 3
    assert segs[0].start == 1.0 and segs[0].end == 3.5
    assert segs[0].text == "第一句台词"
    assert segs[2].text == "跨行 台词"  # 换行合并,保留措辞


def test_parse_srt():
    segs = parse_subtitle(SRT)
    assert len(segs) == 2
    assert segs[1].text == "second line"
    assert segs[1].start == 4.0


def test_read_subtitle_file(tmp_path):
    p = tmp_path / "a.vtt"
    p.write_text(VTT, encoding="utf-8")
    segs = read_subtitle_file(p)
    assert len(segs) == 3
    with pytest.raises(TranscriptError):
        read_subtitle_file(tmp_path / "missing.vtt")


# ---- contact sheet ----

def test_contact_sheet(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    paths = []
    for i in range(4):
        p = frames_dir / f"f{i}.png"
        Image.new("RGB", (64, 36), (i * 40, 40, 80)).save(p)
        paths.append(p)
    out = build_contact_sheet(paths, tmp_path / "sheet.jpg", cols=2, thumb_width=32)
    assert out.exists()
    img = Image.open(out)
    # 2 cols x 2 rows, cell width 32
    assert img.size[0] == 64


def test_contact_sheet_empty_raises(tmp_path):
    with pytest.raises(ContactSheetError):
        build_contact_sheet([], tmp_path / "x.jpg")


# ---- frame extraction (real tiny video via PyAV) ----

def _make_tiny_video(tmp_path: Path, n_frames: int = 12) -> Path:
    import av

    p = tmp_path / "tiny.mp4"
    with av.open(str(p), "w") as container:
        stream = container.add_stream("mpeg4", rate=30)
        stream.width, stream.height = 64, 36
        for i in range(n_frames):
            img = Image.new("RGB", (64, 36), (i * 20 % 255, 0, 0))
            frame = av.VideoFrame.from_image(img)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return p


def test_extract_frames_efficient_budget(tmp_path):
    vid = _make_tiny_video(tmp_path)
    frames = extract_watch_frames(
        vid, tmp_path / "out", detail=WatchDetail.EFFICIENT, budget=5
    )
    assert 0 < len(frames) <= 5
    assert all(f.path.exists() for f in frames)
    # 时间升序
    ts = [f.timestamp_s for f in frames]
    assert ts == sorted(ts)


def test_extract_frames_image_passthrough(tmp_path):
    img = tmp_path / "img.png"
    Image.new("RGB", (64, 36)).save(img)
    frames = extract_watch_frames(img, tmp_path / "out")
    assert len(frames) == 1
    assert frames[0].path == img


def test_extract_frames_transcript_detail_returns_empty(tmp_path):
    vid = _make_tiny_video(tmp_path)
    frames = extract_watch_frames(vid, tmp_path / "out", detail=WatchDetail.TRANSCRIPT)
    assert frames == []


def test_extract_frames_missing_raises(tmp_path):
    with pytest.raises(FramesError):
        extract_watch_frames(tmp_path / "nope.mp4", tmp_path / "out")
