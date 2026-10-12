# OMRENDER 返工 r4（审核方 2026-10-12 08:40 CST 核验未通过）

上轮 FIX 的 2（SVG 骨骼角色）、3（Blender Cycles 场景）、4（仓库干净）、5（MIT 署名）已核实修好，保留。OpenMontage AGPL 长行比对未发现代码复制（命中只有 MIT LICENSE 原文、CDN URL、通用 `<svg viewBox>`），继续保持 clean-room。lint=基线 4 项，未新增。

不通过的原因（必须修）：

1. **HyperFrames 风格片是写死的上游样片，不是由输入驱动**（最严重）。
   `hevi/providers/hyperframes/styled.py::style_source(style)` 只看 style，只要 `third_party/lanshu_explainer/examples/kv-cache/<style>/index.html` 存在就无条件拿它当片源——这是 lanshu 自带的「KV cache / 天空为什么是蓝的」成品样片。换任何 story_dir，画面仍是 KV cache 内容，只有旁白变了，画面与口播对不上。6 条 hf_*.mp4 的 contact sheet 全是上游 kv-cache 样片的画面（大模型/token/KV 表/Llama 2 显存/GQA/复习脑图），E2E 的 STORY 也是上游 `stories/kv-cache`，等于重渲上游 demo。
   要求：
   - `style_source` 绝不能读 `examples/`（examples 只可做参考/测试夹具）。片源 = 该风格的 `kits/<style>/starter` + **根据输入 story.json 的每条旁白生成的 beats**（场景元素、文字、数字来自输入稿，按各风格 SKILL/STYLES 规范编排），不能是 placeholder「待演绎」草稿卡。
   - E2E 必须用一个**非 KV cache 的新中文主题**（自己写 30–60 秒科普稿，例如「为什么冬天静电多」），本地 piper 旁白 + faster-whisper 词级时间，至少渲染 4 种风格（含 v6-cinematic 与 v8-chalkboard），每条 30–60 秒、16:9、带音轨。
   - 再用第二个不同主题至少渲染 1 种风格（可短，≥20s），证明画面随输入变化；DONE 里并排给出两主题同一风格的 contact sheet 路径，并说明哪些画面元素来自输入稿。
   - `stories/kv-cache/audio/tts/*.mp3`（上游 MiniMax 配音）不得进入 Hevi 渲染路径。
2. **原任务第 1 条缺失**：HyperFrames 的 kinetic typography 与产品宣传两类合成（各 15–30 秒）没有任何产物，report.json 里也没有。补上，内容由输入（文案/产品信息）驱动，带音轨，接进 runtime.select。
3. **原任务第 4 条缺失**：16:9 / 9:16 / 1:1 / 21:9 平台输出档没有任何验证产物。至少用 kinetic typography 合成各出一条短片（≥5s），ffprobe 报分辨率。
4. character_animation 最后「扭一扭」一段角色整体倒立（头朝下，抽帧第 6 格），检查 twist 片段根节点旋转/坐标轴换算是否有误，修正后重渲；同时让 `render_character` 的动作序列/台词可由参数传入（E2E 用两组不同动作序列各出一条，第二条可 ≥10s）。
5. 重跑 `scripts/om_render_e2e.py`，ffprobe + sha256 + 亲自看 contact sheet，真实数据写入 OMRENDER_DONE.md；跑新增测试（注意测试要能在 PATH 不含 /home/soffy/.local/bin 时自己找到 ffmpeg，或在测试里 monkeypatch PATH）和 lint（不得多于基线 4 项）。git status 干净后 commit。不要 push。禁止 mock/占位兜底/写死样片。
