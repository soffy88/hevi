#!/usr/bin/env python3
"""G0 Master Runner — 三家分晋三镜头垂直切片

顺序执行所有任务，生成交付报告。
用法:
  cd /home/soffy/projects/hevi
  .venv/bin/python hevi/tongjian/sandbox/g0_run.py

  --skip-video: 跳过视频生成（仅跑 SVG + 风格包 + 关键帧 + 断言）
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

# 确保项目根在 sys.path
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

OUT_ROOT = ROOT / "output/g0_sanjia_fenjin"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

SANDBOX = Path(__file__).parent

TASKS = [
    ("g0_01_draw_maps",   "Task-1: 手绘两张 SVG"),
    ("g0_02_style_pack",  "Task-2: 最小风格包 v0"),
    ("g0_03_keyframe_pairs", "Task-3: 关键帧对 ×3 + A1-A4"),
    ("g0_04_prompts",     "Task-4: 提示词 ×3"),
    ("g0_05_video_gen",   "Task-5: 视频生成 + B1/B2"),
]


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SANDBOX / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    # 确保工作目录在项目根
    os.chdir(ROOT)
    spec.loader.exec_module(mod)
    return mod


def run_task(name: str, label: str) -> dict:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    t0 = time.perf_counter()
    try:
        mod = load_module(name)
        mod.main()
        elapsed = time.perf_counter() - t0
        status = "OK"
        error = None
    except SystemExit as e:
        elapsed = time.perf_counter() - t0
        status = "SKIP" if str(e) == "0" else "ERROR"
        error = str(e)
        print(f"  SystemExit: {e}")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        status = "ERROR"
        error = f"{type(e).__name__}: {e}"
        print(f"  ERROR: {error}")
        import traceback
        traceback.print_exc()

    return {
        "task": name,
        "label": label,
        "status": status,
        "elapsed_seconds": round(elapsed, 3),
        "error": error,
    }


def collect_deliverables() -> dict:
    """收集所有交付物路径和数值。"""
    out = {}

    # SVG 工时
    timing_path = OUT_ROOT / "maps/timing.json"
    if timing_path.exists():
        out["svg_timing"] = json.loads(timing_path.read_text())

    # 风格包
    style_path = OUT_ROOT / "style/style_pack_v0.json"
    if style_path.exists():
        sp = json.loads(style_path.read_text())
        out["style_pack"] = {
            "n_textures": sp.get("n_textures"),
            "timing": sp.get("timing"),
        }

    # 关键帧断言
    kf_assert_path = OUT_ROOT / "keyframes/keyframe_assertions.json"
    if kf_assert_path.exists():
        kf = json.loads(kf_assert_path.read_text())
        out["keyframe_assertions"] = [
            {
                "shot_id": s["shot_id"],
                "A1_delta_E": s["assertions"]["A1"]["delta_E"],
                "A2_passed": s["assertions"]["A2_frame_a"]["passed"] and s["assertions"]["A2_frame_b"]["passed"],
                "A3_cosine": s["assertions"]["A3"]["cosine_similarity"],
                "A4_ssim": s["assertions"]["A4"]["ssim"],
                "A4_passed": s["assertions"]["A4"]["passed"],
                "timing_s": s["timing_seconds"],
            }
            for s in kf.get("shots", []) if "assertions" in s
        ]
        out["threshold_suggestions_A3"] = kf.get("threshold_suggestions")

    # 视频断言
    video_assert_path = OUT_ROOT / "video/video_assertions.json"
    if video_assert_path.exists():
        va = json.loads(video_assert_path.read_text())
        out["video_assertions"] = [
            {
                "shot_id": s["shot_id"],
                "provider": s.get("provider"),
                "retry_count": s.get("retry_count", 0),
                "B1_ssim": s["assertions"]["B1"].get("ssim"),
                "B1_cos": s["assertions"]["B1"].get("cosine_similarity"),
                "B1_passed": s["assertions"]["B1"].get("passed"),
                "B2_regions": s["assertions"]["B2"]["distinct_color_count"],
                "B2_expected": s["assertions"]["B2"]["expected_count"],
                "B2_passed": s["assertions"]["B2"]["passed"],
            }
            for s in va.get("shots", []) if "assertions" in s
        ]
        out["threshold_suggestions_B1"] = va.get("threshold_suggestions")
        out["failure_class_summary"] = va.get("failure_class_summary")

    return out


def print_final_report(task_results: list[dict], deliverables: dict, total_elapsed: float):
    print("\n" + "="*70)
    print("  G0 三家分晋 — 交付报告")
    print("="*70)

    # 任务状态
    print("\n【任务状态】")
    for r in task_results:
        icon = "✅" if r["status"] == "OK" else ("⚠️" if r["status"] == "SKIP" else "❌")
        print(f"  {icon} {r['label'][:30]}  {r['elapsed_seconds']:.1f}s  {r['status']}")
        if r["error"]:
            print(f"      error: {r['error'][:60]}")

    # SVG 工时（Q5）
    print("\n【SVG 工时 (Q5)】")
    svg_t = deliverables.get("svg_timing", {})
    print(f"  ms_hua_453bc:       {svg_t.get('ms_hua_453bc_seconds', 'N/A')}s")
    print(f"  ms_hua_453bc_split: {svg_t.get('ms_hua_453bc_split_seconds', 'N/A')}s")
    print(f"  总工时:              {svg_t.get('total_seconds', 'N/A')}s")

    # 风格包
    print("\n【最小风格包 v0】")
    sp = deliverables.get("style_pack", {})
    st = sp.get("timing", {})
    print(f"  材质图张数: {sp.get('n_textures', 'N/A')}")
    print(f"  材质生成: {st.get('torn_paper_seconds', 'N/A')}s  色卡: {st.get('color_calibration_seconds', 'N/A')}s")

    # 关键帧断言
    print("\n【关键帧断言数值表 (A1–A4)】")
    kfa = deliverables.get("keyframe_assertions", [])
    if kfa:
        print(f"  {'Shot':4}  {'A1_ΔE':8}  {'A2':5}  {'A3_cos':8}  {'A4_SSIM':8}  {'A4':4}  {'工时s':6}")
        print(f"  {'-'*55}")
        for row in kfa:
            a2 = "OK" if row.get("A2_passed") else "⚠️"
            a4 = "OK" if row.get("A4_passed") else "⚠️"
            print(f"  {row['shot_id']:4}  {row.get('A1_delta_E', 'N/A'):8}  {a2:5}  "
                  f"{row.get('A3_cosine', 'N/A'):8}  {row.get('A4_ssim', 'N/A'):8}  {a4:4}  {row.get('timing_s', 'N/A'):6}")
    else:
        print("  (无数据)")

    # 视频断言
    print("\n【视频断言数值表 (B1/B2) + 重跑次数】")
    va = deliverables.get("video_assertions", [])
    if va:
        print(f"  {'Shot':4}  {'Provider':20}  {'Retry':5}  {'B1_SSIM':8}  {'B1_cos':7}  {'B1':4}  {'B2 cnt/exp':10}  {'B2':4}")
        print(f"  {'-'*75}")
        for row in va:
            b1 = "OK" if row.get("B1_passed") else "⚠️"
            b2 = "OK" if row.get("B2_passed") else "⚠️"
            b1_ssim = f"{row.get('B1_ssim', 'N/A'):.4f}" if row.get("B1_ssim") is not None else "N/A"
            b1_cos = f"{row.get('B1_cos', 'N/A'):.4f}" if row.get("B1_cos") is not None else "N/A"
            b2_cnt = f"{row.get('B2_regions','?')}/{row.get('B2_expected','?')}"
            prov = (row.get("provider") or "none")[:20]
            print(f"  {row['shot_id']:4}  {prov:20}  {row.get('retry_count',0):5}  "
                  f"{b1_ssim:8}  {b1_cos:7}  {b1:4}  {b2_cnt:10}  {b2:4}")
    else:
        print("  (无数据)")

    # 失败分类
    fail_cls = deliverables.get("failure_class_summary", {})
    if fail_cls:
        print("\n【失败分类记录】")
        for cls, cnt in fail_cls.items():
            print(f"  {cls}: {cnt}次")

    # 阈值建议
    ts_a3 = deliverables.get("threshold_suggestions_A3", {})
    ts_b1 = deliverables.get("threshold_suggestions_B1", {})
    print("\n【A3/B1 阈值建议】")
    if ts_a3:
        print(f"  A3 cos (transition): {ts_a3.get('A3_cos_transition_suggest', 0.50)}")
        print(f"  A3 cos (same scene): {ts_a3.get('A3_cos_same_scene_suggest', 0.80)}")
    if ts_b1:
        print(f"  B1 SSIM 建议: {ts_b1.get('B1_ssim_suggest')}  观测区间: {ts_b1.get('B1_ssim_observed_range')}")
        print(f"  B1 cos  建议: {ts_b1.get('B1_cos_suggest')}   观测区间: {ts_b1.get('B1_cos_observed_range')}")

    print(f"\n总执行时间: {total_elapsed:.1f}s")
    print("="*70)


def main():
    parser = argparse.ArgumentParser(description="G0 三家分晋垂直切片主运行器")
    parser.add_argument("--skip-video", action="store_true", help="跳过视频生成步骤")
    args = parser.parse_args()

    t_start = time.perf_counter()
    task_results = []

    tasks_to_run = TASKS if not args.skip_video else TASKS[:-1]

    for name, label in tasks_to_run:
        result = run_task(name, label)
        task_results.append(result)
        # 同类失败检测（跨任务级）
        errors = [r for r in task_results if r["status"] == "ERROR"]
        if len(errors) >= 3:
            print(f"\n⚠️ 同类任务失败 ≥3（{[r['task'] for r in errors]}），停止执行")
            break

    total_elapsed = time.perf_counter() - t_start
    deliverables = collect_deliverables()
    print_final_report(task_results, deliverables, total_elapsed)

    # 写最终报告
    report = {
        "run_id": "g0_master",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_results": task_results,
        "deliverables": deliverables,
        "total_elapsed_seconds": round(total_elapsed, 3),
    }
    report_path = OUT_ROOT / "g0_final_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ 最终报告: {report_path}")


if __name__ == "__main__":
    main()
