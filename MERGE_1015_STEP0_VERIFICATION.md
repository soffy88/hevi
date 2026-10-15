# MERGE-1015 第 0 步：巡检可疑点独立核验

核验员：pi（soffy 身份），2026-10-15，worktree `/data/soffy/projects/hevi-pubfix`（detached @ `b418dbc3` = `origin/closure/3o-v3-architecture-creative-baseline` 尖端）。

本步不采信 `hevi-patrol/STATUS.md` 的自报结论，逐个复核 HEAD、`*_DONE.md` 末行、`audit/<名>/verify_rN/REPORT.md` 是否存在且结论为 PASS，并对任务点名的 3 个单元亲自跑独立核验。

## 逐单元结论

| 单元 | 分支 | 分支 HEAD | DONE 末行 | 核验报告 | 独立复测 | 结论 |
|---|---|---|---|---|---|---|
| scene3d | feat/scene3d-line | `7849adb2` | DONE SCENE3D-R1D | `audit/scene3d/verify_r1d/REPORT.md` = **PASS**（已提交） | pytest `test_scene3d*.py` 45 passed | **合并** |
| kidsmanifest | feat/kids-manifest | `ca6408a3` | DONE KIDSMANIFEST-R4 | 无 verify_r4 REPORT.md；`verify_r3/REPORT.md`=FAIL | 复跑 FIX_R4 样本：H1 血/武器 3/3 FAIL、H2 4/4 FAIL、H3 正确；`probe_adversarial.py` MISS 0；`extra.py` 全 OK；pytest 49 passed | **合并**（见残留缺口） |
| agentops | feat/agent-ops | `e22d04d1` | DONE AGENTOPS-R4 | 无 verify_r4 REPORT.md；`verify_r3/REPORT.md`=FAIL | R4 全量 134 passed/1 skipped；`verify.py` 第 2/5 项 pass_=true；`seed_assets` 无生产引用；pytest 25 passed | **合并** |
| reviewsheet | feat/review-sheet | `c9afc054` | DONE REVIEWSHEET-R2 | `verify_r1/REPORT.md`=FAIL（R1 证据） | **`bash audit/reviewsheet/verify_r1/run_all.sh` 退出码 0，TOTAL_BAD 0**（review_sheet 38/annotation 36/kids_gate 13 全 0 漏放，e2e problems []） | **合并** |
| anatomy | feat/anatomy-explainer | `07829500` | DONE ANATOMY-R2 | `verify_r1/REPORT.md`=FAIL；R2 自检 `audit/anatomy/REPORT.md` 矩阵全 PASS | pytest `test_anatomy_explainer.py` 5 passed；`renderer.py` 真调 `audit.mjs`+`audit_lines.mjs`，失败 raise；`anatomy_audit.json` passed=true | **合并** |
| handdraw | feat/handdraw-line | `96dd5bb0` | **DONE HANDDRAW-R3**（非 R4） | `verify_r3/REPORT.md`=**FAIL**；无 verify_r4 REPORT.md | R4 改动仍在**未提交 WIP**；HEAD 只含 5 个主题（无 fear_night/bedtime/gratitude…）；独立 faster-whisper large-v3-turbo 复测 L8_wash **p95=0.46s > 0.25s**（FIX_R4 B3 未达标） | **不合并**（返工单见下） |
| motiondir | feat/motion-director | `6a9936ef` | DONE MOTIONDIR-R1 | 无 `verify_r1/REPORT.md`（`audit/motiondir/REPORT.md` 只是样片报告） | **已提交的 4 份 `*_comparison_report.json` 全部 `director_report.passed=false`**（与 REPORT.md 声称"导演版 PASS"矛盾）；`render.py` 有 mock 兜底 + 硬写 `base_report["passed"]=False`；我独立重渲 director 仍 `passed=false`（`beat_alignment=0.00`） | **不合并**（返工单见下） |

## 与巡检 STATUS.md 的差异

巡检 `STATUS.md` 把 7 个单元全记 PASS，但 commit 列存在错位/失实：

- reviewsheet 记 `88d4518f`（实为 R1 **FAIL 证据**提交），真 HEAD 是 `c9afc054`（R2 修复）。
- handdraw 记 `96dd5bb0` 且称 R4 PASS，但 `96dd5bb0` 的 DONE 末行是 `DONE HANDDRAW-R3`，R4 成果未提交。
- motiondir 记 `f6dfd194`（"merge dirstyle"），看不到 `MOTIONDIR-R1` 的 DONE 提交；真 HEAD 是 `6a9936ef`，且交付项实测失败。
- anatomy 记 `d97d3284`（实为 R1 **FAIL 证据**提交），真 HEAD 是 `07829500`（R2）。

结论：巡检把"证据提交/中间提交"误当"核验通过提交"，且对 handdraw/motiondir 的 DONE 自报未做真机复测。

## 遗留缺口（不阻断本轮合并，记入报告）

- **kidsmanifest**：`check_content_safety_text` 对 FIX_R4 明确要求的样本（H1/H2/H3）全部达标，但对更广的常见暴力词仍有漏放（如「勒脖子/踹飞/针扎/绑树堵嘴/鞭打/狗咬/扯断尾巴/关笼子/棍子敲头/踩踏」）。`hevi/kids/story_gate.py` 的 `kids_story_gate` 入口对这批词亦放行。本轮按任务第 0 步"4 个快速确认单元"处理并合并，缺口另记后续跟进。
