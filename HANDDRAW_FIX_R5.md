# HANDDRAW_FIX_R5 — 独立核验 R4 未通过（2026-10-15，MERGE-1015 第 0 步）

核验：`/data/soffy/projects/hevi-pubfix` 的合并核验员。对象：worktree `/data/soffy/projects/hevi-handdraw`，分支 `feat/handdraw-line`，HEAD `96dd5bb0`。

## 判定：不合并

`HANDDRAW_FIX_R4.md` 要求"完成后在 `HANDDRAW_DONE.md` 末尾追加实测结果…并单独一行写 `DONE HANDDRAW-R4`"。实际：

- **HEAD `96dd5bb0` 的 `HANDDRAW_DONE.md` 末行仍是 `DONE HANDDRAW-R3`**；`git log` 中无任何 `HANDDRAW-R4` 提交。
- R4 的改动（`kids_storyboards.py` 新主题、`tts.py` ASR 对齐、`illustrator.py` 水墨晕染、`tests/test_handdraw_capabilities.py` 的 12 个 R4 测试）全部还是**未提交工作区 WIP**。
- `audit/handdraw/` 只有 `verify_r3/REPORT.md`（结论 **FAIL**），没有 `verify_r4/REPORT.md`。
- 因此分支 HEAD 不含任何声称的 R4 修复 → 按 MERGE-1015 第 0 步规则**不合并**。

## 阻断项（复测证据）

### B1 未提交（流程阻断）
- 复现：`git -C /data/soffy/projects/hevi-handdraw status --short` → 5 个源/测试文件 `M`；`git log --oneline -1` → `96dd5bb0 ... DONE HANDDRAW-R3`。
- 期望：R4 成果以真实提交落盘，`HANDDRAW_DONE.md` 末行 `DONE HANDDRAW-R4`。

### B3 字幕起点仍未达标（真机复测）
- 复现（独立 faster-whisper large-v3-turbo，CPU int8；**不同于管线自带 small 模型**）：
  ```
  cd /data/soffy/projects/hevi-handdraw
  JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD \
    /data/soffy/projects/hevi/.venv/bin/python audit/handdraw/verify_r4/independent_asr_audit.py \
    ".tmp/r4/final_runs/R4_L8_wash/outputs/film.mp4,.tmp/r4/final_runs/R4_L8_wash/outputs/editing/transcript.srt" \
    --out /tmp/hd_r5_l8.json
  ```
- 实测：`cues=16 matched=16 coverage=100.0% p95=0.460s max=0.980s`（连跑两次一致）。
- 期望（`HANDDRAW_FIX_R4.md` B3）：**每片 cue 起点误差 p95 ≤ 0.25s**。当前 0.46s 超标。
- 注意：`tests/test_handdraw_capabilities.py::test_r4_independent_large_v3_turbo_caption_timing_on_two_full_films` 断言的是 `p95 <= 0.90`，比 FIX_R4 的 0.25 宽，属于**放宽验收**，不得据此报 PASS。必须把断言收紧到 `<= 0.25`（或明确记录并让核验员认可放宽理由）。

## 需保留（不要回退）
- R4 WIP 中 12 个新测试当前**全部通过**（`pytest tests/test_handdraw_capabilities.py -q` → 39 passed，425s）；主题路由（分享/过马路/洗手/怕黑/睡前/谢谢/生气/难过/对不起/勇敢/朋友/自然）实测可出片，成人主题正确拒绝。
- 独立 ASR 的 `matching_coverage=1.0`、无 `unmatched`、无 `leading_punctuation`（这两项达标）。

## 完成标志
- R4/R5 成果真实提交；`HANDDRAW_DONE.md` 末尾追加实测结果（含 4 风格×2 画幅 8 部完整片全部出片 + 独立 ASR p95 数字，且 p95 ≤ 0.25s 才算过），末行 `DONE HANDDRAW-R4`（或 R5，按返工轮次）。
- 独立核验员用**与管线不同的** ASR 模型复测 p95 ≤ 0.25s。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 `DISK_FULL_NOTE.md` 停止）；CPU-only、单进程渲染；不调付费 API；禁止 mock/硬编码通过；不 push；临时文件 `.tmp/`。
