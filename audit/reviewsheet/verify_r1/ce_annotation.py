"""核验员反例脚本：annotation_revision（K2 验收 2）。

每个用例写明期望（expect）：
  patch_only:<fields>  —— 出 patch，changes 键恰为这些，且 apply 后其余字段 JSON 字节不变、
                          且 merge_patch(ShotSpec 校验器) 能通过
  advisory_only        —— changes 为空，advisory 非空
  reject               —— 必须抛异常（AnnotationError/AnnotationRejected/ValueError/ValidationError…）
  clarify              —— 必须抛 AnnotationTemporalClarification，不出 patch
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import traceback
from pathlib import Path

from PIL import Image

from hevi.kids import annotation_revision as ar
from hevi.kids.manifest_adapter import draft_manifest, load_manifest
from hevi.production.shot_spec import ShotSpec, merge_patch

OUT = Path(__file__).resolve().parent
M = ar.AnnotationMark


def base_manifest(n=5):
    shots = []
    for i in range(1, n + 1):
        shots.append({
            "shot_index": i, "duration": 4.0, "line": f"第{i}镜", "camera": "缓慢推近", "framing": "中景",
            "shot_spec": {"template": None, "transition_in": "fade", "effect": "warm", "style": "soft",
                          "sfx": [], "camera": "slow_push_in", "subtitle_style": "kids_large",
                          "duration": 4.0},
        })
    return {
        "schema_version": "1.0", "episode": 1, "title": "t", "theme": {"one_line": "x"},
        "style_bible": {"art_style": "a", "camera_language": "b", "color_grade": "c", "negative": "d"},
        "transition_table": [{"cut": f"S{i}->S{i+1}"} for i in range(1, n)],
        "spoken_language": [{"shot_index": i, "language": "zh-CN"} for i in range(1, n + 1)],
        "shots": shots,
    }


MAN = draft_manifest(base_manifest())
SPEC3 = MAN.shot(3).spec()  # S3 窗口 [8000, 12000] ms


def check(name, expect, fn, results):
    rec = {"case": name, "expect": expect}
    try:
        patch, spec = fn()
        d = patch.to_dict()
        rec["patch"] = d
        problems = []
        if expect in ("reject", "clarify"):
            problems.append(f"期望 {expect}，实际出了 patch")
        elif expect == "advisory_only":
            if d["changes"]:
                problems.append(f"changes 应为空，实际 {d['changes']}")
            if not d["advisory"]:
                problems.append("advisory 应非空（静默丢弃了标注）")
        elif expect.startswith("patch_only:"):
            want = set(expect.split(":", 1)[1].split(","))
            if set(d["changes"]) != want:
                problems.append(f"changes 键 {sorted(d['changes'])} != {sorted(want)}")
            applied = ar.apply_patch(spec, patch)
            for k in spec:
                if k not in want and json.dumps(spec[k], sort_keys=True) != json.dumps(applied.get(k), sort_keys=True):
                    problems.append(f"非映射字段 {k} 被改")
            extra = set(applied) - set(spec) - want
            if extra:
                problems.append(f"apply 新增字段 {extra}")
            try:
                merge_patch(ShotSpec.model_validate(spec), d["changes"])
            except Exception as e:  # noqa: BLE001
                problems.append(f"patch 产出的 ShotSpec 非法却未被 build/apply 拒绝: {type(e).__name__}: {str(e)[:160]}")
        rec["verdict"] = "PASS" if not problems else "LEAK"
        rec["problems"] = problems
    except ar.AnnotationTemporalClarification as e:
        rec["raised"] = f"AnnotationTemporalClarification: {e}"
        rec["verdict"] = "PASS" if expect in ("clarify",) else ("PASS" if expect == "reject" else "LEAK(unexpected raise)")
    except Exception as e:  # noqa: BLE001
        rec["raised"] = f"{type(e).__name__}: {str(e)[:200]}"
        rec["verdict"] = "PASS" if expect == "reject" else "LEAK(unexpected raise)"
    results.append(rec)
    print(json.dumps({k: rec.get(k) for k in ("case", "expect", "verdict", "problems", "raised")}, ensure_ascii=False))


def bp(marks, times=(9000.0,), shot=3, man=None, rev=0, src=None):
    inp = ar.AnnotationInput(shot_index=shot, from_revision=rev, marks=list(marks),
                             source_time_ms=list(times), authoritative_source=src)
    m = man or MAN
    return ar.build_patch(m, inp), copy.deepcopy((m.shot(shot).spec() if m.shot(shot) else {}))


def ap(spec, changes, shot=3):
    """手工 patch → 走 apply_patch（模块对外的应用入口）。"""
    p = ar.ShotSpecPatch(shot_index=shot, from_revision=0, changes=changes)
    out = ar.apply_patch(copy.deepcopy(spec), p)
    # apply_patch 本身若不校验，就模拟"拿着结果往下游走"：我们只看它有没有拒绝
    return out


def main():
    R: list = []
    # ── 基础验收 ──
    check("S3 pin+arrow 只改 camera", "patch_only:camera",
          lambda: bp([M("pin", .5, .5), M("arrow", .5, .5, direction="right")]), R)
    check("未知标注 → advisory", "advisory_only", lambda: bp([M("mystery_glyph", .5, .5)]), R)
    check("时间码在镜外(S3 给 S1 时间)", "reject", lambda: bp([M("pin", .5, .5)], times=(1000.0,)), R)
    check("2 个时间码锚点", "clarify", lambda: bp([M("pin", .5, .5)], times=(8500.0, 11000.0)), R)
    check("3 个时间码锚点", "clarify", lambda: bp([M("pin", .5, .5)], times=(8500.0, 9000.0, 11000.0)), R)
    check("2 个相同时间码(重叠锚点)", "clarify", lambda: bp([M("pin", .5, .5)], times=(9000.0, 9000.0)), R)
    # ── 时间码边界 ──
    check("负时间码 -1ms 于 S1", "reject", lambda: bp([M("pin", .5, .5)], times=(-1.0,), shot=1), R)
    check("NaN 时间码", "reject", lambda: bp([M("pin", .5, .5)], times=(float("nan"),)), R)
    check("inf 时间码", "reject", lambda: bp([M("pin", .5, .5)], times=(float("inf"),)), R)
    check("时间码=S3 起点 8000（也是 S2 终点）归 S2 也被接受→歧义", "reject",
          lambda: bp([M("pin", .5, .5)], times=(8000.0,), shot=2), R)
    check("时间码是字符串 '9000'", "reject", lambda: bp([M("pin", .5, .5)], times=("9000",)), R)
    check("不存在的镜 S9", "reject", lambda: bp([M("pin", .5, .5)], shot=9), R)
    check("负镜号 S-1", "reject", lambda: bp([M("pin", .5, .5)], shot=-1), R)
    # ── 非法字段 / 非法标注 ──
    check("arrow 无方向 → 应进 advisory 而不是静默丢弃", "advisory_only",
          lambda: bp([M("arrow", .5, .5, direction=None)]), R)
    check("arrow 方向 'diagonal' → advisory", "advisory_only",
          lambda: bp([M("arrow", .5, .5, direction="diagonal")]), R)
    check("arrow 方向 'RIGHT'(大写) → advisory 或映射，不可静默丢", "advisory_only",
          lambda: bp([M("arrow", .5, .5, direction="RIGHT")]), R)
    check("坐标越界 nx=-5 ny=7", "reject", lambda: bp([M("pin", -5, 7)]), R)
    check("负宽高 rect nw=-0.3", "reject", lambda: bp([M("rect", .5, .5, nw=-0.3, nh=-0.2)]), R)
    check("坐标 NaN", "reject", lambda: bp([M("pin", float("nan"), .5)]), R)
    check("from_revision=-3", "reject", lambda: bp([M("pin", .5, .5)], rev=-3), R)
    check("kind=None", "advisory_only", lambda: bp([M(None, .5, .5)]), R)
    # ── 冲突/非法产物 ──
    check("arrow 左+右 冲突 → 应 advisory，不应合成 pan_left+pan_right", "advisory_only",
          lambda: bp([M("arrow", .5, .5, direction="left"), M("arrow", .5, .5, direction="right")]), R)
    check("freehand + rect 同镜 → effect 合成值必须合法", "patch_only:effect",
          lambda: bp([M("freehand", .5, .5, .2, .2), M("rect", .5, .5, .2, .2)]), R)
    check("rect 单独 → effect=vignette 合法", "patch_only:effect",
          lambda: bp([M("rect", .5, .5, .2, .2)]), R)
    check("text 批注 → 只 advisory", "advisory_only", lambda: bp([M("text", .5, .5, note="台词改短一点")]), R)
    check("pin + 未知 → camera + advisory", "patch_only:camera",
          lambda: bp([M("pin", .5, .5), M("lasso", .5, .5)]), R)

    # ── apply_patch：patch 后 ShotSpec 非法必须被拒 ──
    def apply_case(name, changes):
        rec = {"case": name, "expect": "reject"}
        try:
            out = ap(SPEC3, changes)
            rec["applied"] = {k: out.get(k) for k in changes}
            rec["verdict"] = "LEAK"
            rec["problems"] = ["apply_patch 接受了让 ShotSpec 非法/越权的 patch"]
        except Exception as e:  # noqa: BLE001
            rec["raised"] = f"{type(e).__name__}: {str(e)[:200]}"
            rec["verdict"] = "PASS"
        R.append(rec)
        print(json.dumps({k: rec.get(k) for k in ("case", "verdict", "raised")}, ensure_ascii=False))

    apply_case("apply duration=-1", {"duration": -1})
    apply_case("apply effect='explode'", {"effect": "explode"})
    apply_case("apply 未知字段 foo", {"foo": 1})
    apply_case("apply transition_in='zzz'", {"transition_in": "zzz"})
    apply_case("apply sfx=[{id:'nope'}]", {"sfx": [{"id": "nope", "offset": 0}]})

    # ── 重叠/重复镜号 manifest 必须被拒 ──
    d = base_manifest()
    d["shots"][3]["shot_index"] = 3  # 两个 S3
    mp = OUT / "dup_s3.manifest.json"
    mp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    rec = {"case": "manifest 两个 S3（时间区间重叠/歧义）必须在 load_manifest 被拒", "expect": "reject"}
    try:
        m = load_manifest(mp)
        try:
            p, _ = bp([M("pin", .5, .5)], times=(13000.0,), man=m)
            got = p.to_dict()["changes"]
        except Exception as e2:  # noqa: BLE001
            got = f"{type(e2).__name__}: {str(e2)[:120]}"
        rec["verdict"] = "LEAK"
        rec["problems"] = [f"load_manifest 接受重复镜号；第二个 S3 实际区间 [12000,16000] 内 13000ms 的标注 -> {got}"]
    except Exception as e:  # noqa: BLE001
        rec["raised"] = f"{type(e).__name__}: {str(e)[:200]}"
        rec["verdict"] = "PASS"
    R.append(rec)
    print(json.dumps(rec, ensure_ascii=False)[:400])

    # ── 确定性 + 顺序无关 ──
    a, _ = bp([M("pin", .5, .5), M("arrow", .5, .5, direction="right"), M("zzz", 0, 0)])
    b, _ = bp([M("zzz", 0, 0), M("arrow", .5, .5, direction="right"), M("pin", .5, .5)])
    R.append({"case": "确定性/顺序无关", "expect": "same sha", "sha_a": a.sha256(), "sha_b": b.sha256(),
              "verdict": "PASS" if a.sha256() == b.sha256() else "LEAK"})
    print(R[-1])

    # ── dry-run diff 交付物是否存在 ──
    has = [n for n in dir(ar) if "dry" in n.lower() or "diff" in n.lower()]
    R.append({"case": "dry-run diff API 存在（§3.5/任务书交付物）", "expect": "exists", "found": has,
              "verdict": "PASS" if has else "LEAK"})
    print(R[-1])

    # ── 干净原图与标注图分离：out_path==source 不得覆盖原图 ──
    src = OUT / "clean_src.png"
    Image.new("RGB", (320, 180), (10, 120, 200)).save(src)
    h0 = hashlib.sha256(src.read_bytes()).hexdigest()
    rec = {"case": "render_annotated(out==source) 不得覆盖干净原图", "expect": "reject or source unchanged"}
    try:
        ar.render_annotated(src, [M("pin", .5, .5)], src)
    except Exception as e:  # noqa: BLE001
        rec["raised"] = str(e)[:200]
    h1 = hashlib.sha256(src.read_bytes()).hexdigest()
    rec["verdict"] = "PASS" if h0 == h1 else "LEAK"
    rec["problems"] = [] if h0 == h1 else ["原图被标注覆盖"]
    R.append(rec)
    print(rec)
    # 正常分离
    src2 = OUT / "clean_src2.png"
    Image.new("RGB", (320, 180), (10, 120, 200)).save(src2)
    h0 = hashlib.sha256(src2.read_bytes()).hexdigest()
    ar.render_annotated(src2, [M("pin", .5, .5), M("text", .2, .2, note="这里")], OUT / "annotated2.png")
    R.append({"case": "render_annotated 正常分离", "expect": "source unchanged",
              "verdict": "PASS" if hashlib.sha256(src2.read_bytes()).hexdigest() == h0 else "LEAK"})

    (OUT / "results_annotation.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str),
                                                  encoding="utf-8")
    leaks = [r for r in R if str(r["verdict"]).startswith("LEAK")]
    print(f"TOTAL {len(R)} LEAK {len(leaks)}")


if __name__ == "__main__":
    main()
