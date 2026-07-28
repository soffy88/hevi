"""N0-D-033 子拍出画装配:显示拍切成 ~12s 子镜,每镜一画面/构图变化,跟旁白节奏走。
map/compare/choice/question/point 五类镜头;申生抉择点专用 choice(三条路)+question(换作是你)。
复用 s2_assemble 的 TTS/字幕/音频基建,只改「一拍一静图」为「多子镜」。零 provider。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "hevi/tongjian/sandbox")
import s2_assemble as A  # 复用 OUT/W/H/FPS/JIN/DUAL_BY/tts_beat/make_sub_png/_probe/音频

from hevi.tongjian.map_anim import animate_establish
from hevi.tongjian.modern_shots import (
    render_choice_card,
    render_modern_compare,
    render_point_card,
    render_question_card,
)

NET = Path(os.environ.get("S2_NET", "output/n0_s2_baihua/s1_full_clean_script.json"))
TARGET = 12.0  # 子镜目标时长(s)
ACCENTS = [(214, 69, 65), (54, 116, 217), (176, 132, 58)]  # 要点卡轮换强调色
KICKER = {
    "b0": "骊姬乱嫡的起点",
    "b1": "献公娶骊姬",
    "b2": "太子申生",
    "b3": "重耳与夷吾出逃",
    "b4": "晋国公室的崩坏",
    "b5": "卫国的镜鉴",
}


def _choices(text: str) -> list[str]:
    """从『…三条路——辩白自证、逃往别国，或者一死』精确解析(定位『三条路』之后)。"""
    m = re.search(r"三条路[——、，,：:\-]*(.+)", text)
    seg = m.group(1) if m else text
    parts = re.split(r"[、，,；]|或者", seg)
    parts = [
        re.sub(r"[。！？.\s]", "", p) for p in parts if len(re.sub(r"[。！？.\s]", "", p)) >= 2
    ]
    return parts[:3] or ["辩白自证", "逃往别国", "一死"]


def segment(net: dict) -> list[dict]:
    """净稿 vo 句 → 子镜列表(不跨显示拍;三条路/换作是你 单独成镜;其余按 ~TARGET 合并)。"""
    seq = []
    for b in net["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") == "onscreen":
                continue
            bid = re.match(r"b\d+", s["sid"]).group()
            seq.append((bid, s["text"]))
    shots, i, seen_compare = [], 0, set()
    while i < len(seq):
        bid, text = seq[i]
        if "三条路" in text:
            shots.append({"kind": "choice", "bid": bid, "vo": text})
            i += 1
            continue
        if "换作是你" in text:
            shots.append({"kind": "question", "bid": bid, "vo": text})
            i += 1
            continue
        acc, j = text, i + 1
        while (
            j < len(seq)
            and seq[j][0] == bid
            and "三条路" not in seq[j][1]
            and "换作是你" not in seq[j][1]
            and len(acc) / 5.0 < TARGET
        ):
            acc += seq[j][1]
            j += 1
        # 视觉类型:b0=map;dual拍首镜=compare(其余point);其它=point
        if bid == "b0":
            kind = "map"
        elif bid in A.DUAL_BY and bid not in seen_compare:
            kind = "compare"
            seen_compare.add(bid)
        else:
            kind = "point"
        shots.append({"kind": kind, "bid": bid, "vo": acc})
        i = j
    # 装配层稳定排序:按显示拍序 b0→b5(拍内顺序不变),理顺净稿里 b3 摘要早于 b2 的错位(不动净稿)。
    shots.sort(key=lambda s: int(s["bid"][1:]))
    return shots


def render(shot: dict, idx: int, dur: float, d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    k, bid = shot["kind"], shot["bid"]
    if k == "map":
        return animate_establish(A.JIN, d, duration_s=dur, fps=A.FPS)
    if k == "compare":
        return render_modern_compare(A.DUAL_BY[bid], d, size=(A.W, A.H), fps=A.FPS, duration_s=dur)
    if k == "choice":
        return render_choice_card(
            shot["vo"], _choices(shot["vo"]), d, size=(A.W, A.H), fps=A.FPS, duration_s=dur
        )
    if k == "question":
        q = "换作是你，会怎样选择？"
        return render_question_card(q, d, size=(A.W, A.H), fps=A.FPS, duration_s=dur)
    # point 卡只显**首句短标**(punchy),完整叙述交底部字幕,避免卡片与字幕重复。
    head = re.split(r"[。！？]", shot["vo"])[0][:22]
    return render_point_card(
        head,
        d,
        size=(A.W, A.H),
        fps=A.FPS,
        duration_s=dur,
        accent=ACCENTS[idx % 3],
        kicker=KICKER.get(bid, ""),
        variant=idx,
    )


def main():
    net = json.loads(NET.read_text())
    shots = segment(net)
    print(f"共 {len(shots)} 子镜:", [f"{s['bid']}:{s['kind']}" for s in shots], flush=True)
    root = A.OUT
    clips, vo_mp3s, edl, t = [], [], [], 0.0
    for idx, shot in enumerate(shots):
        d = root / f"shot{idx:02d}_{shot['bid']}_{shot['kind']}"
        d.mkdir(parents=True, exist_ok=True)
        vo, clip = d / "vo.mp3", d / "clip.mp4"
        dur = (
            max(A._probe(vo), 2.5)
            if vo.exists() and vo.stat().st_size > 500
            else max(asyncio.run(A.tts_beat(shot["vo"], vo)), 2.5)
        )
        vo_mp3s.append(vo)
        if not clip.exists():
            print(f"  子镜{idx:02d} {shot['bid']}/{shot['kind']} VO{dur:.1f}s → 渲染…", flush=True)
            raw = render(shot, idx, dur, d)
            sub = d / "sub.png"
            # question 镜留白不打底部字幕(画面已是大问);其余打白话字幕
            A.make_sub_png("" if shot["kind"] == "question" else shot["vo"], [], sub)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(raw),
                    "-i",
                    str(sub),
                    "-filter_complex",
                    "[0][1]overlay=0:0[v]",
                    "-map",
                    "[v]",
                    "-r",
                    str(A.FPS),
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    "18",
                    str(clip),
                ],
                check=True,
            )
        clips.append(clip)
        edl.append(
            {
                "shot": idx,
                "beat": shot["bid"],
                "kind": shot["kind"],
                "start_s": round(t, 2),
                "dur_s": round(dur, 2),
            }
        )
        t += dur

    (root / "clips.txt").write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    video = root / "video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(root / "clips.txt"),
            "-c",
            "copy",
            str(video),
        ],
        check=True,
    )
    (root / "vo.txt").write_text("".join(f"file '{c.resolve()}'\n" for c in vo_mp3s))
    vo_all = root / "vo_all.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(root / "vo.txt"),
            "-c:a",
            "aac",
            str(vo_all),
        ],
        check=True,
    )
    audio = root / "audio.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(vo_all),
            "-stream_loop",
            "-1",
            "-i",
            A.BGM,
            "-filter_complex",
            "[1:a]volume=0.09[bg];[0:a][bg]amix=inputs=2:duration=first:normalize=0[a]",
            "-map",
            "[a]",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )
    seg = root / "s2_liji_segment.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(seg),
        ],
        check=True,
    )
    (root / "edl.json").write_text(
        json.dumps(
            {
                "episode": "ep_jin_decline_s2",
                "version": "s2-N9-shots",
                "total_s": round(t, 2),
                "n_shots": len(shots),
                "beats": edl,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    durs = {}
    for e in edl:
        durs.setdefault(e["beat"], 0.0)
        durs[e["beat"]] += e["dur_s"]
    from collections import Counter

    print(f"\n成片段 → {seg}  ({A._probe(seg):.1f}s)")
    print("每显示拍子镜数:", dict(Counter(e["beat"] for e in edl)))
    print("每拍时长:", {k: round(v) for k, v in durs.items()})
    print("子镜时长分布:", [round(e["dur_s"]) for e in edl])


if __name__ == "__main__":
    main()
