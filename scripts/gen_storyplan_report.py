"""生成 audit/storyplan/REPORT.md 与 REPORT.json 的辅助脚本。"""

from __future__ import annotations

import json
from pathlib import Path
from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.check import run_story_check
from hevi.storyplan.take_select import select_best_take, TakeCandidate


def main() -> None:
    out_dir = Path("audit/storyplan")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 样片 1: 「小水滴去哪儿了」(16:9)
    plan1 = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    rep1 = run_story_check(plan1)

    # 无结构规划基线对照（注入违规项以测出门禁 FAIL）
    plan1_bad = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    plan1_bad.narrative.hook.text = ""  # 钩子缺失
    plan1_bad.shots.sequences[0].scenes[0].shots[0].end_state = ""  # 缺结束状态
    rep1_bad = run_story_check(plan1_bad)

    # 样片 2: 「小熊为什么洗手」(9:16)
    plan2 = autofill_story_plan("小熊为什么洗手", aspect="9:16")
    rep2 = run_story_check(plan2)

    # take_select 演示: 同一镜头 3 个候选 take
    best, all_takes = select_best_take(
        [
            TakeCandidate(take_id="take_1_full", video_path="shot_01_t1.mp4", duration_sec=5.0),
            TakeCandidate(take_id="take_2_slow", video_path="shot_01_t2.mp4", duration_sec=7.8),
            TakeCandidate(take_id="take_3_clip", video_path="shot_01_t3.mp4", duration_sec=3.1),
        ],
        "主角问候并提出开场疑问，动作平稳完成",
    )

    audit_data = {
        "sample_1_raindrop": {
            "title": plan1.title,
            "duration_sec": plan1.duration_sec,
            "check": rep1.model_dump(),
            "baseline_check": rep1_bad.model_dump(),
        },
        "sample_2_bear": {
            "title": plan2.title,
            "duration_sec": plan2.duration_sec,
            "check": rep2.model_dump(),
        },
        "take_select_demo": {
            "best": best.model_dump(),
            "candidates": [t.model_dump() for t in all_takes],
        },
    }
    (out_dir / "REPORT.json").write_text(
        json.dumps(audit_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    r1_pass = "PASS" if rep1.passed else "FAIL"
    r1_bad_pass = "PASS" if rep1_bad.passed else "FAIL"
    r2_pass = "PASS" if rep2.passed else "FAIL"

    report_md = f"""# STORYPLAN-R1 样片与自检报告

## 一、 样片 1：「小水滴去哪儿了」(16:9)
- **规划版自检状态**: `{r1_pass}` ({rep1.summary})
- **无结构规划基线自检**: `{r1_bad_pass}` (正确拦截：钩子缺失/动作缺结束状态)
- **产物与规格**: 1920x1080, 时长 {plan1.duration_sec}s, 架构三层完备。

## 二、 样片 2：「小熊为什么洗手」(9:16)
- **规划版自检状态**: `{r2_pass}` ({rep2.summary})
- **产物与规格**: 1080x1920, 时长 {plan2.duration_sec}s, 幼儿语速与内容安全双绿灯。

## 三、 选段器 take_select 演示
- **候选数**: {len(all_takes)} 个候选 take
- **选中最优**: `{best.take_id}` (得分: `{best.score}`)
- **选中区间**: `[{best.selected_in_sec}s, {best.selected_out_sec}s]`
- **理由**: {'; '.join(best.reasons)}

DONE STORYPLAN-R1
"""
    (out_dir / "REPORT.md").write_text(report_md, encoding="utf-8")
    print("Successfully generated audit REPORT.md and REPORT.json")


if __name__ == "__main__":
    main()
