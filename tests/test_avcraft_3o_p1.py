"""avcraft P1 最小测试：烧录/软挂、逐句编辑时间线、画面信号剪、规则断句修补、分镜编译/重拍/sequence。
全部 CPU + ffmpeg 合成素材，无模型、无网络。"""

import json
import subprocess

import pytest

from hevi.avcraft.obase.media import ffmpeg_bin, list_streams, parse_visual_detect, probe_duration
from hevi.avcraft.obase.shot_table import SHOT_SCHEMA, validate_shot_table
from hevi.avcraft.oskill.shotprompt import (
    apply_retake,
    compile_shot_prompt,
    diagnose_retake,
    retake_budget,
)
from hevi.avcraft.oskill.subtitle import repair_breaks
from hevi.avcraft.oskill.timeline import (
    apply_ops,
    keep_ranges,
    map_time,
    merge_cut_signals,
    render_cues,
    timeline_from_cues,
)

CUES = [
    {"id": 1, "start": 0.5, "end": 2.0, "text": "First line.", "tr": "第一句。"},
    {"id": 2, "start": 2.2, "end": 3.8, "text": "Second line.", "tr": "第二句。"},
    {"id": 3, "start": 4.0, "end": 5.5, "text": "Third line.", "tr": "第三句。"},
]


def test_parse_visual_detect():
    err = (
        "[blackdetect @ 0x] black_start:0 black_end:1.04 black_duration:1.04\n"
        "[freezedetect @ 0x] lavfi.freezedetect.freeze_start: 2.5\n"
        "[freezedetect @ 0x] lavfi.freezedetect.freeze_duration: 2\n"
        "[freezedetect @ 0x] lavfi.freezedetect.freeze_end: 4.5\n"
        "[scdet @ 0x] lavfi.scd.score: 35.120, lavfi.scd.time: 1.04\n"
        "[freezedetect @ 0x] lavfi.freezedetect.freeze_start: 7\n"
    )
    r = parse_visual_detect(err, 8.0)
    assert r == {"black": [(0.0, 1.04)], "freeze": [(2.5, 4.5), (7.0, 8.0)], "scene": [(1.04, 35.12)]}


def test_edit_ops_and_cue_mapping():
    tl = timeline_from_cues(CUES, 6.0)
    apply_ops(tl, [{"op": "delete", "cue": 2}, {"op": "retext", "cue": 3, "text": "Third, fixed."},
                   {"op": "retime", "cue": 1, "start": 0.3, "end": 9}])
    assert keep_ranges(tl) == [(0.0, 2.2), (3.8, 6.0)]
    out = render_cues(tl)
    assert [c["id"] for c in out] == [1, 3]
    assert out[0]["start"] == 0.3 and out[0]["end"] == 2.2  # retime 夹到下一句开头
    assert out[1]["start"] == 2.4 and out[1]["end"] == 3.9 and out[1]["tr_stale"] is True
    apply_ops(tl, [{"op": "restore", "cue": 2}])
    assert keep_ranges(tl) == [(0.0, 6.0)] and len(tl["ops"]) == 4
    assert map_time([(0, 1), (2, 3)], 1.5, "start") == 1.0 and map_time([(0, 1), (2, 3)], 2.5) == 1.5


def test_merge_visual_signals_protects_speech():
    tl = timeline_from_cues(CUES, 6.0)
    sig = {"black": [(0.0, 0.5)], "freeze": [(3.0, 6.0)], "scene": [(4.0, 30.0)]}
    merge_cut_signals(tl, sig, {"freeze": {"min": 1.0, "keep_head": 0.0}})
    # 黑场 0-0.5 剪；静止 3-6 只剪掉无字幕的 5.5-6
    assert keep_ranges(tl) == [(0.5, 5.75)]  # 句尾留 0.25s 保护
    assert tl["markers"][0]["t"] == 4.0 and any(abs(c["start"] - 4.0) < 1e-6 for c in tl["clips"])


def test_repair_breaks_rules():
    en = [
        {"start": 0, "end": 2, "text": "He lived at Dragonbone"},
        {"start": 2, "end": 4, "text": "Hill in China about 700,000"},
        {"start": 4, "end": 6, "text": "years ago, with the"},
        {"start": 6, "end": 7, "text": "others."},
    ]
    r = repair_breaks(en, terms=["Dragonbone Hill"])
    assert r[0]["text"] == "He lived at Dragonbone Hill"
    assert r[1]["text"] == "in China about 700,000 years"
    assert r[3]["text"] == "with the others." and 0 < r[0]["end"] < 4
    zh = [{"start": 0, "end": 2, "text": "我们来到北京猿"}, {"start": 2, "end": 4, "text": "人遗址的"},
          {"start": 4, "end": 6, "text": "山洞里面看看吧"}]
    r = repair_breaks(zh, terms=["北京猿人"])
    assert "北京猿人" in r[0]["text"] and r[1]["text"] == "遗址的山洞" and r[2]["text"] == "里面看看吧"


TABLE = {
    "schema": SHOT_SCHEMA, "title": "t", "aspect": "9:16", "style": "documentary, natural",
    "characters": {"pm": {"name": "Peking Man", "look": "heavy brow ridge", "wardrobe": "animal hide"}},
    "locations": {"cave": {"name": "Dragonbone Hill cave", "look": "limestone cave", "light": "firelight from left"}},
    "shots": [
        {"id": "s1", "duration_s": 5, "camera": {"size": "WS", "angle": "eye-level", "move": "slow push-in"},
         "in_frame": ["pm"], "location": "cave", "positions": {"pm": "frame-left"},
         "action": "crouches by the fire", "gaze": "looks at the fire", "end_frame": "pm crouched, facing right"},
        {"id": "s2", "duration_s": 4, "camera": {"size": "CU", "angle": "low", "move": "static"},
         "in_frame": ["pm"], "location": "cave", "action": "strikes two stones", "continue_from": "s1",
         "end_frame": "sparks fall"},
    ],
}


def test_shot_table_compile_and_lock():
    assert validate_shot_table(TABLE) == []
    bad = json.loads(json.dumps(TABLE))
    bad["shots"][1]["camera"]["size"] = "huge"
    bad["shots"][1]["in_frame"] = ["ghost"]
    assert len(validate_shot_table(bad)) == 2
    p1 = compile_shot_prompt(TABLE["shots"][0], TABLE)
    p2 = compile_shot_prompt(TABLE["shots"][1], TABLE)
    assert p1["prompt"].endswith(p1["lock_line"]) and "heavy brow ridge" in p1["lock_line"]
    assert p1["lock_line"].replace("; frame-left", "") == p2["lock_line"]  # 同一人物/场景/光 → 同一 lock
    assert "camera movement" in p2["negative"]


def test_retake_single_variable_and_budget():
    s = TABLE["shots"][0]
    d1 = diagnose_retake(s, ["camera shake too strong"])
    assert d1["variable"] == "camera"
    s2 = apply_retake(s, d1)
    changed = [k for k in s if s[k] != s2.get(k)]
    assert changed == ["camera"] and s2["camera"]["move"] == "static"
    d2 = diagnose_retake(s2, ["camera shake still"], [{"variable": "camera"}])
    assert d2["variable"] != "camera"
    assert retake_budget([{}, {}, {}], max_per_shot=3)["allowed"] is False
    assert retake_budget([{}], total_used=12, max_total=12)["action"] == "accept_best"


def test_sequence_plan_chain():
    from hevi.avcraft.omodul.sequence_plan import record_take, sequence_plan

    st = sequence_plan(TABLE, max_per_shot=1)
    assert st["shots"]["s1"]["status"] == "ready" and st["shots"]["s2"]["status"] == "pending"
    st = record_take(st, "s1", False, ["extra person in background"])
    assert st["shots"]["s1"]["status"] == "retake" and "no other people" in st["shots"]["s1"]["prompt"]["prompt"]
    st = record_take(st, "s1", True, facts={"end_frame": "crouched by fire, right hand on stone"})
    assert st["shots"]["s2"]["status"] == "ready" and st["bible"]["version"] == 1
    assert "right hand on stone" in st["shots"]["s2"]["prompt"]["prompt"]
    st = record_take(st, "s2", False, ["face drift"])
    st = record_take(st, "s2", False, ["face drift"])
    assert st["shots"]["s2"]["status"] == "gave_up"


@pytest.fixture(scope="module")
def av(tmp_path_factory):
    d = tmp_path_factory.mktemp("p1")
    p = d / "v.mp4"
    # 0-1s 黑场，1-6s 测试图（3-6s 静止帧），带 6s 正弦音
    vf = "[0:v][1:v]concat=n=2:v=1:a=0[v]"
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25:d=1",
                    "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=5", "-f", "lavfi", "-i",
                    "sine=f=440:d=6", "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], check=True)
    cues = d / "c.json"
    cues.write_text(json.dumps({"cues": [
        {"id": 1, "start": 1.2, "end": 2.6, "text": "Hello Dragonbone", "tr": "你好"},
        {"id": 2, "start": 2.6, "end": 4.0, "text": "Hill world.", "tr": "世界"},
        {"id": 3, "start": 4.2, "end": 5.8, "text": "Bye now.", "tr": "再见"}]}))
    return p, cues


def test_edit_session_e2e(av, tmp_path):
    from hevi.avcraft.omodul.edit_session import export_session, init_session

    v, cues = av
    tl = init_session(v, cues, terms=["Dragonbone Hill"], visual=True)
    assert tl["cues"][0]["text"] == "Hello Dragonbone Hill"
    assert keep_ranges(tl)[0][0] >= 0.9  # 黑场被剪
    apply_ops(tl, [{"op": "delete", "cue": 3}])
    r = export_session(tl, tmp_path, stem="v")
    assert r["cues_out"] == 2 and 3.2 <= r["output_s"] <= 3.6, r
    kinds = [s["codec_type"] for s in list_streams(r["files"]["soft_mkv"])]
    assert kinds.count("subtitle") == 3
    assert [s["codec_name"] for s in list_streams(r["files"]["soft_mp4"]) if s["codec_type"] == "subtitle"] == [
        "mov_text", "mov_text"]
    assert probe_duration(r["files"]["burned"]) > 2.4
