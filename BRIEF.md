# hevi 新产线：collage_broll 半调纸拼贴 B-roll（2026-11-07）

你在 worktree /data/soffy/projects/hevi-collage（分支 hark/collage-broll，基于 8da6d735）。参考仓库 https://github.com/pyang5166/gbro-collage-broll（MIT）：git clone --depth 1 到 /tmp/drama-repos/gbro-collage-broll 只读参考。其 SKILL.md 的提示词模板、QA 清单可复用，但必须在 hevi/collage_broll/LICENSE_gbro 放原 LICENSE 全文并在 THIRD_PARTY_NOTICES.md 注明。不要用它的 Gemini/Veo 视频脚本，不需要 GEMINI_API_KEY。

## 目标流程（每句约 5 秒口播 → 一段 B-roll）
1. 隐喻卡（LLM，用 hevi 已配置的免费 LLM；不可用则确定性回退）：核心意思、视觉隐喻、3–6 个关键物件、语义底色（焦橙/红=时间消耗劳动紧迫；芥末黄=工具警示；墨绿=认知审美；深紫=规范沉淀；青绿=判断协作）、组装顺序。可选人工确认闸门（API/CLI 参数 confirm_metaphor，默认关闭=自动通过）。批量时多句隐喻前后成叙事。
2. visual-spec.json：平涂色场、黑白半调剪片、彩色卡纸点缀、机切边+奶油白描边、柔和投影、纸纤维颗粒。
3. 静帧：通过服务器上已用 ChatGPT 登录的 Codex CLI（/home/soffy/.local/sgbin/codex，codex exec，调用其图像生成）出 9:16 静帧，按清单自检（隐喻可读、主体集中在中间 70%、无假字/logo/水印/UI、空场留够、3–6 大组），不过就重出（最多 2 次）。
4. 动画两种引擎：
   a) codex：以静帧为终点让图像模型出 5 秒 20fps 循环 GIF（assemble-from-empty，顺序固定、物理动词、镜头锁死），再 ffmpeg 转 720x1280 24fps H.264 MP4（-ignore_loop 1，yuv420p，-an）；逐段 QA：首帧空场、尾帧≈静帧、循环接头。
   b) procedural（零额度回退、默认在测试里用）：让图像模型或本地 PIL 生成可分离的 3–6 个纸片图层（透明 PNG）+ 色场，用代码渲染定格式“从空场逐块滑入/落下/卡位→定格→清场”的 5 秒循环，半调网点和描边用 PIL 实现。没有 Codex 时整条链可完全离线跑（纯程序化素材）。
5. 交付：每句 GIF + MP4；多句时按 TTS 时长拼成带旁白和字幕的成片，并提供给 talking_head/explainer 作为逐句 B-roll 插入的接口。
6. 接入：hevi 能力注册 + /api/studio 产线（line_id=collage_broll）+ CLI python -m hevi.collage_broll run。

## 额度规则（重要）
- 开发与单测全部用 mock/procedural，不调用 Codex。
- 全部完成后，用 Codex 真实调用最多 3 句（静帧+GIF，含自检重出在内总调用 ≤12 次），记录每次调用耗时。之后不得再调用。
- 不调用任何付费 API，不下载 >200MB。

## 规则
- 只在本 worktree 改代码和 commit；不推送、不碰主仓库工作区、不重启/改动生产容器。同一问题卡两次就记录并继续。每完成一项追加 PROGRESS.md。单测 + /data/soffy/projects/hevi/.venv/bin/python -m pytest 相关测试通过。

## 验收
3 句示例（“一只橘猫第一次看海”的三句口播）：procedural 模式全部出片；Codex 模式 3 句真实出片。ffprobe 结果、contact sheet、GIF/MP4 路径放 samples/。

## 输出
COLLAGE_REPORT.md（中文）：实现、文件、commit、两种模式结果、Codex 调用次数与耗时、QA 结果、许可署名、仍存问题。最后一行 DONE。
