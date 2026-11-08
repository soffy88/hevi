"""avcraft P1 剩余项测试：多信号高光、横转竖平滑轨迹、moderation 预审、init_session 开放参数。
CPU + ffmpeg 合成素材；人脸检测仅在本机已有 YuNet 时跑（不下载）。"""

import json
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

pytest.importorskip("hevi.avcraft.oskill.shotprompt")  # deferred at admission 2026-11-04 (origin/main)

from hevi.avcraft.obase.media import ffmpeg_bin, ffprobe_bin, probe_duration
from hevi.avcraft.oskill.highlight import (
    candidate_windows,
    highlights_to_timeline,
    score_highlights,
)
from hevi.avcraft.oskill.moderation import moderation_prescreen
from hevi.avcraft.oskill.reframe import (
    crop_size,
    per_frame_x,
    pick_targets,
    sendcmd_script,
    smooth_crop_path,
)
from hevi.avcraft.oskill.shotprompt import compile_shot_prompt
from hevi.avcraft.oskill.timeline import keep_ranges, render_cues, timeline_from_cues


def _cues(n=12, d=4.0):
    out = []
    for i in range(n):
        txt = f"Line number {i} is plain and calm."
        if i == 6:
            txt = "But here is the secret nobody tells you about this."
        if i == 7:
            txt = "The truth is it changed everything for a million people!"
        if i == 3:
            txt = "and then it continued without a stop"
        out.append({"id": i + 1, "start": i * d, "end": i * d + d - 0.3, "text": txt})
    return out


def test_highlight_sentence_aligned_reasons_and_signals():
    cs = _cues()
    audio = [(t * 0.5, -30.0 + (12.0 if 24 <= t * 0.5 < 32 else 0.0)) for t in range(96)]
    motion = [(t * 0.5, 0.02 + (0.08 if 24 <= t * 0.5 < 32 else 0.0)) for t in range(96)]
    hs = score_highlights(cs, audio=audio, motion=motion, scenes=[25.0, 27.0, 29.0], keywords=["secret"],
                          top_n=2, min_len=7.0, max_len=12.0)
    assert len(hs) == 2 and hs[0]["rank"] == 1
    starts = {c["start"] for c in cs}
    ends = {c["end"] for c in cs}
    for h in hs:  # 边界对齐整句
        assert h["start"] in starts and h["end"] in ends
        assert 7.0 <= h["duration"] <= 12.0 and h["reasons"]
    top = hs[0]
    assert top["start"] <= 24.0 and top["end"] >= 31.0  # 高能量+关键词段胜出
    assert any("音量" in r for r in top["reasons"]) and any("secret" in r for r in top["reasons"])
    assert any("运动" in r for r in top["reasons"]) and any("场景" in r for r in top["reasons"])
    assert min(hs[0]["end"], hs[1]["end"]) - max(hs[0]["start"], hs[1]["start"]) <= 0  # 不重叠
    # 连接词开头的句子不应作为片段起点获得完整性分
    w = [h for h in score_highlights(cs, top_n=20, min_len=7, max_len=12) if h["cue_ids"][0] == 4]
    assert all(h["features"]["complete"] <= 0.5 for h in w)


def test_highlight_missing_signals_and_short_video():
    cs = _cues(3, 3.0)
    assert candidate_windows(cs, min_len=30) == [(0, 2)]
    hs = score_highlights(cs, top_n=3, min_len=30)
    assert len(hs) == 1 and hs[0]["cue_ids"] == [1, 2, 3]
    assert "loud" not in hs[0]["features"] and "motion" not in hs[0]["features"]


def test_highlight_into_timeline_and_render():
    cs = _cues()
    hs = score_highlights(cs, top_n=2, min_len=7.0, max_len=12.0, keywords=["secret"])
    tl = highlights_to_timeline(timeline_from_cues(cs, 48.0), hs)
    kr = keep_ranges(tl)
    assert len(kr) == 2 and sum(b - a for a, b in kr) == pytest.approx(sum(h["duration"] for h in hs), abs=0.01)
    assert next(m for m in tl["markers"] if m["kind"] == "highlight")["reasons"]
    one = highlights_to_timeline(timeline_from_cues(cs, 48.0), hs, only=1)
    sub = render_cues(one)
    assert len(sub) == len(hs[0]["cue_ids"]) and sub[0]["start"] == pytest.approx(0.0, abs=0.01)


def test_reframe_face_then_hold_then_motion_then_center_and_smooth():
    W, H = 1920, 1080
    cw, ch = crop_size(W, H)
    assert (cw, ch) == (606, 1080)
    samples = []
    for i in range(40):
        t = i * 0.25
        s = {"t": t, "motion": 0.0, "mx": 0.5, "faces": []}
        if t < 3:
            s["faces"] = [(1400, 300, 200, 200, 0.9), (200, 400, 80, 80, 0.7)]  # 大脸在右
        elif 5 <= t < 7:
            s["motion"], s["mx"] = 0.05, 0.2
        samples.append(s)
    tg = pick_targets(samples, W, H, hold_s=1.0)
    srcs = [x["src"] for x in tg]
    assert srcs[0] == "face" and "hold" in srcs and "motion" in srcs and srcs[-1] == "center"
    assert tg[0]["x"] == pytest.approx(1500)
    path = smooth_crop_path(tg, W, cw, alpha=0.3, max_speed=0.3)
    assert all(0 <= p["x0"] <= W - cw for p in path)
    steps = [abs(b["x0"] - a["x0"]) for a, b in pairwise(path)]
    assert max(steps) <= 0.3 * W * 0.25 + 1  # 速度上限
    # 死区：目标微抖不移动
    jit = [{"t": i * 0.25, "x": 960 + (10 if i % 2 else -10), "src": "face"} for i in range(20)]
    assert len({p["x0"] for p in smooth_crop_path(jit, W, cw)}) == 1
    # 说话人：两张同样大的脸，嘴部活动大的那张胜出
    two = [{"t": 0.0, "motion": 0, "faces": [(300, 300, 150, 150, 0.9, 0.0), (1400, 300, 150, 150, 0.9, 0.08)]}]
    assert pick_targets(two, W, H)[0]["x"] == pytest.approx(1475)
    fr = per_frame_x(path, 25, 10.0)
    assert len(fr) == 251 and all(x % 2 == 0 for _, x in fr)
    assert sendcmd_script(fr).count("crop x") <= len(fr)


def test_moderation_prescreen_rules_and_rewrite():
    r = moderation_prescreen("A close-up of the bloody knife, then Spider-Man walks in. 背景有可口可乐广告。")
    cats = {h["category"] for h in r["hits"]}
    assert {"blood", "weapon", "ip_brand"} <= cats and r["risk"] == "medium" and not r["ok"]
    assert "Spider-Man" not in r["rewritten"] and "可口可乐" not in r["rewritten"] and "bloody" not in r["rewritten"]
    assert "the red-stained prop tool" == moderation_prescreen("the bloody knife")["rewritten"]
    assert moderation_prescreen("他拿着匕首，地上有血迹")["rewritten"] == "他拿着道具，地上有暗红色痕迹"
    assert moderation_prescreen("A calm sunrise over the lake.")["risk"] == "none"
    k = moderation_prescreen("The chef picks up a knife.", allow=["knife"])
    assert k["risk"] == "none"
    m = moderation_prescreen("a naked child")
    assert not m["ok"] and m["risk"] == "high" and any("未成年" in n for n in m["notes"])
    c = moderation_prescreen("Brand Zeta logo", extra_terms={"brand zeta": "a generic logo"})
    assert c["rewritten"] == "a generic logo logo" and c["hits"][0]["category"] == "custom"


def test_moderation_wired_into_shotprompt():
    tbl = {"aspect": "9:16", "characters": {"a": {"name": "Lin", "look": "short hair"}},
           "locations": {"k": {"name": "kitchen", "look": "tiled", "light": "soft window light"}}}
    shot = {"id": "s1", "in_frame": ["a"], "location": "k", "camera": {"size": "ms", "move": "static"},
            "action": "Lin wipes blood from the knife", "end_frame": "Lin looks up", "duration_s": 5}
    p = compile_shot_prompt(shot, tbl)
    assert p["moderation"]["risk"] == "medium" and "rewritten" in p["moderation"]
    assert "blood" in p["prompt"]  # 默认只提示不改
    p2 = compile_shot_prompt(shot, tbl, auto_rewrite=True, moderation_opts={"allow": ["knife"]})
    assert "blood" not in p2["prompt"] and "knife" in p2["prompt"] and p2["prompt_original"]
    assert "moderation" not in compile_shot_prompt(shot, tbl, prescreen=False)


def test_init_session_open_params(tmp_path):
    from hevi.avcraft.omodul.edit_session import init_session, visual_detect_params

    assert visual_detect_params(scene_threshold=5, still_sensitivity="high", still_min=1.0) == {
        "scene_th": 5.0, "freeze_noise_db": -46.0, "freeze_min": 1.0}
    assert visual_detect_params(still_sensitivity=0.0)["freeze_noise_db"] == -70.0
    with pytest.raises(ValueError):
        visual_detect_params(still_sensitivity="extreme")
    v = tmp_path / "v.mp4"
    # 0-2s 测试图（动），2-5s 静帧，5-7s 动
    subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=2",
                    "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=25:d=3", "-f", "lavfi",
                    "-i", "testsrc2=s=320x180:r=25:d=2", "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(v)], check=True)
    cues = [{"id": 1, "start": 0.2, "end": 1.5, "text": "Hi."}, {"id": 2, "start": 5.2, "end": 6.5, "text": "Bye."}]
    tl = init_session(v, cues, visual=True, repair=False, scene_threshold=8, still_sensitivity="medium",
                      still_min=1.0)
    assert tl["params"]["visual_detect"]["scene_th"] == 8.0
    assert tl["params"]["visual_detect"]["freeze_noise_db"] == -55.0
    kept = sum(b - a for a, b in keep_ranges(tl))
    assert kept < probe_duration(v) - 1.0  # 静帧段被剪
    tl2 = init_session(v, cues, visual=True, repair=False, still_min=5.0)
    assert sum(b - a for a, b in keep_ranges(tl2)) == pytest.approx(probe_duration(v), abs=0.05)


def test_reframe_vertical_e2e_no_face_fallback(tmp_path):
    pytest.importorskip("cv2")
    from hevi.avcraft.omodul.reframe_vertical import reframe_vertical

    v = tmp_path / "wide.mp4"
    # 一个白块从左移到右（运动显著区），无人脸
    subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=3",
                    "-f", "lavfi", "-i", "color=c=white:s=60x60:r=25:d=3", "-filter_complex",
                    "[0][1]overlay=x='20+t*180':y=150", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(v)],
                   check=True)
    r = reframe_vertical(v, tmp_path / "v.mp4", cues=[{"id": 1, "start": 0.2, "end": 2.5, "text": "Move."}],
                         size=(270, 480), faces=False, smooth={"alpha": 0.5, "max_speed": 0.8})
    assert r["out_size"] == [270, 480] and r["stats"]["sources"].get("motion", 0) > 0
    xs = [p["x0"] for p in json.loads(Path(r["files"]["crop_path"]).read_text())["path"]]
    assert xs[-1] > xs[1]  # 跟随向右
    out = subprocess.run([ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0", r["files"]["burned"]],
                         capture_output=True, text=True).stdout.strip()
    assert out == "270,480"
