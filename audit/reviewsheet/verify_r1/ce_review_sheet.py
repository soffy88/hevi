"""核验员反例脚本：review_sheet（K2 验收 1）。

真跑 hevi.kids.review_sheet，用像素检测独立数格子、查溢出/崩溃/确定性。
输出 results_review_sheet.json，图放 sheets/。
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import traceback
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from hevi.kids import review_sheet as rs
from hevi.kids.manifest_adapter import draft_manifest, load_manifest

OUT = Path(__file__).resolve().parent
SHEETS = OUT / "sheets"
SHEETS.mkdir(parents=True, exist_ok=True)
KF = OUT / "kf"
KF.mkdir(exist_ok=True)

PANEL_BG = np.array(rs.PANEL_BG)
ACCENT = np.array(rs.ACCENT)
BG = np.array(rs.BG)
TEXT = np.array(rs.TEXT)

LONG_LINE = "小狐狸说：今晚的星星真亮呀，我们一起把亮晶晶的星星分享给森林里所有的好朋友吧！"


def mk_kf(i: int, color: tuple[int, int, int]) -> str:
    p = KF / f"kf_{i}.png"
    if not p.exists():
        Image.new("RGB", (320, 568), color).save(p)
    return str(p)


def make_manifest(n: int, *, keyframes: bool = True, long_line: bool = False, title="小狐狸与星星",
                  durations=None) -> dict:
    shots = []
    for i in range(1, n + 1):
        d = durations[i - 1] if durations else 3.5 + (i % 3) * 0.25
        shots.append({
            "shot_index": i,
            "duration": d,
            "line": (LONG_LINE if long_line else f"第{i}镜台词：星星亮"),
            "camera": "缓慢推近" if i % 2 else "固定机位",
            "framing": "中景",
            "keyframe": (mk_kf(i, ((i * 40) % 255, 120, 200)) if keyframes and i % 3 != 0 else None),
            "shot_spec": {"transition_in": "fade", "effect": "warm", "duration": d},
        })
    return {
        "schema_version": "1.0", "episode": 1, "title": title,
        "theme": {"one_line": "分享让快乐变大"},
        "style_bible": {"art_style": "a", "camera_language": "b", "color_grade": "c", "negative": "d"},
        "transition_table": [{"cut": f"S{i}->S{i+1}"} for i in range(1, n)],
        "spoken_language": [{"shot_index": i, "language": "zh-CN"} for i in range(1, n + 1)],
        "shots": shots,
    }


def count_panels(img: Image.Image) -> int:
    """独立计数：ACCENT 色描边围成的面板外框连通域数量。"""
    a = np.asarray(img).astype(int)
    mask = (np.abs(a - ACCENT).sum(axis=2) <= 6)
    lab, n = ndimage.label(mask)
    # 只算尺寸像面板外框的连通域（宽高都 >40px），排除 S{n} 文字（同为 ACCENT 色）
    sl = ndimage.find_objects(lab)
    big = 0
    for s in sl:
        h = s[0].stop - s[0].start
        w = s[1].stop - s[1].start
        if h > 40 and w > 40:
            big += 1
    return big


def text_overflow(img: Image.Image, cols: int) -> dict:
    """检查文字是否越出格子/画布：
    - grid 区（去掉 40px 页脚）：格间隙列（正常为纯 BG）出现亮像素 = 台词/机位越格；
      最右 2 列出现亮像素 = 被画布截断；
    - 页脚区：最右 2 列出现亮像素 = 页脚被截断。"""
    a = np.asarray(img).astype(int)
    h, w, _ = a.shape
    footer_h = 40
    grid = a[: h - footer_h]
    foot = a[h - footer_h:]
    cell_w = w // cols
    bright = (grid.sum(axis=2) > 400)
    gap = 0
    for c in range(1, cols):
        x = c * cell_w
        gap += int(bright[:, x - 2:x + 2].sum())
    return {
        "grid_gap_px": gap,
        "grid_right_edge_px": int(bright[:, w - 2:].sum()),
        "footer_right_edge_px": int((foot.sum(axis=2) > 400)[:, w - 2:].sum()),
    }


def run_case(name: str, data: dict, aspect: str, expect_cells: int | None, results: list,
             *, expect_crash_ok=False, use_load=False):
    rec = {"case": name, "aspect": aspect, "n_shots": len(data["shots"]), "expect_cells": expect_cells}
    out = SHEETS / f"{name}_{aspect.replace(':', 'x')}.png"
    try:
        if use_load:
            mp = OUT / f"{name}.manifest.json"
            mp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            m = load_manifest(mp)
        else:
            m = draft_manifest(data)
        p = rs.render_review_sheet(m, out, aspect)
        sha1 = rs.review_sheet_sha256(p)
        p2 = rs.render_review_sheet(m, out.with_name(out.stem + "_again.png"), aspect)
        sha2 = rs.review_sheet_sha256(p2)
        out.with_name(out.stem + "_again.png").unlink()
        img = Image.open(p).convert("RGB")
        cells = count_panels(img)
        ov = text_overflow(img, rs._SHEET_COLS[aspect])
        rec.update({"ok": True, "png": str(p), "sha256": sha1, "deterministic": sha1 == sha2,
                    "size": img.size, "cells_detected": cells, "overflow": ov})
        ok = True
        why = []
        if expect_cells is not None and cells != expect_cells:
            ok = False
            why.append(f"格数 {cells} != {expect_cells}")
        if sha1 != sha2:
            ok = False
            why.append("两次 SHA 不一致")
        if any(v > 0 for v in ov.values()):
            ok = False
            why.append(f"文字溢出格子/画布 {ov}")
        rec["verdict"] = "PASS" if ok else "LEAK"
        if expect_crash_ok:
            ok = False
            why.append("应被拒绝却正常渲染")
            rec["verdict"] = "LEAK(accepted)"
        rec["why"] = why
    except Exception as e:  # noqa: BLE001
        rec.update({"ok": False, "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-600:]})
        rec["verdict"] = "PASS(rejected)" if expect_crash_ok else "LEAK(crash)"
    results.append(rec)
    print(json.dumps({k: rec.get(k) for k in ("case", "aspect", "verdict", "cells_detected", "why", "error")},
                     ensure_ascii=False))


def main():
    results: list = []
    for n in (1, 2, 3, 4, 5, 6, 7, 9, 12, 16, 20, 30):
        for aspect in ("9:16", "16:9"):
            run_case(f"n{n:02d}", make_manifest(n), aspect, n, results)
    # 长台词：截断应保证不溢出
    for aspect in ("9:16", "16:9"):
        run_case("longline_n6", make_manifest(6, long_line=True), aspect, 6, results)
        run_case("longline_n2", make_manifest(2, long_line=True), aspect, 2, results)
    # 超长标题 → 页脚溢出
    for aspect in ("9:16", "16:9"):
        run_case("longtitle_n6", make_manifest(6, title="小狐狸与星星之森林里最亮的那颗星星和所有好朋友的分享大冒险特别篇"),
                 aspect, 6, results)
    # 全部缺关键帧 / 关键帧损坏 / 关键帧是目录
    d = make_manifest(6, keyframes=False)
    run_case("nokf_n6", d, "9:16", 6, results)
    d = make_manifest(6)
    bad = KF / "corrupt.png"
    bad.write_bytes(b"not a png at all")
    d["shots"][0]["keyframe"] = str(bad)
    d["shots"][1]["keyframe"] = str(KF)
    d["shots"][2]["keyframe"] = "/nonexistent/x.png"
    run_case("badkf_n6", d, "16:9", 6, results)
    # 时长精度：3.456 → 3.46（±0.05 内）
    run_case("dur_precision", make_manifest(4, durations=[2.504, 3.456, 9.999, 4.0]), "16:9", 4, results)
    # 重复镜号（manifest 应被拒）
    d = make_manifest(4)
    d["shots"][2]["shot_index"] = 2
    run_case("dup_shot_index_via_load", d, "16:9", None, results, expect_crash_ok=True, use_load=True)
    # 非法 aspect
    run_case("bad_aspect", make_manifest(3), "1:1", None, results, expect_crash_ok=True)
    # 空 shots
    d = make_manifest(1)
    d["shots"] = []
    run_case("empty_shots", d, "9:16", None, results, expect_crash_ok=True)
    # 真实关键帧必须贴进缩略图（不是一律占位）
    for aspect in ("9:16", "16:9"):
        d = make_manifest(2)
        kfp = KF / "solid_red.png"
        Image.new("RGB", (320, 568), (200, 40, 40)).save(kfp)
        for sh in d["shots"]:
            sh["keyframe"] = str(kfp)
        rec = {"case": "keyframe_pasted", "aspect": aspect}
        out = SHEETS / f"keyframe_pasted_{aspect.replace(':', 'x')}.png"
        rs.render_review_sheet(draft_manifest(d), out, aspect)
        a = np.asarray(Image.open(out).convert("RGB")).astype(int)
        cols = rs._SHEET_COLS[aspect]
        cw = a.shape[1] // cols
        cy = (a.shape[0] - 40) // 2
        px = a[cy, cw // 2].tolist()
        red_px = int(((np.abs(a - np.array([200, 40, 40])).sum(axis=2)) < 30).sum())
        rec.update({"center_px": px, "red_px": red_px, "png": str(out)})
        rec["verdict"] = "PASS" if red_px > 1000 else "LEAK"
        rec["why"] = [] if red_px > 1000 else ["关键帧存在且可解码，但缩略图区一律画成「无关键帧」灰底（ImageDraw.bitmap 对 RGB 图抛 bad transparency mask 被吞）"]
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False))
    (OUT / "results_review_sheet.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    leaks = [r for r in results if r["verdict"].startswith("LEAK")]
    print(f"TOTAL {len(results)} LEAK {len(leaks)}")


if __name__ == "__main__":
    main()
