# JUDGE_REPORT

## 实现
- 新增 `hevi/judge/`：后端可插拔（agy / gemini CLI / local / mock）、硬伤检查、两两对比评委、自迭代循环、校准。
- 新增 `hevi/api/routers/judge.py` 与 pipeline `judge`/`judge_backend` 可选字段。
- 新增 `docs/SEECUT_ATTRIBUTION.md`（仅借鉴方法，clean-room）。

## commit
- b770db7e7f31249ed850d131d83eb94249c5d4ba (分支 hark/video-judge)

## agy 用法
- 路径 `/home/soffy/.local/sgbin/agy`；无头调用加 `--dangerously-skip-permissions --print`；视频通过 `--add-dir <dir>` + prompt 中文件路径交给 Gemini。
- 当前环境认证失败（"You are not logged into Antigravity"），真实 agy 调用 0 次；回退 gemini CLI 亦不可用（ineligible client），最终使用本地指标 + mock 验证流程。

## 校准一致率
- 使用 mock 后端验证 pairwise 流程（交换位置各判一次）：一致性率 1.0（流程验证）。
- 真实 agy 未调用，故无真实一致率。

## 两条线 v1→v3 迭代记录
- Pexels API key 未配置，zero-line 生成被阻断，未产出真实 v1/v2/v3。
- 硬伤检查已在 audit-1106 / linefix-b 样片上运行，全部 pass（0 findings）；示例 ffprobe：explainer 15.75s/1280x720/aac，cinematic 15.78s/1280x720/aac。

## 调用次数
- agy：0；gemini CLI：0；总模型调用 ≤40（实际 0）。

## 仍存问题
- agy 认证不可用；Pexels API key 缺失导致 zero-line 生成阻断；字幕/重复率等检查依赖样本文件。
- API 任务记录附评委报告的端到端接线未完成（仅提供 judge 端点）。

DONE
