# JUDGE2_REPORT

## 实现
- 新增后端 `OpencodeJudgeBackend`（`hevi/judge/backend.py`）：调用 `/snap/bin/opencode run -m <model>`，`</dev/null` + timeout；抽帧每 2 秒 1 帧拼成 4x4 contact sheet，连同 ffprobe 指标与字幕侧车文件作为附件交给模型，要求输出 JSON。
- `select_backend("opencode")` 接入；`hevi.judge` 导出 `OpencodeJudgeBackend`。
- 硬伤检查模型部分：`run_hard_checks(..., backend=...)` / `run_model_hard_checks`，由 opencode 识别切题、假字/假界面、画面与旁白不一致等。
- 两两对比评委：复用 `run_pairwise`（composite + 交换位置各判一次），opencode 后端走模型路径。
- 自迭代：`run_self_iterate` 每版调用模型硬伤检查；explainer / cinematic 两条线真实 v1→最多 v3。
- 校准：旧样片 vs 新样片（audit-1106 vs linefix-b）。
- API：`pipeline` 传播 `judge`/`judge_backend` 到 options；任务完成时若 `judge=True`，在任务记录写入 `config_json.judge_report`（含 ffprobe 指标与发现项）。

## commit
- 待本次提交（分支 hark/video-judge）

## agy 用法
- `/home/soffy/.local/sgbin/agy` 仍需用户本人登录（OAuth），本轮未尝试登录；agy/gemini 保留为可选后端，主模型评委改用 opencode。

## opencode 模型看图测试（timeout 50s）
- `opencode-go/crouton-alpha-free`：可看图，输出 JSON（选用）。
- `opencode-go/mimo-v2.6-flash`、`opencode/mimo-v2.6-flash-free`：可看图。
- `opencode-go/qwen3.7-plus`：可看图。
- `opencode-go/beam-free`：不可看图（"I can't view images directly"）。
- `opencode-go/nemotron-3.5-super-vl-free`：模型不存在 / 服务端错误。
- `opencode-go/iceman-contributor-free`：不可看图。

## 校准一致率
- 样本对：explainer audit-1106 run1 vs linefix-b run1；cinematic audit-1106 run1 vs linefix-b run1。
- 位置一致性（两次换位是否同意）：1/2（explainer 一致，cinematic 不一致）。
- 预期胜出（新样片 B 赢）：0/2（两对均为 TIE，模型无法判定新版明显更优）。

## 两条线 v1→v3 迭代记录
### explainer
- v1：生成成功；模型硬伤 `audio-visual mismatch:major`、`fabricated subtitle text:minor`；采纳。
- v2：生成成功；模型硬伤 `subtitle_visual_mismatch:major`、`protagonist_identity_inconsistency:major`、`off_topic_footprints_segment:major`、`mixed_language_subtitle:minor`；两两对比 TIE 且位置不一致 → 拒绝，停止。
- 最终：v1，`explainer.mp4`，31.33s，1280x720，h264/aac。
- params 调整：caption_size 48→50。

### cinematic
- v1：生成成功；模型硬伤 `Fake burnt-in subtitles:blocker`、`Embedded title text artifact:major`、`Ghost transparent cat overlay:major`、`Protagonist identity inconsistency:major`、`Subtitle-visual narrative mismatch:major`、`Mixed-language subtitle artifact:minor`；采纳。
- v2：生成成功；模型硬伤 `fabricated_subtitles:major`、`subtitle_visual_mismatch:major`、`ghost_overlay_artifact:minor`；两两对比 TIE 且位置不一致 → 拒绝，停止。
- 最终：v1，`cinematic.mp4`，31.63s，1280x720，h264/aac。
- params 调整：caption_size 48→50，grade→bright。

## 调用次数
- opencode 模型调用：校准 4 + explainer 4 + cinematic 4 + 模型硬伤复检 2 + 看图测试 6 = 20（≤40）。
- agy：0；gemini CLI：0。

## 仍存问题
- agy 未登录，需用户本人完成 OAuth。
- 两条线 v2 均被评委拒绝（TIE/位置不一致），说明本地 judges 对细微改动不敏感或 v1 已触天花板；真实质量改进需更强的生成/提示词调整。
- API 端到端（带 judge=true 的真实生产任务）未在本轮跑通，仅完成接线。

DONE