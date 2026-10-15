"""核验员反例脚本：kids_gate 扩展（K2 验收 3）。

1) 真实 CPU 渲染片（handdraw / scene3d 产物，只读引用）跑原门 + 扩展门：原 6 项判定必须一致，
   扩展门对合规片不得误报。
2) 用真实 ffmpeg/PIL 从真实片构造坏样本：低饱和发灰、成人文字残留、空画面/空星海、色温跳变、
   服装色块跳变、色相漂移；扩展门必须 red 且给出落在坏区间内的时间码。
单进程，逐个跑。输出 results_kids_gate.json。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

from PIL import Image, ImageDraw

from hevi.kids.fonts import cjk_font
from hevi.quality.kids_gate import kids_gate_extended, kids_gate_workflow, CHECKLIST_ITEMS

OUT = Path(__file__).resolve().parent
S = OUT / "samples"
S.mkdir(exist_ok=True)

REAL = {
    "handdraw_P1_9x16": "/data/soffy/projects/hevi-handdraw/.tmp/vr2/runs/P_1/outputs/film.mp4",
    "handdraw_L1_16x9": "/data/soffy/projects/hevi-handdraw/.tmp/vr2/runs/L_1/outputs/film.mp4",
    "scene3d_fox_wheat_9x16": "/data/soffy/projects/hevi-scene3d/output/scene3d_r1b/fox_wheat_9x16/fox_in_wheat.mp4",
    "scene3d_star_sea_9x16": "/data/soffy/projects/hevi-scene3d/output/scene3d_r1b/star_sea_9x16/through_star_sea.mp4",
}
ORIG6 = ["shot_duration_min", "shot_duration_avg", "photosensitive_flash", "loudness",
         "speech_rate", "subtitle_fontsize", "dialogue_content"]


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-threads", "2", *args], check=True)


def build_samples():
    src = REAL["handdraw_P1_9x16"]
    base = S / "base16.mp4"
    if not base.exists():
        # 真实片 16s 摘段，降到 540x960，保留真实音轨
        # 音轨 loudnorm 到 -16 LUFS，使原 6 项能 PASS，扩展项的判定才可单独观察
        ff("-ss", "10", "-t", "16", "-i", src, "-vf", "scale=540:960", "-af", "loudnorm=I=-16:TP=-2:LRA=7",
           "-ar", "48000", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(base))
    out = {}
    out["control_base16"] = (base, None)

    def fx(name, vf, window):
        p = S / f"{name}.mp4"
        if not p.exists():
            ff("-i", str(base), "-filter_complex", vf, "-map", "[v]", "-map", "0:a", "-c:v", "libx264",
               "-preset", "veryfast", "-c:a", "copy", str(p))
        out[name] = (p, window)

    fx("gray_full", "[0:v]hue=s=0.12[v]", (0, 16))
    fx("gray_second_half", "[0:v]split[a][b];[a]trim=0:8,setpts=PTS-STARTPTS[a1];"
       "[b]trim=8:16,setpts=PTS-STARTPTS,hue=s=0.1[b1];[a1][b1]concat=n=2:v=1:a=0[v]", (8, 16))
    fx("temp_jump", "[0:v]split[a][b];[a]trim=0:8,setpts=PTS-STARTPTS,colortemperature=temperature=4500[a1];"
       "[b]trim=8:16,setpts=PTS-STARTPTS,colortemperature=temperature=11000[b1];[a1][b1]concat=n=2:v=1:a=0[v]",
       (7.5, 9))
    fx("hue_drift_half", "[0:v]split[a][b];[a]trim=0:8,setpts=PTS-STARTPTS[a1];"
       "[b]trim=8:16,setpts=PTS-STARTPTS,hue=h=100[b1];[a1][b1]concat=n=2:v=1:a=0[v]", (7.5, 9))

    # 成人文字残留："深入机制分析"（PIL 烧字，ffmpeg overlay，4–12s）
    tp = S / "adult_text.png"
    if not tp.exists():
        img = Image.new("RGBA", (540, 960), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        f = cjk_font(56)
        d.rectangle((20, 80, 520, 170), fill=(0, 0, 0, 160))
        d.text((40, 90), "深入机制分析", fill=(255, 255, 255, 255), font=f)
        d.text((40, 820), "第三章 宏观经济传导", fill=(255, 255, 255, 255), font=cjk_font(36))
        img.save(tp)
    p = S / "adult_text.mp4"
    if not p.exists():
        ff("-i", str(base), "-i", str(tp), "-filter_complex",
           "[0:v][1:v]overlay=0:0:enable='between(t,4,12)'[v]", "-map", "[v]", "-map", "0:a",
           "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy", str(p))
    out["adult_text_4_12"] = (p, (4, 12))

    # 空画面 / 空星海：前 8s 真实，后 8s 近黑底 + 稀疏星点
    star = S / "starfield.png"
    if not star.exists():
        img = Image.new("RGB", (540, 960), (6, 8, 20))
        d = ImageDraw.Draw(img)
        import random
        rnd = random.Random(7)
        for _ in range(40):
            x, y = rnd.randrange(540), rnd.randrange(960)
            d.ellipse((x, y, x + 2, y + 2), fill=(230, 230, 255))
        img.save(star)
    p = S / "empty_star_second_half.mp4"
    if not p.exists():
        ff("-i", str(base), "-loop", "1", "-t", "8", "-r", "25", "-i", str(star), "-filter_complex",
           "[0:v]trim=0:8,setpts=PTS-STARTPTS,fps=25,format=yuv420p[a];[1:v]scale=540:960,fps=25,format=yuv420p,setsar=1[b];"
           "[a]setsar=1[a2];[a2][b]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "0:a",
           "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy", "-t", "16", str(p))
    out["empty_star_8_16"] = (p, (8, 16))
    p = S / "empty_black_full.mp4"
    if not p.exists():
        ff("-f", "lavfi", "-i", "color=c=0x05060A:s=540x960:r=25:d=16", "-i", str(base), "-map", "0:v",
           "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy", "-t", "16", str(p))
    out["empty_black_full"] = (p, (0, 16))

    # 服装跳变：真实背景帧 + 同一角色（圆头+身体），身体颜色 0–8s 红、8–16s 绿（约 8% 画面）
    bg = S / "bgframe.png"
    if not bg.exists():
        ff("-ss", "3", "-i", str(base), "-frames:v", "1", str(bg))
    for tag, col in (("red", (220, 40, 40)), ("green", (40, 180, 60))):
        fp = S / f"char_{tag}.png"
        if not fp.exists():
            img = Image.open(bg).convert("RGB")
            d = ImageDraw.Draw(img)
            d.ellipse((210, 380, 330, 500), fill=(250, 210, 170))  # 头
            d.rectangle((195, 500, 345, 700), fill=col)  # 衣服
            img.save(fp)
    p = S / "wardrobe_jump.mp4"
    if not p.exists():
        ff("-loop", "1", "-t", "8", "-r", "25", "-i", str(S / "char_red.png"),
           "-loop", "1", "-t", "8", "-r", "25", "-i", str(S / "char_green.png"), "-i", str(base),
           "-filter_complex", "[0:v]format=yuv420p,setsar=1[a];[1:v]format=yuv420p,setsar=1[b];"
           "[a][b]xfade=transition=fade:duration=0.5:offset=7.75[v]",
           "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy",
           "-t", "15.5", str(p))
    out["wardrobe_jump_8"] = (p, (7, 9))
    return out


SRT = OUT / "clean_kids.srt"
SRT.write_text("1\n00:00:00,000 --> 00:00:16,000\n小狐狸抬头看星星，星星真亮呀。\n", encoding="utf-8")


def run_gate(path: Path):
    # 显式给干净 SRT：原门在无 SRT 时会把 mp4 二进制当台词扫禁用词（既有缺陷，见 REPORT），这里排除其干扰
    t0 = time.time()
    w = kids_gate_workflow(path, srt_path=SRT)
    t1 = time.time()
    e = kids_gate_extended(path, srt_path=SRT)
    t2 = time.time()
    return w, e, round(t1 - t0, 1), round(t2 - t1, 1)


def main():
    only = set(sys.argv[1:])
    results = []
    resf = OUT / "results_kids_gate.json"
    if resf.exists():
        results = json.loads(resf.read_text(encoding="utf-8"))
    done = {r["sample"] for r in results}

    jobs = []
    for k, v in REAL.items():
        # through_star_sea 是近期核验点名的"空星海/发灰"真实片：只观察，不计误报也不计漏放
        jobs.append((k, Path(v), None, "observe" if "star_sea" in k else "good_real"))
    for k, (p, win) in build_samples().items():
        jobs.append((k, p, win, "control" if win is None else "bad"))

    for name, path, win, kind in jobs:
        if name in done or (only and name not in only):
            continue
        rec = {"sample": name, "path": str(path), "kind": kind, "bad_window_s": win}
        try:
            w, e, tw, te = run_gate(path)
            rec["secs"] = {"orig": tw, "ext": te}
            rec["orig_status"] = w["status"]
            rec["orig_checklist"] = w.get("checklist")
            rec["ext_status"] = e["status"]
            rec["ext_checklist"] = e["checklist"]
            rec["ext_violations"] = e["violations"]
            rec["ext_timecodes"] = e["timecodes"]
            rec["ext_metrics"] = {k: e["metrics"].get(k) for k in (
                "identity_max_color_diff", "color_grade_max_ratio_jump", "detected_cuts",
                "min_shot_duration", "integrated_lufs", "flashes_per_second", "forbidden_words_found")}
            problems = []
            # 原 6 项一致性（不误伤）
            for k in ORIG6:
                if (w.get("checklist") or {}).get(k) != e["checklist"].get(k):
                    problems.append(f"原项 {k} 判定不一致 orig={w['checklist'].get(k)} ext={e['checklist'].get(k)}")
            if set(e["checklist"]) != set(CHECKLIST_ITEMS):
                problems.append("checklist 不完整")
            new_fail = [k for k, v in e["checklist"].items() if k not in ORIG6 and v == "fail"]
            rec["ext_new_fails"] = new_fail
            if kind == "observe":
                rec["verdict"] = "OBSERVE"
            elif kind in ("good_real", "control"):
                if new_fail:
                    problems.append(f"合规真实片被扩展项误报: {new_fail}")
                rec["verdict"] = "PASS" if not problems else "FALSE_POSITIVE"
            else:
                tcs = [t.get("time") for t in e["timecodes"] if isinstance(t.get("time"), (int, float))]
                ext_tcs = [t.get("time") for t in e["timecodes"]
                           if t.get("item") not in ("shot_duration", "flash") and isinstance(t.get("time"), (int, float))]
                in_win = [t for t in ext_tcs if win[0] - 0.6 <= t <= win[1] + 0.6]
                if not new_fail:
                    problems.append("坏样本扩展项未红灯（漏放）")
                elif not in_win:
                    problems.append(f"红灯但无落在坏区间 {win} 的时间码: {ext_tcs}")
                rec["verdict"] = "PASS" if not problems else "LEAK"
            rec["problems"] = problems
        except Exception as ex:  # noqa: BLE001
            rec["verdict"] = "ERROR"
            rec["error"] = f"{type(ex).__name__}: {ex}"
            rec["trace"] = traceback.format_exc()[-800:]
        results.append(rec)
        resf.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps({k: rec.get(k) for k in ("sample", "kind", "verdict", "ext_status", "ext_new_fails",
                                                    "problems", "secs", "error")}, ensure_ascii=False), flush=True)
    print("ALLDONE", flush=True)


if __name__ == "__main__":
    main()
