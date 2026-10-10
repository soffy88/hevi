"""Unit tests for the talkcraft capability (no model, no render, no network)."""

from __future__ import annotations

import json
from itertools import pairwise

import pytest

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import (
    AlignedChar,
    NarrationSegment,
    SentenceTiming,
    norm_chars,
)
from hevi.layer4_legacy.talkcraft.oskill_impl.align import align_script, chars_from_words
from hevi.layer4_legacy.talkcraft.oskill_impl.shotbook import (
    CARDS,
    pick_keyword,
    plan_project,
    wrap_lines,
)
from hevi.talkcraft.explainer_adapter import segments_from_storyboard, split_sentences


def _timing(i: int, text: str, start: float, end: float) -> SentenceTiming:
    chars, ratio = align_script(
        script=text,
        asr_chars=[AlignedChar(c, k * 0.2, k * 0.2 + 0.2) for k, c in enumerate(norm_chars(text))],
        start_s=start,
        end_s=end,
    )
    return SentenceTiming(i, text, start, end, tuple(chars), ratio, "test")


SEGS = [
    NarrationSegment("hook", "hook", ("为什么复利是奇迹？", "答案在时间、本金和收益率。"), ("复利",),
                     {"title": "复利的力量", "subtitle": "三分钟", "items": [{"label": "时间"}, {"label": "本金"}]}),
    NarrationSegment("m", "method", ("记住三步。", "越早开始越好。", "保持投入。"), ("三步",),
                     {"header": "三步", "points": [{"title": "尽早"}, {"title": "持续"}]}),
]


def _plan():
    texts = [s for seg in SEGS for s in seg.sentences]
    t, tm = 0.4, []
    for i, x in enumerate(texts):
        tm.append(_timing(i, x, t, t + 2.0))
        t += 2.35
    return plan_project(name="t", segments=SEGS, timings=tm, voice_file="runs/x/voice.wav", total_s=t)


def test_align_exact_match_takes_asr_times():
    chars, ratio = align_script(
        script="你好，世界",
        asr_chars=chars_from_words(words=[("你好", 0.0, 0.4), ("世界", 0.5, 0.9)]),
        start_s=10.0,
        end_s=11.0,
    )
    assert ratio == 1.0
    assert [c.char for c in chars] == list("你好世界")
    assert chars[2].start_s == pytest.approx(10.5)


def test_align_interpolates_unmatched_chars_monotonically():
    chars, ratio = align_script(
        script="今天天气很好",
        asr_chars=chars_from_words(words=[("今天", 0.0, 0.5), ("很好", 1.0, 1.5)]),
        start_s=0.0,
        end_s=2.0,
    )
    assert ratio == pytest.approx(4 / 6)
    starts = [c.start_s for c in chars]
    assert starts == sorted(starts)
    assert 0.5 <= chars[2].start_s <= 1.0


def test_align_without_asr_spreads_over_sentence():
    chars, ratio = align_script(script="一二三四", asr_chars=[], start_s=1.0, end_s=3.0)
    assert ratio == 0.0
    assert chars[0].start_s == pytest.approx(1.0) and chars[-1].end_s == pytest.approx(3.0)


def test_char_time_finds_keyword():
    tm = _timing(0, "复利是奇迹", 5.0, 6.0)
    assert tm.char_time(substring="奇迹") == pytest.approx(5.6)
    assert tm.char_time(substring="不存在") is None


def test_wrap_and_keyword():
    assert all(len(x) <= 12 for x in wrap_lines("这是一个非常非常非常非常非常长的句子，后面还有一句", width=12))
    assert pick_keyword("我们要控制成本。", ["成本"]) == "成本"
    assert pick_keyword("先说结论，再讲原因。", []) in ("先说结论", "再讲原因")


def test_plan_is_deterministic_and_well_formed():
    a, b = _plan(), _plan()
    assert json.dumps(a.to_json(), sort_keys=True) == json.dumps(b.to_json(), sort_keys=True)
    ids = a.card_ids()
    assert len(ids) == 5
    assert all(x != y for x, y in pairwise(ids))  # never back-to-back
    assert all(c in CARDS for c in ids)
    tracks = {t["id"]: t for t in a.project["tracks"]}
    assert set(tracks) == {"fx", "subs", "cards", "bg", "voice"}
    assert len(tracks["fx"]["clips"]) == 1  # one wipe at the single segment change
    clips = tracks["cards"]["clips"]
    for x, y in pairwise(clips):
        assert x["start"] + x["duration"] == y["start"]  # gapless beats


def test_plan_uses_structure_and_anchors_to_keyword():
    p = _plan()
    first = p.beats[0]
    assert first.card_id == "slab-punch-title" and first.props["line1"] == "复利的力量"
    assert p.beats[1].card_id == "title-demote-to-label"
    assert p.beats[2].card_id == "step-timeline-vertical"
    assert any(b.anchor_offset_s is not None for b in p.beats)


def test_plan_rejects_timing_mismatch():
    with pytest.raises(ValueError):
        plan_project(name="t", segments=SEGS, timings=[], voice_file="v", total_s=1.0)


def test_storyboard_adapter():
    assert split_sentences("第一句。第二句！没有标点") == ["第一句。", "第二句！", "没有标点"]
    segs = segments_from_storyboard(
        {"topic": "t", "segments": [{"id": "a", "sceneType": "hook", "narration": "甲。乙。", "keywords": ["甲"], "props": {"title": "T"}}]}
    )
    assert segs[0].role == "hook" and segs[0].sentences == ("甲。", "乙。")


def test_lead_is_capped_so_stage_is_never_empty_long():
    from hevi.layer4_legacy.talkcraft.oskill_impl.shotbook import MAX_LEAD_S
    p = _plan()
    for b in p.beats:
        for key in ("lead", "delay", "startDelay", "startAt"):
            if key in b.props:
                assert b.props[key] <= MAX_LEAD_S


# ---------------- optional digital-human avatar ----------------
import numpy as np  # noqa: E402

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AvatarSpec  # noqa: E402
from hevi.layer4_legacy.talkcraft.oskill_impl import avatar_math as am  # noqa: E402


def test_avatar_spec_is_optional_and_validated():
    assert AvatarSpec.from_config(None) is None
    assert AvatarSpec.from_config(False) is None
    assert AvatarSpec.from_config({"enabled": False}) is None
    assert AvatarSpec.from_config(True) == AvatarSpec()
    assert AvatarSpec.from_config("still").mode == "still"
    spec = AvatarSpec.from_config({"mode": "lipsync", "position": "left", "image": "/x.jpg"})
    assert spec == AvatarSpec(mode="lipsync", image="/x.jpg", position="left")
    with pytest.raises(ValueError):
        AvatarSpec.from_config({"mode": "deepfake"})


def test_mel_chunks_cover_every_frame():
    mel = np.random.default_rng(0).normal(size=(80, 300)).astype(np.float32)
    ch = am.mel_chunks(mel=mel, fps=30, n_frames=120)
    assert ch.shape == (120, 80, 16)
    assert np.allclose(ch[3], mel[:, 8:24])  # int(80*3/30)=8
    assert np.allclose(ch[-1], mel[:, 284:300])  # past the end -> last full window


def test_yolo_decode_maps_back_through_letterbox():
    s, px, py = am.letterbox(w=1000, h=500)
    out = np.zeros((1, 20, 8400), dtype=np.float32)
    out[0, :5, 7] = [320, 320, 64, 64, 0.9]
    x1, y1, x2, y2, sc = am.decode_yoloface(output=out, scale=s, pad_x=px, pad_y=py)
    assert sc == pytest.approx(0.9)
    assert (x1 + x2) / 2 == pytest.approx(500, abs=1) and (y1 + y2) / 2 == pytest.approx(250, abs=1)
    out[0, 4, 7] = 0.1
    assert am.decode_yoloface(output=out, scale=s, pad_x=px, pad_y=py) is None


def test_lagged_correlation_finds_shift():
    rng = np.random.default_rng(1)
    b = rng.random(200)
    a = np.roll(b, 3)
    r, lag = am.lagged_correlation(a, b, smooth=1)
    assert r > 0.95 and lag == 3


def test_layouts_stay_inside_frame():
    for portrait, (w, h) in ((False, (1920, 1080)), (True, (1080, 1920))):
        for pos in ("right", "left"):
            x, y, d = am.overlay_layout(frame_w=w, frame_h=h, position=pos, portrait=portrait)
            assert x >= 0 and x + d <= w and y >= 0 and y + d <= h
    x, y, d = am.overlay_layout(frame_w=1080, frame_h=1920, position="right", portrait=True)
    assert y >= (1920 + 608) // 2  # below the 16:9 stage band


def test_mouth_mask_only_lower_face():
    m = am.mouth_mask(w=100, h=100)
    assert m[:45].max() == 0 and m[75, 50] == pytest.approx(1.0)
