# DIRSTYLE_TASK_ADD1 — 追加：火柴人风格 + 5 段心跳结构 + Omni Flash / Google Flow 提示词包

同一分支 feat/director-styles、同一 worktree（/data/soffy/projects/hevi-dirstyle）。DIRSTYLE_TASK.md 的全部规则继续有效（CPU-only、无付费 API、不删数据、不 push、不合并、3O lint 不新增失败、禁止 mock、DONE 如实）。先看 git log/status，在已有提交上继续，**不要推翻已完成的导演风格库**。

## 上游（已 vendor，主审已做）
`third_party/stickman-video-director/` ← github.com/kaomei/stickman-video-director @821a381，MIT（Copyright (c) 2026 Stickman Video Director contributors）。已去掉 .git 和 assets/readme 媒体（见 VENDORED.md）。
重点读：`skills/directing-stickman-videos/SKILL.md`、`references/storyboard-template.md`（5 段心跳 + 按时长分配）、`references/style-catalog.md`（风格 1A/1B/2A/2B 的角色 DNA、配色契约）、`references/prehistoric-dark-comedy.md`（风格 3）、`references/omni-flash-prompt-contract.md`（单条提示词顺序、负面契约、拼接说明）、`references/voice-continuity.md`、`references/examples.md`。
署名：在 third_party/dirstyle_refs/README.md（或你已建的第三方台账）和 THIRD_PARTY_NOTICES 登记此仓库；风格库里吸收来的条目写 `source: stickman-video-director`。

## 必须实现
1. **5 段心跳叙事结构模板**（黄金钩子 → 打破认知 → 揭示秘密 → 终极真相 → 升华+讨论），作为 Hevi 脚本/分镜规划的**可选**结构（不改变现有默认结构）：
   - 按总时长自适应分配段数/秒数（参考 storyboard-template 的 N = 时长/10 分配表）；**钩子必须落在 2–5 秒内**（测试断言 15s/30s/60s/3min 都满足）。
   - 只重组/改写输入素材，**不编造事实、数字、引语**（输入里没有的数字不得出现在产出里，加测试）。
   - 接入点：找到现有脚本/分镜规划入口（dramaplan / comicnarr script_planner / storyboard 等，grep 后选最合适的），加可选参数 `structure="heartbeat5"`。
2. **火柴人风格**进同一个风格库，作为与导演风格**正交的"画风/角色维度"**：`stickman_1a_light`（白底黑线）、`stickman_1b_dark`（黑底白线）、`stickman_2a_studio_tech`、`stickman_2b_cinematic_story`、`stickman_3_prehistoric`。每条含：角色 DNA 锚定句（逐字冻结）、线宽、配色契约（≤3 强调色，**生成提示词里用普通颜色词，不写 hex/RGB**——hex 只放 grade 参数）、负面约束、9:16 / 16:9 构图规则。
   - 可叠加：`compile_prompt(..., director_style="wes_anderson", art_style="stickman_1a_light")` → 火柴人角色 + 韦斯式对称/粉彩配色/机械横移；冲突时画风维度（线条、无写实）优先，导演维度只贡献构图/配色/运动/节奏。与国风动漫默认的兼容规则同理。测试覆盖叠加结果不含写实词、不含 hex、不含导演名。
3. **分段与连续性**：视频目标按约 10 秒一段，每段 3 个计时节拍 `[0–3s] [3–7s] [7–10s]`；**每一条段提示词都独立完整重复连续性锁定块**（角色 DNA、线宽、配色、配音档案、负面约束），不得用"同上/same character/…"省略（测试：每段都包含完整锁定块原文）；段 i 结尾画面 = 段 i+1 开头画面（衔接描述）；9:16 **重新构图**（纵深、上下堆叠运动、竖向揭示、UI 安全区），不是只改比例标签（测试：9:16 与 16:9 的构图句不同）。旁白只做音频（不出字幕气泡/画面文字）。
4. **Gemini Omni Flash / Google Flow 提示词包导出**（新增 omodul，例如 `export_flow_pack(source_text, duration_s, aspect, art_style, director_style=None, voice=..., lang=...)`）：
   - 只产出文件，**不调用任何 API**：`pack.md`（人读：导演预案 + 全局连续性块 + 逐段提示词 + 拼接说明 + 配音/音乐连续性说明 + 后期可选文字叠加建议）和 `pack.json`（机读）。
   - 拼接说明写清：在 Flow 里逐段生成、按序号命名、首尾帧衔接检查、用 ffmpeg concat（给出命令）或 Hevi 的哪个步骤拼接；用户用自己的 Google AI Pro Flow 额度手动生成。
   - 旁白语言：默认中文（Hevi 用户），可选英文；字数按每 10 秒段约 20–25 英文词 / 约 45–60 汉字缩放。

## 样片 / 示例（追加到 output/dirstyle_e2e/）
- **一条 9:16 火柴人风格 CPU 样片**：用仓库现有能力画简单火柴人（Remotion / SVG→帧 / PIL / manim 均可，先 grep hevi-remotion-* 与现有 SVG 渲染能力复用；CPU 渲染，长任务 nohup setsid）。内容用 5 段心跳结构的一段短稿（10–30s），本地 TTS（piper 等现有）配音可选；字幕/文字在安全区内不出框。**真做不出来就不要硬凑**：如实在 DONE 里说明原因，只交提示词包。
- **一份 60 秒提示词包示例**：`output/dirstyle_e2e/flow_pack_60s/`（pack.md + pack.json），9:16，火柴人风格（建议 stickman_1a_light 或 2A）+ 一个导演配色叠加（如 wes_anderson），素材用一段真实中文短文（仓库里已有文案或自写的通用常识文，不编造数据）。6 段 × 3 节拍，每段完整锁定块。
- record.json / SHA256SUMS / contact_sheet.png 把火柴人样片补进去（contact sheet 多一行）。

## 交付
- 阶段性 git commit（只 add 自己的文件），不 push。
- 在 DIRSTYLE_DONE.md 追加「ADD1」一节：接口、文件、测试命令和结果、样片 ffprobe+sha256、提示词包路径、已知限制。如实写，不自评通过。不要询问，直接执行。
