# hevi 新口型引擎：LivLiv 2.5D 角色（2026-11-07）
worktree /data/soffy/projects/hevi-livliv，分支 hark/livliv-avatar，基于本地 main（bcf52b17）。
来源 https://github.com/livliv-dev/player ：代码 Apache-2.0（可复用，须带 LICENSE 与 NOTICE 原文，在 THIRD_PARTY_NOTICES 署名）。自带 21 个角色另有许可（个人非商用、须署名“Characters: LivLiv (livliv.ai)”、不得用于训练 AI、保留角落 LivLiv 标记、公开展示须注明 AI 制作）；用户确认 hevi 不商用，允许使用这些角色。Kujira/Kujira Q/Pen 按 characters/CREDITS.md 单独署名。
先用 GitHub API 看仓库大小，>200MB 则 sparse checkout 只取 src、package 相关与 characters 全部（单个角色若过大可跳过并记录）。clone 到 /data/soffy/vendor/livliv-player（只读引用，不进 hevi git；hevi 内只放构建产物和许可证文件，或在 Dockerfile 里构建）。Node 需 ≥22.18。

## 目标：做得比 wav2lip 版更好
1. 离线确定性渲染器 hevi/avatar_livliv/：Playwright 无头 Chromium（服务器 GPU 驱动坏了，用 SwiftShader/软件 GL，参数如 --use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader），页面加载 player 与角色，按帧推进时间（不靠实时录屏），每帧 canvas 导出 PNG（透明背景）管道给 ffmpeg，30fps，输出带 alpha 的 mov/webm + 合成用 mp4。
2. 口型：从 TTS 音频逐帧算音量包络 + 简单元音/口型估计（如频谱质心映射 a/i/u/e/o，若 player 支持多口型参数就用），平滑、提前 1–2 帧；对齐误差 ≤1 帧。
3. 表演：逐句情感/功能（来自 hevi 现有脚本或 koubo_cut 的句子分类）选表情（smile 等，用 player.expressions 实际可用 id）、在重音/句首加 act('nod') 等动作、自然眨眼与呼吸、头部微转；同一角色全片一致。
4. 接入：作为口型引擎选项 engine=livliv 接入 koubo_cut（小窗/全屏人像）、talking_head、avatar_spokesperson；API/studio 参数可选 character_id（列出 21 个及名称、署名）。默认引擎保持现状，不改坏原有路径。
5. 合规：成片角落保留 LivLiv 标记；片尾或元数据写“Characters: LivLiv (livliv.ai)，AI 制作”；角色许可 LICENSE.md/CREDITS.md 原文随附；配置项 LIVLIV_CHARACTERS_ENABLED（默认 true，注释说明仅限非商用）。
6. 性能：记录 30 秒片的渲染耗时与内存；>5 分钟则降分辨率/帧率选项。

## 验收
- 3 个不同角色（含 d03ft Nana refined）各渲染一段 30 秒中文 TTS 口播（edge-tts 等免费），ffprobe（时长、音轨、分辨率）、volumedetect；
- 口型对齐：抽 1 秒内 30 帧比较 mouthOpen 序列与音量包络相关系数 ≥0.7；
- koubo_cut 用 engine=livliv 跑 3 次完整成片，抽 6 帧拼 contact sheet 存 samples/livliv/；
- 和 wav2lip 版同题对比：耗时、观感（用 hevi/judge 的 opencode 评委做换位两两对比，≤10 次调用）。
- pytest 相关测试通过。

## 规则
只在本 worktree 改并 commit；不推送、不合并 main、不碰 /data/soffy/projects/hevi 与 hevi-golive、不动生产容器。不花钱、不调用 Google Flow、单文件不下载 >200MB。opencode 子调用加 </dev/null。卡两次记录跳过。PROGRESS.md 逐项追加。
输出 LIVLIV_REPORT.md（中文）：实现、commit、许可处理、渲染耗时、对齐相关系数、评委对比结果、样片路径、仍存问题。末行 DONE。
