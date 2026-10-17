# BRIEF OPUSCAR — 把 lemo-opuscar 中 hevi 不具备的能力全部集成进 hevi

用户原话："不单用精华，hevi不具备的都要集成过去"。

## 背景
- 参考库：https://github.com/lemomo-ai/lemo-opuscar （代码 MIT，文档/风格/样片 CC BY 4.0）。已 clone 到 /data/soffy/refs/lemo-opuscar（若无则自己 `git clone --depth 1`）。
- 它的内容：DIRECTOR.md（故事、声音、节奏、镜头、表演、自检）、TECHNIQUE.md（Canvas/WebGL 逐帧渲染、本地 TTS 配音、免费采样库作曲、混音、审片）、styles/<风格>/STYLE.md + demo/（39 种风格，每个有完整源码和 build.sh）、tools/（fetch.sh 等）、AGENTS.md/CLAUDE.md 工作流（两个确认点：故事+分镜；风格帧+角色设定表）、CREDITS 版权规则（只用 CC0/CC BY/OFL）。
- 关键方法：音乐网格先于动画（cue map：BPM、小节、每个卡点落在哪一拍，画面卡网格）；全片≥4 种运镜+一个签名镜头；转场在风格里设计，不用默认淡入淡出；动作有预备-动作-跟随；每个动作都有声音、≥2 处真正静音；对标只学语法；质检：每句配音 ASR 转写回核、响度 −14 LUFS、黑帧检测、每 1–2 秒一帧缩略图总览、关键动作按 0.2 秒抽帧；用户需求万能模板（风格/时长/主题/故事/节奏/旁白/对标/素材/画幅）；弱模型策略（从样片改、代码原生风格优先、缩短、拆小步、强模型导演+便宜模型执行）。

## 工作目录
worktree：/data/soffy/projects/hevi-opuscar，分支 feat/opuscar-integration（基于 closure/3o-v3-architecture-creative-baseline 的 HEAD b6eeaedb）。只在这个目录里改。

## 先读
1. lemo-opuscar 全部：README、AGENTS.md/CLAUDE.md、DIRECTOR.md、TECHNIQUE.md、tools/、每个 styles/*/STYLE.md、至少 3 个 demo/ 源码与 build.sh（一个 2D Canvas、一个 WebGL/three.js、一个排版类）。
2. hevi：README.md、CAPABILITY_CONTRACT.md、STATUS.md、hevi/capabilities/registry.py、hevi/director、hevi/canvas、hevi/audio、hevi/dub、hevi/narrative、hevi/motion、hevi/fx、hevi/qa 或类似质检模块、hevi/prompt/h3_compiler.py、以及已有的 *_DONE.md 了解已有能力和注册方式。

## 要做
1. GAP_OPUSCAR.md：逐条列出 opuscar 的每项能力/方法/工具/风格（包括 39 个风格逐个），标注 hevi 是否已有（给出 hevi 中对应文件路径）、部分有、没有。先提交这份清单。
2. 把所有"没有/部分有"的项集成进 hevi，按 hevi 现有的 capability 注册与契约方式接入，不要另起一套孤立代码。至少包括：
   - 导演方法层：DIRECTOR 规则作为可加载的导演规范+可程序化检查的规则（运镜种类数、签名镜头、转场类型、静音段数、动作有声等），接入 hevi director/narrative 流程。
   - cue map / 音乐网格先行：BPM/小节/卡点数据结构，画面时间线吸附到网格。
   - 代码逐帧渲染引擎：headless Chrome（puppeteer/playwright）驱动 Canvas/WebGL 页面逐帧截取 → ffmpeg 合成，作为 hevi 一个渲染 capability。
   - 39 种风格全部：每个风格的 STYLE.md 规范 + demo 源码 + build 方式作为 hevi 风格库条目（可列举、可选用、可从样片改），能用 tools/fetch.sh 取输入的保留。
   - 配乐（免费采样库原创作曲）、本地 TTS 配音、混音若 hevi 没有对应实现则接入。
   - 质检：ASR 回核配音、−14 LUFS、黑帧、缩略图总览、0.2s 关键动作抽帧；hevi 已有的复用并补缺。
   - 两个人工确认点（故事+分镜；风格帧+角色设定表+最没把握点）作为工作流 gate。
   - 需求模板 + "帮我挑两三个风格" 选风格入口；弱模型策略写进 hevi 文档/配置。
   - 版权：把 opuscar 的 CREDITS 规则接入 hevi credits 模块；在 hevi NOTICE 中注明来源 lemo-opuscar（MIT + CC BY 4.0，作者 lemomo-ai）。
3. 端到端验证：用新能力真实跑出至少 2 支样片——一支代码原生风格（如 Swiss Motion Graphics 或 ASCII 终端，30 秒）、一支其他风格（如水墨或白板），输出 mp4 到 outputs/_opuscar_smoke/，并跑完上面全部质检，把质检报告贴进 report。若某风格需下载的大文件（TTS 模型/采样库）下载失败，换另一个风格并在报告说明。

## 验收
- 真实测试，不 mock；新增能力有测试；跑 hevi 现有测试套件，无新增失败（先记录基线失败数）。
- GAP_OPUSCAR.md 中每一项最终状态都是"已集成（路径）"或"已有（路径）"；如有确实不能集成的，写明原因。
- 2 支样片真实存在、ffprobe 时长正确、质检通过。

## 规则
- CPU-only，不用付费 API。不要 push/merge/deploy/重启服务。不删除工作目录以外的文件。每完成一步就 commit。
- /data 剩余 <5G 立即停止并报告。大文件放 /data/soffy/cache/opuscar/，不要提交进 git。
- 报告写到 OPUSCAR_DONE.md，最后一行是 `OPUSCAR DONE` 或 `OPUSCAR BLOCKED: <原因>`。
