# ANATOMY_TASK — 「会动的小机器」幼儿科普镜头线（完成标志：ANATOMY_DONE.md 最后一行 `DONE ANATOMY-R1`）

参考仓库：wheresryan22/anatomy（MIT，已 clone 到 /data/soffy/refs/anatomy）。它是 agent skill：把一个概念做成可动的等距（isometric）机械插画，SVG 四色明暗 + 可选 WebGL 着色器 + 3D(beta)，纯 Node 内置模块，无依赖；自带几何审计 kit/audit.mjs（不穿模、每个端点有支撑、遮挡顺序正确）、scripts/capture.mjs / drive.mjs（headless Chrome 截图、慢放接触表）、lines.mjs（悬空线检查）。

Hevi 产品定位：2–6 岁幼儿教育动画故事片，规则见本 worktree 的 KIDS_ANIME_DIRECTION.md（必须遵守），能力接入规则见 CAPABILITY_CONTRACT.md（必须遵守）。

## 目标
把 anatomy 的 kit（iso-kit.mjs、lathe.mjs、tube.mjs、audit.mjs、gl.mjs 可选）vendor 到 third_party/anatomy（保留 LICENSE，NOTICE 署名），做成 Hevi 的一条 CPU 镜头能力 `anatomy_explainer`：给幼儿讲「东西是怎么动的」。
1. 至少 4 个幼儿向示例对象，每个都由「一个小模型驱动零件运动」：风车带动磨盘、水车、按压式洗手液泵（配合洗手主题）、牙刷电机或闹钟齿轮（任选替换，但必须贴近幼儿生活）。配色明亮高饱和（平均饱和度 ≥0.35），浅色主题，圆角友好，不出现英文、成人术语、品牌。画面文字只允许中文短标签（≤6 字），字号在 1080 画面上 ≥56px。
2. 渲染成视频：headless Chrome（CPU / SwiftShader，复用仓库已有的 Playwright 或 anatomy 的 capture/drive 脚本）按 30fps 逐帧推进时间（不要实时录屏），ffmpeg 合成 MP4。支持 16:9 和 9:16（9:16 不得硬裁掉主体），输出 1080p（1920×1080 / 1080×1920），时长 4–10 秒，镜头运动平缓（适合幼儿，无闪烁 >3Hz）。
3. 同参数同 seed 两次渲染 sha256 一致。
4. 每条片自动跑 anatomy 几何审计（audit.mjs + lines.mjs）和 hevi kids_gate；任何一项失败就拒绝出片（不是只记日志）。
5. 能力注册：hevi/capabilities/registry.py 注册 `anatomy_explainer`，ShotSpec capability 字段可调，参数校验（非法对象名、非法画幅、时长 <2s 或 >15s 都拒绝），所有产品线可调用。
6. 测试（pytest，必须真跑渲染，不准 mock）：4 个对象 × 2 画幅出片且 ffprobe 正确；sha 一致；审计失败注入（人为让一个零件穿模）必须拒绝出片；参数非法拒绝；饱和度和字号断言基于真实像素。
7. 样片放 audit/anatomy/samples/（只提交 ≤5MB 的小样片和关键帧 PNG），写 audit/anatomy/REPORT.md：实测时长、渲染耗时、内存峰值、sha、审计结果、kids_gate 结果。

## 范围外
不做 React 输出；不做 3D beta 模式（除非 4 个对象都已完成且稳定）；不发布到 anatomy 社区画廊；不调用任何付费 API。

## 通用规则
- 只改本 worktree；不改主 checkout /data/soffy/projects/hevi；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）。
- CPU-only；渲染单进程；所有 python 设 PYTHONPATH=本 worktree；pytest 用 JWT_SECRET=test-only，Python /data/soffy/projects/hevi/.venv/bin/python；ffmpeg 在 ~/.local/bin。
- 禁止 mock/占位产物/硬编码 passed=True；每步 commit；不 push；不要把日志、.tmp 提交进仓库。
- 完成后写 ANATOMY_DONE.md（实测数字 + 复现命令），最后一行 `DONE ANATOMY-R1`，commit。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-anatomy；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 ANATOMY_DONE.md 最后一行写 DONE ANATOMY-R1。
