"""avcraft 3O 最小测试：oskill 纯函数单测 + obase/omodul 真实 ffmpeg 合成样例冒烟。

ASR/LLM 真实链路需 HEVI_AVCRAFT_E2E=1（CPU 慢，默认跳过）。
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from hevi.avcraft.obase.media import ffmpeg_bin, parse_silencedetect
from hevi.avcraft.oskill.subtitle import segment_sentences, to_ass, to_srt, translate_cues
from hevi.avcraft.oskill.timeline import build_pause_timeline, keep_ranges, timeline_set_keep


def test_parse_silencedetect_unclosed():
    err = (
        "[silencedetect @ x] silence_start: 1.5\n[silencedetect @ x] silence_end: 2.5 | silence_duration: 1\n"
        "[silencedetect @ x] silence_start: 9.0\n"
    )
    assert parse_silencedetect(err, 10.0) == [(1.5, 2.5), (9.0, 10.0)]


def test_pause_timeline_margin_and_keep():
    tl = build_pause_timeline([(0.0, 1.0), (3.0, 3.4), (5.0, 7.0)], 10.0, margin=0.1, min_pause=0.5)
    pauses = [c for c in tl["clips"] if c["kind"] == "pause"]
    assert [(c["start"], c["end"]) for c in pauses] == [(0.0, 0.9), (5.1, 6.9)]  # 0.4s 停顿保留
    assert keep_ranges(tl) == [(0.9, 5.1), (6.9, 10.0)]
    timeline_set_keep(tl, [pauses[1]["id"]], True)
    assert keep_ranges(tl) == [(0.9, 10.0)]


def _w(seq):
    t, out = 0.0, []
    for tok, gap in seq:
        t += gap
        out.append({"start": t, "end": t + 0.3, "word": tok})
        t += 0.3
    return out


def test_segment_sentences_en_punct_and_gap():
    ws = _w(
        [
            (" Hello", 0),
            (" world.", 0),
            (" This", 0),
            (" is", 0),
            (" fine", 0),
            (" after", 1.0),
            (" gap.", 0),
        ]
    )
    cues = segment_sentences(ws, min_dur=0)
    assert [c["text"] for c in cues] == ["Hello world.", "This is fine", "after gap."]


def test_translate_and_render_with_fallback_and_glossary():
    cues = [
        {"id": 1, "start": 0, "end": 1.5, "text": "Use Hevi now."},
        {"id": 2, "start": 1.5, "end": 3.2, "text": "Bye."},
    ]
    calls = []

    def fake(p):
        calls.append(p)
        if len(calls) == 1:
            return "garbage"  # 批失败 → 逐句兜底
        return json.dumps({"t": ["现在用 Hevi。" if "Hevi" in p.split("\n\n")[-1] else "再见。"]})

    out = translate_cues(cues, fake, src="en", tgt="zh", glossary={"Hevi": "嘿微"})
    assert out[0]["tr"] == "现在用 嘿微。" and out[1]["tr"] == "再见。"
    srt = to_srt(out)
    assert "00:00:01,500 --> 00:00:03,200" in srt and "Use Hevi now.\n现在用 嘿微。" in srt
    ass = to_ass(out)
    assert ass.count("Dialogue:") == 4 and "0:00:01.50" in ass


@pytest.fixture(scope="module")
def tone_video(tmp_path_factory):
    d = tmp_path_factory.mktemp("av")
    p = d / "tone.mp4"
    # 1s 静音 + 2s 音 + 1.5s 静音 + 2s 音 + 1s 静音 = 7.5s，带视频轨
    f = "aevalsrc='if(between(t,1,3)+between(t,4.5,6.5),0.5*sin(2*PI*440*t),0)':s=48000:d=7.5"
    subprocess.run(
        [
            ffmpeg_bin(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f,
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:r=25:d=7.5",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(p),
        ],
        check=True,
    )
    return p


def test_pause_cut_e2e_ffmpeg(tone_video, tmp_path):
    from hevi.avcraft.omodul.pause_cut import export_timeline, pause_cut

    r = pause_cut(tone_video, tmp_path, margin=0.1, min_pause=0.5)
    assert r["silences"] == 3 and r["removed"] == 3
    assert 4.2 <= r["output_duration_s"] <= 4.8, r  # 2+2 + 4*0.1 边距
    tl = json.loads(Path(r["timeline"]).read_text())
    timeline_set_keep(tl, [c["id"] for c in tl["clips"] if c["kind"] == "pause"][1:2], True)
    r2 = export_timeline(tl, tmp_path / "re.mp4")
    assert r2["output_duration_s"] > r["output_duration_s"] + 1.0


@pytest.mark.skipif(os.environ.get("HEVI_AVCRAFT_E2E") != "1", reason="slow CPU ASR/LLM")
def test_bilingual_subtitles_real(tmp_path):
    from hevi.avcraft.omodul.bilingual_subs import bilingual_subtitles

    src = os.environ.get("HEVI_AVCRAFT_SAMPLE", "sample_speech_60s.wav")
    r = bilingual_subtitles(src, tmp_path)
    assert r["cues"] > 0 and Path(r["files"]["ass"]).exists()
