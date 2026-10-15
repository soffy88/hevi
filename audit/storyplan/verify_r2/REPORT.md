# STORYPLAN-R2 独立核验报告（verify_r2）

**核验对象**: 提交 `9ffa237a`（`DONE STORYPLAN-R2`，分支 `feat/story-plan`）
**核验者**: hevi-patrol 独立核验员（只读源码 + 自写探针，不采信工人自报数字）
**核验日期**: 2026-10-15（第三轮）
**核验依据**: `STORYPLAN_TASK.md`（A–H）、`STORYPLAN_FIX.md`（FIX-1..7）

```
VERDICT: PASS
```

---

## 一、逐条复测（对 STORYPLAN_FIX.md 的 7 项修复）

| FIX | 验收点 | 结论 | 独立证据 |
|---|---|---|---|
| FIX-1 | C5 叙事闭环不可被 6 字无关文本绕过 | PASS | 上轮核验员 `counter.py` 反例 `d2_closing_no_overlap` 期望拒绝，实测 C5=FAIL、passed=False |
| FIX-2 | C6 时间线：空轨/越界/字幕超语音区间必须 FAIL | PASS | 反例 `e3_no_tracks`（空时间线）、`e4_subtitle_over_voice`（越界）实测 C6=FAIL |
| FIX-3 | C7 幼儿安全词表覆盖 15 类 | PASS | 反例 `f_harmful_15_rejected` 15/15 拒；`f_normal_10_kept` 误杀 0/10 |
| FIX-4 | 非预设主题不得同模板换名 | PASS | 反例 `h_autofill_varies`：5 主题 distinct hash 5/5，非预设主题同模板=False |
| FIX-5 | take_select 真帧检（区分冻结/破损 vs 完整） | PASS | **自写探针**用 ffmpeg 造真实 frozen.mp4 / motion.mp4，`take_select` 选中 t_motion（66.93 vs 40.0），motion_completeness 0.173 vs 0.1、stability 1.0 vs 0.2，可区分 |
| FIX-6 | 三能力进统一 catalog 且挂路由 | PASS | 亲自 import：`capability_catalog()` 含 story_plan/story_check/take_select；`app.routes` 含 `/api/story-plan/plan`、`/check`、`/take-select`、`/capabilities` |
| FIX-7 | 2 支 1080p 样片 + 基线 FAIL/规划版 PASS | PASS | 见第二、三节 |

## 二、样片独立复测（亲自重渲 + ffprobe + 抽帧）

重跑 `audit/storyplan/render_samples.py`（纯 CPU：Pillow 逐帧 + ffmpeg libx264）：

- `raindrop_16_9.mp4`：**1920x1080**，h264，30fps，300 帧，10.0s
- `bear_9_16.mp4`：**1080x1920**，h264，30fps，300 帧，10.0s

重渲后 sha256（确定性，见 `sha256_rerender.txt`）：

```
aab81b7d11564fb0041058087eda813625c2778fa33ebb1dc7875e917cff3276  raindrop_16_9.mp4
a92c981fedbedb5f749623b7019bb543868cd74aa27befd98cc4ec36e0ca344b  bear_9_16.mp4
```

与 `samples_meta.json` 记录值逐字节一致（同 seed/同脚本 sha256 一致）。抽帧图见 `frames/`（各 3 帧，已肉眼确认：16:9 与 9:16 画幅正确、暖色背景 + 橙色主角 + 进度条 + 中文字幕，非黑场）。

## 三、基线对照真实成立（自写 `baseline_probe.py`）

```
小水滴去哪儿了 | planned.passed=True  | baseline.passed=False | baseline FAILs=['C1_OPENING_HOOK','C2_SHOT_REQUIRED_FIELDS']
小熊为什么洗手 | planned.passed=True  | baseline.passed=False | baseline FAILs=['C1_OPENING_HOOK','C2_SHOT_REQUIRED_FIELDS']
```

规划版 PASS、无结构基线 FAIL，均真实成立（非硬写）。

## 四、take_select 演示输出（自写 `take_select_probe.py`）

真实视频抽帧打分可区分冻结与运动镜头，最优选 `t_motion`；`audit/storyplan/REPORT.json` 的 3 候选演示 best=`take_1_full` score=96.1，区间 [0.0s,5.0s]。

## 五、pytest 与 lint（亲自重跑）

```bash
JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=<worktree> \
  /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_storyplan.py -q
# => 7 passed
```

`scripts/ci/run_3o_v3_lint.py` 失败集合 = `check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py`，与基线 **4 项完全一致，零新增**。

## 六、反例脚本复跑（上轮核验员 `verify_r1/counter.py`，未改）

`总检查项 21，未达预期 0`（`counter_results.json` 已由 R2 更新）。

## 七、已知限制（不影响本轮 PASS）

1. 样片为无声 MP4（仅视频轨），旁白/字幕以画面字幕条形式呈现；任务 G 未强制要求嵌入音轨，属交付形态说明。
2. 非预设主题的散列模板使用了进程内 `hash()`（PYTHONHASHSEED 随机化）——跨进程同一主题可能落到不同模板分支（`h_autofill_varies` 在单进程内确定性）；建议后续改为稳定哈希（如 `hashlib`）。此为建议，非阻断。

## 签字

独立核验员：hevi-patrol R3
结论：**PASS**（分支 `feat/story-plan`，HEAD `9ffa237a`）
