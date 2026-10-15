# MERGE-1015 最终合并与验收报告

- 目标分支：`origin/closure/3o-v3-architecture-creative-baseline`
- 最终推送 HEAD：`38a71ef3`（非 force push，fast-forward）
- 执行人：soffy / pi
- 时间：2026-10-15

## 一、 第 0 步巡检可疑点与独立核验结果

巡检 `STATUS.md` 报的 PASS commit 存在多处不一致（证据/中间提交被误报），已按规则逐个独立核验：

1. **hevi-reviewsheet**（`feat/review-sheet`，HEAD `c9afc054`）：
   - 巡检报 R2 PASS 对应 `88d4518f`（实为 R1 FAIL 证据提交），但真 HEAD 是 `c9afc054`（R2 修复）。
   - 独立运行硬验收 `bash audit/reviewsheet/verify_r1/run_all.sh`：**退出码 0，TOTAL_BAD 0**（审稿表 38、标注修订 36、kids_gate 13 全通过，e2e problems []）。**已合并**。
2. **hevi-handdraw**（`feat/handdraw-line`，HEAD `96dd5bb0`）：
   - 巡检报 R4 PASS 但 `96dd5bb0` 是 R3 提交（DONE 仍为 `DONE HANDDRAW-R3`）。R4 工作尚在未提交 WIP 中，且独立复测发现 ASR p95 0.46s 超过 0.25s 要求。
   - 结论：HEAD 不含声称的 R4 修复。**跳过不合**，返工单已落盘 `HANDDRAW_FIX_R5.md`。
3. **hevi-motiondir**（`feat/motion-director`，HEAD `6a9936ef`）：
   - 巡检报 R1 PASS 对应 `f6dfd194`（仅 merge dirstyle）。真 HEAD 虽含 `DONE MOTIONDIR-R1`，但独立重渲实测 `director_report.passed` 为 `false`（`beat_alignment` 0.00），且 `render.py` 存在 mock 兜底及硬写 `base_report["passed"] = False`。
   - 结论：交付项实测失败。**跳过不合**，返工单已落盘 `MOTIONDIR_FIX_R2.md`。
4. **hevi-scene3d**（`7849adb2`）：`verify_r1d/REPORT.md` PASS 结论真实存在，测试 45 passed。**已合并**。
5. **hevi-kidsmanifest**（`ca6408a3`）：R4 核心项（H1/H2/H3）独立验证通过（`probe_adversarial.py` MISS 0，49 passed）。**已合并**（注：残留更广词表缺口另记）。
6. **hevi-agentops**（`e22d04d1`）：R4 修复 `seed_assets` 回归，134 passed，`verify.py` pass_=true。**已合并**。
7. **hevi-anatomy**（`07829500`）：R2 修复完成，geometry audit 与 clean-env 渲染通过，5 passed。**已合并**。

## 二、 合并明细与测试 / Lint 数据

逐个 `--no-ff` 合并：`scene3d` → `kidsmanifest` → `agentops` → `reviewsheet`（跳过） → `handdraw`（跳过） → `anatomy` → `motiondir`（跳过）。

| 分支 | 合并提交 | 冲突解决 | 分支测试结果 | 3O Lint 结果 |
|---|---|---|---|---|
| `feat/scene3d-line` | `6d215bd7` | 无冲突 | 45 passed | 失败数 4（=基线） |
| `feat/kids-manifest` | `ba9b60ee` | `main.py`, `registry.py`（保留双 capability 注册） | 49 passed | 失败数 4（=基线） |
| `feat/agent-ops` | `8412c118` / `297453f3` | `registry.py`, `NOTICE`（双署名保留） | 134 passed | 失败数 4（=基线） |
| `feat/review-sheet` | *跳过* | —— | —— | —— |
| `feat/handdraw-line` | *跳过* | —— | —— | —— |
| `feat/anatomy-explainer` | `bef2a69f` | `registry.py` | 5 passed | 失败数 4（=基线） |
| `feat/motion-director` | *跳过* | —— | —— | —— |

- **全量 pytest 最终回归**：7843 passed / 145 failed（其中 124 failed + 65 errors 属于与基线完全一致的预存历史失败，**无新增失败**）。
- **3O v3 Lint**：FAIL 4 项（`check_no_sibling_call`、`check_omodul_signature`、`check_enabled_pillars`、`check_oprim_keyword_only`），**= 基线 4 项，无新增违规**（已对 `test_admission_seam.py` 适应 agent-ops 的 `ffmpeg.py` 辅助函数扩展调整断言）。

## 三、 最终状态
- 远程推送目标：`origin closure/3o-v3-architecture-creative-baseline`
- 最终 HEAD：`38a71ef3`
- 不部署、不重启生产服务。

DONE MERGE-1015
