# Anatomy 上游补齐（worker brief）
上游：https://github.com/wheresryan22/anatomy（MIT）。Hevi 已在 third_party/anatomy 引入 kit 2D 部分（iso-kit/lathe/tube/gl/audit/canvas-painter）和少量 scripts，能力在 hevi/capabilities/anatomy_explainer。
先 git clone 上游到 .tmp/anatomy-up，对比后补齐有价值部分，保留 LICENSE/NOTICE 署名并记录上游 commit：
1. 3D 模式：kit/turn.mjs、turn-build.mjs、turn-audit.mjs，接入 anatomy_explainer（mode=3d），至少 1 个可转动示例。
2. 核验脚本：scripts/capture.mjs、drive.mjs（截图+动作联系表）、lines.mjs（悬空线检查）、turn-check.mjs；用本机 Chromium headless（CPU，无 GPU 用 SwiftShader），接入渲染后自检，失败给出明确错误。
3. references/ 工艺规则（craft/kit/motion/verify/webgl/3d）放入 third_party，并把关键规则落成 renderer 的生成约束/提示。
4. 示例：至少引入 dial-indicator、ripple-tank、turning-dial 三个，作为回归基准（构建产物字节稳定或截图可比）。
5. 视频化：任一示例经 drive.mjs 录帧→ffmpeg 出 ≥10 秒 mp4，ffprobe 验时长。
不引 React 部分（Hevi 不用）。CPU-only，不调付费 API，不 push/合并/部署，不删 worktree 外文件，/data<5G 停。
测试：每项真实测试（禁止 mock 渲染结果），全量回归相对基线无新增失败。
报告 audit/anatomy_up/REPORT.md，末行 `ANATUP-FINAL DONE <commit>` 或 `ANATUP-FINAL BLOCKED <原因>` 并 commit。
