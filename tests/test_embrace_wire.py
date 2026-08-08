"""3O 内化 wire 测试: 负向子句 / 交付门 / replay trace 接 verdict / 资产导出。"""

from __future__ import annotations

import pytest

from hevi.director.verdict_checks import verdict_shot
from hevi.prompt.negative_clause import (
    merge_negative_clauses,
    shot_negative_clause,
    with_failure_registry_clause,
)
from hevi.verdict.delivery_gate import (
    DeliveryGateError,
    parse_silence_events,
    run_delivery_gate,
)
from hevi.verdict.replay_trace import load_traces

# ---- wire ①: 失败注册表 → 负向子句 ----

def test_shot_negative_clause_action_layer():
    clause = shot_negative_clause("action")
    assert clause.startswith("负面约束:")
    assert "手部结构正常" in clause


def test_merge_negative_clauses():
    assert merge_negative_clauses() == ""
    assert merge_negative_clauses("a。", "a。", "") == "a。"
    assert merge_negative_clauses("a。", "b。") == "a。b。"


def test_with_failure_registry_clause_keeps_base():
    merged = with_failure_registry_clause("避免多指。", layer="action")
    assert "避免多指" in merged
    assert "手部结构正常" in merged


# ---- wire ②: 成片交付门 ----

def test_parse_silence_events():
    stderr = (
        "[silencedetect @ 0x1] silence_start: 2.5\n"
        "[silencedetect @ 0x1] silence_end: 4.5 | silence_duration: 2\n"
        "[silencedetect @ 0x1] silence_start: 10.0\n"
        "[silencedetect @ 0x1] silence_end: 10.8 | silence_duration: 0.8\n"
    )
    events = parse_silence_events(stderr, floor_s=1.5)
    assert events == [(2.5, 2.0)]  # 0.8s 的不过阈值


def test_delivery_gate_missing_video_raises(tmp_path):
    with pytest.raises(DeliveryGateError):
        run_delivery_gate(tmp_path / "missing.mp4", out_dir=tmp_path)


def test_delivery_gate_real_video(tmp_path):
    import av
    from PIL import Image

    vid = tmp_path / "tiny.mp4"
    with av.open(str(vid), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height = 64, 36
        for _i in range(10):
            img = Image.new("RGB", (64, 36), (60, 60, 60))
            frame = av.VideoFrame.from_image(img)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)

    result = run_delivery_gate(vid, out_dir=tmp_path / "gate")
    names = {i.name for i in result.items}
    assert {"flicker", "dead_air", "contact_sheet", "bgm_loop"} <= names
    # 无音轨/无 BGM → dead_air 视环境而定(ffmpeg 缺失时 None,否则无静音 = True)
    assert any(i.name == "contact_sheet" for i in result.items)
    assert "P1" in result.canon_report  # 判例库流程族自检


# ---- wire ③: replay trace 接 verdict ----

def test_verdict_shot_with_trace(tmp_path):
    import av
    from PIL import Image

    clip = tmp_path / "clip.mp4"
    with av.open(str(clip), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height = 64, 36
        for _i in range(5):
            frame = av.VideoFrame.from_image(Image.new("RGB", (64, 36), (200, 200, 200)))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)

    import asyncio

    v = asyncio.run(
        verdict_shot(
            shot_index=1,
            shot_id="shot_0001",
            clip_path=clip,
            identity_score=0.9,
            trace_root=tmp_path / "traces",
        )
    )
    # 明亮帧 → 非黑 → passed(identity 0.9 >= 0.75)
    assert v.passed is True
    traces = load_traces(tmp_path / "traces")
    assert len(traces) == 1
    assert traces[0]["final_status"] == "accepted"
    assert traces[0]["ref_id"] == "shot_0001"


def test_verdict_shot_without_trace_unchanged(tmp_path):
    import asyncio

    import av
    from PIL import Image

    clip = tmp_path / "clip.mp4"
    with av.open(str(clip), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height = 64, 36
        for _i in range(5):
            frame = av.VideoFrame.from_image(Image.new("RGB", (64, 36), (0, 0, 0)))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)

    v = asyncio.run(
        verdict_shot(
            shot_index=1, shot_id="shot_0001", clip_path=clip, identity_score=0.9
        )
    )
    # 全黑帧 → 判不过(re_roll);trace_root=None 不落盘
    assert v.passed is False
    assert v.retake_tier == "re_roll"


# ---- wire ④: 资产导出 ----

def test_export_embrace_assets(tmp_path):
    from scripts.export_embrace_assets import main as export_main

    out = tmp_path / "embrace"
    export_main(["--out", str(out)])
    assert (out / "cards.json").exists()
    assert (out / "canon.json").exists()
    assert (out / "failure_modes.json").exists()
    cards = __import__("json").loads((out / "cards.json").read_text(encoding="utf-8"))
    assert len(cards) >= 10
